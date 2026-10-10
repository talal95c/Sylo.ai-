// Where events come from: the live engine stream, or the recorded fixtures when the engine is off.
// Both expose the same demo actions; neither decides anything about a payment.
import { parseJsonl, type SyloEvent } from "./events";

export type SourceKind = "live" | "replay";
export type ConnectionStatus = "connecting" | "open" | "offline";
export type ScenarioName = "legit" | "diverted";
export type SupplierAnswer = "confirm" | "deny";

export interface ActionResult {
  ok: boolean;
  message?: string;
}

export interface SourceCallbacks {
  onEvent(event: SyloEvent): void;
  onStatus(status: ConnectionStatus): void;
  /** Live only: the stream did not open within 2 s, or dropped and did not come back within 5 s. */
  onOffline(): void;
  /** Replay only: there is no engine to emit session.reset, so the view is cleared locally. */
  onReset(): void;
}

export interface DemoSource {
  readonly kind: SourceKind;
  start(): void;
  stop(): void;
  runScenario(name: ScenarioName, speed: number): Promise<ActionResult>;
  supplierResponse(paymentId: string, answer: SupplierAnswer, speed: number): Promise<ActionResult>;
  attack(paymentId: string, speed: number): Promise<ActionResult>;
  reset(): Promise<ActionResult>;
}

export const ENGINE_URL = (process.env.NEXT_PUBLIC_ENGINE_URL || "http://localhost:8000").replace(/\/+$/, "");
export const DEFAULT_SOURCE: SourceKind = process.env.NEXT_PUBLIC_SOURCE === "replay" ? "replay" : "live";

const OPEN_TIMEOUT_MS = 2000;
const RECONNECT_TIMEOUT_MS = 5000;

export class LiveSource implements DemoSource {
  readonly kind = "live" as const;
  private stream: EventSource | null = null;
  private openTimer: ReturnType<typeof setTimeout> | null = null;
  private dropTimer: ReturnType<typeof setTimeout> | null = null;
  private opened = false;

  constructor(
    private readonly callbacks: SourceCallbacks,
    private readonly baseUrl: string = ENGINE_URL,
  ) {}

  start(): void {
    this.callbacks.onStatus("connecting");
    // The browser reconnects by itself and sends Last-Event-ID, so the engine only resends newer events.
    const stream = new EventSource(`${this.baseUrl}/v1/stream`);
    this.stream = stream;
    this.openTimer = setTimeout(() => {
      if (!this.opened) this.fail();
    }, OPEN_TIMEOUT_MS);

    stream.onopen = () => {
      this.opened = true;
      this.clearTimers();
      this.callbacks.onStatus("open");
    };
    stream.onmessage = (message: MessageEvent<string>) => {
      let event: SyloEvent;
      try {
        event = JSON.parse(message.data) as SyloEvent;
      } catch {
        return;
      }
      this.callbacks.onEvent(event);
    };
    stream.onerror = () => {
      if (!this.opened) return;
      if (stream.readyState === EventSource.CLOSED) {
        this.fail();
        return;
      }
      this.callbacks.onStatus("connecting");
      this.dropTimer ??= setTimeout(() => this.fail(), RECONNECT_TIMEOUT_MS);
    };
  }

  stop(): void {
    this.clearTimers();
    if (this.stream) {
      this.stream.onopen = null;
      this.stream.onmessage = null;
      this.stream.onerror = null;
      this.stream.close();
      this.stream = null;
    }
  }

  runScenario(name: ScenarioName, speed: number): Promise<ActionResult> {
    return this.post(`/v1/scenarios/${name}/run`, { speed });
  }

  supplierResponse(paymentId: string, answer: SupplierAnswer): Promise<ActionResult> {
    return this.post(`/v1/payments/${encodeURIComponent(paymentId)}/supplier-response`, { answer });
  }

  attack(paymentId: string): Promise<ActionResult> {
    return this.post("/v1/attacks/release_revoked", { paymentId });
  }

  reset(): Promise<ActionResult> {
    return this.post("/v1/reset");
  }

  private fail(): void {
    this.stop();
    this.callbacks.onStatus("offline");
    this.callbacks.onOffline();
  }

  private clearTimers(): void {
    if (this.openTimer) clearTimeout(this.openTimer);
    if (this.dropTimer) clearTimeout(this.dropTimer);
    this.openTimer = null;
    this.dropTimer = null;
  }

