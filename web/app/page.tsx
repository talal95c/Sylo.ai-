"use client";

import { useCallback, useEffect, useMemo, useReducer, useRef, useState } from "react";

import AlertOverlay from "@/components/AlertOverlay";
import DemoControls from "@/components/DemoControls";
import EventFeed from "@/components/EventFeed";
import GlobeStage from "@/components/GlobeStage";
import ModeBanner from "@/components/ModeBanner";
import PaymentCard from "@/components/PaymentCard";
import type { SyloEvent } from "@/lib/events";
import { indexInstitutions, loadGeo, shortNames, type Geo } from "@/lib/geo";
import {
  DEFAULT_SOURCE,
  LiveSource,
  ReplaySource,
  type ActionResult,
  type ConnectionStatus,
  type DemoSource,
  type ScenarioName,
  type SourceCallbacks,
  type SourceKind,
  type SupplierAnswer,
} from "@/lib/source";
import { canAnswerSupplier, canAttack, canRunScenario, initialState, reduce, resetView, type ViewState } from "@/lib/store";

type ViewAction = { kind: "event"; event: SyloEvent } | { kind: "clear" };

function viewReducer(state: ViewState, action: ViewAction): ViewState {
  return action.kind === "event" ? reduce(state, action.event) : resetView(state);
}

export default function Home() {
  const [state, dispatch] = useReducer(viewReducer, undefined, initialState);
  const [geo, setGeo] = useState<Geo | null>(null);
  const [source, setSource] = useState<SourceKind>(DEFAULT_SOURCE);
  const [fallback, setFallback] = useState(false);
  const [connection, setConnection] = useState<ConnectionStatus>("connecting");
  const [speed, setSpeed] = useState(1);
  const [playbackRate, setPlaybackRate] = useState(1);
  const [notice, setNotice] = useState<string | null>(null);
  const [dismissedAlert, setDismissedAlert] = useState<string | null>(null);
  const sourceRef = useRef<DemoSource | null>(null);

  useEffect(() => {
    let cancelled = false;
    loadGeo()
      .then((loaded) => {
        if (!cancelled) setGeo(loaded);
      })
      .catch(() => {
        if (!cancelled) setNotice("The institutions file is missing (run pnpm sync-spec): the globe has no places to draw.");
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    const callbacks: SourceCallbacks = {
      onEvent: (event) => dispatch({ kind: "event", event }),
      onStatus: setConnection,
      onOffline: () => {
        dispatch({ kind: "clear" });
        setFallback(true);
        setSource("replay");
      },
      onReset: () => dispatch({ kind: "clear" }),
    };
    const instance: DemoSource = source === "live" ? new LiveSource(callbacks) : new ReplaySource(callbacks);
    sourceRef.current = instance;
    instance.start();
    return () => {
      instance.stop();
      if (sourceRef.current === instance) sourceRef.current = null;
    };
  }, [source]);

  const perform = useCallback(async (action: (current: DemoSource) => Promise<ActionResult>, rate?: number) => {
    const current = sourceRef.current;
    if (!current) return;
    setNotice(null);
    // Live durations are already scaled by the engine; recorded ones are scaled here.
    if (rate !== undefined) setPlaybackRate(current.kind === "replay" ? rate : 1);
    const result = await action(current);
    if (!result.ok) setNotice(result.message ?? "This action is not available right now.");
  }, []);

  const paymentId = state.payment.id;
  const onRun = (name: ScenarioName) => perform((current) => current.runScenario(name, speed), speed);
  const onAnswer = (answer: SupplierAnswer) => {
    if (paymentId) perform((current) => current.supplierResponse(paymentId, answer, speed), speed);
  };
  const onAttack = () => {
    if (paymentId) perform((current) => current.attack(paymentId, speed), speed);
  };
  const onReset = () => perform((current) => current.reset());
  const onSource = (next: SourceKind) => {
    setFallback(false);
    setNotice(null);
    if (next === source) return;
    dispatch({ kind: "clear" });
    setSource(next);
  };

  const names = useMemo(() => shortNames(geo), [geo]);
  const institutions = useMemo(() => indexInstitutions(geo), [geo]);
  const alertKey = state.held ? `${state.run}:${state.held.seq}` : null;

  return (
    <main className="stage">
      <GlobeStage state={state} geo={geo} playbackRate={playbackRate} />
      <div className="console">
        <div className="console__left">
          <div className="brand">
            <p className="brand__mark">
              Sylo<span>.ai</span>
            </p>
            <p className="brand__tag">Decision and control layer for cross-border business payments</p>
          </div>
          <ModeBanner mode={state.mode} source={source} connection={connection} fallback={fallback} />
          <div className="console__spacer" />
          <DemoControls
            canRun={canRunScenario(state)}
            canAnswer={canAnswerSupplier(state) && paymentId !== null}
            canAttack={canAttack(state) && paymentId !== null}
            speed={speed}
            source={source}
            notice={notice}
            onRun={onRun}
            onAnswer={onAnswer}
            onAttack={onAttack}
            onReset={onReset}
            onSpeed={setSpeed}
            onSource={onSource}
          />
        </div>
        <div className="console__center">
          <PaymentCard state={state} institutions={institutions} />
          <div className="console__spacer" />
          {alertKey !== null && alertKey !== dismissedAlert && (
            <AlertOverlay state={state} names={names} onClose={() => setDismissedAlert(alertKey)} />
          )}
        </div>
        <div className="console__right">
          <EventFeed feed={state.feed} names={names} />
        </div>
      </div>
    </main>
  );
}
