"use client";

import { useEffect } from "react";
import { motion } from "framer-motion";
import dynamic from "next/dynamic";
import Link from "next/link";
import { wakeEngine } from "../lib/engine";
import { CORRIDOR_LABEL } from "@/lib/corridor";
import { cx, ease } from "./ui";

const LandingGlobe = dynamic(() => import("./LandingGlobe"), { ssr: false });

function Arrow() {
  return (
    <svg width="10" height="10" viewBox="0 0 10 10" fill="none" aria-hidden className="transition-transform duration-300 group-hover:-translate-y-px group-hover:translate-x-px">
      <path d="M2.5 7.5 7.5 2.5M3.5 2.5h4v4" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

function Cta({ href, children, tone }: { href: string; children: React.ReactNode; tone: "light" | "dark" }) {
  return (
    <motion.div whileHover={{ y: -1 }} whileTap={{ scale: 0.97 }}>
      <Link
        href={href}
        className={cx(
          "group inline-flex h-9 items-center gap-2 rounded-full px-4 text-[13px] font-medium tracking-[-0.02em] transition-colors",
          tone === "light" && "bg-[#efefef] text-ink hover:bg-[#e6e6e6]",
          tone === "dark" && "bg-ink text-white hover:bg-[#222]",
        )}
      >
        {children}
        <Arrow />
      </Link>
    </motion.div>
  );
}

const reveal = (delay: number) => ({
  initial: { opacity: 0, y: 12, filter: "blur(6px)" },
  animate: { opacity: 1, y: 0, filter: "blur(0px)" },
  transition: { duration: 0.8, ease, delay },
});

export default function Landing() {
  useEffect(() => {
    wakeEngine();
  }, []);

  return (
    <main className="relative flex h-dvh w-full flex-col items-center overflow-hidden bg-white">
      <motion.header {...reveal(0)} className="flex w-full items-center justify-between px-6 pt-5 sm:px-8">
        <Link href="/" className="flex items-center gap-2.5">
          <span className="relative grid size-6 place-items-center">
            <span className="absolute inset-0 rounded-full" style={{ background: "var(--iridescent)" }} />
            <span className="absolute inset-[5px] rounded-full bg-white" />
            <span className="relative size-1.5 rounded-full bg-ink" />
          </span>
          <span className="text-[16px] font-semibold tracking-[-0.04em]">Sylo.ai</span>
        </Link>
        <span className="font-mono text-[11px] text-ink-3">{CORRIDOR_LABEL} · Avalanche Fuji</span>
      </motion.header>

      <section className="relative z-10 mt-[11vh] flex flex-col items-center px-6 text-center">
        <motion.p {...reveal(0.1)} className="text-[13px] text-ink-2">
          Payment integrity for cross-border B2B
        </motion.p>
        <motion.h1
          {...reveal(0.2)}
          className="mt-3 max-w-[760px] text-[clamp(38px,6vw,64px)] font-normal leading-[1.04] tracking-[-0.045em] text-ink"
        >
          Every payment checked
          <br />
          before it moves
        </motion.h1>
        <motion.p {...reveal(0.3)} className="mt-4 max-w-xl text-[14px] leading-relaxed text-ink-2">
          Sylo checks the law, scores fraud and seals each cross-border payment on Avalanche before money moves.
        </motion.p>
        <motion.div {...reveal(0.35)} className="mt-9 flex items-center gap-2.5">
          <Cta href="/test" tone="light">Try a payment</Cta>
          <Cta href="/demo" tone="dark">Watch the 3-minute demo</Cta>
        </motion.div>
      </section>

      <motion.div
        initial={{ opacity: 0, y: 40 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 1.4, ease, delay: 0.3 }}
        className="pointer-events-auto absolute left-1/2 top-[clamp(300px,42vh,420px)] w-[min(780px,128vw,100vh)] -translate-x-1/2"
      >
        <LandingGlobe />
      </motion.div>
    </main>
  );
}
