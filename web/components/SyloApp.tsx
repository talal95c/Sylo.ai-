"use client";

import { AnimatePresence, motion, MotionConfig } from "framer-motion";
import { useCallback, useEffect, useRef, useState, useSyncExternalStore } from "react";
import Link from "next/link";
import { loadGeo, type Institution } from "@/lib/geo";
import { riskModeForSource } from "@/lib/store";
import { useSylo } from "@/lib/useSylo";
import { AlertOverlay } from "./AlertOverlay";
import { DecisionSteps } from "./DecisionSteps";
import { DemoControls } from "./DemoControls";
import { EventFeed } from "./EventFeed";
import { FlowGraph } from "./FlowGraph";
import GlobeStage from "./GlobeStage";
import { IncidentDrawer } from "./IncidentDrawer";
import { Onboarding, onboardingSeen } from "./Onboarding";
import { PaymentCard } from "./PaymentCard";
import { StatusBanner } from "./StatusBanner";
import { TopBar, type DemoView } from "./TopBar";
import { Toast } from "./Toast";
import { cx, ease } from "./ui";

const noopSubscribe = () => () => undefined;
const readUrlView = () => new URLSearchParams(window.location.search).get("view");

export default function SyloApp() {
  const sylo = useSylo();
  const urlView = useSyncExternalStore(noopSubscribe, readUrlView, () => null);
  const [picked, setViewState] = useState<DemoView | null>(null);
  const [decisionsUserOpen, setDecisionsUserOpen] = useState(false);
  const [decisionsClosedAtStart, setDecisionsClosedAtStart] = useState<number | null>(null);
  const [feedUserOpen, setFeedUserOpen] = useState(false);
  const [feedClosedAtStart, setFeedClosedAtStart] = useState<number | null>(null);
  const [incidentOpen, setIncidentOpen] = useState(false);
  useEffect(() => {
    const lastEvent = sylo.state.lastEvent;
    if (lastEvent?.type === "session.reset" || lastEvent?.type === "scenario.started") setIncidentOpen(false);
  }, [sylo.state.lastEvent]);
  const view: DemoView = picked ?? (urlView === "nodes" ? "nodes" : "globe");
  const [geo, setGeo] = useState<{ institutions: Record<string, Institution>; chainAltitude: number } | null>(null);
  const [geoLoadFailed, setGeoLoadFailed] = useState(false);
  const [geoAssetsFailed, setGeoAssetsFailed] = useState(false);
  const [geoRetryKey, setGeoRetryKey] = useState(0);
  const autoRunRef = useRef(false);
  const [tourOpen, setTourOpen] = useState(false);
  const [mobileDemoOpen, setMobileDemoOpen] = useState(false);
  const decisionsOpen =
    decisionsUserOpen ||
    (sylo.scenarioStartedVersion > 0 &&
      decisionsClosedAtStart !== sylo.scenarioStartedVersion);
  const feedOpen =
    feedUserOpen ||
    (sylo.scenarioStartedVersion > 0 &&
      feedClosedAtStart !== sylo.scenarioStartedVersion);
  const setDecisionsOpen = useCallback(
    (open: boolean) => {
      setDecisionsUserOpen(open);
      setDecisionsClosedAtStart(open ? null : sylo.scenarioStartedVersion);
    },
    [sylo.scenarioStartedVersion],
  );
  const setFeedOpen = useCallback(
    (open: boolean) => {
      setFeedUserOpen(open);
      setFeedClosedAtStart(open ? null : sylo.scenarioStartedVersion);
    },
    [sylo.scenarioStartedVersion],
  );

  useEffect(() => {
    const fromTest = new URLSearchParams(window.location.search).has("scene");
    if (fromTest || onboardingSeen()) return;
    const timer = window.setTimeout(() => setTourOpen(true), 900);
    return () => window.clearTimeout(timer);
  }, []);

  useEffect(() => {
    if (!sylo.ready || autoRunRef.current) return;
    const url = new URL(window.location.href);
    const run = url.searchParams.get("scene");
    if (run !== "legit" && run !== "diverted") return;
    autoRunRef.current = true;
    url.searchParams.delete("scene");
    window.history.replaceState(null, "", url);
    if (run === "legit") void sylo.actions.runLegit();
    else void sylo.actions.runDiverted();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sylo.ready]);

  useEffect(() => {
    let alive = true;
    loadGeo()
      .then((value) => {
        if (alive) {
          setGeo({ institutions: value.institutions, chainAltitude: value.chain.arcAltitude });
          setGeoLoadFailed(false);
        }
      })
      .catch(() => {
        if (alive) setGeoLoadFailed(true);
      });
    return () => {
      alive = false;
    };
  }, [geoRetryKey]);

  const setView = useCallback((next: DemoView) => {
    setViewState(next);
    const url = new URL(window.location.href);
    if (next === "nodes") url.searchParams.set("view", "nodes");
    else url.searchParams.delete("view");
    window.history.replaceState(null, "", url);
  }, []);

  const globe = view === "globe";

  return (
    <MotionConfig reducedMotion="user">
    <main className="relative h-dvh w-full overflow-hidden">
      <div
        aria-hidden
        className="absolute inset-0"
        style={{
          background:
            "radial-gradient(60% 55% at 50% 48%, #eef2ff 0%, rgba(250,250,250,0) 70%), radial-gradient(40% 40% at 80% 10%, rgba(255,204,253,0.25) 0%, rgba(250,250,250,0) 70%), #fafafa",
        }}
      />
      <motion.div
        className="absolute inset-0"
        initial={false}
        animate={{ opacity: globe ? 1 : 0 }}
        transition={{ duration: 0.45, ease }}
        style={{ pointerEvents: globe ? "auto" : "none" }}
        aria-hidden={!globe}
      >
        <GlobeStage
          state={sylo.state}
          institutions={geo?.institutions ?? null}
          chainAltitude={geo?.chainAltitude ?? 0.45}
          speed={sylo.speed}
          visible={globe}
          geoRetryKey={geoRetryKey}
          onGeoLoad={setGeoAssetsFailed}
        />
      </motion.div>
      {globe && (geoLoadFailed || geoAssetsFailed) ? (
        <div role="alert" className="glass absolute left-1/2 top-[140px] z-30 flex -translate-x-1/2 items-center gap-3 rounded-xl px-4 py-2.5 text-[12px] text-ink">
          <span>Map data failed to load</span>
          <button type="button" onClick={() => setGeoRetryKey((attempt) => attempt + 1)} className="rounded-full bg-[var(--accent-soft)] px-3 py-1 font-medium text-accent hover:bg-[color-mix(in_srgb,var(--accent)_12%,white)]">
            Retry
          </button>
        </div>
      ) : null}

      <AnimatePresence>
        {globe ? null : (
          <motion.div
            key="nodes"
            className="flow-dots absolute inset-0 z-[5]"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.45, ease }}
          >
            <FlowGraph
              state={sylo.state}
              speed={sylo.speed}
              unsupportedScene={
                sylo.state.scenario === "mule_wave" ||
                Boolean(sylo.state.incident) ||
                Object.keys(sylo.state.rails).length > 0
              }
              onSwitchToGlobe={() => setView("globe")}
            />
          </motion.div>
        )}
      </AnimatePresence>

      <TopBar mode={sylo.state.mode} riskMode={riskModeForSource(sylo.state, sylo.sourceKind)} sourceKind={sylo.sourceKind} connectionStatus={sylo.connectionStatus} notice={sylo.notice} onSource={sylo.setSourceKind} view={view} onView={setView} onHelp={() => setTourOpen(true)} />
      <StatusBanner state={sylo.state} view={view} onOpenIncident={() => setIncidentOpen(true)} />

      <AnimatePresence>
        {globe ? (
          <motion.div key="panels" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} transition={{ duration: 0.35, ease }}>
            <aside data-globe-occluder="left" className="absolute bottom-[88px] left-4 top-[76px] z-10 flex min-h-0 w-[340px] max-w-[calc(100vw-2rem)] flex-col gap-3 overflow-hidden 2xl:w-[372px]">
              <PaymentCard state={sylo.state} panelOpen={decisionsOpen} onViewAlert={sylo.actions.openAlert} />
              <DecisionSteps state={sylo.state} expanded={decisionsOpen} onExpandedChange={setDecisionsOpen} sourceKind={sylo.sourceKind} />
            </aside>

            <aside data-globe-occluder="right" className={cx("absolute right-4 top-[76px] z-10 flex min-h-0 w-[320px] max-w-[calc(100vw-2rem)] flex-col overflow-hidden 2xl:w-[360px]", feedOpen ? "bottom-[88px]" : "bottom-auto")}>
              <EventFeed feed={sylo.state.feed} expanded={feedOpen} onExpandedChange={setFeedOpen} onOpenIncident={() => setIncidentOpen(true)} sourceKind={sylo.sourceKind} />
            </aside>

          </motion.div>
        ) : null}
      </AnimatePresence>
      <AlertOverlay state={sylo.state} onClose={sylo.actions.closeAlert} />
      <Onboarding open={tourOpen} onClose={() => setTourOpen(false)} onRunLegit={() => void sylo.actions.runLegit()} onRunDiverted={() => void sylo.actions.runDiverted()} />
      <IncidentDrawer incident={sylo.state.incident} open={incidentOpen} onClose={() => setIncidentOpen(false)} />
      <DemoControls
        state={sylo.state}
        actions={sylo.actions}
        available={sylo.available}
        speed={sylo.speed}
        setSpeed={sylo.setSpeed}
        sourceKind={sylo.sourceKind}
      />
      <Toast toasts={sylo.toasts} onDismiss={sylo.dismissToast} />
      {!mobileDemoOpen ? (
        <div className="fixed inset-0 z-[100] grid place-items-center bg-[var(--bg)] p-5 md:hidden">
          <section className="card w-full max-w-sm rounded-[24px] p-6 text-center" aria-labelledby="mobile-demo-title">
            <div className="mx-auto mb-5 grid size-12 place-items-center rounded-full bg-[var(--surface-2)]">
              <span className="size-5 rounded-full" style={{ background: "var(--iridescent)" }} />
            </div>
            <p className="font-mono text-[11px] uppercase tracking-[0.12em] text-ink-3">Sylo.ai demo</p>
            <h1 id="mobile-demo-title" className="mt-2 text-[22px] font-semibold tracking-[-0.04em]">Best viewed on a laptop</h1>
            <p className="mt-3 text-[13px] leading-relaxed text-ink-2">
              The live globe and decision panels are designed for a larger screen. You can still try a payment or open the demo here.
            </p>
            <div className="mt-6 grid gap-2.5">
              <Link href="/test" className="flex h-11 items-center justify-center rounded-full bg-ink text-[13px] font-medium text-white">Try a payment</Link>
              <button type="button" onClick={() => setMobileDemoOpen(true)} className="h-11 rounded-full border border-[var(--line-strong)] bg-white text-[13px] font-medium text-ink">Open the demo anyway</button>
            </div>
          </section>
        </div>
      ) : null}
    </main>
    </MotionConfig>
  );
}
