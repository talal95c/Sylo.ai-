import type { SyloEvent } from "./events";

export type SourceKind = "live" | "replay";
export type ScenarioName = "legit" | "diverted";

export interface SourceCallbacks {
  onEvent(event: SyloEvent): void;
  onStatus(status: {
    kind: SourceKind;
    connected: boolean;
    notice?: string;
  }): void;
}

export interface Source {
  kind: SourceKind;
  start(callbacks: SourceCallbacks): void;
  stop(): void;
  runScenario(name: ScenarioName, opts: { speed: number }): Promise<void>;
  supplierResponse(
    paymentId: string,
    answer: "confirm" | "deny",
  ): Promise<void>;
  attack(paymentId: string): Promise<void>;
  reset(): Promise<void>;
}

function isEvent(value: unknown): value is SyloEvent {
  if (typeof value !== "object" || value === null) return false;
  const event = value as Record<string, unknown>;
  return (
    typeof event.type === "string" &&
    typeof event.seq === "number" &&
    typeof event.ts === "string" &&
    typeof event.data === "object" &&
    event.data !== null
  );
}

async function post(
  engineUrl: string,
  pathname: string,
  body?: Record<string, unknown>,
): Promise<void> {
  const response = await fetch(`${engineUrl.replace(/\/$/, "")}${pathname}`, {
    method: "POST",
    ...(body
      ? {
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        }
      : {}),
  });
  if (!response.ok) {
    throw new Error(`Engine request failed (${response.status})`);
  }
}

export function createLiveSource(engineUrl: string): Source {
  let eventSource: EventSource | null = null;
  let callbacks: SourceCallbacks | null = null;

  return {
    kind: "live",
    start(nextCallbacks) {
      callbacks = nextCallbacks;
      eventSource?.close();
      eventSource = new EventSource(
        `${engineUrl.replace(/\/$/, "")}/v1/stream`,
      );
      eventSource.onopen = () => {
        callbacks?.onStatus({ kind: "live", connected: true });
      };
      eventSource.onmessage = (message) => {
        try {
          const event: unknown = JSON.parse(message.data);
          if (isEvent(event)) callbacks?.onEvent(event);
        } catch {
          callbacks?.onStatus({
            kind: "live",
            connected: false,
            notice: "The engine sent an invalid event.",
          });
        }
      };
      eventSource.onerror = () => {
        callbacks?.onStatus({ kind: "live", connected: false });
      };
    },
    stop() {
      eventSource?.close();
      eventSource = null;
      callbacks = null;
    },
    runScenario(name, opts) {
      return post(engineUrl, `/v1/scenarios/${name}/run`, {
        speed: opts.speed,
        auto: false,
      });
    },
    supplierResponse(paymentId, answer) {
      return post(
        engineUrl,
        `/v1/payments/${encodeURIComponent(paymentId)}/supplier-response`,
        { answer },
      );
    },
    attack(paymentId) {
      return post(engineUrl, "/v1/attacks/release_revoked", { paymentId });
    },
    reset() {
      return post(engineUrl, "/v1/reset");
    },
  };
}

const fixtureFiles = {
  legit: "scene1-legit.jsonl",
  diverted: "scene2-diverted.jsonl",
  deny: "scene2-deny.jsonl",
  confirm: "scene2-confirm.jsonl",
  attack: "scene2b-release-revoked.jsonl",
} as const;

async function loadFixture(file: string): Promise<SyloEvent[]> {
  const response = await fetch(`/spec/fixtures/${file}`);
  if (!response.ok) {
    throw new Error(`Unable to load replay fixture (${response.status})`);
  }

  const contents = await response.text();
  return contents
    .split(/\r?\n/)
    .filter(Boolean)
    .map((line) => {
      const event: unknown = JSON.parse(line);
      if (!isEvent(event)) throw new Error("Invalid event in replay fixture");
      return event;
    });
}

export function createReplaySource(): Source {
  let callbacks: SourceCallbacks | null = null;
  let lastSeq = 0;
  let lastTimestamp: number | null = null;
  let speed = 1;
  let generation = 0;
  let timer: ReturnType<typeof setTimeout> | null = null;
  let resolveTimer: (() => void) | null = null;

  function cancelPending() {
    generation += 1;
    if (timer !== null) clearTimeout(timer);
    timer = null;
    resolveTimer?.();
    resolveTimer = null;
  }

  function wait(milliseconds: number, token: number): Promise<void> {
    if (token !== generation || milliseconds <= 0) return Promise.resolve();
    return new Promise((resolve) => {
      resolveTimer = resolve;
      timer = setTimeout(() => {
        timer = null;
        resolveTimer = null;
        resolve();
      }, milliseconds);
    });
  }

  async function playFixture(
    file: string,
    resetClock: boolean,
  ): Promise<void> {
    cancelPending();
    const token = generation;
    const events = await loadFixture(file);
    if (token !== generation || !callbacks || events.length === 0) return;
    if (resetClock) lastTimestamp = null;
    const offset = lastSeq + 1 - events[0].seq;

    for (const event of events) {
      if (token !== generation || !callbacks) return;
      const timestamp = Date.parse(event.ts);
      const elapsed =
        lastTimestamp === null ? 0 : Math.max(0, timestamp - lastTimestamp);
      await wait(elapsed / speed, token);
      if (token !== generation || !callbacks) return;
      const seq = event.seq + offset;
      callbacks.onEvent({
        ...event,
        seq,
        id: `evt-${String(seq).padStart(6, "0")}`,
      });
      lastSeq = seq;
      lastTimestamp = timestamp;
    }
  }

  return {
    kind: "replay",
    start(nextCallbacks) {
      callbacks = nextCallbacks;
      callbacks.onStatus({ kind: "replay", connected: true });
    },
    stop() {
      cancelPending();
      callbacks = null;
    },
    runScenario(name, opts) {
      speed = opts.speed;
      return playFixture(fixtureFiles[name], true);
    },
    supplierResponse(paymentId, answer) {
      if (!paymentId) return Promise.resolve();
      return playFixture(
        answer === "deny" ? fixtureFiles.deny : fixtureFiles.confirm,
        false,
      );
    },
    attack(paymentId) {
      if (!paymentId) return Promise.resolve();
      return playFixture(fixtureFiles.attack, false);
    },
    async reset() {
      cancelPending();
      lastTimestamp = null;
      lastSeq += 1;
      callbacks?.onEvent({
        v: 1,
        seq: lastSeq,
        id: `evt-${String(lastSeq).padStart(6, "0")}`,
        ts: new Date().toISOString(),
        type: "session.reset",
        paymentId: null,
        simulated: false,
        data: {},
      });
    },
  };
}
