"use client";

import { useCallback, useEffect, useReducer, useRef, useState } from "react";

import AlertOverlay from "@/components/AlertOverlay";
import DemoControls from "@/components/DemoControls";
import EventFeed from "@/components/EventFeed";
import GlobeStage from "@/components/GlobeStage";
import ModeBanner from "@/components/ModeBanner";
import PaymentCard from "@/components/PaymentCard";
import {
  DEFAULT_ENGINE_URL,
  LiveSource,
  ReplaySource,
  localEvent,
  type Connection,
  type DemoSource,
  type ScenarioName,
  type SourceHandlers,
  type SourceKind,
  type SupplierAnswer,
} from "@/lib/source";
import { availableActions, initialState, reduce } from "@/lib/store";

const ENGINE_URL = (process.env.NEXT_PUBLIC_ENGINE_URL ?? "").trim().replace(/\/+$/, "") || DEFAULT_ENGINE_URL;
const INITIAL_SOURCE: SourceKind = process.env.NEXT_PUBLIC_SOURCE === "replay" ? "replay" : "live";

export default function Home() {
  // The whole view is a pure function of the events (lib/store.ts). The engine decides, the page draws.
  const [state, dispatch] = useReducer(reduce, initialState);
  const [sourceKind, setSourceKind] = useState<SourceKind>(INITIAL_SOURCE);
  const [connection, setConnection] = useState<Connection>("connecting");
  const [engineOffline, setEngineOffline] = useState(false);
  const [speed, setSpeed] = useState(1);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const sourceRef = useRef<DemoSource | null>(null);
  const speedRef = useRef(1);
  /** True once the current source has shown something: the view is then cleared when the source changes. */
  const dirtyRef = useRef(false);

  const clearView = useCallback(() => {
    if (dirtyRef.current) dispatch(localEvent("session.reset", {}));
    dirtyRef.current = false;
  }, []);

  useEffect(() => {
    const handlers: SourceHandlers = {
      onEvent: (event) => {
        if (event.type !== "system.mode") dirtyRef.current = true;
        dispatch(event);
      },
      onConnection: setConnection,
      onUnavailable: (reason) => {
        // Automatic fallback: stream not open within 2 s, or dropped and not back within 5 s.
        console.warn(`[sylo] ${reason}: replaying recorded events`);
        clearView();
        setEngineOffline(true);
        setSourceKind("replay");
      },
    };
    const source: DemoSource = sourceKind === "live" ? new LiveSource(ENGINE_URL, handlers, speedRef.current) : new ReplaySource(handlers, speedRef.current);
    sourceRef.current = source;
    source.start();
    return () => {
      source.stop();
      if (sourceRef.current === source) sourceRef.current = null;
    };
  }, [sourceKind, clearView]);

  /** Runs one demo action; errors (engine 404/409, engine unreachable, missing recording) never break the page. */
  const act = useCallback(async (label: string, action: (source: DemoSource) => Promise<void>) => {
    const source = sourceRef.current;
    if (!source) return;
    setBusy(true);
    setError(null);
    try {
      await action(source);
    } catch (cause) {
      const message = cause instanceof Error ? cause.message : String(cause);
      console.warn(`[sylo] ${label} failed: ${message}`);
      setError(`${label}: ${message}`);
    } finally {
      setBusy(false);
    }
  }, []);

  const paymentId = state.payment.id;
  const onRun = (scenario: ScenarioName) => void act(scenario === "legit" ? "Run legit payment" : "Run diverted invoice", (source) => source.runScenario(scenario));
  const onSupplier = (answer: SupplierAnswer) => void act(`Supplier: ${answer}`, (source) => source.supplierResponse(paymentId, answer));
  const onAttack = () => void act("Attack", (source) => source.attackReleaseRevoked(paymentId));
  const onReset = () => void act("Reset", (source) => source.reset());

  const onSpeed = (next: number) => {
    speedRef.current = next;
    setSpeed(next);
    sourceRef.current?.setSpeed(next);
  };

  const onSource = (kind: SourceKind) => {
    if (kind === sourceKind) return;
    clearView();
    setError(null);
    setEngineOffline(false);
    setConnection("connecting");
    setSourceKind(kind);
  };

  const actions = availableActions(state);
  // A recorded attack can be played once per run (its events keep their recorded seq).
  const attack = actions.attack && !(sourceKind === "replay" && state.attack !== null);

  return (
    <main className="relative h-dvh w-full overflow-clip bg-[#02040a] text-slate-100">
      <div className="fixed inset-0 z-0">
        <GlobeStage events={state.events} />
      </div>

      <div className="pointer-events-none absolute inset-0 z-10 grid grid-cols-[340px_minmax(0,1fr)_380px] grid-rows-[auto_minmax(0,1fr)_auto] gap-4 overflow-clip p-4">
        <div className="pointer-events-auto col-start-1 row-start-1 self-start justify-self-start">
          <ModeBanner mode={state.mode} sourceKind={sourceKind} connection={connection} engineOffline={engineOffline} />
        </div>
        <div className="pointer-events-auto col-start-2 row-start-1 self-start justify-self-center">
          <PaymentCard state={state} />
        </div>
        <div className="pointer-events-auto col-start-3 row-span-3 row-start-1 min-h-0">
          <EventFeed feed={state.feed} />
        </div>
        <div className="pointer-events-auto col-start-2 row-start-3 self-end justify-self-center">
          <AlertOverlay state={state} />
        </div>
        <div className="pointer-events-auto col-start-1 row-start-3 self-end justify-self-start">
          <DemoControls
            actions={{ ...actions, attack }}
            busy={busy}
            sourceKind={sourceKind}
            speed={speed}
            error={error}
            onRun={onRun}
            onSupplier={onSupplier}
            onAttack={onAttack}
            onReset={onReset}
            onSpeed={onSpeed}
            onSource={onSource}
          />
        </div>
      </div>
    </main>
  );
}
