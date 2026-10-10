/**
 * Where the events come from.
 *
 * - LiveSource: the engine's server-sent-event stream, with the demo buttons calling its API.
 * - ReplaySource: the fixtures recorded by the engine (/spec/fixtures/*.jsonl), played with their
 *   original `ts` gaps divided by the speed.
 *
 * Fallback rule (build spec 8.3): when the stream does not open within 2 s, or drops and is not
 * back within 5 s, LiveSource calls `onUnavailable` and the page switches to ReplaySource.
 */

import { parseEventJson, parseJsonl, SCHEMA_VERSION, type SyloEvent, type SystemModeData } from "./events";

export type SourceKind = "live" | "replay";
export type ScenarioName = "legit" | "diverted";
export type SupplierAnswer = "confirm" | "deny";
export type Connection = "connecting" | "open" | "reconnecting";

export const DEFAULT_ENGINE_URL = "http://localhost:8000";
export const OPEN_TIMEOUT_MS = 2000;
export const RECONNECT_TIMEOUT_MS = 5000;
export const ENGINE_OFFLINE_TEXT = "Engine offline: replaying recorded events";

/** Demo button -> recorded file (build spec 8.3). */
export const FIXTURE_FILES = {
  legit: "scene1-legit.jsonl",
  diverted: "scene2-diverted.jsonl",
  deny: "scene2-deny.jsonl",
  confirm: "scene2-confirm.jsonl",
  attack: "scene2b-release-revoked.jsonl",
} as const;

/** How the fixtures are recorded (`make fixtures`, build spec 4.8): rules-based risk and the mock chain. */
export const RECORDED_MODE: SystemModeData = { risk: "rules", chain: "mock", llm: "off", rails: "simulated", degraded: [] };

export interface SourceHandlers {
  onEvent: (event: SyloEvent) => void;
  onConnection?: (connection: Connection) => void;
  onUnavailable?: (reason: string) => void;
}

export interface DemoSource {
  readonly kind: SourceKind;
  start(): void;
  stop(): void;
  setSpeed(speed: number): void;
  runScenario(name: ScenarioName): Promise<void>;
  supplierResponse(paymentId: string | null, answer: SupplierAnswer): Promise<void>;
  attackReleaseRevoked(paymentId: string | null): Promise<void>;
  reset(): Promise<void>;
}

/** A session-level event made by the page itself (view reset, mode of the replay source). Never sent anywhere. */
export function localEvent(type: "session.reset" | "system.mode", data: Record<string, unknown> | SystemModeData): SyloEvent {
  return {
    v: SCHEMA_VERSION,
    seq: 0,
    id: "evt-000000",
    ts: new Date().toISOString(),
    type,
    paymentId: null,
    simulated: false,
    data,
  } as SyloEvent;
}

/** Wait before each event of a recorded file: 0 for the first, then the original `ts` gap divided by the speed. */
export function replayDelays(events: readonly SyloEvent[], speed: number): number[] {
  const rate = speed > 0 ? speed : 1;
  return events.map((event, index) => {
    if (index === 0) return 0;
    const gap = Date.parse(event.ts) - Date.parse(events[index - 1].ts);
    return Number.isFinite(gap) && gap > 0 ? gap / rate : 0;
  });
}

// ---------------------------------------------------------------- live engine

export class LiveSource implements DemoSource {
  readonly kind = "live" as const;
  private stream: EventSource | null = null;
  private stopped = true;
  private opened = false;
  private deadline: ReturnType<typeof setTimeout> | null = null;
  private retry: ReturnType<typeof setTimeout> | null = null;

  constructor(
    private readonly baseUrl: string,
    private readonly handlers: SourceHandlers,
    private speed = 1,
  ) {}

  start(): void {
    this.stopped = false;
    this.opened = false;
    this.armDeadline(OPEN_TIMEOUT_MS, "the event stream did not open within 2 s");
    this.connect();
  }

  stop(): void {
    this.stopped = true;
    this.clearTimers();
    this.closeStream();
  }

