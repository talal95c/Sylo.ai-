"""FastAPI app: the engine's HTTP API and server-sent-event stream (spec/api.md).

    uv run uvicorn sylo.main:app --port 8000
"""

import asyncio
import json
import logging
from dataclasses import dataclass, replace
from typing import Any, AsyncIterator, Literal, Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from . import __version__
from .bus import EventBus
from .config import Settings, load_settings
from .orchestrator import Conflict, NotFound, Orchestrator
from .pacer import RealPacer
from .ports_loader import Ports, load_ports
from .signer import Signer

log = logging.getLogger("sylo")
HEARTBEAT_SECONDS = 15


@dataclass
class Core:
    settings: Settings
    pacer: Any
    ports: Ports
    signer: Signer
    bus: EventBus
    orchestrator: Orchestrator


def build_core(settings: Optional[Settings] = None, pacer: Any = None) -> Core:
    """Wire the engine. Missing real components fall back to mocks and are reported as degraded."""
    settings = settings or load_settings()
    pacer = pacer or RealPacer(settings.demo_speed)
    degraded: list[str] = []
    try:
        signer = Signer(settings)
    except RuntimeError as err:
        # Real keys are missing: fall back to the mock chain with the public dev keys.
        log.warning("%s; falling back to the mock chain", err)
        settings = replace(settings, chain_mode="mock")
        signer = Signer(settings)
        degraded.append("chain")
    ports = load_ports(settings, clock=lambda: pacer.now().timestamp(), addresses=signer.addresses)
    for name in degraded:
        if name not in ports.degraded:
            ports.degraded.append(name)
    bus = EventBus(pacer, ports.mode_data)
    orchestrator = Orchestrator(settings, bus, pacer, ports, signer)
    return Core(settings=settings, pacer=pacer, ports=ports, signer=signer, bus=bus, orchestrator=orchestrator)


class RunBody(BaseModel):
    speed: Optional[float] = Field(default=None, gt=0)
    auto: bool = False
    autoAnswer: Literal["deny", "confirm"] = "deny"


class SupplierResponseBody(BaseModel):
    answer: Literal["confirm", "deny"]


class AttackBody(BaseModel):
    paymentId: str


def _sse(event: dict[str, Any]) -> dict[str, str]:
    return {"id": str(event["seq"]), "data": json.dumps(event, ensure_ascii=False, separators=(",", ":"))}


def create_app(core: Optional[Core] = None) -> FastAPI:
    core = core or build_core()
    app = FastAPI(title="Sylo.ai engine", version=__version__)
    app.state.core = core
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(core.settings.cors_origins),
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["*"],
    )
    orchestrator, bus = core.orchestrator, core.bus

    @app.get("/health")
    async def health() -> dict[str, Any]:
        return {"ok": True, "mode": core.ports.mode_data()}

    @app.get("/v1/stream")
    async def stream(request: Request) -> EventSourceResponse:
        header = request.headers.get("last-event-id", "")
        after = int(header) if header.isdigit() else None
        if after is not None and after > bus.last_seq:
            after = None  # the id comes from a previous engine process: send the whole session

        async def events() -> AsyncIterator[dict[str, str]]:
            queue = bus.subscribe()  # subscribe first, so nothing is lost between the buffer and the live events
            try:
                yield _sse(bus.mode_event())
                sent = after or 0
                for event in bus.events(after):
                    sent = event["seq"]
                    yield _sse(event)
                while True:
                    event = await queue.get()
                    if event["seq"] <= sent:
                        continue
                    sent = event["seq"]
                    yield _sse(event)
            finally:
                bus.unsubscribe(queue)

        return EventSourceResponse(events(), ping=HEARTBEAT_SECONDS)

    @app.post("/v1/scenarios/{name}/run")
    async def run_scenario(name: str, body: Optional[RunBody] = None) -> dict[str, str]:
        body = body or RunBody()
        try:
            payment_id = orchestrator.start(name, speed=body.speed, auto=body.auto, auto_answer=body.autoAnswer)
        except NotFound as err:
            raise HTTPException(status_code=404, detail=str(err)) from err
        except Conflict as err:
            raise HTTPException(status_code=409, detail=str(err)) from err
        return {"paymentId": payment_id}

    @app.post("/v1/payments/{payment_id}/supplier-response")
    async def supplier_response(payment_id: str, body: SupplierResponseBody) -> dict[str, bool]:
        try:
            orchestrator.supplier_response(payment_id, body.answer)
        except NotFound as err:
            raise HTTPException(status_code=404, detail=str(err)) from err
        except Conflict as err:
            raise HTTPException(status_code=409, detail=str(err)) from err
        return {"ok": True}

    @app.post("/v1/attacks/{name}")
    async def attack(name: str, body: AttackBody) -> dict[str, Any]:
        try:
            return await orchestrator.attack(name, body.paymentId)
        except NotFound as err:
            raise HTTPException(status_code=404, detail=str(err)) from err
        except Conflict as err:
            raise HTTPException(status_code=409, detail=str(err)) from err

    @app.post("/v1/reset")
    async def reset() -> dict[str, bool]:
        await orchestrator.reset()
        return {"ok": True}

    @app.get("/v1/payments/{payment_id}")
    async def payment(payment_id: str) -> dict[str, Any]:
        try:
            return await asyncio.to_thread(orchestrator.payment_view, payment_id)
        except NotFound as err:
            raise HTTPException(status_code=404, detail=str(err)) from err

    return app


app = create_app()
