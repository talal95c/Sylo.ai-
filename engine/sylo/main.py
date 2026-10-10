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

from .config import Settings
from .orchestrator import (
    AttackNotApplicable,
    NotWaiting,
    Orchestrator,
    ScenarioBusy,
    UnknownAttack,
    UnknownPayment,
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


def _dump(event: dict[str, Any]) -> str:
    return json.dumps(event, ensure_ascii=False, separators=(",", ":"))


def create_app(settings: Settings | None = None, orchestrator: Orchestrator | None = None) -> FastAPI:
    settings = settings or Settings.from_env()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.orchestrator = orchestrator or build_orchestrator(settings)
        yield
        await app.state.orchestrator.reset()

    app = FastAPI(title="Sylo.ai engine", version="0.1.0", lifespan=lifespan)
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
            raise HTTPException(404, f"unknown scenario {name!r}; expected 'legit' or 'diverted'") from None
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

    @app.post("/v1/attacks/{name}")
    async def attack(name: str, body: AttackBody, request: Request) -> dict[str, Any]:
        try:
            return await orch(request).attack(name, body.paymentId)
        except UnknownAttack:
            raise HTTPException(404, f"unknown attack {name!r}; expected 'release_revoked'") from None
        except UnknownPayment:
            raise HTTPException(404, f"unknown payment {body.paymentId!r}") from None
        except AttackNotApplicable as err:
            raise HTTPException(409, str(err)) from None

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

    return app


app = create_app()
