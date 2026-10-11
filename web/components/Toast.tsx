"use client";

import { AnimatePresence, motion } from "framer-motion";
import { useEffect } from "react";
import { ease } from "./ui";

interface ToastMessage {
  id: number;
  message: string;
}

function ToastItem({
  toast,
  onDismiss,
}: {
  toast: ToastMessage;
  onDismiss: (id: number) => void;
}) {
  useEffect(() => {
    const timer = setTimeout(() => onDismiss(toast.id), 6000);
    return () => clearTimeout(timer);
  }, [onDismiss, toast.id]);

  return (
    <motion.div
      layout
      role="alert"
      initial={{ opacity: 0, y: 8, scale: 0.98 }}
      animate={{ opacity: 1, y: 0, scale: 1 }}
      exit={{ opacity: 0, y: 4, scale: 0.98 }}
      transition={{ duration: 0.18, ease }}
      className="pointer-events-auto flex max-w-[min(92vw,520px)] items-start gap-3 rounded-2xl border border-[color-mix(in_srgb,var(--danger)_24%,white)] bg-white px-4 py-3 text-[13px] text-ink shadow-[var(--shadow-float)]"
    >
      <span className="mt-0.5 size-2 shrink-0 rounded-full bg-[var(--danger)]" aria-hidden />
      <p className="min-w-0 flex-1 leading-5">{toast.message}</p>
      <button
        type="button"
        aria-label="Dismiss notification"
        onClick={() => onDismiss(toast.id)}
        className="-mr-1 -mt-1 grid size-7 shrink-0 place-items-center rounded-full text-ink-3 transition-colors hover:bg-[var(--surface-2)] hover:text-ink"
      >
        <svg width="12" height="12" viewBox="0 0 12 12" fill="none" aria-hidden>
          <path d="m3 3 6 6m0-6L3 9" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" />
        </svg>
      </button>
    </motion.div>
  );
}

export function Toast({
  toasts,
  onDismiss,
}: {
  toasts: ToastMessage[];
  onDismiss: (id: number) => void;
}) {
  return (
    <div
      aria-live="assertive"
      aria-atomic="false"
      className="pointer-events-none absolute inset-x-0 bottom-[88px] z-[60] flex flex-col items-center gap-2 px-4"
    >
      <AnimatePresence initial={false}>
        {toasts.map((toast) => (
          <ToastItem key={toast.id} toast={toast} onDismiss={onDismiss} />
        ))}
      </AnimatePresence>
    </div>
  );
}
