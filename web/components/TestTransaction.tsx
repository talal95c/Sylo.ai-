"use client";

import { AnimatePresence, motion } from "framer-motion";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useRef, useState } from "react";
import { engineConnectTimeoutMs, engineUrl } from "@/lib/engine";
import { ORDERS, summarizeQuote, type OrderDetails, type QuoteDecision } from "@/lib/orders";
import { Check, cx, ease, Spinner } from "./ui";

type EngineStatus = "checking" | "live" | "offline";
type Run = "idle" | "running" | "done" | "offline";

const base = engineUrl.replace(/\/$/, "");

function Field({ label, value, mono }: { label: string; value: string; mono?: boolean }) {
  return (
    <div className="flex flex-col gap-1.5">
      <span className="text-[12px] text-ink-2">{label}</span>
      <div className={cx("flex h-10 items-center rounded-xl border border-[var(--line)] bg-[var(--surface-2)] px-3 text-[13.5px] text-ink", mono && "font-mono text-[12.5px]")}>
        {value}
      </div>
    </div>
  );
}

function CountryPill({ country }: { country: string }) {
  return (
    <span className="inline-flex h-5 items-center rounded-full border border-[var(--line-strong)] bg-white px-2 font-mono text-[10px] font-medium text-ink-2">
      {country}
    </span>
  );
}

