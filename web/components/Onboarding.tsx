"use client";

import { AnimatePresence, motion, useReducedMotion } from "framer-motion";
import { useCallback, useEffect, useLayoutEffect, useState } from "react";
import { cx, ease } from "./ui";

interface Step {
  target: string | null;
  eyebrow: string;
  title: string;
  body: string;
}

const STEPS: Step[] = [
  {
    target: null,
    eyebrow: "Welcome",
    title: "Sylo checks a payment before any money moves",
    body: "A French company pays its supplier in Ghana. In a few seconds Sylo checks which routes are legal, scores fraud, picks the cheapest safe route and seals the payment on Avalanche.",
  },
  {
    target: '[aria-label="Payment"]',
    eyebrow: "1 · The payment",
    title: "Who pays whom, how much, by which route",
    body: "The payer in Lyon, the beneficiary in Tamale and the account the money goes to. A new or changed account is flagged here.",
  },
  {
    target: '[aria-label="Engine decisions"]',
    eyebrow: "2 · The decisions",
    title: "Every check, in order, with its reason",
    body: "Legal routes, fraud risk, route and cost, approval, sealed intent, settlement. Open it to see why each step passed or held.",
  },
  {
    target: '[aria-label="Demo view"]',
    eyebrow: "3 · Two views",
    title: "Follow the money on the globe, or as a flow",
    body: "Globe shows each leg between institutions. Nodes shows the same payment as a decision graph.",
  },
  {
    target: '[aria-label="Demo controls"]',
    eyebrow: "4 · Run a scene",
    title: "Start with a payment",
    body: "Run a legitimate payment, then the one whose bank details were changed by email, and watch Sylo hold it.",
  },
];

type Rect = { x: number; y: number; width: number; height: number };

const PAD = 8;
const CARD_W = 340;
const GAP = 16;

function measure(selector: string | null): Rect | null {
  if (!selector) return null;
  const element = document.querySelector<HTMLElement>(selector);
  if (!element) return null;
  const rect = element.getBoundingClientRect();
  if (rect.width === 0 || rect.height === 0) return null;
  return { x: rect.left - PAD, y: rect.top - PAD, width: rect.width + PAD * 2, height: rect.height + PAD * 2 };
}

function cardPosition(rect: Rect | null, cardH: number) {
  const vw = window.innerWidth;
  const vh = window.innerHeight;
  if (!rect) return { left: (vw - CARD_W) / 2, top: Math.max(24, (vh - cardH) / 2) };
  const clampTop = (top: number) => Math.min(Math.max(16, top), vh - cardH - 16);
  const clampLeft = (left: number) => Math.min(Math.max(16, left), vw - CARD_W - 16);
  if (rect.x + rect.width + GAP + CARD_W <= vw - 16) return { left: rect.x + rect.width + GAP, top: clampTop(rect.y) };
  if (rect.x - GAP - CARD_W >= 16) return { left: rect.x - GAP - CARD_W, top: clampTop(rect.y) };
  const below = rect.y + rect.height + GAP;
  if (below + cardH <= vh - 16) return { left: clampLeft(rect.x + rect.width / 2 - CARD_W / 2), top: below };
  return { left: clampLeft(rect.x + rect.width / 2 - CARD_W / 2), top: Math.max(16, rect.y - GAP - cardH) };
}

