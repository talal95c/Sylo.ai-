"use client";

import { AnimatePresence, motion } from "framer-motion";
import { useCallback, useEffect, useState, useSyncExternalStore } from "react";
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
import { PaymentCard } from "./PaymentCard";
import { StatusBanner } from "./StatusBanner";
import { TopBar, type DemoView } from "./TopBar";
import { cx, ease } from "./ui";

const noopSubscribe = () => () => undefined;
const readUrlView = () => new URLSearchParams(window.location.search).get("view");

export default function SyloApp() {
  const sylo = useSylo();
  const urlView = useSyncExternalStore(noopSubscribe, readUrlView, () => null);
  const [picked, setViewState] = useState<DemoView | null>(null);
  const [decisionsOpen, setDecisionsOpen] = useState(false);
  const [feedOpen, setFeedOpen] = useState(false);
  const [incidentOpen, setIncidentOpen] = useState(false);
  const view: DemoView = picked ?? (urlView === "nodes" ? "nodes" : "globe");
  const [geo, setGeo] = useState<{ institutions: Record<string, Institution>; chainAltitude: number } | null>(null);

  useEffect(() => {
    let alive = true;
    loadGeo()
      .then((value) => {
        if (alive) setGeo({ institutions: value.institutions, chainAltitude: value.chain.arcAltitude });
      })
      .catch(() => undefined);
    return () => {
      alive = false;
    };
  }, []);

  const setView = useCallback((next: DemoView) => {
    setViewState(next);
    const url = new URL(window.location.href);
    if (next === "nodes") url.searchParams.set("view", "nodes");
    else url.searchParams.delete("view");
    window.history.replaceState(null, "", url);
  }, []);

  const globe = view === "globe";

  return (
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
        />
      </motion.div>

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
            <FlowGraph state={sylo.state} />
          </motion.div>
        )}
      </AnimatePresence>

      <TopBar mode={sylo.state.mode} riskMode={riskModeForSource(sylo.state, sylo.sourceKind)} sourceKind={sylo.sourceKind} notice={sylo.notice} onSource={sylo.setSourceKind} view={view} onView={setView} />
      <StatusBanner state={sylo.state} onOpenIncident={() => setIncidentOpen(true)} />

      <AnimatePresence>
        {globe ? (
          <motion.div key="panels" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} transition={{ duration: 0.35, ease }}>
            <aside className="thin-scrollbar absolute bottom-[88px] left-4 top-[76px] z-10 flex min-h-0 w-[340px] max-w-[calc(100vw-2rem)] flex-col gap-3 overflow-x-hidden overflow-y-auto 2xl:w-[372px]">
              <PaymentCard state={sylo.state} />
              <DecisionSteps state={sylo.state} expanded={decisionsOpen} onExpandedChange={setDecisionsOpen} />
            </aside>

            <aside className={cx("absolute right-4 top-[76px] z-10 flex min-h-0 w-[320px] max-w-[calc(100vw-2rem)] flex-col overflow-hidden 2xl:w-[360px]", feedOpen ? "bottom-[88px]" : "bottom-auto")}>
              <EventFeed feed={sylo.state.feed} expanded={feedOpen} onExpandedChange={setFeedOpen} onOpenIncident={() => setIncidentOpen(true)} />
            </aside>

            <AlertOverlay state={sylo.state} onClose={sylo.actions.closeAlert} />
          </motion.div>
        ) : null}
      </AnimatePresence>
      <IncidentDrawer incident={sylo.state.incident} open={incidentOpen} onClose={() => setIncidentOpen(false)} />
      <DemoControls
        state={sylo.state}
        actions={sylo.actions}
        available={sylo.available}
        speed={sylo.speed}
        setSpeed={sylo.setSpeed}
        sourceKind={sylo.sourceKind}
      />
    </main>
  );
}