  setSpeed(speed: number): void {
    this.speed = speed > 0 ? speed : 1;
  }

  runScenario(name: ScenarioName): Promise<void> {
    return this.post(`/v1/scenarios/${name}/run`, { speed: this.speed, auto: false });
  }

  supplierResponse(paymentId: string | null, answer: SupplierAnswer): Promise<void> {
    if (!paymentId) return Promise.reject(new Error("no payment is waiting for an answer"));
    return this.post(`/v1/payments/${encodeURIComponent(paymentId)}/supplier-response`, { answer });
  }

  attackReleaseRevoked(paymentId: string | null): Promise<void> {
    if (!paymentId) return Promise.reject(new Error("no payment to attack"));
    return this.post("/v1/attacks/release_revoked", { paymentId });
  }

  reset(): Promise<void> {
    return this.post("/v1/reset");
  }

  private connect(): void {
    if (this.stopped) return;
    this.closeStream();
    let stream: EventSource;
    try {
      stream = new EventSource(`${this.baseUrl}/v1/stream`);
    } catch {
      this.scheduleRetry();
      return;
    }
    this.stream = stream;
    stream.onopen = () => {
      if (this.stream !== stream) return;
      this.opened = true;
      this.clearDeadline();
      this.handlers.onConnection?.("open");
    };
    stream.onmessage = (message: MessageEvent) => {
      if (this.stream !== stream) return;
      const event = parseEventJson(String(message.data));
      if (event) this.handlers.onEvent(event);
    };
    stream.onerror = () => {
      if (this.stream !== stream || this.stopped) return;
      // Always reconnect with a fresh EventSource. A native reconnect sends `Last-Event-ID`, and
      // after an engine restart (seq starts again at 1) the engine would then skip every event up
      // to that stale id. A fresh connection gets `system.mode` and the whole session buffer; the
      // reducer drops what it has already seen.
      this.closeStream();
      if (this.opened && this.deadline === null) {
        this.handlers.onConnection?.("reconnecting");
        this.armDeadline(RECONNECT_TIMEOUT_MS, "the event stream dropped and did not come back within 5 s");
      }
      this.scheduleRetry();
    };
  }

  private scheduleRetry(): void {
    if (this.stopped || this.retry !== null) return;
    this.retry = setTimeout(
      () => {
        this.retry = null;
        this.connect();
      },
      this.opened ? 1000 : 500,
    );
  }

  private armDeadline(ms: number, reason: string): void {
    this.clearDeadline();
    this.deadline = setTimeout(() => {
      this.deadline = null;
      if (this.stopped) return;
      this.stop();
      this.handlers.onUnavailable?.(reason);
    }, ms);
  }

  private clearDeadline(): void {
    if (this.deadline !== null) clearTimeout(this.deadline);
    this.deadline = null;
  }

  private clearTimers(): void {
    this.clearDeadline();
    if (this.retry !== null) clearTimeout(this.retry);
    this.retry = null;
  }

  private closeStream(): void {
    if (this.stream) {
      this.stream.onopen = null;
      this.stream.onmessage = null;
      this.stream.onerror = null;
      this.stream.close();
    }
    this.stream = null;
  }

  private async post(path: string, body?: unknown): Promise<void> {
    let response: Response;
    try {
      response = await fetch(`${this.baseUrl}${path}`, {
        method: "POST",
        headers: body === undefined ? undefined : { "Content-Type": "application/json" },
        body: body === undefined ? undefined : JSON.stringify(body),
      });
    } catch {
      throw new Error("the engine did not answer");
    }
    if (!response.ok) throw new Error(await errorMessage(response));
  }
}

/** Engine errors are 404/409 with `{ "detail": "<message>" }`. */
async function errorMessage(response: Response): Promise<string> {
  try {
    const body: unknown = await response.json();
    if (typeof body === "object" && body !== null && typeof (body as { detail?: unknown }).detail === "string") {
      return `${(body as { detail: string }).detail} (HTTP ${response.status})`;
    }
  } catch {
    // not JSON: fall through
  }
  return `HTTP ${response.status}`;
}

