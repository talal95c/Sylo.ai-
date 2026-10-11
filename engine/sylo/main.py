"""FastAPI app: the HTTP API and the server-sent-event stream (spec/api.md)."""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any, Literal

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from .approvals import ApprovalError
from .config import Settings
from .metrics import load_metrics
from .orchestrator import (
    ATTACKS,
    SCENARIOS,
    ActionNotAllowed,
    AttackNotApplicable,
    ChainUnavailable,
    NotWaiting,
    Orchestrator,
    ScenarioBusy,
    UnknownAttack,
    UnknownBreaker,
    UnknownPayment,
    UnknownRoute,
    UnknownScenario,
    build_orchestrator,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


class RunBody(BaseModel):
    speed: float | None = Field(default=None, gt=0, le=100)
    auto: bool = False
    autoAnswer: Literal["confirm", "deny"] = "deny"


class AnswerBody(BaseModel):
    answer: Literal["confirm", "deny"]


class AttackBody(BaseModel):
    paymentId: str


class ApproveBody(BaseModel):
    approver: str = Field(min_length=1, max_length=40)


class CaseActionBody(BaseModel):
    action: Literal["CONFIRM_REVOCATION", "RELEASE", "FREEZE"]


class WaveBody(BaseModel):
    speed: float | None = Field(default=None, gt=0, le=100)
    auto: bool = False


class RailBody(BaseModel):
    reason: str | None = Field(default=None, max_length=200)


class ClockBody(BaseModel):
    advanceHours: float = Field(gt=0, le=744)


class IncidentBody(BaseModel):
    """What the guardian (Lane C) reports. Unknown fields are kept out; DORA fields are optional overrides."""

    rule: str = Field(min_length=1, max_length=120)
    action: str = Field(default="NONE", max_length=60)
    txHash: str | None = Field(default=None, pattern=r"^0x[0-9a-fA-F]{64}$")
    explorerUrl: str | None = Field(default=None, max_length=300)
    incidentId: str | None = Field(default=None, max_length=60)
    paymentId: str | None = Field(default=None, max_length=60)
    simulated: bool | None = None
    clientsAffected: int | None = Field(default=None, ge=0)
    amountEur: float | None = Field(default=None, ge=0)
    durationMinutes: float | None = Field(default=None, ge=0)
    geographicSpread: list[str] | None = None
    criticality: str | None = Field(default=None, max_length=120)
    thirdParties: list[str] | None = None
    major: bool | None = None


def _names(values: object) -> str:
    return ", ".join(repr(value) for value in values)  # type: ignore[union-attr]


def _dump(event: dict[str, Any]) -> str:
    return json.dumps(event, ensure_ascii=False, separators=(",", ":"))


def create_app(settings: Settings | None = None, orchestrator: Orchestrator | None = None) -> FastAPI:
    settings = settings or Settings.from_env()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.orchestrator = orchestrator or build_orchestrator(settings)
        yield
        await app.state.orchestrator.reset()

    app = FastAPI(title="Sylo.ai engine", version="1.0.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.cors_origins),
        allow_methods=["*"],
        allow_headers=["*"],
    )

    def orch(request: Request) -> Orchestrator:
        return request.app.state.orchestrator

    @app.get("/health")
    async def health(request: Request) -> dict[str, Any]:
        return {"ok": True, "mode": orch(request).mode()}

    @app.get("/v1/stream")
    async def stream(request: Request) -> EventSourceResponse:
        o = orch(request)
        bus = o.bus
        header = request.headers.get("last-event-id")
        last_seq: int | None = int(header) if header and header.isdigit() else None
        if last_seq is not None and last_seq > bus.last_seq:
            last_seq = None  # the engine restarted: resend the whole session
        queue = bus.subscribe()

        async def events() -> AsyncIterator[dict[str, str]]:
            try:
                yield {"data": _dump(o.mode_event())}
                sent = last_seq or 0
                for event in bus.since(last_seq):
                    yield {"id": str(event["seq"]), "data": _dump(event)}
                    sent = event["seq"]
                while True:
                    event = await queue.get()
                    if event["seq"] <= sent:
                        continue
                    yield {"id": str(event["seq"]), "data": _dump(event)}
                    sent = event["seq"]
            finally:
                bus.unsubscribe(queue)

        return EventSourceResponse(events(), ping=15)

    @app.post("/v1/scenarios/{name}/run")
    async def run_scenario(name: str, request: Request, body: RunBody | None = None) -> dict[str, str]:
        body = body or RunBody()
        try:
            payment_id = orch(request).start(
                name, speed=body.speed or settings.demo_speed, auto=body.auto, auto_answer=body.autoAnswer
            )
        except UnknownScenario:
            raise HTTPException(404, f"unknown scenario {name!r}; expected one of {_names(SCENARIOS)}") from None
        except ScenarioBusy:
            raise HTTPException(409, "a scenario is running; wait for it to finish or POST /v1/reset") from None
        return {"paymentId": payment_id}

    @app.post("/v1/payments/{payment_id}/supplier-response")
    async def supplier_response(payment_id: str, body: AnswerBody, request: Request) -> dict[str, bool]:
        try:
            orch(request).supplier_response(payment_id, body.answer)
        except UnknownPayment:
            raise HTTPException(404, f"unknown payment {payment_id!r}") from None
        except NotWaiting:
            raise HTTPException(409, "this payment is not waiting for a supplier answer") from None
        return {"ok": True}

    @app.post("/v1/payments/{payment_id}/approve")
    async def approve(payment_id: str, body: ApproveBody, request: Request) -> dict[str, Any]:
        try:
            return orch(request).approve(payment_id, body.approver.strip().lower())
        except UnknownPayment:
            raise HTTPException(404, f"unknown payment {payment_id!r}") from None
        except NotWaiting:
            raise HTTPException(409, "this payment is not waiting for an approval") from None
        except ApprovalError as err:
            raise HTTPException(409, str(err)) from None

    @app.post("/v1/cases/{payment_id}/actions")
    async def case_action(payment_id: str, body: CaseActionBody, request: Request) -> dict[str, Any]:
        try:
            return await orch(request).case_action(payment_id, body.action)
        except UnknownPayment:
            raise HTTPException(404, f"unknown payment {payment_id!r}") from None
        except ActionNotAllowed as err:
            raise HTTPException(409, str(err)) from None
        except ChainUnavailable as err:
            raise HTTPException(503, f"the chain did not answer during {err.step}; nothing was changed") from None

    @app.post("/v1/attacks/{name}")
    async def attack(name: str, body: AttackBody, request: Request) -> dict[str, Any]:
        try:
            return await orch(request).attack(name, body.paymentId)
        except UnknownAttack:
            raise HTTPException(404, f"unknown attack {name!r}; expected one of {_names(ATTACKS)}") from None
        except UnknownPayment:
            raise HTTPException(404, f"unknown payment {body.paymentId!r}") from None
        except AttackNotApplicable as err:
            raise HTTPException(409, str(err)) from None
        except ChainUnavailable as err:
            raise HTTPException(503, f"the chain did not answer during {err.step}") from None

    @app.post("/v1/sim/mule-wave")
    async def mule_wave(request: Request, body: WaveBody | None = None) -> dict[str, Any]:
        body = body or WaveBody()
        try:
            return orch(request).start_wave(speed=body.speed or settings.demo_speed, auto=body.auto)
        except ScenarioBusy:
            raise HTTPException(409, "a scenario is running; wait for it to finish or POST /v1/reset") from None

    @app.post("/v1/sim/rails/{route_id}/{state}")
    async def rail_state(route_id: str, state: Literal["down", "up"], request: Request, body: RailBody | None = None) -> dict[str, Any]:
        try:
            if state == "down":
                return orch(request).rail_down(route_id, body.reason if body else None)
            return orch(request).rail_up(route_id)
        except UnknownRoute:
            raise HTTPException(404, f"unknown route {route_id!r}; expected R1, R2, R3 or R4") from None

    @app.post("/v1/sim/clock")
    async def clock(body: ClockBody, request: Request) -> dict[str, Any]:
        return orch(request).advance_clock(body.advanceHours)

    @app.post("/v1/breakers/{breaker_id}/{decision}")
    async def breaker(breaker_id: str, decision: Literal["confirm", "lift"], request: Request) -> dict[str, Any]:
        try:
            if decision == "confirm":
                return orch(request).confirm_breaker(breaker_id)
            return orch(request).lift_breaker(breaker_id)
        except UnknownBreaker:
            raise HTTPException(404, f"unknown circuit breaker {breaker_id!r}") from None
        except ActionNotAllowed as err:
            raise HTTPException(409, str(err)) from None

    @app.post("/v1/guardian/incidents")
    async def guardian_incident(body: IncidentBody, request: Request) -> dict[str, Any]:
        return orch(request).guardian_incident(body.model_dump(exclude_none=True))

    @app.get("/v1/metrics")
    async def metrics() -> dict[str, Any]:
        return load_metrics()

    @app.post("/v1/reset")
    async def reset(request: Request) -> dict[str, bool]:
        await orch(request).reset()
        return {"ok": True}

    @app.get("/v1/payments/{payment_id}")
    async def payment(payment_id: str, request: Request) -> dict[str, Any]:
        try:
            return await orch(request).payment_info(payment_id)
        except UnknownPayment:
            raise HTTPException(404, f"unknown payment {payment_id!r}") from None

    @app.get("/v1/payments/{payment_id}/proof")
    async def proof(payment_id: str, request: Request) -> dict[str, Any]:
        try:
            return await orch(request).proof(payment_id)
        except UnknownPayment:
            raise HTTPException(404, f"unknown payment {payment_id!r}") from None

    return app


app = create_app()
