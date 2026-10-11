export const engineUrl =
  process.env.NEXT_PUBLIC_ENGINE_URL ?? "http://localhost:8000";

export const engineConnectTimeoutMs =
  Number(process.env.NEXT_PUBLIC_ENGINE_CONNECT_TIMEOUT_MS) || 2000;

export function wakeEngine(): void {
  if (process.env.NEXT_PUBLIC_SOURCE === "replay") return;

  void fetch(`${engineUrl.replace(/\/$/, "")}/health`, {
    cache: "no-store",
  }).catch(() => {});
}