// ---------------------------------------------------------------- recorded fixtures

export class ReplaySource implements DemoSource {
  readonly kind = "replay" as const;
  private stopped = true;
  private generation = 0;
  private timer: ReturnType<typeof setTimeout> | null = null;
  private modeTimer: ReturnType<typeof setTimeout> | null = null;
  private readonly cache = new Map<string, Promise<SyloEvent[]>>();

  constructor(
    private readonly handlers: SourceHandlers,
    private speed = 1,
    private readonly basePath = "/spec/fixtures",
  ) {}

  start(): void {
    this.stopped = false;
    // The recorded files carry no `system.mode` (seq 0 is not stored): say how they were recorded.
    this.modeTimer = setTimeout(() => {
      this.modeTimer = null;
      if (!this.stopped) this.handlers.onEvent(localEvent("system.mode", RECORDED_MODE));
    }, 0);
  }

  stop(): void {
    this.stopped = true;
    this.cancel();
    if (this.modeTimer !== null) clearTimeout(this.modeTimer);
    this.modeTimer = null;
  }

  setSpeed(speed: number): void {
    this.speed = speed > 0 ? speed : 1;
  }

  runScenario(name: ScenarioName): Promise<void> {
    return this.play(name === "legit" ? FIXTURE_FILES.legit : FIXTURE_FILES.diverted);
  }

  supplierResponse(_paymentId: string | null, answer: SupplierAnswer): Promise<void> {
    return this.play(answer === "confirm" ? FIXTURE_FILES.confirm : FIXTURE_FILES.deny);
  }

  attackReleaseRevoked(): Promise<void> {
    return this.play(FIXTURE_FILES.attack);
  }

  reset(): Promise<void> {
    this.cancel();
    if (!this.stopped) this.handlers.onEvent(localEvent("session.reset", {}));
    return Promise.resolve();
  }

  private cancel(): void {
    this.generation += 1;
    if (this.timer !== null) clearTimeout(this.timer);
    this.timer = null;
  }

  private load(file: string): Promise<SyloEvent[]> {
    let pending = this.cache.get(file);
    if (!pending) {
      pending = fetch(`${this.basePath}/${file}`).then(async (response) => {
        if (!response.ok) throw new Error(`recorded file ${file} is not available (HTTP ${response.status}); run \`pnpm sync-spec\``);
        const events = parseJsonl(await response.text());
        if (events.length === 0) throw new Error(`recorded file ${file} holds no events`);
        return events;
      });
      pending.catch(() => this.cache.delete(file));
      this.cache.set(file, pending);
    }
    return pending;
  }

  /** Resolves when the playback has started (or was replaced by another one). */
  private async play(file: string): Promise<void> {
    this.cancel();
    const generation = this.generation;
    const events = await this.load(file);
    if (this.stopped || generation !== this.generation) return;

    const step = (index: number): void => {
      if (this.stopped || generation !== this.generation) return;
      this.handlers.onEvent(this.atPlaybackSpeed(events[index]));
      const next = index + 1;
      if (next >= events.length) return;
      // Computed at each step, so a speed change applies to the rest of the file.
      const delay = replayDelays([events[index], events[next]], this.speed)[1];
      this.timer = setTimeout(() => step(next), delay);
    };
    step(0);
  }

  /**
   * `scenario.started.speed` is the speed of the run. A file recorded at speed 1 and played at 2x
   * runs at 2: the copy sent to the page says so, which keeps `durationMs / speed` true for the
   * comet. The recorded event itself is not changed.
   */
  private atPlaybackSpeed(event: SyloEvent): SyloEvent {
    if (event.type !== "scenario.started" || this.speed === 1) return event;
    const recorded = Number((event.data as { speed?: unknown }).speed);
    const speed = (Number.isFinite(recorded) && recorded > 0 ? recorded : 1) * this.speed;
    return { ...event, data: { ...event.data, speed } } as SyloEvent;
  }
}
