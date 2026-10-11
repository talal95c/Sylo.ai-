import type { SyloEvent } from "./events";

export type SourceKind = "live" | "replay";
export type ScenarioName = "legit" | "diverted" | "muleWave" | "guardian" | "outage";
export type AttackName = "release_revoked" | "swap_beneficiary" | "replay";

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
  attack(paymentId: string, name: AttackName): Promise<void>;
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
      if (name === "muleWave") {
        return post(engineUrl, "/v1/sim/mule-wave", {
          speed: opts.speed,
          auto: true,
        });
      }
      if (name === "guardian") {
        return Promise.reject(new Error("Guardian incidents are reported by the guardian service; use Replay for the recorded scene."));
      }
      return post(engineUrl, `/v1/scenarios/${name}/run`, {
        speed: opts.speed,
        auto: name === "outage",
      });
    },
    supplierResponse(paymentId, answer) {
      return post(
        engineUrl,
        `/v1/payments/${encodeURIComponent(paymentId)}/supplier-response`,
        { answer },
      );
    },
    attack(paymentId, name) {
      return post(engineUrl, `/v1/attacks/${name}`, { paymentId });
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
  swap: "scene2b-swap-beneficiary.jsonl",
  replayAttack: "scene2b-replay.jsonl",
  muleWave: "samples-scene3-mule-wave.jsonl",
  guardian: "samples-scene4-guardian.jsonl",
  outage: "samples-scene5-outage.jsonl",
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

  function waitUntil(deadline: number, token: number): Promise<void> {
    const milliseconds = Math.max(0, deadline - performance.now());
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
    firstEventDelayMs?: number,
  ): Promise<void> {
    cancelPending();
    const token = generation;
    const events = await loadFixture(file);
    if (token !== generation || !callbacks || events.length === 0) return;
    if (resetClock) lastTimestamp = null;
    const offset = lastSeq + 1 - events[0].seq;
    let deadline = performance.now();

    for (const [index, event] of events.entries()) {
      if (token !== generation || !callbacks) return;
      const timestamp = Date.parse(event.ts);
      const elapsed =
        lastTimestamp === null
          ? 0
          : Math.max(0, timestamp - lastTimestamp);
      deadline +=
        (firstEventDelayMs !== undefined && index === 0
          ? firstEventDelayMs
          : elapsed) / speed;
      await waitUntil(deadline, token);
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
        800,
      );
    },
    attack(paymentId, name) {
      if (!paymentId) return Promise.resolve();
      const file = name === "swap_beneficiary"
        ? fixtureFiles.swap
        : name === "replay"
          ? fixtureFiles.replayAttack
          : fixtureFiles.attack;
      return playFixture(file, false);
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
