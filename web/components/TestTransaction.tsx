"use client";

import { motion } from "framer-motion";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import {
  executeQuote,
  mapIntakePipeline,
  orderForMatchedPayment,
  requestQuote,
  submitIntake,
  type IntakePipelineStep,
  type IntakeResponse,
} from "@/lib/intake";
import { Check, cx, ease, Spinner } from "./ui";

const STEPS: IntakePipelineStep[] = [
  { title: "Norms", detail: "Awaiting the engine's rule-pack result.", state: "idle" },
  { title: "Risk", detail: "Awaiting the engine's risk assessment.", state: "idle" },
  { title: "Route & cost", detail: "Awaiting route selection.", state: "idle" },
  {
    title: "Commit",
    detail: "Not yet: nothing is committed until you execute.",
    state: "idle",
  },
] as const;

const PRESETS = {
  legit: `From: payments@savanna-shea.com
Invoice no: SSE-2026-118
Amount due: EUR 85,000.00
Beneficiary: Savanna Shea Exports Ltd
Account: GH•• •••• 2207`,
  diverted: `From: accounts@savannashea-exports.com
Invoice no: SSE-2026-118
Amount due: EUR 85,000.00
Beneficiary: K. MENSAH VENTURES
Account: GH•• •••• 9083
New bank details are included on this invoice.`,
} as const;

const EXTRACTED_FIELDS = [
  ["invoiceRef", "Invoice reference"],
  ["accountHolder", "Beneficiary"],
  ["account", "Beneficiary account"],
  ["amount", "Amount"],
  ["senderDomain", "Sender domain"],
] as const;

