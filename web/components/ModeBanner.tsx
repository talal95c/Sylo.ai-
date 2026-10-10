import type { SystemMode } from "@/lib/events";
import type { ConnectionStatus, SourceKind } from "@/lib/source";

interface ModeBannerProps {
  mode: SystemMode | null;
  source: SourceKind;
  connection: ConnectionStatus;
  fallback: boolean;
}

const DEGRADED_TEXT: Record<string, string> = {
  risk: "risk model unavailable, rules only",
  chain: "Avalanche Fuji unavailable, chain simulated",
  llm: "language model unavailable",
};

export default function ModeBanner({ mode, source, connection, fallback }: ModeBannerProps) {
  const degraded = mode?.degraded ?? [];
  const warning = fallback || degraded.length > 0;
  const sourceText =
    source === "replay"
      ? "replay"
      : connection === "open"
        ? "live engine"
        : connection === "connecting"
          ? "live engine (connecting…)"
          : "live engine (offline)";

  return (
    <section className={`panel mode-banner${warning ? " mode-banner--warning" : ""}`} aria-label="System mode">
      <p className="mode-banner__line">
        Risk: {mode?.risk ?? "rules"} · Chain: {mode?.chain === "fuji" ? "Avalanche Fuji" : "simulated"} · Rails:{" "}
        {mode?.rails ?? "simulated"} · Source: {sourceText}
      </p>
      {fallback && (
        <p className="mode-banner__warning" role="status">
          Engine offline: replaying recorded events
        </p>
      )}
      {degraded.length > 0 && (
        <p className="mode-banner__warning" role="status">
          Stricter mode: {degraded.map((d) => DEGRADED_TEXT[d] ?? d).join("; ")}
        </p>
      )}
      <p className="mode-banner__note">Synthetic data · nothing here moves real money</p>
    </section>
  );
}
