# Sylo.ai engine API (v0)

Base URL `http://localhost:8000`. JSON everywhere. CORS allows `http://localhost:3000` (env `CORS_ORIGINS`).
Event payloads are defined in [`events.schema.json`](events.schema.json). Changes to this file follow the rules in [`README.md`](README.md): additive only.

| Method | Path | Body | Response | Errors |
|---|---|---|---|---|
| GET | `/health` | — | `{ "ok": true, "mode": { ...system.mode data } }` | — |
| GET | `/v1/stream` | — | Server-sent events (see below) | — |
| POST | `/v1/scenarios/{name}/run` | `{ "speed"?: number = DEMO_SPEED, "auto"?: boolean = false, "autoAnswer"?: "confirm" \| "deny" = "deny" }` | `{ "paymentId": "PAY-2026-0001" }` | 404 unknown name; 409 a scenario is running |
| POST | `/v1/payments/{paymentId}/supplier-response` | `{ "answer": "confirm" \| "deny" }` | `{ "ok": true }` | 404 unknown payment; 409 not waiting for an answer |
| POST | `/v1/attacks/{name}` | `{ "paymentId": "PAY-2026-0002" }` | `{ "ok": true, "reverted": boolean, "reason": string \| null }` | 404 unknown attack or payment; 409 payment not in a state where the attack makes sense |
| POST | `/v1/reset` | — | `{ "ok": true }` — cancels the running scenario and emits `session.reset` | — |
| GET | `/v1/payments/{paymentId}` | — | `{ "paymentId", "status", "tier", "routeId", "chainStatus", "lastSeq" }` | 404 |

- Scenario names: `legit` (PAY-2026-0001), `diverted` (PAY-2026-0002).
- Attack names in v0: `release_revoked` (only when the payment is revoked on-chain).
- With `auto: true`, the diverted scenario answers the supplier request itself after 3,000 ms (divided by `speed`) with `autoAnswer`.
- `status` in `GET /v1/payments/{id}` is one of `deciding`, `in_transit`, `held`, `awaiting_supplier`, `stopped`, `credited`; `chainStatus` is the registry status name (`NONE` … `EXECUTED`).

## Stream (`GET /v1/stream`)

Each message is

```
id: <seq>
data: <event JSON on one line>
```

On connect the engine sends one `system.mode` event (`seq: 0`, no `id:` line, not stored in the session), then every event of the current session in order — or only the events after `Last-Event-ID` when the browser reconnects with that header — then live events. A heartbeat comment is sent every 15 s.

`seq` keeps increasing for the life of the engine process (a reset does not restart it); `system.mode.data.bootId` changes when the engine restarts, so a client can tell that it must forget what it has seen.

## Example

```bash
curl -N http://localhost:8000/v1/stream &
curl -X POST http://localhost:8000/v1/scenarios/diverted/run -H 'content-type: application/json' -d '{"speed": 2}'
curl -X POST http://localhost:8000/v1/payments/PAY-2026-0002/supplier-response -H 'content-type: application/json' -d '{"answer": "deny"}'
curl -X POST http://localhost:8000/v1/attacks/release_revoked -H 'content-type: application/json' -d '{"paymentId": "PAY-2026-0002"}'
```
