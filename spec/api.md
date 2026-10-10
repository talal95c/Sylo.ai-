# Engine API (v0)

Base URL `http://localhost:8000`. JSON everywhere. CORS allows `http://localhost:3000`.
Events are described in [`events.schema.json`](./events.schema.json).

| Method | Path | Body | Response | Errors |
|---|---|---|---|---|
| GET | `/health` | — | `{ ok: true, mode: {...system.mode data} }` | — |
| GET | `/v1/stream` | — | Server-sent events. Each message: `id: <seq>`, `data: <event JSON>`. On connect: one `system.mode` (`seq: 0`), then every event of the current session in order, or only the events after `Last-Event-ID` when the browser reconnects with that header. A comment line is sent every 15 s as a heartbeat | — |
| POST | `/v1/scenarios/{name}/run` | `{ speed?: number = 1, auto?: boolean = false, autoAnswer?: "deny" \| "confirm" = "deny" }` | `{ paymentId }` | 404 unknown name; 409 a scenario is running |
| POST | `/v1/payments/{paymentId}/supplier-response` | `{ answer: "confirm" \| "deny" }` | `{ ok: true }` | 404 unknown payment; 409 not waiting for an answer |
| POST | `/v1/attacks/{name}` | `{ paymentId }` | `{ ok: true, reverted: boolean, reason: string \| null }` | 404 unknown attack or payment; 409 payment not in a state where the attack makes sense |
| POST | `/v1/reset` | — | `{ ok: true }` (cancels the running scenario, clears the session, emits `session.reset`) | — |
| GET | `/v1/payments/{paymentId}` | — | `{ paymentId, status, tier, routeId, chainStatus, lastSeq }` | 404 |

- Scenario names: `legit` (payment `PAY-2026-0001`), `diverted` (payment `PAY-2026-0002`).
- Attack names in v0: `release_revoked` (only when the payment is REVOKED, otherwise 409).
- With `auto: true`, the diverted scenario answers the supplier request itself after 3,000 ms (divided by `speed`) with `deny`, or with `confirm` when `autoAnswer` is `"confirm"`.
- `speed` divides every wait of the scenario (2 = twice as fast).
- Error bodies are `{ "detail": "<message>" }`.

## Stream details

- `seq` increases by one for every stored event and never restarts while the engine runs. `/v1/reset` clears the session buffer; the `session.reset` event is the first event of the new session.
- The `system.mode` message sent on each connection has `seq: 0`, `id: "evt-000000"` and is not stored.
- `status` in `GET /v1/payments/{id}` is one of `deciding`, `committed`, `in_transit`, `held`, `awaiting_supplier`, `revoked`, `refunded`, `stopped`, `released`, `credited`.
  `chainStatus` is the registry status name (`NONE`, `COMMITTED`, `CONFIRMED`, `DENIED`, `REVOKED`, `EXECUTED`).
