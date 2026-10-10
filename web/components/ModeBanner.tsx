import type { SystemModeData } from "@/lib/events";
import { ENGINE_OFFLINE_TEXT, type Connection, type SourceKind } from "@/lib/source";

interface Props {
  mode: SystemModeData | null;
  sourceKind: SourceKind;
  connection: Connection;
  /** True when replay was entered because the engine could not be reached. */
  engineOffline: boolean;
}

function sourceLabel(sourceKind: SourceKind, connection: Connection): string {
  if (sourceKind === "replay") return "replay";
  if (connection === "open") return "live engine";
  if (connection === "reconnecting") return "live engine (reconnecting…)";
  return "connecting to the engine…";
}

/** "Risk: rules · Chain: simulated · Rails: simulated · Source: live engine"; amber when something is degraded. */
export default function ModeBanner({ mode, sourceKind, connection, engineOffline }: Props) {
  const degraded = mode?.degraded ?? [];
  const amber = degraded.length > 0 || engineOffline;
  const chain = mode ? (mode.chain === "mock" ? "simulated" : mode.chain) : "…";
  const parts = [
    `Risk: ${mode?.risk ?? "…"}`,
    `Chain: ${chain}`,
    `Rails: ${mode?.rails ?? "…"}`,
    `Source: ${sourceLabel(sourceKind, connection)}`,
  ];
  if (mode && mode.llm !== "off") parts.splice(3, 0, `LLM: ${mode.llm}`);

  return (
    <div
      role="status"
      className={`max-w-[360px] rounded-xl border px-3 py-2 text-xs leading-5 shadow-lg shadow-black/40 backdrop-blur-md ${
        amber ? "border-amber-400/60 bg-amber-950/70 text-amber-100" : "border-white/10 bg-slate-950/75 text-slate-300"
      }`}
    >
      <p className="font-semibold tracking-wide text-slate-100">Sylo.ai</p>
      {engineOffline && <p className="font-semibold text-amber-200">{ENGINE_OFFLINE_TEXT}</p>}
      <p>{parts.join(" · ")}</p>
      {degraded.length > 0 && <p className="text-amber-200">Degraded, running on the safe fallback: {degraded.join(", ")}</p>}
    </div>
  );
}
