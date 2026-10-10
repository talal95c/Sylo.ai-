# Sylo.ai — web (Lane D)

The demo screen: a 3D globe that draws the engine's events. The web app never decides anything; it only renders what the event stream says.

## Run

```bash
pnpm install
pnpm dev            # http://localhost:3000 (copies ../spec/geo and ../spec/fixtures to public/spec first)
```

Start the engine too (`make dev` at the repo root starts both). Without an engine, the page switches to replay and shows "Engine offline: replaying recorded events".

| Variable | Default | Meaning |
|---|---|---|
| `NEXT_PUBLIC_ENGINE_URL` | `http://localhost:8000` | Engine base URL (stream on `/v1/stream`) |
| `NEXT_PUBLIC_SOURCE` | `live` | `live` (engine) or `replay` (recorded fixtures) |

## Checks

```bash
pnpm typecheck && pnpm test && pnpm build
```

`pnpm test` replays every fixture in `spec/fixtures` through the reducer and checks the final payment status.

## Layout

| Path | Role |
|---|---|
| `lib/events.ts` | Types mirroring `spec/events.schema.json` |
| `lib/store.ts` | Pure reducer: events → view state, plus the one-line feed text |
| `lib/source.ts` | `LiveSource` (server-sent events) and `ReplaySource` (fixtures), with the automatic fallback |
| `components/GlobeCanvas.tsx` | The only file that imports `react-globe.gl` (loaded client-side by `GlobeStage`) |
| `components/*` | Payment card, alert overlay, event feed, demo controls, mode banner |

Interfaces (events, API, colors, globe behaviour) are defined in [`docs/v0-build-spec.md`](../docs/v0-build-spec.md) §4 and §8.
