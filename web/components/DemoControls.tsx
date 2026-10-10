import type { ScenarioName, SourceKind, SupplierAnswer } from "@/lib/source";

interface Props {
  /** Which actions apply to the current view (lib/store.ts, availableActions). */
  actions: { run: boolean; supplierAnswer: boolean; attack: boolean };
  /** A request is in flight. */
  busy: boolean;
  sourceKind: SourceKind;
  speed: number;
  /** Last action error (engine 404/409, engine unreachable, missing recording). */
  error: string | null;
  onRun: (scenario: ScenarioName) => void;
  onSupplier: (answer: SupplierAnswer) => void;
  onAttack: () => void;
  onReset: () => void;
  onSpeed: (speed: number) => void;
  onSource: (kind: SourceKind) => void;
}

const BUTTON =
  "rounded-lg border px-3 py-1.5 text-left text-[13px] font-medium transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-sky-400 disabled:cursor-not-allowed disabled:border-white/5 disabled:bg-white/5 disabled:text-slate-500";
const PRIMARY = `${BUTTON} border-sky-400/40 bg-sky-500/15 text-sky-100 hover:bg-sky-500/25`;
const NEUTRAL = `${BUTTON} border-white/15 bg-white/5 text-slate-100 hover:bg-white/10`;
const DANGER = `${BUTTON} border-red-400/40 bg-red-500/15 text-red-100 hover:bg-red-500/25`;

function Toggle<T extends string | number>({ label, value, options, onChange }: { label: string; value: T; options: { value: T; label: string }[]; onChange: (value: T) => void }) {
  return (
    <div role="group" aria-label={label} className="flex items-center gap-2 text-xs text-slate-400">
      <span>{label}</span>
      <div className="flex overflow-hidden rounded-lg border border-white/15">
        {options.map((option) => (
          <button
            key={String(option.value)}
            type="button"
            aria-pressed={option.value === value}
            onClick={() => onChange(option.value)}
            className={`px-2.5 py-1 text-xs font-medium focus-visible:outline focus-visible:outline-2 focus-visible:outline-sky-400 ${
              option.value === value ? "bg-slate-100 text-slate-900" : "bg-transparent text-slate-300 hover:bg-white/10"
            }`}
          >
            {option.label}
          </button>
        ))}
      </div>
    </div>
  );
}

export default function DemoControls({ actions, busy, sourceKind, speed, error, onRun, onSupplier, onAttack, onReset, onSpeed, onSource }: Props) {
  const canRun = actions.run && !busy;
  const canAnswer = actions.supplierAnswer && !busy;
  return (
    <section aria-label="Demo controls" className="w-[340px] rounded-xl border border-white/10 bg-slate-950/75 p-3 shadow-xl shadow-black/40 backdrop-blur-md">
      <h2 className="mb-2 text-sm font-semibold text-slate-100">Demo controls</h2>
      <div className="grid grid-cols-2 gap-2">
        <button type="button" className={PRIMARY} disabled={!canRun} onClick={() => onRun("legit")}>
          Run legit payment
        </button>
        <button type="button" className={PRIMARY} disabled={!canRun} onClick={() => onRun("diverted")}>
          Run diverted invoice
        </button>
        <button type="button" className={NEUTRAL} disabled={!canAnswer} onClick={() => onSupplier("confirm")}>
          Supplier: confirm
        </button>
        <button type="button" className={NEUTRAL} disabled={!canAnswer} onClick={() => onSupplier("deny")}>
          Supplier: deny
        </button>
        <button type="button" className={`${DANGER} col-span-2`} disabled={!actions.attack || busy} onClick={onAttack}>
          Attack: release revoked payment
        </button>
      </div>
      <div className="mt-3 flex flex-wrap items-center justify-between gap-2">
        <button type="button" className={NEUTRAL} onClick={onReset}>
          Reset
        </button>
        <Toggle
          label="Speed"
          value={speed}
          onChange={onSpeed}
          options={[
            { value: 1, label: "1×" },
            { value: 2, label: "2×" },
          ]}
        />
        <Toggle
          label="Source"
          value={sourceKind}
          onChange={onSource}
          options={[
            { value: "live", label: "Live" },
            { value: "replay", label: "Replay" },
          ]}
        />
      </div>
      <p role="status" className="mt-2 min-h-4 text-xs leading-4 text-amber-300">
        {error ?? ""}
      </p>
    </section>
  );
}
