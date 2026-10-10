"use client";

import { useEffect, useState } from "react";
import { loadGeo, type Institution } from "@/lib/geo";
import { useSylo } from "@/lib/useSylo";
import { AlertOverlay } from "./AlertOverlay";
import { DecisionSteps } from "./DecisionSteps";
import { DemoControls } from "./DemoControls";
import { EventFeed } from "./EventFeed";
import GlobeStage from "./GlobeStage";
import { PaymentCard } from "./PaymentCard";
import { TopBar } from "./TopBar";

export default function SyloApp() {
  const sylo = useSylo();
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
      <GlobeStage
        state={sylo.state}
        institutions={geo?.institutions ?? null}
        chainAltitude={geo?.chainAltitude ?? 0.45}
        speed={sylo.speed}
      />

      <TopBar mode={sylo.state.mode} sourceKind={sylo.sourceKind} notice={sylo.notice} onSource={sylo.setSourceKind} />

      <aside className="no-scrollbar absolute bottom-[88px] left-4 top-[88px] z-10 flex w-[340px] flex-col gap-3 overflow-y-auto 2xl:w-[372px]">
        <PaymentCard state={sylo.state} />
        <DecisionSteps state={sylo.state} />
      </aside>

      <aside className="absolute bottom-[88px] right-4 top-[88px] z-10 flex w-[320px] flex-col 2xl:w-[360px]">
        <EventFeed feed={sylo.state.feed} />
      </aside>

      <AlertOverlay state={sylo.state} onClose={sylo.actions.closeAlert} />
      <DemoControls
        state={sylo.state}
        actions={sylo.actions}
        available={sylo.available}
        speed={sylo.speed}
        setSpeed={sylo.setSpeed}
      />
    </main>
  );
}
