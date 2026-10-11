"""FastAPI app: the HTTP API and the server-sent-event stream (spec/api.md)."""

from __future__ import annotations

import json
import logging
import math
import time
import unicodedata
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any, Callable, Literal

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, field_validator
from sse_starlette.sse import EventSourceResponse

from .approvals import ApprovalError
from .config import Settings
from .metrics import load_metrics
from .orchestrator import (
    ATTACKS,
    SCENARIOS,
    SIM_EVENTS,
    ActionNotAllowed,
    AttackNotApplicable,
    ChainUnavailable,
    NotWaiting,
    Orchestrator,
    ScenarioBusy,
    UnknownAction,
    UnknownAttack,
    UnknownBreaker,
    UnknownPayee,
    UnknownPayment,
    UnknownQuote,
    UnknownRoute,
    UnknownScenario,
    build_orchestrator,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


class RunBody(BaseModel):
    speed: float | None = Field(default=None, gt=0, le=100)
    auto: bool = False
    autoAnswer: Literal["confirm", "deny"] = "deny"
    invoiceText: str | None = Field(default=None, max_length=2000)

    @field_validator("invoiceText", mode="before")
    @classmethod
    def clean_invoice_text(cls, value: Any) -> Any:
        if not isinstance(value, str):
            return value
        return "".join(
            char
            for char in value
            if char in "\n\t" or unicodedata.category(char) != "Cc"
        ).strip()


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


class QuoteBody(BaseModel):
    order: Literal["legit", "diverted", "lagos-accra"]
    amount: str | None = Field(default=None, pattern=r"^[0-9]{1,12}(\.[0-9]{1,2})?$")


class PaymentBody(BaseModel):
    """One of ``quoteId`` or ``order``."""

    quoteId: str | None = Field(default=None, max_length=20)
    order: Literal["legit", "diverted"] | None = None
    speed: float | None = Field(default=None, gt=0, le=100)
    auto: bool = False
    autoAnswer: Literal["confirm", "deny"] = "deny"


class VerifyBody(BaseModel):
    accountId: str = Field(min_length=1, max_length=60)
    action: Literal["start", "record"] = "start"
    result: Literal["confirmed", "denied"] | None = None


class SimEventBody(BaseModel):
    type: str = Field(min_length=1, max_length=40)
    routeId: str | None = Field(default=None, max_length=10)
    reason: str | None = Field(default=None, max_length=200)
    paymentId: str | None = Field(default=None, max_length=60)
    hoursAgo: float | None = Field(default=None, ge=0, le=8760)
    advanceHours: float | None = Field(default=None, gt=0, le=744)
    speed: float | None = Field(default=None, gt=0, le=100)
    auto: bool = False


class IntakeBody(BaseModel):
    text: str = Field(min_length=1, max_length=40_000)
    senderDomain: str | None = Field(default=None, max_length=120, pattern=r"^[A-Za-z0-9][A-Za-z0-9.-]*$")


class WebhookBody(BaseModel):
    idempotencyKey: str = Field(min_length=1, max_length=120)
    status: str = Field(min_length=1, max_length=20)


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


def create_app(
    settings: Settings | None = None,
    orchestrator: Orchestrator | None = None,
    *,
    invoice_clock: Callable[[], float] | None = None,
) -> FastAPI:
    settings = settings or Settings.from_env()
    monotonic = invoice_clock or time.monotonic
    invoice_rate = {"last_started": None}

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
        invoice_text = body.invoiceText
        if invoice_text is not None and not settings.live_invoice:
            raise HTTPException(403, "live invoice is disabled (LIVE_INVOICE=off)")
        if invoice_text is not None and name != "diverted":
            raise HTTPException(422, "invoiceText is only allowed for scenario 'diverted'")
        now = monotonic()
        last_started = invoice_rate["last_started"]
        if invoice_text is not None and last_started is not None:
            remaining = 30.0 - (now - last_started)
            if remaining > 0:
                raise HTTPException(
                    429,
                    "one invoice run is allowed every 30 seconds",
                    headers={"Retry-After": str(max(1, math.ceil(remaining)))},
                )
        try:
            payment_id = orch(request).start(
                name,
                speed=body.speed or settings.demo_speed,
                auto=body.auto,
                auto_answer=body.autoAnswer,
                invoice_text=invoice_text,
            )
        except UnknownScenario:
            raise HTTPException(404, f"unknown scenario {name!r}; expected one of {_names(SCENARIOS)}") from None
        except ScenarioBusy:
            raise HTTPException(409, "a scenario is running; wait for it to finish or POST /v1/reset") from None
        if invoice_text is not None:
            invoice_rate["last_started"] = monotonic()
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

    @app.post("/v1/quotes")
    async def quote(body: QuoteBody, request: Request) -> dict[str, Any]:
        return orch(request).quote(body.order, body.amount)

    @app.post("/v1/payments")
    async def submit_payment(
        body: PaymentBody, request: Request, idempotency_key: str | None = Header(default=None, max_length=120)
    ) -> dict[str, Any]:
        if (body.quoteId is None) == (body.order is None):
            raise HTTPException(422, "give exactly one of quoteId and order")
        try:
            return orch(request).submit(
                quote_id=body.quoteId,
                order_name=body.order,
                speed=body.speed or settings.demo_speed,
                auto=body.auto,
                auto_answer=body.autoAnswer,
                idempotency_key=idempotency_key,
            )
        except UnknownQuote:
            raise HTTPException(404, f"unknown quote {body.quoteId!r}") from None
        except ActionNotAllowed as err:
            raise HTTPException(409, str(err)) from None
        except ScenarioBusy:
            raise HTTPException(409, "a payment is running; wait for it to finish or POST /v1/reset") from None

    @app.post("/v1/intake")
    async def intake(body: IntakeBody, request: Request) -> dict[str, Any]:
        return orch(request).intake(body.text, body.senderDomain)

    @app.get("/v1/cases")
    async def cases(request: Request) -> dict[str, Any]:
        return {"cases": orch(request).cases()}

    @app.post("/v1/payees/{payee_id}/verify")
    async def verify_payee(payee_id: str, body: VerifyBody, request: Request) -> dict[str, Any]:
        try:
            if body.action == "start":
                return orch(request).start_payee_verification(payee_id, body.accountId)
            if body.result is None:
                raise HTTPException(422, "action 'record' needs result: 'confirmed' or 'denied'")
            return orch(request).record_payee_verification(payee_id, body.accountId, body.result.upper())
        except UnknownPayee as err:
            raise HTTPException(404, f"unknown payee or account {str(err)!r}") from None
        except ActionNotAllowed as err:
            raise HTTPException(409, str(err)) from None

    @app.post("/v1/sim/events")
    async def sim_event(body: SimEventBody, request: Request) -> dict[str, Any]:
        try:
            return await orch(request).sim_event(body.type, body.model_dump(exclude_none=True))
        except UnknownAction:
            raise HTTPException(404, f"unknown simulated event {body.type!r}; expected one of {_names(SIM_EVENTS)}") from None
        except UnknownRoute:
            raise HTTPException(404, f"unknown route {body.routeId!r}; expected R1, R2, R3 or R4") from None
        except UnknownPayment:
            raise HTTPException(404, f"unknown payment {body.paymentId!r}") from None
        except (AttackNotApplicable, ActionNotAllowed) as err:
            raise HTTPException(409, str(err)) from None
        except ScenarioBusy:
            raise HTTPException(409, "a scenario is running; wait for it to finish or POST /v1/reset") from None
        except ChainUnavailable as err:
            raise HTTPException(503, f"the chain did not answer during {err.step}") from None

    @app.post("/v1/rails/{route_id}/webhook")
    async def rail_webhook(route_id: str, body: WebhookBody, request: Request) -> dict[str, Any]:
        try:
            return orch(request).rail_webhook(route_id, body.model_dump())
        except UnknownRoute:
            raise HTTPException(404, f"unknown route {route_id!r}; expected R1, R2, R3 or R4") from None

    @app.get("/v1/rails/{route_id}/reconcile")
    async def rail_reconcile(route_id: str, request: Request) -> dict[str, Any]:
        try:
            return orch(request).rail_reconcile(route_id)
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