export default function TestTransaction() {
  const router = useRouter();
  const [text, setText] = useState("");
  const [phase, setPhase] = useState<"idle" | "checking" | "ready" | "executing">("idle");
  const [result, setResult] = useState<IntakeResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const steps = result ? mapIntakePipeline(result) : STEPS;
  const order = orderForMatchedPayment(result?.matchedOrder ?? null);
  const busy = phase === "checking" || phase === "executing";

  async function checkInvoice() {
    setPhase("checking");
    setError(null);
    setResult(null);
    try {
      const response = await submitIntake(text);
      setResult(response);
      setPhase("ready");
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : String(failure));
      setPhase("idle");
    }
  }

  async function executePayment() {
    if (!order) return;
    setPhase("executing");
    setError(null);
    try {
      const quote = await requestQuote(order);
      await executeQuote(quote.quoteId);
      router.push("/demo");
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : String(failure));
      setPhase("ready");
    }
  }

  function applyPreset(preset: keyof typeof PRESETS) {
    setText(PRESETS[preset]);
    setError(null);
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
          <span className="size-1.5 rounded-full bg-[var(--low)]" />
          Live engine · synthetic data
        </span>
        <h1 className="mt-4 text-center text-[clamp(30px,4.4vw,44px)] font-normal leading-[1.08] tracking-[-0.04em]">
          Test a transaction
        </h1>
        <p className="mt-3 max-w-[460px] text-center text-[14px] leading-relaxed text-ink-2">
          Submit an invoice or e-mail. The engine extracts its fields and checks the matching recorded payment.
        </p>

        <div className="mt-10 grid w-full gap-4 md:grid-cols-[1.1fr_1fr]">
          <form
            className="card rounded-2xl p-5"
            onSubmit={(event) => {
              event.preventDefault();
              void checkInvoice();
            }}
          >
            <div className="flex flex-col gap-3">
              <label htmlFor="invoice-text" className="text-[12px] text-ink-2">
                Invoice or e-mail
              </label>
              <textarea
                id="invoice-text"
                name="text"
                value={text}
                onChange={(event) => setText(event.currentTarget.value)}
                rows={7}
                required
                className="min-h-36 resize-y rounded-xl border border-[var(--line-strong)] bg-white px-3 py-2.5 text-[13px] leading-relaxed text-ink outline-none transition focus:border-[var(--accent)] focus:ring-4 focus:ring-[var(--accent-soft)]"
                placeholder="Paste the invoice text or e-mail here…"
              />
              <div className="flex flex-wrap gap-2">
                {([
                  ["legit", "Legitimate invoice"],
                  ["diverted", "Diverted invoice"],
                ] as const).map(([preset, label]) => (
                  <button
                    key={preset}
                    type="button"
                    onClick={() => applyPreset(preset)}
                    className="inline-flex h-8 items-center gap-2 rounded-full border border-[var(--line-strong)] bg-white px-3 text-[11px] font-medium text-ink-2 transition-colors hover:bg-[var(--surface-2)]"
                  >
                    {label}
                    <span className="rounded-full bg-[var(--surface-2)] px-1.5 py-0.5 text-[8px] font-semibold tracking-wide text-ink-3">
                      SYNTHETIC
                    </span>
                  </button>
                ))}
              </div>
            </div>
            <motion.button
              type="submit"
              whileHover={{ y: -1 }}
              whileTap={{ scale: 0.98 }}
              disabled={busy || !text.trim()}
              className="mt-5 flex h-10 w-full items-center justify-center gap-2 rounded-full bg-ink text-[13px] font-medium tracking-[-0.02em] text-white transition-colors hover:bg-[#222] disabled:opacity-70"
            >
              {phase === "checking" ? <Spinner size={14} color="#fff" /> : null}
              {phase === "checking" ? "Checking with the engine…" : "Check this invoice"}
            </motion.button>
            {result ? (
              <div className="mt-5 border-t border-[var(--line)] pt-4">
                <div className="text-[11px] font-medium text-ink-2">Extracted fields</div>
                <dl className="mt-2 grid grid-cols-[minmax(0,1fr)_minmax(0,1.2fr)] gap-x-3 gap-y-2">
                  {EXTRACTED_FIELDS.map(([key, label]) => {
                    const field =
                      key === "senderDomain"
                        ? result.intake.senderDomain
                        : result.intake.fields[key];
                    return (
                      <div key={key} className="contents">
                        <dt className="text-[10px] text-ink-3">{label}</dt>
                        <dd className="min-w-0 truncate text-right text-[10.5px] text-ink" title={field?.value ?? undefined}>
                          {field?.value ?? "Not detected"}
                        </dd>
                      </div>
                    );
                  })}
                </dl>
                {result.matchedOrder ? (
                  <p className="mt-3 text-[10px] text-ink-3">
                    Matched recorded order <span className="font-mono text-ink-2">{result.matchedOrder}</span>
                  </p>
                ) : (
                  <p className="mt-3 rounded-xl bg-[var(--surface-2)] p-3 text-[11px] leading-relaxed text-ink-2">
                    No recorded order matches this document: the PoC only executes the two recorded FR → GH orders.
                  </p>
                )}
              </div>
            ) : null}
            {error ? (
              <div role="alert" className="mt-4 rounded-xl border border-[color-mix(in_srgb,var(--danger)_20%,white)] bg-[color-mix(in_srgb,var(--danger)_4%,white)] p-3 text-[11px] leading-relaxed text-[var(--danger)]">
                {error}
                {error.startsWith("Engine unreachable") ? (
                  <>
                    {" "}
                    <Link href="/demo" className="font-medium underline underline-offset-2">
                      Watch the recorded demo
                    </Link>
                  </>
                ) : null}
              </div>
            ) : null}
          </form>

          <div className="card flex flex-col rounded-2xl p-5">
            <div className="text-[12px] text-ink-2">Pipeline</div>
            <ol className="mt-3 flex flex-col">
              {steps.map((item, index) => {
                const state = item.state;
                return (
                  <li key={item.title} className="flex items-start gap-3 border-b border-[var(--line)] py-3 last:border-0">
                    <span
                      className={cx(
                        "mt-0.5 grid size-6 shrink-0 place-items-center rounded-full border font-mono text-[10.5px] transition-colors duration-300",
                        state === "idle" && "border-[var(--line-strong)] text-ink-3",
                        state === "done" && "border-transparent bg-[var(--surface-2)]",
                      )}
                    >
                      {state === "done" ? <Check size={12} color="var(--ink-2)" /> : index + 1}
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

            {result?.matchedOrder && order ? (
              <motion.button
                type="button"
                whileHover={{ y: -1 }}
                whileTap={{ scale: 0.98 }}
                disabled={busy}
                onClick={() => void executePayment()}
                className="mt-auto flex h-10 items-center justify-center gap-2 rounded-full bg-[var(--accent)] text-[13px] font-medium text-white transition-colors hover:bg-[#0022d6] disabled:opacity-60"
              >
                {phase === "executing" ? <Spinner size={14} color="#fff" /> : null}
                {phase === "executing" ? "Starting payment…" : "Execute this payment"}
              </motion.button>
            ) : null}
          </div>
        </div>
      </motion.section>
    </main>
  );
}
