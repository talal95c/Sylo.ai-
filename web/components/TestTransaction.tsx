"use client";

import { AnimatePresence, motion } from "framer-motion";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { HOP_COLORS, TIER_COLORS } from "@/lib/colors";
import { loadGeo, type Institution } from "@/lib/geo";
import {
  EngineError,
  fetchPaymentQuote,
  fetchQuote,
  fetchRegistry,
  INVOICE_AMOUNT,
  submitPayment,
  type Bank,
  type DetailsSource,
  type OrderName,
  type PaymentDraft,
  type SavedPayee,
  type Quote,
  type QuoteRoute,
} from "@/lib/quote";
import { submitIntake, type IntakeResponse } from "@/lib/intake";
import { RollingNumber } from "./RollingNumber";
import { Check, cx, ease, euros, Spinner } from "./ui";

const STEPS = ["Recipient", "Amount", "Route", "Review"] as const;

const STEP_COPY = [
  { title: "Who are you paying?", note: "" },
  { title: "How much?", note: "Sylo prices every compliant route for this amount." },
  { title: "How it travels", note: "The engine picked the cheapest route that is legal and safe enough." },
  { title: "Review and send", note: "Nothing moves until the signed intent is committed." },
] as const;

const pad = (value: number) => String(value).padStart(2, "0");
const money = (value: number) => `€${value.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;

const SLIDER_MIN = 1_000;
const SLIDER_MAX = 1_000_000;
const TICKS = 56;

function toSlider(amount: number) {
  const clamped = Math.min(Math.max(amount, SLIDER_MIN), SLIDER_MAX);
  return Math.log(clamped / SLIDER_MIN) / Math.log(SLIDER_MAX / SLIDER_MIN);
}

function fromSlider(position: number) {
  const raw = SLIDER_MIN * (SLIDER_MAX / SLIDER_MIN) ** position;
  const step = raw < 10_000 ? 100 : raw < 100_000 ? 500 : 5_000;
  return Math.round(raw / step) * step;
}

function AmountSlider({ amount, onChange }: { amount: number | null; onChange: (value: number) => void }) {
  const position = amount === null ? 0 : toSlider(amount);
  return (
    <div className="mt-4 px-1">
      <div className="relative h-6">
        <div className="pointer-events-none absolute inset-0 flex items-center justify-between">
          {Array.from({ length: TICKS }, (_, index) => {
            const distance = Math.abs(index / (TICKS - 1) - position);
            return (
              <span
                key={index}
                className="w-[1.5px] rounded-full transition-[height,background-color] duration-200"
                style={{
                  height: distance < 0.012 ? 20 : distance < 0.045 ? 13 : 7,
                  background: distance < 0.045 ? "var(--accent)" : "var(--line-strong)",
                }}
              />
            );
          })}
        </div>
        <input
          type="range"
          min={0}
          max={1000}
          value={Math.round(position * 1000)}
          onChange={(event) => onChange(fromSlider(Number(event.target.value) / 1000))}
          aria-label="Amount slider"
          className="absolute inset-0 h-full w-full cursor-pointer opacity-0"
        />
      </div>
      <div className="mt-1 flex justify-between font-mono text-[10.5px] text-ink-3">
        <span>€1k</span>
        <span>€1M</span>
      </div>
    </div>
  );
}

const RECIPIENTS: { order: OrderName; account: string; holder: string; source: string; tag: string; tagTone: string }[] = [
  {
    order: "legit",
    account: "GH•• •••• 2207",
    holder: "SAVANNA SHEA EXPORTS LTD",
    source: "From your verified supplier records",
    tag: "Saved account",
    tagTone: "text-[var(--low)] bg-[rgba(22,163,74,0.08)]",
  },
  {
    order: "diverted",
    account: "GH•• •••• 9083",
    holder: "K. MENSAH VENTURES",
    source: "From an invoice emailed by savannashea-exports.com",
    tag: "New bank details",
    tagTone: "text-[var(--medium)] bg-[rgba(217,119,6,0.08)]",
  },
];

const SETTLEMENT: Record<string, string> = {
  DIRECT: "Direct settlement",
  ONCHAIN_ESCROW: "Held in on-chain escrow",
  FIAT_HOLD: "Held by the bank",
  NONE: "No hold possible",
};

const METHOD: Record<string, string> = { DUAL_CONTROL: "Dual control", SCA: "Strong authentication" };

const slide = {
  initial: { opacity: 0, x: 16, filter: "blur(4px)" },
  animate: { opacity: 1, x: 0, filter: "blur(0px)" },
  exit: { opacity: 0, x: -16, filter: "blur(4px)" },
  transition: { duration: 0.35, ease },
};

function parseAmount(text: string) {
  const value = Number(text.replace(/[^\d.]/g, ""));
  return Number.isFinite(value) && value > 0 && value <= 10_000_000 ? Math.round(value * 100) / 100 : null;
}

function formatInput(text: string) {
  const [whole, decimals] = text.replace(/[^\d.]/g, "").split(".");
  const grouped = (whole ?? "").replace(/^0+(?=\d)/, "").replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  return decimals === undefined ? grouped : `${grouped}.${decimals.slice(0, 2)}`;
}

function costOf(quote: Quote, routeId: string) {
  return quote.route.candidates.find((candidate) => candidate.routeId === routeId)?.s ?? null;
}

function etaOf(quote: Quote, routeId: string) {
  return quote.rails.find((rail) => rail.routeId === routeId)?.etaLabel ?? null;
}

function excludedReason(quote: Quote, route: QuoteRoute) {
  const code = route.excludedBy ?? quote.route.candidates.find((c) => c.routeId === route.routeId)?.excludedBy;
  if (!code) return null;
  if (route.reason) return route.reason.replace(/^Excluded:\s*/, "");
  if (code.startsWith("TIER_")) return `Not allowed at ${quote.risk.tier} risk: this route cannot hold the money.`;
  return code;
}

function orderedRoutes(quote: Quote) {
  const rank = (route: QuoteRoute) => {
    if (route.routeId === quote.route.chosen) return -1;
    return excludedReason(quote, route) ? 1e9 : (costOf(quote, route.routeId) ?? 1e8);
  };
  return [...quote.routes].sort((a, b) => rank(a) - rank(b));
}

function RoutePath({
  route,
  institutions,
  tone,
}: {
  route: QuoteRoute;
  institutions: Record<string, Institution> | null;
  tone: "chosen" | "open" | "excluded";
}) {
  const stops = [route.hops[0]?.from, ...route.hops.map((hop) => hop.to)].filter(Boolean) as string[];
  return (
    <div className="mx-4 mt-3 flex items-start">
      {stops.map((stop, index) => {
        const hop = route.hops[index];
        const color = tone === "excluded" ? "var(--danger)" : tone === "chosen" ? HOP_COLORS[hop?.kind ?? "bank"] : "rgba(0,0,0,0.28)";
        return (
          <div key={`${stop}-${index}`} className={cx("flex min-w-0 items-start", hop && "flex-1")}>
            <div className="flex w-0 flex-col items-center">
              <span
                className={cx("mt-[3px] size-[7px] shrink-0 rounded-full", tone === "chosen" ? "bg-ink" : "bg-[rgba(0,0,0,0.25)]")}
              />
              <span className="mt-1.5 whitespace-nowrap text-[11px] text-ink-3">
                {institutions?.[stop]?.city ?? "·"}
              </span>
            </div>
            {hop ? (
              <span className="relative mx-1.5 mt-[6px] flex-1">
                <span
                  className="block h-0 border-t-2 border-dotted"
                  style={{ borderColor: color, opacity: tone === "open" ? 0.8 : 1 }}
                />
                {hop.kind === "chain" ? (
                  <span
                    className="absolute -top-[15px] left-1/2 -translate-x-1/2 whitespace-nowrap font-mono text-[9.5px]"
                    style={{ color: tone === "excluded" ? "var(--danger)" : HOP_COLORS.chain }}
                  >
                    Avalanche
                  </span>
                ) : null}
              </span>
            ) : null}
          </div>
        );
      })}
    </div>
  );
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-start justify-between gap-6 border-b border-[var(--line)] py-3 text-[13px] last:border-0">
      <span className="shrink-0 pt-px font-mono text-[11.5px] text-ink-3">{label}</span>
      <span className="min-w-0 text-right text-ink">{children}</span>
    </div>
  );
}

const SOURCES: { id: DetailsSource; label: string }[] = [
  { id: "typed", label: "I typed them myself" },
  { id: "invoice_email", label: "From an invoice email" },
  { id: "phone", label: "Given on a phone call" },
];

const NEW_RECIPIENT = { name: "", accountHolder: "", accountNumber: "", bankId: "", detailsSource: "typed" as DetailsSource, senderDomain: "" };

const inputClass = "mt-0.5 w-full bg-transparent text-[14px] text-ink placeholder:text-ink-3";

const cleanName = (text: string) => text.replace(/[^\p{L}\p{N} .,'&()/_-]/gu, "").slice(0, 120);
const cleanRef = (text: string) => text.replace(/[^A-Za-z0-9 ._/-]/g, "").slice(0, 40);

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block rounded-xl border border-[var(--line)] px-3.5 py-2.5 transition focus-within:border-ink focus-within:shadow-[0_0_0_3px_rgba(10,10,10,0.06)]">
      <span className="block font-mono text-[11px] text-ink-3">{label}</span>
      {children}
    </label>
  );
}

function RecipientCard({
  active,
  onSelect,
  title,
  tag,
  tagTone,
  account,
  holder,
  source,
}: {
  active: boolean;
  onSelect: () => void;
  title: string;
  tag: string;
  tagTone: string;
  account: string;
  holder: string;
  source: string;
}) {
  const initials = title
    .split(/\s+/)
    .slice(0, 2)
    .map((word) => word[0] ?? "")
    .join("")
    .toUpperCase();
  return (
    <motion.button
      type="button"
      whileTap={{ scale: 0.99 }}
      onClick={onSelect}
      className={cx(
        "flex items-center gap-4 rounded-2xl border bg-white p-4 text-left transition-[border-color,box-shadow] duration-200",
        active ? "border-ink shadow-[0_0_0_3px_rgba(10,10,10,0.06)]" : "border-[var(--line)] hover:border-[rgba(0,0,0,0.22)]",
      )}
    >
      <span className="grid size-10 shrink-0 place-items-center rounded-full bg-[var(--surface-2)] text-[13px] font-medium">{initials}</span>
      <span className="min-w-0 flex-1">
        <span className="flex items-center gap-2">
          <span className="truncate text-[14px] font-medium tracking-[-0.02em]">{title}</span>
          <span className={cx("shrink-0 rounded-full px-2 py-0.5 text-[11px] font-medium", tagTone)}>{tag}</span>
        </span>
        <span className="mt-0.5 block font-mono text-[11.5px] text-ink-2">
          {account} · {holder}
        </span>
        <span className="mt-0.5 block text-[11.5px] text-ink-3">{source}</span>
      </span>
      <span
        className={cx(
          "grid size-5 shrink-0 place-items-center rounded-full border transition-colors",
          active ? "border-ink bg-ink" : "border-[var(--line-strong)]",
        )}
      >
        {active ? <Check size={11} color="#fff" /> : null}
      </span>
    </motion.button>
  );
}

const SAMPLE_INVOICES = {
  legitimate: ["From: payments@savanna-shea.com", "Invoice no: SSE-2026-118", "Amount due: EUR 85,000.00", "Beneficiary: Savanna Shea Exports Ltd", "Account: GH•• •••• 2207"],
  diverted: ["From: accounts@savannashea-exports.com", "Invoice no: SSE-2026-118", "Amount due: EUR 85,000.00", "Beneficiary: K. MENSAH VENTURES", "Account: GH•• •••• 9083", "New bank details are included on this invoice."],
};

function InvoiceIntake({ onRead }: { onRead: (result: IntakeResponse) => void }) {
  const [open, setOpen] = useState(false);
  const [text, setText] = useState("");
  const [reading, setReading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<IntakeResponse | null>(null);

  async function read() {
    setReading(true);
    setError(null);
    setResult(null);
    try {
      const next = await submitIntake(text);
      setResult(next);
      onRead(next);
    } catch (err) {
      setError(
        err instanceof Error && err.message.startsWith("Engine unreachable")
          ? "Reading an invoice needs the live engine."
          : err instanceof Error
            ? err.message
            : "The engine could not read this document.",
      );
    } finally {
      setReading(false);
    }
  }

  const fields = result?.intake.fields;
  return (
    <div className="mt-4 rounded-2xl border border-[var(--line)] px-4 py-3">
      <button type="button" onClick={() => setOpen(!open)} className="flex w-full items-center justify-between text-[12.5px] font-medium text-ink">
        Fill from an invoice or e-mail
        <span className="text-ink-3">{open ? "−" : "+"}</span>
      </button>
      {open ? (
        <div className="mt-3 grid gap-2.5">
          <div className="flex flex-wrap gap-x-4 gap-y-1">
            {(["legitimate", "diverted"] as const).map((kind) => (
              <button
                key={kind}
                type="button"
                onClick={() => setText(SAMPLE_INVOICES[kind].join("\n"))}
                className="text-[11.5px] text-ink-2 underline underline-offset-2 transition-colors hover:text-ink"
              >
                Use a {kind} invoice
              </button>
            ))}
          </div>
          <textarea
            aria-label="Invoice or e-mail"
            value={text}
            onChange={(event) => setText(event.target.value)}
            rows={5}
            className="w-full resize-y rounded-xl border border-[var(--line-strong)] bg-white px-3 py-2.5 text-[12px] leading-relaxed text-ink focus:border-ink"
          />
          <button
            type="button"
            disabled={reading || !text.trim()}
            onClick={read}
            className="h-9 justify-self-start rounded-full bg-ink px-4 text-[12px] font-medium text-white transition-colors hover:bg-[#222] disabled:cursor-not-allowed disabled:bg-[rgba(0,0,0,0.12)] disabled:text-ink-3"
          >
            {reading ? "Reading…" : "Read it"}
          </button>
          {error ? (
            <p role="alert" className="text-[12px] text-[var(--danger)]">
              {error}
            </p>
          ) : null}
          {fields ? (
            <div className="rounded-xl border border-[var(--line)] px-3.5">
              <Row label="Payee">{fields.accountHolder?.value ?? "—"}</Row>
              <Row label="Account">{fields.account?.value ?? "—"}</Row>
              <Row label="Amount">{fields.amount?.value ?? "—"}</Row>
              <Row label="Reference">{fields.invoiceRef?.value ?? "—"}</Row>
              <p className="py-2.5 text-[11.5px] leading-relaxed text-ink-3">
                Read by the engine as data, never as instructions. An invoice only shows the last four digits: type the full account number.
              </p>
            </div>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

export default function TestTransaction() {
  const router = useRouter();
  const [step, setStep] = useState(0);
  const [order, setOrder] = useState<OrderName | null>(null);
  const [amountText, setAmountText] = useState("85,000");
  const [quoted, setQuoted] = useState<{ key: string; quote: Quote } | null>(null);
  const [quoting, setQuoting] = useState(false);
  const [quoteError, setQuoteError] = useState<string | null>(null);
  const [sending, setSending] = useState(false);
  const [sendError, setSendError] = useState<string | null>(null);
  const [institutions, setInstitutions] = useState<Record<string, Institution> | null>(null);
  const [registry, setRegistry] = useState<{ payees: SavedPayee[]; banks: Bank[] } | null>(null);
  const [tab, setTab] = useState<"saved" | "new">("saved");
  const [accountId, setAccountId] = useState<string | null>(null);
  const [form, setForm] = useState(NEW_RECIPIENT);
  const [invoiceRef, setInvoiceRef] = useState("SSE-2026-131");
  const [purpose, setPurpose] = useState<"GOODS" | "SERVICES">("GOODS");
  const [locRef, setLocRef] = useState("LOC-GH-2026-0457");

  const amount = parseAmount(amountText);
  const atInvoiceAmount = amount === INVOICE_AMOUNT;
  const recipient = RECIPIENTS.find((item) => item.order === order) ?? null;
  const live = registry !== null;
  const savedAccounts = registry?.payees.flatMap((payee) => payee.accounts.map((account) => ({ payee, account }))) ?? [];
  const saved = savedAccounts.find((item) => item.account.accountId === accountId) ?? null;
  const bank = registry?.banks.find((item) => item.id === form.bankId) ?? null;
  const newReady =
    form.name.trim().length >= 2 && form.accountHolder.trim().length >= 2 && /^[0-9]{10,16}$/.test(form.accountNumber) && bank !== null;
  const beneficiary: PaymentDraft["beneficiary"] | null =
    tab === "saved"
      ? saved
        ? { accountId: saved.account.accountId }
        : null
      : newReady
        ? { name: form.name.trim(), accountHolder: form.accountHolder.trim(), accountNumber: form.accountNumber, bankId: form.bankId }
        : null;
  const draft: PaymentDraft | null =
    live && beneficiary && amount !== null && invoiceRef.trim()
      ? {
          beneficiary,
          amount: amount.toFixed(2),
          purpose,
          invoiceRef: invoiceRef.trim(),
          locRef: purpose === "GOODS" && locRef.trim() ? locRef.trim() : undefined,
          detailsSource: tab === "saved" ? "saved" : form.detailsSource,
          senderDomain: tab === "new" && form.detailsSource === "invoice_email" && form.senderDomain.trim() ? form.senderDomain.trim() : undefined,
        }
      : null;
  const draftKey = draft && step >= 1 ? JSON.stringify(draft) : null;
  const requestKey = draftKey ?? (!live && order && amount !== null ? `${order}|${amount}` : null);
  // A quote only counts for the exact draft it priced: any edit hides it until the engine re-prices.
  const quote = quoted && quoted.key === requestKey ? quoted.quote : null;
  const setQuote = (next: Quote | null) => setQuoted(next && requestKey ? { key: requestKey, quote: next } : null);
  const to = live
    ? tab === "saved"
      ? saved
        ? { name: saved.payee.name, account: saved.account.accountMasked, holder: saved.account.accountHolder, bank: saved.account.bankName }
        : null
      : newReady && bank
        ? {
            name: form.name.trim(),
            account: `GH•• •••• ${form.accountNumber.slice(-4)}`,
            holder: form.accountHolder.trim().toUpperCase(),
            bank: `${bank.short}, ${bank.city}`,
          }
        : null
    : recipient
      ? { name: "Savanna Shea Exports Ltd", account: recipient.account, holder: recipient.holder, bank: null }
      : null;
  const chosen = quote?.routes.find((route) => route.routeId === quote.route.chosen) ?? null;
  const chosenCost = quote && chosen ? costOf(quote, chosen.routeId) : null;
  const swiftCost = quote ? costOf(quote, "R1") : null;

  useEffect(() => {
    loadGeo()
      .then((geo) => setInstitutions(geo.institutions))
      .catch(() => undefined);
    void fetchRegistry().then(setRegistry);
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    const request =
      draftKey !== null
        ? () => fetchPaymentQuote(JSON.parse(draftKey) as PaymentDraft, controller.signal)
        : !live && order && amount !== null
          ? () => fetchQuote(order, amount, controller.signal)
          : null;
    if (!request || requestKey === null) return;
    const timer = setTimeout(() => {
      setQuoting(true);
      setQuoteError(null);
      request()
        .then((next) => {
          if (!controller.signal.aborted) setQuoted({ key: requestKey, quote: next });
        })
        .catch((error: unknown) => {
          if (controller.signal.aborted) return;
          setQuoted(null);
          setQuoteError(
            live
              ? error instanceof EngineError && error.status !== 0 && error.detail
                ? `The engine refused this payment: ${error.detail}.`
                : "The engine did not answer. Try again."
              : error instanceof EngineError && error.status === 0
              ? "Estimates for other amounts need the live engine. The recorded quote is for €85,000."
              : "The engine could not price this payment.",
          );
        })
        .finally(() => {
          if (!controller.signal.aborted) setQuoting(false);
        });
    }, 280);
    return () => {
      controller.abort();
      clearTimeout(timer);
    };
  }, [order, amount, live, draftKey, requestKey]);

  function applyIntake(result: IntakeResponse) {
    const fields = result.intake.fields;
    const holder = fields.accountHolder?.value ?? "";
    const last4 = (fields.account?.value ?? "").replace(/\D/g, "").slice(-4);
    const amount = fields.amount?.value?.replace(/[^\d.]/g, "");
    if (amount) setAmountText(formatInput(amount));
    if (fields.invoiceRef?.value) setInvoiceRef(fields.invoiceRef.value.slice(0, 40));
    setQuote(null);
    const match = last4
      ? savedAccounts.find(({ account }) => account.accountMasked.replace(/\D/g, "").endsWith(last4))
      : undefined;
    if (match) {
      setTab("saved");
      setAccountId(match.account.accountId);
      return;
    }
    setTab("new");
    setForm({
      ...form,
      name: cleanName(holder),
      accountHolder: cleanName(holder.toUpperCase()),
      accountNumber: "",
      detailsSource: "invoice_email",
      senderDomain: result.intake.senderDomain?.value ?? form.senderDomain,
    });
  }

  async function send() {
    if (!quote) return;
    setSendError(null);
    if (quote.recorded || !quote.quoteId) {
      if (order) router.push(`/demo?scene=${order}`);
      return;
    }
    setSending(true);
    try {
      await submitPayment(quote.quoteId);
      router.push("/demo");
    } catch (error) {
      setSending(false);
      setSendError(
        error instanceof EngineError && error.status === 409
          ? (error.detail ?? "A payment is already running.") + " Reset it from the demo, then send again."
          : "The engine did not accept the payment. Try again.",
      );
    }
  }

  const canContinue =
    step === 0
      ? live
        ? beneficiary !== null
        : Boolean(order)
      : step === 1
        ? Boolean(quote) && !quoting && amount !== null && (!live || draftKey !== null)
        : step === 2 ? Boolean(quote) : false;

  return (
    <main className="h-dvh w-full overflow-y-auto bg-[var(--surface-2)]">
      <header className="flex w-full items-center justify-between px-6 pt-5 sm:px-8">
        <Link href="/" className="flex items-center gap-2.5">
          <span className="relative grid size-6 place-items-center">
            <span className="absolute inset-0 rounded-full" style={{ background: "var(--iridescent)" }} />
            <span className="absolute inset-[5px] rounded-full bg-[var(--surface-2)]" />
            <span className="relative size-1.5 rounded-full bg-ink" />
          </span>
          <span className="text-[16px] font-semibold tracking-[-0.04em]">Sylo.ai</span>
        </Link>
        <Link href="/demo" className="text-[13px] text-ink-2 transition-colors hover:text-ink">
          Watch the demo →
        </Link>
      </header>

      <section className="mx-auto flex w-full max-w-[520px] flex-col px-5 pb-16 pt-[5vh]">
        <div className="rounded-[28px] border border-[var(--line)] bg-white p-6 shadow-[0_30px_80px_-44px_rgba(0,0,0,0.28)] sm:p-7">
          <div className="flex items-start justify-between gap-4">
            <div className="min-w-0">
              <p className="font-mono text-[12px] text-ink-3">
                <span className="text-ink">{pad(step + 1)}</span> / {pad(STEPS.length)}
              </p>
              <AnimatePresence mode="wait" initial={false}>
                <motion.div
                  key={step}
                  initial={{ opacity: 0, y: 6 }}
                  animate={{ opacity: 1, y: 0 }}
                  exit={{ opacity: 0, y: -6 }}
                  transition={{ duration: 0.25, ease }}
                >
                  <h1 className="mt-1.5 text-[24px] font-normal leading-tight tracking-[-0.04em]">{STEP_COPY[step].title}</h1>
                  <p className="mt-1 text-[13px] text-ink-2">
                    {step === 0 ? `From Rhône Cosmétiques SAS${live ? "" : " · invoice SSE-2026-118"}` : STEP_COPY[step].note}
                  </p>
                </motion.div>
              </AnimatePresence>
            </div>
            <Link
              href="/"
              aria-label="Close"
              className="grid size-8 shrink-0 place-items-center rounded-full bg-[var(--surface-2)] text-ink-2 transition-colors hover:text-ink"
            >
              <svg width="10" height="10" viewBox="0 0 10 10" aria-hidden>
                <path d="M1 1l8 8M9 1 1 9" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" />
              </svg>
            </Link>
          </div>

          <div className="relative mt-6 min-h-[400px]">
          <AnimatePresence mode="wait" initial={false}>
            {step === 0 ? (
              <motion.div key="recipient" {...slide}>
                {live ? (
                  <>
                    <div className="inline-flex rounded-full bg-[var(--surface-2)] p-1">
                      {(["saved", "new"] as const).map((id) => (
                        <button
                          key={id}
                          type="button"
                          onClick={() => {
                            setTab(id);
                            setQuote(null);
                          }}
                          className={cx(
                            "relative h-8 rounded-full px-4 text-[12.5px] font-medium transition-colors",
                            tab === id ? "text-ink" : "text-ink-2 hover:text-ink",
                          )}
                        >
                          {tab === id ? (
                            <motion.span
                              layoutId="recipient-tab"
                              className="absolute inset-0 rounded-full bg-white shadow-[0_1px_2px_rgba(0,0,0,0.08)]"
                              transition={{ duration: 0.3, ease }}
                            />
                          ) : null}
                          <span className="relative">{id === "saved" ? "Saved" : "New recipient"}</span>
                        </button>
                      ))}
                    </div>
                    {tab === "saved" ? (
                      <div className="mt-4 flex flex-col gap-2.5">
                        {savedAccounts.map(({ payee, account }) => (
                          <RecipientCard
                            key={account.accountId}
                            active={accountId === account.accountId}
                            onSelect={() => {
                              setAccountId(account.accountId);
                              setQuote(null);
                            }}
                            title={payee.name}
                            tag="Saved account"
                            tagTone="text-[var(--low)] bg-[rgba(22,163,74,0.08)]"
                            account={account.accountMasked}
                            holder={account.accountHolder}
                            source={`${account.bankName} · ${account.successfulPayments} payments made`}
                          />
                        ))}
                      </div>
                    ) : (
                      <div className="mt-4 grid gap-2.5">
                        <Field label="Business name">
                          <input
                            className={inputClass}
                            value={form.name}
                            placeholder="Savanna Shea Exports Ltd"
                            onChange={(event) => setForm({ ...form, name: cleanName(event.target.value) })}
                          />
                        </Field>
                        <Field label="Account holder, as the bank shows it">
                          <input
                            className={inputClass}
                            value={form.accountHolder}
                            placeholder="SAVANNA SHEA EXPORTS LTD"
                            onChange={(event) => setForm({ ...form, accountHolder: cleanName(event.target.value) })}
                          />
                        </Field>
                        <div className="grid grid-cols-2 gap-2.5">
                          <Field label="Bank in Ghana">
                            <select
                              className={inputClass}
                              value={form.bankId}
                              onChange={(event) => setForm({ ...form, bankId: event.target.value })}
                            >
                              <option value="">Choose a bank</option>
                              {registry.banks.map((item) => (
                                <option key={item.id} value={item.id}>
                                  {item.short} · {item.city}
                                </option>
                              ))}
                            </select>
                          </Field>
                          <Field label="Account number">
                            <input
                              className={cx(inputClass, "font-mono")}
                              inputMode="numeric"
                              value={form.accountNumber}
                              placeholder="10 to 16 digits"
                              onChange={(event) => setForm({ ...form, accountNumber: event.target.value.replace(/\D/g, "").slice(0, 16) })}
                            />
                          </Field>
                        </div>
                        <Field label="Where do these bank details come from?">
                          <select
                            className={inputClass}
                            value={form.detailsSource}
                            onChange={(event) => setForm({ ...form, detailsSource: event.target.value as DetailsSource })}
                          >
                            {SOURCES.map((item) => (
                              <option key={item.id} value={item.id}>
                                {item.label}
                              </option>
                            ))}
                          </select>
                        </Field>
                        {form.detailsSource === "invoice_email" ? (
                          <Field label="Sender's email domain">
                            <input
                              className={inputClass}
                              value={form.senderDomain}
                              placeholder="savannashea-exports.com"
                              onChange={(event) => setForm({ ...form, senderDomain: event.target.value.replace(/[^A-Za-z0-9.-]/g, "").slice(0, 120) })}
                            />
                          </Field>
                        ) : null}
                        <p className="text-[11.5px] text-ink-3">Synthetic banks · only the last four digits leave the engine.</p>
                      </div>
                    )}
                    <InvoiceIntake onRead={applyIntake} />
                  </>
                ) : (
                  <div className="flex flex-col gap-2.5">
                    {RECIPIENTS.map((item) => (
                      <RecipientCard
                        key={item.order}
                        active={order === item.order}
                        onSelect={() => {
                          setOrder(item.order);
                          setQuote(null);
                        }}
                        title="Savanna Shea Exports Ltd"
                        tag={item.tag}
                        tagTone={item.tagTone}
                        account={item.account}
                        holder={item.holder}
                        source={item.source}
                      />
                    ))}
                  </div>
                )}
              </motion.div>
            ) : null}

            {step === 1 ? (
              <motion.div key="amount" {...slide}>
                <label className="block rounded-2xl border border-[var(--line-strong)] p-4 transition focus-within:border-ink focus-within:shadow-[0_0_0_3px_rgba(10,10,10,0.06)]">
                  <span className="font-mono text-[11px] text-ink-3">You send</span>
                  <span className="mt-1 flex items-center gap-3">
                    <input
                      inputMode="decimal"
                      value={amountText}
                      onChange={(event) => setAmountText(formatInput(event.target.value))}
                      className="min-w-0 flex-1 bg-transparent font-mono text-[32px] tracking-[-0.03em] text-ink"
                      aria-label="Amount in euros"
                    />
                    <span className="flex h-9 shrink-0 items-center gap-2 rounded-full bg-[var(--surface-2)] px-3 text-[13px] font-medium">
                      <span className="grid size-4 place-items-center rounded-full bg-[#003399] text-[11px] text-[#ffcc00]">★</span>
                      EUR
                    </span>
                  </span>
                </label>

                <AmountSlider amount={amount} onChange={(value) => setAmountText(formatInput(String(value)))} />

                <div className="mt-5 border-t border-[var(--line)] pt-3">
                  {[
                    { label: "Route", value: chosen?.name ?? "—" },
                    { label: "Arrives", value: chosen && quote ? etaOf(quote, chosen.routeId) ?? "—" : "—" },
                    {
                      label: "Fraud check",
                      value: quote ? `${quote.risk.tier} · ${quote.risk.score}` : "—",
                      color: quote ? TIER_COLORS[quote.risk.tier] : undefined,
                    },
                    ...(swiftCost !== null && chosen?.routeId !== "R1" ? [{ label: "Same payment via SWIFT", value: money(swiftCost), muted: true }] : []),
                  ].map((line) => (
                    <div key={line.label} className="flex items-baseline justify-between gap-4 py-1.5">
                      <span className="font-mono text-[11.5px] text-ink-3">{line.label}</span>
                      <span
                        className={cx("truncate font-mono text-[12.5px]", "muted" in line && line.muted ? "text-ink-3 line-through" : "text-ink")}
                        style={"color" in line && line.color ? { color: line.color } : undefined}
                      >
                        {quoting ? <span className="inline-block h-3 w-16 animate-pulse rounded bg-[var(--surface-2)] align-middle" /> : line.value}
                      </span>
                    </div>
                  ))}
                  <div className="mt-2 flex items-end justify-between gap-4 border-t border-[var(--line)] pt-3">
                    <div>
                      <div className="text-[14px] font-medium tracking-[-0.02em]">All-in cost</div>
                      <div className="mt-0.5 text-[11.5px] text-ink-3">Cheapest compliant route, priced by the engine</div>
                    </div>
                    <RollingNumber
                      value={chosenCost !== null ? money(chosenCost) : "€—"}
                      className={cx("text-[22px] tracking-[-0.02em] transition-opacity", quoting && "opacity-40")}
                    />
                  </div>
                </div>

                {live ? (
                  <div className="mt-5 grid gap-2.5">
                    <div className="grid grid-cols-2 gap-2.5">
                      <Field label="Invoice reference">
                        <input className={inputClass} value={invoiceRef} onChange={(event) => setInvoiceRef(cleanRef(event.target.value))} />
                      </Field>
                      <Field label="Purpose">
                        <select className={inputClass} value={purpose} onChange={(event) => setPurpose(event.target.value as "GOODS" | "SERVICES")}>
                          <option value="GOODS">Goods</option>
                          <option value="SERVICES">Services</option>
                        </select>
                      </Field>
                    </div>
                    {purpose === "GOODS" ? (
                      <Field label="Export letter of credit (Bank of Ghana)">
                        <input className={inputClass} value={locRef} placeholder="Needed for goods" onChange={(event) => setLocRef(cleanRef(event.target.value))} />
                      </Field>
                    ) : null}
                  </div>
                ) : null}
                {quoteError ? <p className="mt-2 text-[12.5px] text-[var(--danger)]">{quoteError}</p> : null}
                {!live && !atInvoiceAmount && amount !== null ? (
                  <p className="mt-3 rounded-xl bg-[var(--surface-2)] px-3.5 py-2.5 text-[12px] leading-relaxed text-ink-2">
                    Estimate only: this proof of concept sends the invoice amount.{" "}
                    <button type="button" className="font-medium text-ink underline-offset-2 hover:underline" onClick={() => setAmountText("85,000")}>
                      Use €85,000
                    </button>
                  </p>
                ) : null}
              </motion.div>
            ) : null}

            {step === 2 && quote ? (
              <motion.div key="route" {...slide}>
                <div className="flex flex-col gap-2.5">
                  {orderedRoutes(quote).map((route, index) => {
                    const isChosen = route.routeId === quote.route.chosen;
                    const reason = excludedReason(quote, route);
                    const cost = costOf(quote, route.routeId);
                    const tone = isChosen ? "chosen" : reason ? "excluded" : "open";
                    return (
                      <motion.div
                        key={route.routeId}
                        initial={{ opacity: 0, y: 8 }}
                        animate={{ opacity: 1, y: 0 }}
                        transition={{ duration: 0.35, ease, delay: 0.05 * index }}
                        className={cx(
                          "rounded-2xl border p-4",
                          isChosen ? "border-transparent bg-[var(--surface-2)]" : "border-[var(--line)]",
                        )}
                      >
                        <div className="flex items-start justify-between gap-4">
                          <div className="min-w-0">
                            <div className="flex items-center gap-2">
                              <span className={cx("text-[13.5px] font-medium tracking-[-0.02em]", reason ? "text-ink-3" : "text-ink")}>{route.name}</span>
                              {isChosen ? (
                                <span className="rounded-full bg-[var(--accent-soft)] px-2 py-0.5 text-[11px] font-medium text-accent">Chosen by Sylo</span>
                              ) : null}
                            </div>
                            <div className="mt-0.5 text-[11.5px] text-ink-3">
                              {SETTLEMENT[route.settlement] ?? route.settlement} · <span className="font-mono">{route.routeId}</span>
                            </div>
                          </div>
                          <div className="shrink-0 text-right">
                            <div className={cx("font-mono text-[13px]", reason ? "text-ink-3" : "text-ink")}>{cost !== null ? euros(cost) : "—"}</div>
                            <div className="text-[11.5px] text-ink-3">{etaOf(quote, route.routeId) ?? ""}</div>
                          </div>
                        </div>
                        <RoutePath route={route} institutions={institutions} tone={tone} />
                        {reason ? <p className="mt-3 text-[11.5px] leading-relaxed text-[var(--danger)]">{reason}</p> : null}
                      </motion.div>
                    );
                  })}
                </div>
                <p className="mt-4 text-[12px] leading-relaxed text-ink-2">{quote.route.reason}</p>
              </motion.div>
            ) : null}

            {step === 3 && quote && to ? (
              <motion.div key="review" {...slide}>
                <div>
                  <Row label="To">
                    {to.name}
                    <span className="block font-mono text-[11.5px] text-ink-3">
                      {to.account} · {to.holder}
                    </span>
                    {to.bank ? <span className="block text-[11.5px] text-ink-3">{to.bank}</span> : null}
                  </Row>
                  {live ? (
                    <Row label="Invoice">
                      <span className="font-mono">{invoiceRef}</span>
                      <span className="block text-[11.5px] text-ink-3">
                        {purpose === "GOODS" ? `Goods · LOC ${locRef || "missing"}` : "Services"}
                      </span>
                    </Row>
                  ) : null}
                  <Row label="Route">
                    {chosen?.name ?? "No route"}
                    <span className="block text-[11.5px] text-ink-3">
                      {chosenCost !== null ? `${euros(chosenCost)} all-in` : ""} {chosen ? `· ${etaOf(quote, chosen.routeId) ?? ""}` : ""}
                    </span>
                  </Row>
                  <Row label="Settlement">{SETTLEMENT[quote.route.settlement] ?? quote.route.settlement}</Row>
                  <Row label="Fraud check">
                    <span className="font-mono" style={{ color: TIER_COLORS[quote.risk.tier] }}>
                      {quote.risk.tier} · {quote.risk.score}
                    </span>
                    {quote.risk.topReasons[0] ? (
                      <span className="mt-0.5 block max-w-[300px] text-[11.5px] leading-snug text-ink-3">{quote.risk.topReasons[0].text}</span>
                    ) : null}
                  </Row>
                  <Row label="Approval">
                    {METHOD[quote.approval.method] ?? quote.approval.method}
                    <span className="block text-[11.5px] text-ink-3">{quote.approval.required.map((person) => person.name).join(" + ")}</span>
                  </Row>
                </div>
                <div className="mt-1 flex items-end justify-between gap-4 border-t border-[var(--line)] pt-4">
                  <div>
                    <div className="text-[14px] font-medium tracking-[-0.02em]">You send</div>
                    <div className="mt-0.5 text-[11.5px] text-ink-3">
                      {chosenCost !== null ? `${money(chosenCost)} all-in fees, priced by the engine` : "No compliant route"}
                    </div>
                  </div>
                  <RollingNumber value={amount !== null ? money(amount) : "€—"} className="text-[22px] tracking-[-0.02em]" />
                </div>
                <p className="mt-4 text-[11.5px] text-ink-3">
                  Synthetic data · rails simulated{quote.recorded ? " · engine offline, recorded quote" : ""}
                </p>
                {sendError ? <p className="mt-3 text-[12.5px] text-[var(--danger)]">{sendError}</p> : null}
              </motion.div>
            ) : null}
          </AnimatePresence>
          </div>

          <div className={cx("mt-6 grid gap-2.5", step > 0 && "grid-cols-[2fr_3fr]")}>
            {step > 0 ? (
              <button
                type="button"
                onClick={() => setStep(step - 1)}
                className="h-11 rounded-xl border border-[var(--line)] bg-[var(--surface-2)] text-[13px] font-medium text-ink transition-colors hover:bg-[#eceef0]"
              >
                Back
              </button>
            ) : null}
            {step < 3 ? (
              <motion.button
                type="button"
                whileTap={{ scale: 0.98 }}
                disabled={!canContinue}
                onClick={() => setStep(step + 1)}
                className="flex h-11 items-center justify-center gap-1.5 rounded-xl bg-[linear-gradient(180deg,#2b2b2b,#0a0a0a)] text-[13px] font-medium tracking-[-0.02em] text-white shadow-[inset_0_1px_0_rgba(255,255,255,0.14)] transition-opacity hover:opacity-90 disabled:bg-none disabled:bg-[rgba(0,0,0,0.07)] disabled:text-ink-3 disabled:shadow-none"
              >
                {step === 1 && quoting ? <Spinner size={14} color="currentColor" /> : null}
                Continue
                {canContinue ? <span aria-hidden className="text-white/50">›</span> : null}
              </motion.button>
            ) : live || atInvoiceAmount ? (
              <motion.button
                type="button"
                whileTap={{ scale: 0.98 }}
                disabled={sending || !chosen}
                onClick={() => void send()}
                className="flex h-11 items-center justify-center gap-1.5 rounded-xl bg-[linear-gradient(180deg,#2b2b2b,#0a0a0a)] text-[13px] font-medium tracking-[-0.02em] text-white shadow-[inset_0_1px_0_rgba(255,255,255,0.14)] transition-opacity hover:opacity-90 disabled:bg-none disabled:bg-[rgba(0,0,0,0.07)] disabled:text-ink-3 disabled:shadow-none"
              >
                {sending ? <Spinner size={14} color="#fff" /> : null}
                {chosen ? `Send ${euros(live && amount !== null ? amount : INVOICE_AMOUNT)}` : "No route available"}
                {chosen && !sending ? <span aria-hidden className="text-white/50">›</span> : null}
              </motion.button>
            ) : (
              <button type="button" onClick={() => setAmountText("85,000")} className="flex h-11 items-center justify-center gap-1.5 rounded-xl bg-[linear-gradient(180deg,#2b2b2b,#0a0a0a)] text-[13px] font-medium tracking-[-0.02em] text-white shadow-[inset_0_1px_0_rgba(255,255,255,0.14)] transition-opacity hover:opacity-90 disabled:bg-none disabled:bg-[rgba(0,0,0,0.07)] disabled:text-ink-3 disabled:shadow-none">
                Use the invoice amount (€85,000) to send
              </button>
            )}
          </div>
        </div>

        <nav aria-label="Steps" className="mt-5 flex justify-center gap-1.5">
          {STEPS.map((label, index) => (
            <button
              key={label}
              type="button"
              aria-label={label}
              aria-current={index === step ? "step" : undefined}
              disabled={index >= step}
              onClick={() => setStep(index)}
              className="h-1.5 rounded-full transition-[width,background-color] duration-300 disabled:cursor-default"
              style={{ width: index === step ? 18 : 6, background: index <= step ? "var(--ink)" : "rgba(0,0,0,0.15)" }}
            />
          ))}
        </nav>
      </section>
    </main>
  );
}