export default function TestTransaction() {
  const router = useRouter();
  const replay = process.env.NEXT_PUBLIC_SOURCE === "replay";
  const [orderId, setOrderId] = useState<OrderDetails["id"]>("legit");
  const order = useMemo(() => ORDERS.find((item) => item.id === orderId) ?? ORDERS[0], [orderId]);
  const [amount, setAmount] = useState(order.amount.value);
  const [engine, setEngine] = useState<EngineStatus>(replay ? "offline" : "checking");
  const [run, setRun] = useState<Run>("idle");
  const [steps, setSteps] = useState<ReturnType<typeof summarizeQuote>>([]);
  const [step, setStep] = useState(-1);
  const [decision, setDecision] = useState<QuoteDecision | null>(null);
  const [watchNote, setWatchNote] = useState<string | null>(null);
  const timers = useRef<ReturnType<typeof setTimeout>[]>([]);

  const amountChanged = amount.trim() !== order.amount.value;
  const executable = order.executable && !amountChanged && decision?.executable !== false;

  useEffect(() => () => timers.current.forEach(clearTimeout), []);

  const [prevOrder, setPrevOrder] = useState(order);
  if (prevOrder !== order) {
    setPrevOrder(order);
    setAmount(order.amount.value);
    setDecision(null);
    setSteps([]);
    setStep(-1);
    setRun("idle");
    setWatchNote(null);
  }

  useEffect(() => {
    if (replay) return;
    let alive = true;
    const timeout = setTimeout(() => {
      if (alive) setEngine("offline");
    }, engineConnectTimeoutMs);
    fetch(`${base}/health`, { cache: "no-store" })
      .then((response) => {
        if (!alive) return;
        setEngine(response.ok ? "live" : "offline");
      })
      .catch(() => {
        if (alive) setEngine("offline");
      })
      .finally(() => clearTimeout(timeout));
    return () => {
      alive = false;
      clearTimeout(timeout);
    };
  }, [replay]);

  async function runChecks() {
    timers.current.forEach(clearTimeout);
    setRun("running");
    setDecision(null);
    setSteps([]);
    setStep(0);
    setWatchNote(null);
    if (replay) {
      setRun("offline");
      setStep(-1);
      return;
    }
    try {
      const response = await fetch(`${base}/v1/quotes`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          order: order.id,
          ...(amountChanged ? { amount: amount.trim() } : {}),
        }),
        signal: AbortSignal.timeout(engineConnectTimeoutMs + 6000),
      });
      if (!response.ok) throw new Error(String(response.status));
      const next = (await response.json()) as QuoteDecision;
      const summary = summarizeQuote(next);
      setDecision(next);
      timers.current = summary.map((_, index) =>
        setTimeout(() => {
          setSteps((current) => [...current, summary[index]]);
          setStep(index + 1);
          if (index === summary.length - 1) setRun("done");
        }, 450 * (index + 1)),
      );
    } catch {
      setRun("offline");
      setStep(-1);
      setEngine("offline");
    }
  }

  async function watch() {
    setWatchNote(null);
    if (engine === "live" && executable && decision?.quoteId) {
      try {
        const response = await fetch(`${base}/v1/payments`, {
          method: "POST",
          headers: { "Content-Type": "application/json", "Idempotency-Key": decision.quoteId },
          body: JSON.stringify({ quoteId: decision.quoteId, speed: 1 }),
        });
        if (response.status === 409) {
          setWatchNote("A payment is already running — reset it in the demo");
          return;
        }
        if (!response.ok) throw new Error(String(response.status));
        router.push("/demo");
        return;
      } catch {
        setWatchNote("Could not start the payment on the engine");
        return;
      }
    }
    if (order.globe) router.push(`/demo?run=${order.id}`);
  }

  const chip =
    engine === "live" ? (
      <>
        <span className="size-1.5 rounded-full bg-[var(--low)]" />
        Live engine
      </>
    ) : engine === "checking" ? (
      <>
        <span className="size-1.5 rounded-full bg-[var(--medium)]" />
        Connecting…
      </>
    ) : (
      <>
        <span className="size-1.5 rounded-full bg-[var(--medium)]" />
        Recorded · simulated
      </>
    );

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
          {chip}
        </span>
        <h1 className="mt-4 text-center text-[clamp(30px,4.4vw,44px)] font-normal leading-[1.08] tracking-[-0.04em]">
          Test a transaction
        </h1>
        <p className="mt-3 max-w-[460px] text-center text-[14px] leading-relaxed text-ink-2">
          Pick one of the recorded orders and run it through the four checks Sylo runs before any money moves.
        </p>

        <div className="mt-8 grid w-full gap-2.5 sm:grid-cols-3" role="radiogroup" aria-label="Recorded order">
          {ORDERS.map((item) => (
            <button
              key={item.id}
              type="button"
              role="radio"
              aria-checked={orderId === item.id}
              onClick={() => setOrderId(item.id)}
              className={cx(
                "card rounded-2xl p-3.5 text-left text-[12.5px] font-medium leading-snug transition",
                orderId === item.id ? "border-[var(--accent)] ring-4 ring-[var(--accent-soft)]" : "hover:border-[var(--line-strong)]",
              )}
            >
              <span className="mb-1.5 flex items-center gap-1.5">
                <CountryPill country={item.payer.country} />
                <span className="text-ink-3">→</span>
                <CountryPill country={item.beneficiary.country} />
              </span>
              {item.title}
              {item.badge ? <span className="mt-1.5 block text-[10.5px] font-normal text-ink-3">{item.badge}</span> : null}
            </button>
          ))}
        </div>

        <div className="mt-4 grid w-full gap-4 md:grid-cols-[1.1fr_1fr]">
          <form
            className="card rounded-2xl p-5"
            onSubmit={(event) => {
              event.preventDefault();
              void runChecks();
            }}
          >
            <div className="flex flex-col gap-3.5">
              <div className="grid grid-cols-[1fr_auto] items-end gap-3">
                <Field label="Payer" value={`${order.payer.name} · ${order.payer.city}`} />
                <div className="pb-2.5"><CountryPill country={order.payer.country} /></div>
              </div>
              <div className="grid grid-cols-[1fr_auto] items-end gap-3">
                <Field label="Beneficiary" value={`${order.beneficiary.name} · ${order.beneficiary.city}`} />
                <div className="pb-2.5"><CountryPill country={order.beneficiary.country} /></div>
              </div>
              <Field label="Account holder" value={order.beneficiary.accountHolder} mono />
              <Field label="Beneficiary account" value={order.beneficiary.account} mono />
              <label className="flex flex-col gap-1.5">
                <span className="text-[12px] text-ink-2">Amount ({order.amount.currency})</span>
                <input
                  name="amount"
                  value={amount}
                  onChange={(event) => setAmount(event.target.value)}
                  inputMode="decimal"
                  className="h-10 rounded-xl border border-[var(--line-strong)] bg-white px-3 font-mono text-[12.5px] text-ink outline-none transition focus:border-[var(--accent)] focus:ring-4 focus:ring-[var(--accent-soft)]"
                />
              </label>
              {amountChanged ? (
                <p className="text-[11.5px] text-ink-3">Priced for this amount; the PoC executes the recorded amount</p>
              ) : null}
              <Field label="Invoice reference" value={order.invoiceRef} mono />
            </div>
            <motion.button
              type="submit"
              whileHover={{ y: -1 }}
              whileTap={{ scale: 0.98 }}
              disabled={run === "running" || engine === "checking"}
              className="mt-5 flex h-10 w-full items-center justify-center gap-2 rounded-full bg-ink text-[13px] font-medium tracking-[-0.02em] text-white transition-colors hover:bg-[#222] disabled:opacity-70"
            >
              {run === "running" ? <Spinner size={14} color="#fff" /> : null}
              {run === "running" ? "Running checks…" : run === "done" ? "Run checks again" : "Run checks"}
            </motion.button>
          </form>

          <div className="card flex flex-col rounded-2xl p-5">
            <div className="text-[12px] text-ink-2">Pipeline</div>
            <ol className="mt-3 flex flex-col">
              {["Norms", "Risk", "Route & cost", "Commit"].map((title, index) => {
                const filled = steps[index];
                const state = step > index || filled ? "done" : step === index && run === "running" ? "active" : "idle";
                return (
                  <li key={title} className="flex items-start gap-3 border-b border-[var(--line)] py-3 last:border-0">
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
                        {title}
                      </div>
                      <div className="text-[12px] text-ink-3">{filled?.detail ?? "Waiting for the engine"}</div>
                    </div>
                  </li>
                );
              })}
            </ol>

            <AnimatePresence initial={false}>
              {run === "offline" ? (
                <motion.div
                  initial={{ opacity: 0, y: 8, filter: "blur(4px)" }}
                  animate={{ opacity: 1, y: 0, filter: "blur(0px)" }}
                  exit={{ opacity: 0 }}
                  transition={{ duration: 0.4, ease }}
                  className="mt-auto rounded-xl bg-[var(--surface-2)] p-3.5 text-[12.5px] leading-relaxed text-ink-2"
                >
                  Engine offline — recorded run (simulated)
                </motion.div>
              ) : null}
              {watchNote ? (
                <motion.div
                  initial={{ opacity: 0 }}
                  animate={{ opacity: 1 }}
                  exit={{ opacity: 0 }}
                  className="mt-auto rounded-xl bg-[var(--surface-2)] p-3.5 text-[12.5px] leading-relaxed text-ink-2"
                >
                  {watchNote}
                </motion.div>
              ) : null}
            </AnimatePresence>

            {run === "done" || run === "offline" ? (
              <motion.button
                type="button"
                whileHover={{ y: -1 }}
                whileTap={{ scale: 0.98 }}
                onClick={() => void watch()}
                className="mt-4 flex h-10 w-full items-center justify-center gap-2 rounded-full bg-accent text-[13px] font-medium tracking-[-0.02em] text-white transition-colors hover:bg-[#0022d6] disabled:opacity-50"
                disabled={!order.globe && !(engine === "live" && executable)}
              >
                Watch on the globe
              </motion.button>
            ) : null}
            {run === "done" && !executable ? (
              <p className="mt-2 text-center text-[11px] text-ink-3">Quote only — the PoC executes the two recorded FR → GH orders</p>
            ) : null}
          </div>
        </div>
      </motion.section>
    </main>
  );
}
