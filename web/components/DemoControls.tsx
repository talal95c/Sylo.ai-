import type { ScenarioName, SourceKind, SupplierAnswer } from "@/lib/source";

interface DemoControlsProps {
  canRun: boolean;
  canAnswer: boolean;
  canAttack: boolean;
  speed: number;
  source: SourceKind;
  notice: string | null;
  onRun(name: ScenarioName): void;
  onAnswer(answer: SupplierAnswer): void;
  onAttack(): void;
  onReset(): void;
  onSpeed(speed: number): void;
  onSource(source: SourceKind): void;
}

function Segmented<T extends string | number>({
  label,
  value,
  options,
  onChange,
}: {
  label: string;
  value: T;
  options: { value: T; text: string }[];
  onChange(value: T): void;
}) {
  return (
    <div className="segmented" role="group" aria-label={label}>
      <span className="segmented__label">{label}</span>
      {options.map((option) => (
        <button
          key={String(option.value)}
          type="button"
          className="segmented__option"
          aria-pressed={option.value === value}
          onClick={() => onChange(option.value)}
        >
          {option.text}
        </button>
      ))}
    </div>
  );
}

export default function DemoControls(props: DemoControlsProps) {
  const { canRun, canAnswer, canAttack, speed, source, notice } = props;
  return (
    <section className="panel controls" aria-label="Demo controls">
      <h2 className="controls__title">Demo controls</h2>
      <div className="controls__group">
        <button type="button" className="button button--primary" disabled={!canRun} onClick={() => props.onRun("legit")}>
          Run legit payment
        </button>
        <button type="button" className="button button--primary" disabled={!canRun} onClick={() => props.onRun("diverted")}>
          Run diverted invoice
        </button>
      </div>
      <div className="controls__group controls__group--pair">
        <button type="button" className="button" disabled={!canAnswer} onClick={() => props.onAnswer("confirm")}>
          Supplier: confirm
        </button>
        <button type="button" className="button" disabled={!canAnswer} onClick={() => props.onAnswer("deny")}>
          Supplier: deny
        </button>
      </div>
      <div className="controls__group">
        <button type="button" className="button button--danger" disabled={!canAttack} onClick={props.onAttack}>
          Attack: release revoked payment
        </button>
        <button type="button" className="button button--quiet" onClick={props.onReset}>
          Reset
        </button>
      </div>
      <div className="controls__toggles">
        <Segmented
          label="Speed"
          value={speed}
          options={[
            { value: 1, text: "1×" },
            { value: 2, text: "2×" },
          ]}
          onChange={props.onSpeed}
        />
        <Segmented
          label="Source"
          value={source}
          options={[
            { value: "live", text: "Live" },
            { value: "replay", text: "Replay" },
          ]}
          onChange={props.onSource}
        />
      </div>
      <p className="controls__notice" role="status">
        {notice}
      </p>
    </section>
  );
}