  private async post(path: string, body?: unknown): Promise<ActionResult> {
    let response: Response;
    try {
      response = await fetch(`${this.baseUrl}${path}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: body === undefined ? undefined : JSON.stringify(body),
      });
    } catch {
      return { ok: false, message: `The engine at ${this.baseUrl} is not reachable.` };
    }
    if (response.ok) return { ok: true };
    const detail = await response
      .json()
      .then((json: { detail?: unknown }) => json.detail)
      .catch(() => null);
    return {
      ok: false,
      message: typeof detail === "string" ? `Engine: ${detail}` : `The engine refused this action (HTTP ${response.status}).`,
    };
  }
}

const FIXTURES = {
  legit: "scene1-legit",
  diverted: "scene2-diverted",
  deny: "scene2-deny",
  confirm: "scene2-confirm",
  attack: "scene2b-release-revoked",
} as const;

type ReplayStage = "idle" | "playing" | "awaiting_supplier" | "denied" | "finished";

export class ReplaySource implements DemoSource {
  readonly kind = "replay" as const;
  private timers: ReturnType<typeof setTimeout>[] = [];
  private stage: ReplayStage = "idle";
  private active = false;
  private readonly cache = new Map<string, SyloEvent[]>();

  constructor(
    private readonly callbacks: SourceCallbacks,
    private readonly baseUrl: string = "/spec/fixtures",
  ) {}

  start(): void {
    this.active = true;
    this.callbacks.onStatus("open");
  }

  stop(): void {
    this.active = false;
    this.cancel();
  }

  runScenario(name: ScenarioName, speed: number): Promise<ActionResult> {
    if (this.stage === "playing") {
      return Promise.resolve({ ok: false, message: "A recorded scenario is still playing. Wait for it to end or press Reset." });
    }
    return name === "legit"
      ? this.play(FIXTURES.legit, speed, "finished")
      : this.play(FIXTURES.diverted, speed, "awaiting_supplier");
  }

  supplierResponse(_paymentId: string, answer: SupplierAnswer, speed: number): Promise<ActionResult> {
    if (this.stage !== "awaiting_supplier") {
      return Promise.resolve({ ok: false, message: "No recorded payment is waiting for a supplier answer." });
    }
    return answer === "deny"
      ? this.play(FIXTURES.deny, speed, "denied")
      : this.play(FIXTURES.confirm, speed, "finished");
  }

  attack(_paymentId: string, speed: number): Promise<ActionResult> {
    if (this.stage !== "denied") {
      return Promise.resolve({ ok: false, message: "The release attack is recorded only after the supplier denies." });
    }
    return this.play(FIXTURES.attack, speed, "finished");
  }

  reset(): Promise<ActionResult> {
    this.cancel();
    this.stage = "idle";
    this.callbacks.onReset();
    return Promise.resolve({ ok: true });
  }

  /** Plays a fixture with its original gaps between events, divided by the speed. */
  private async play(file: string, speed: number, after: ReplayStage): Promise<ActionResult> {
    let events: SyloEvent[];
    try {
      events = await this.load(file);
    } catch (error) {
      return { ok: false, message: `Recorded events are missing (${(error as Error).message}). Run pnpm sync-spec.` };
    }
    if (!this.active || events.length === 0) return { ok: false, message: "Replay is not running." };
    this.cancel();
    this.stage = "playing";
    const start = Date.parse(events[0].ts);
    events.forEach((event, index) => {
      const delay = Math.max(0, (Date.parse(event.ts) - start) / speed);
      const timer = setTimeout(() => {
        this.callbacks.onEvent(event);
        if (index === events.length - 1) this.stage = after;
      }, delay);
      this.timers.push(timer);
    });
    return { ok: true };
  }

  private async load(file: string): Promise<SyloEvent[]> {
    const cached = this.cache.get(file);
    if (cached) return cached;
    const response = await fetch(`${this.baseUrl}/${file}.jsonl`);
    if (!response.ok) throw new Error(`${file}.jsonl: HTTP ${response.status}`);
    const events = parseJsonl(await response.text());
    this.cache.set(file, events);
    return events;
  }

  private cancel(): void {
    this.timers.forEach(clearTimeout);
    this.timers = [];
  }
}
