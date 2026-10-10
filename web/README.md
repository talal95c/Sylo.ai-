# /web — Lane D (experience)

**Owner:** Lane D. Next.js app (App Router, TypeScript, Tailwind) with the 3D globe.
**The web draws events; it never decides.** Every sentence about a payment comes from the engine's events.

```bash
pnpm -C web install
pnpm -C web dev          # http://localhost:3000 (the engine must run on :8000, or the app replays fixtures)
pnpm -C web typecheck && pnpm -C web test && pnpm -C web lint && pnpm -C web build
```

| File | Role |
|---|---|
| `lib/events.ts` | TypeScript mirror of `spec/events.schema.json` |
| `lib/store.ts` | Pure reducer: events → view state (tested on every recorded fixture) |
| `lib/source.ts` | `LiveSource` (EventSource on the engine) and `ReplaySource` (fixtures), with automatic fallback to replay |
| `lib/geo.ts`, `lib/colors.ts` | Institutions and great-circle helpers; tier and hop colours |
| `components/GlobeStage.tsx` | Turns events into what the globe shows (routes, comet, lock, refund, revert) |
| `components/GlobeCanvas.tsx` | The only file that imports `react-globe.gl` (loaded client-side only) |
| `components/PaymentCard.tsx`, `AlertOverlay.tsx`, `EventFeed.tsx`, `DemoControls.tsx`, `ModeBanner.tsx` | The panels around the globe |
| `scripts/sync-spec.mjs` | Copies `../spec/geo` and `../spec/fixtures` into `public/spec/` (git-ignored) before dev, build, typecheck and test |

Environment: `NEXT_PUBLIC_ENGINE_URL` (default `http://localhost:8000`), `NEXT_PUBLIC_SOURCE` (`live` by default, or `replay`).
The engine's CORS allows `http://localhost:3000` only: on another port the app falls back to replay.

`<GlobeStage events={events} />` takes every event applied since the last reset, in order. It resets itself on
`scenario.started` and `session.reset`. Only the newest event of a batch animates, so a replayed buffer lands on its
final picture. With `prefers-reduced-motion`, comets and camera moves are skipped.

Tasks for v1 and later: [`docs/roadmap-and-lanes.md`](../docs/roadmap-and-lanes.md) (D1.1 to D1.6).