export function Onboarding({
  open,
  onClose,
  onRunLegit,
  onRunDiverted,
}: {
  open: boolean;
  onClose: () => void;
  onRunLegit: () => void;
  onRunDiverted: () => void;
}) {
  const reduced = useReducedMotion();
  const [index, setIndex] = useState(0);
  const [rect, setRect] = useState<Rect | null>(null);
  const [cardH, setCardH] = useState(220);
  const [card, setCard] = useState<HTMLDivElement | null>(null);
  const step = STEPS[index];
  const last = index === STEPS.length - 1;

  const finish = useCallback(() => {
    setIndex(0);
    onClose();
  }, [onClose]);

  useLayoutEffect(() => {
    if (!open) return;
    const update = () => setRect(measure(step.target));
    update();
    const timer = window.setInterval(update, 250);
    window.addEventListener("resize", update);
    return () => {
      window.clearInterval(timer);
      window.removeEventListener("resize", update);
    };
  }, [open, step.target]);

  useLayoutEffect(() => {
    if (!card) return;
    const observer = new ResizeObserver(([entry]) => setCardH(entry.contentRect.height));
    observer.observe(card);
    return () => observer.disconnect();
  }, [card]);

  useEffect(() => {
    if (!open) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") finish();
      else if (event.key === "ArrowRight" && !last) setIndex((value) => value + 1);
      else if (event.key === "ArrowLeft") setIndex((value) => Math.max(0, value - 1));
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, last, finish]);

  const position = open ? cardPosition(rect, cardH) : { left: 0, top: 0 };
  const transition = reduced ? { duration: 0 } : { duration: 0.45, ease };
  const viewport = typeof window === "undefined" ? { w: 0, h: 0 } : { w: window.innerWidth, h: window.innerHeight };
  const hole = rect ?? { x: viewport.w / 2, y: viewport.h / 2, width: 0, height: 0 };

  return (
    <AnimatePresence>
      {open ? (
        <motion.div
          key="onboarding"
          className="fixed inset-0 z-50"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: reduced ? 0 : 0.3, ease }}
          role="dialog"
          aria-modal="true"
          aria-labelledby="onboarding-title"
        >
          <svg className="absolute inset-0 h-full w-full" aria-hidden>
            <defs>
              <mask id="onboarding-mask">
                <rect width="100%" height="100%" fill="white" />
                <motion.rect
                  initial={false}
                  animate={{ x: hole.x, y: hole.y, width: hole.width, height: hole.height }}
                  transition={transition}
                  rx={22}
                  fill="black"
                />
              </mask>
            </defs>
            <rect width="100%" height="100%" fill="rgba(10,10,14,0.42)" mask="url(#onboarding-mask)" />
            {rect ? (
              <motion.rect
                initial={false}
                animate={{ x: hole.x, y: hole.y, width: hole.width, height: hole.height }}
                transition={transition}
                rx={22}
                fill="none"
                stroke="rgba(255,255,255,0.9)"
                strokeWidth={1.5}
              />
            ) : null}
          </svg>

          <motion.div
            ref={setCard}
            className="card absolute overflow-hidden rounded-[20px]"
            style={{ width: CARD_W, boxShadow: "var(--shadow-float)" }}
            initial={false}
            animate={{ left: position.left, top: position.top }}
            transition={transition}
          >
            <div className="h-1 w-full" style={{ background: "var(--iridescent)" }} />
            <div className="px-5 pb-4 pt-4">
              <AnimatePresence mode="wait" initial={false}>
                <motion.div
                  key={index}
                  initial={{ opacity: 0, y: reduced ? 0 : 6, filter: "blur(4px)" }}
                  animate={{ opacity: 1, y: 0, filter: "blur(0px)" }}
                  exit={{ opacity: 0, y: reduced ? 0 : -6, filter: "blur(4px)" }}
                  transition={{ duration: reduced ? 0 : 0.22, ease }}
                >
                  <div className="font-mono text-[11px] uppercase tracking-[0.08em] text-ink-3">{step.eyebrow}</div>
                  <h2 id="onboarding-title" className="mt-1.5 text-[16px] font-semibold leading-snug tracking-[-0.01em]">
                    {step.title}
                  </h2>
                  <p className="mt-1.5 text-[12.5px] leading-relaxed text-ink-2">{step.body}</p>
                  {index === 0 ? (
                    <div className="mt-3 flex items-start gap-2 rounded-[12px] bg-[var(--surface-2)] px-3 py-2 text-[11.5px] leading-snug text-ink-2">
                      <span className="mt-[5px] h-1.5 w-1.5 shrink-0 rounded-full bg-accent" aria-hidden />
                      <span>
                        <span className="font-medium text-ink">Mentors, please don&apos;t skip.</span> Five short steps, about 30 seconds.
                      </span>
                    </div>
                  ) : null}
                  {last ? (
                    <div className="mt-3.5 grid grid-cols-2 gap-2">
                      <button
                        type="button"
                        onClick={() => {
                          finish();
                          onRunLegit();
                        }}
                        className="h-9 rounded-full border border-[var(--line-strong)] bg-white text-[12px] font-medium transition-colors hover:bg-[var(--surface-2)]"
                      >
                        Legitimate payment
                      </button>
                      <button
                        type="button"
                        onClick={() => {
                          finish();
                          onRunDiverted();
                        }}
                        className="h-9 rounded-full bg-ink text-[12px] font-medium text-white transition-opacity hover:opacity-90"
                      >
                        Diverted payment
                      </button>
                    </div>
                  ) : null}
                </motion.div>
              </AnimatePresence>

              <div className="mt-4 flex items-center justify-between">
                <div className="flex items-center gap-1.5" aria-label={`Step ${index + 1} of ${STEPS.length}`}>
                  {STEPS.map((item, dot) => (
                    <button
                      key={item.eyebrow}
                      type="button"
                      aria-label={`Go to step ${dot + 1}`}
                      onClick={() => setIndex(dot)}
                      className="grid h-4 place-items-center"
                    >
                      <motion.span
                        className="block h-1.5 rounded-full"
                        initial={false}
                        animate={{ width: dot === index ? 18 : 6, background: dot === index ? "var(--ink)" : "rgba(0,0,0,0.16)" }}
                        transition={{ duration: reduced ? 0 : 0.3, ease }}
                      />
                    </button>
                  ))}
                </div>
                <div className="flex items-center gap-1">
                  <button type="button" onClick={finish} className="h-8 rounded-full px-3 text-[12px] text-ink-3 transition-colors hover:text-ink-2">
                    {last ? "Close" : "Skip"}
                  </button>
                  {index > 0 ? (
                    <button
                      type="button"
                      onClick={() => setIndex((value) => value - 1)}
                      className="h-8 rounded-full px-3 text-[12px] font-medium text-ink-2 transition-colors hover:bg-[var(--surface-2)]"
                    >
                      Back
                    </button>
                  ) : null}
                  {!last ? (
                    <button
                      type="button"
                      autoFocus
                      onClick={() => setIndex((value) => value + 1)}
                      className={cx("h-8 rounded-full bg-ink px-3.5 text-[12px] font-medium text-white transition-opacity hover:opacity-90")}
                    >
                      {index === 0 ? "Show me" : "Next"}
                    </button>
                  ) : null}
                </div>
              </div>
            </div>
          </motion.div>
        </motion.div>
      ) : null}
    </AnimatePresence>
  );
}
