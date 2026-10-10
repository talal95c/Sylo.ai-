"use client";

import { AnimatePresence, motion } from "framer-motion";
import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { Check, cx, ease, Spinner } from "./ui";

const STEPS = [
  { title: "Norms", detail: "FR → GH rule pack, sanctions, VAT" },
  { title: "Risk", detail: "Fraud score and BEC signals" },
  { title: "Route & cost", detail: "Cheapest compliant rail" },
  { title: "Commit", detail: "EIP-712 intent on Avalanche Fuji" },
] as const;

const FIELDS = [
  { name: "payer", label: "Payer", value: "Rhône Cosmétiques SAS" },
  { name: "beneficiary", label: "Beneficiary", value: "Savanna Shea Exports Ltd" },
  { name: "account", label: "Beneficiary account", value: "GH 0300 1100 0118 7042", mono: true },
  { name: "amount", label: "Amount (EUR)", value: "48 500", mono: true },
  { name: "reference", label: "Invoice reference", value: "INV-2026-0418", mono: true },
] as const;

type Run = "idle" | "running" | "done";

export default function TestTransaction() {
  const [run, setRun] = useState<Run>("idle");
  const [step, setStep] = useState(-1);
  const timers = useRef<ReturnType<typeof setTimeout>[]>([]);

  useEffect(() => () => timers.current.forEach(clearTimeout), []);

  function simulate() {
    timers.current.forEach(clearTimeout);
    setRun("running");
    setStep(0);
    timers.current = STEPS.map((_, index) =>
      setTimeout(() => {
        if (index === STEPS.length - 1) {
          setStep(STEPS.length);
          setRun("done");
        } else {
          setStep(index + 1);
        }
      }, 750 * (index + 1)),
    );
  }

  return (
    <main className="h-dvh w-full overflow-y-auto bg-white">
      <header className="flex w-full items-center justify-between px-6 pt-5 sm:px-8">
        <Link href="/" className="flex items-center gap-2.5">
          <span className="relative grid size-6 place-items-center">
            <span className="absolute inset-0 rounded-full" style={{ background: "var(--iridescent)" }} />
            <span className="absolute inset-[5px] rounded-full bg-white" />
            <span className="relative size-1.5 rounded-full bg-ink" />
          </span>
          <span className="text-[16px] font-semibold tracking-[-0.04em]">Sylo.ai</span>
        </Link>
        <Link href="/demo" className="text-[13px] text-ink-2 transition-colors hover:text-ink">
          Watch the demo →
        </Link>
      </header>

      <motion.section
        initial={{ opacity: 0, y: 12, filter: "blur(6px)" }}
        animate={{ opacity: 1, y: 0, filter: "blur(0px)" }}
        transition={{ duration: 0.8, ease }}
        className="mx-auto flex max-w-[920px] flex-col items-center px-6 pb-16 pt-[8vh]"
      >
        <span className="inline-flex h-7 items-center gap-2 rounded-full bg-[#f3f3f3] px-3 text-[12px] text-ink-2">
          <span className="size-1.5 rounded-full bg-[var(--medium)]" />
          Simulation · preview
        </span>
        <h1 className="mt-4 text-center text-[clamp(30px,4.4vw,44px)] font-normal leading-[1.08] tracking-[-0.04em]">
          Test a transaction
        </h1>
        <p className="mt-3 max-w-[460px] text-center text-[14px] leading-relaxed text-ink-2">
          Describe a payment and watch it go through the four checks Sylo runs before any money moves.
        </p>

        <div className="mt-10 grid w-full gap-4 md:grid-cols-[1.1fr_1fr]">
          <form
            className="card rounded-2xl p-5"
            onSubmit={(event) => {
              event.preventDefault();
              simulate();
            }}
          >
            <div className="flex flex-col gap-3.5">
              {FIELDS.map((field) => (
                <label key={field.name} className="flex flex-col gap-1.5">
                  <span className="text-[12px] text-ink-2">{field.label}</span>
                  <input
                    name={field.name}
                    defaultValue={field.value}
                    className={cx(
                      "h-10 rounded-xl border border-[var(--line-strong)] bg-white px-3 text-[13.5px] text-ink outline-none transition focus:border-[var(--accent)] focus:ring-4 focus:ring-[var(--accent-soft)]",
                      "mono" in field && field.mono && "font-mono text-[12.5px]",
                    )}
                  />
                </label>
              ))}
            </div>
            <motion.button
              type="submit"
              whileHover={{ y: -1 }}
              whileTap={{ scale: 0.98 }}
              disabled={run === "running"}
              className="mt-5 flex h-10 w-full items-center justify-center gap-2 rounded-full bg-ink text-[13px] font-medium tracking-[-0.02em] text-white transition-colors hover:bg-[#222] disabled:opacity-70"
            >
              {run === "running" ? <Spinner size={14} color="#fff" /> : null}
              {run === "running" ? "Simulating…" : run === "done" ? "Run again" : "Simulate transaction"}
            </motion.button>
          </form>

          <div className="card flex flex-col rounded-2xl p-5">
            <div className="text-[12px] text-ink-2">Pipeline</div>
            <ol className="mt-3 flex flex-col">
              {STEPS.map((item, index) => {
                const state = step > index ? "done" : step === index ? "active" : "idle";
                return (
                  <li key={item.title} className="flex items-start gap-3 border-b border-[var(--line)] py-3 last:border-0">
                    <span
                      className={cx(
                        "mt-0.5 grid size-6 shrink-0 place-items-center rounded-full border font-mono text-[10.5px] transition-colors duration-300",
                        state === "idle" && "border-[var(--line-strong)] text-ink-3",
                        state === "active" && "border-[var(--accent)] text-accent",
                        state === "done" && "border-transparent bg-[var(--surface-2)]",
                      )}
                    >
                      {state === "active" ? <Spinner size={12} /> : state === "done" ? <Check size={12} color="var(--ink-2)" /> : index + 1}
                    </span>
                    <div className="min-w-0">
                      <div className={cx("text-[13.5px] font-medium tracking-[-0.02em] transition-colors", state === "idle" ? "text-ink-3" : "text-ink")}>
                        {item.title}
                      </div>
                      <div className="text-[12px] text-ink-3">{item.detail}</div>
                    </div>
                  </li>
                );
              })}
            </ol>

            <AnimatePresence initial={false}>
              {run === "done" ? (
                <motion.div
                  initial={{ opacity: 0, y: 8, filter: "blur(4px)" }}
                  animate={{ opacity: 1, y: 0, filter: "blur(0px)" }}
                  exit={{ opacity: 0 }}
                  transition={{ duration: 0.4, ease }}
                  className="mt-auto rounded-xl bg-[var(--surface-2)] p-3.5 text-[12.5px] leading-relaxed text-ink-2"
                >
                  Preview only — custom transactions aren&apos;t wired to the engine yet, so no decision was computed.{" "}
                  <Link href="/demo" className="font-medium text-ink underline-offset-2 hover:underline">
                    See the full v0 scenario →
                  </Link>
                </motion.div>
              ) : null}
            </AnimatePresence>
          </div>
        </div>
      </motion.section>
    </main>
  );
}
