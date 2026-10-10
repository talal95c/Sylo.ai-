import json

from fastapi import FastAPI, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from api.events import event_bus
from api.routes import router

app = FastAPI(title="Sylo.ai API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(router, prefix="/v1")


@app.get("/v1/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/v1/stream")
async def stream(last_event_id: int | None = Header(default=None, alias="Last-Event-ID")):
    async def events():
        async for event in event_bus.stream(last_event_id):
            if event is None:
                yield ": keep-alive\n\n"
            else:
                yield (
                    f"id: {event['id']}\n"
                    f"event: {event['type']}\n"
                    f"data: {json.dumps(event, separators=(',', ':'))}\n\n"
                )

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
