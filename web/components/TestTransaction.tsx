"use client";

import { AnimatePresence, motion } from "framer-motion";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { HOP_COLORS, TIER_COLORS } from "@/lib/colors";
import { loadGeo, type Institution } from "@/lib/geo";
import {
  accountDiffersFromVerified,
  orderForMatchedPayment,
  submitIntake,
  type IntakeResponse,
} from "@/lib/intake";
import {
  EngineError,
  fetchQuote,
  INVOICE_AMOUNT,
  INVOICE_REFERENCE,
  submitPayment,
  type OrderName,
  type Quote,
  type QuoteRoute,
} from "@/lib/quote";
import { Check, cx, ease, euros, Spinner } from "./ui";

const STEPS = ["Recipient", "Amount", "Route", "Review"] as const;
type RecipientChoice = OrderName | "new";

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
  return Number.isFinite(value) && value >= 100 && value <= 1_000_000 ? Math.round(value * 100) / 100 : null;
}

function maskAccountNumber(value: string) {
  const normalized = value.replace(/[^A-Za-z0-9]/g, "");
  return normalized ? `GH•• •••• ${normalized.slice(-4)}` : "Account number";
}

function validInvoiceReference(value: string) {
  return /^[A-Za-z0-9-]{3,24}$/.test(value);
}

function validAccountNumber(value: string) {
  return /^[A-Za-z0-9 ]{6,34}$/.test(value);
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
              <span className="mt-1.5 whitespace-nowrap text-[10.5px] text-ink-3">
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
      <span className="shrink-0 text-ink-2">{label}</span>
      <span className="min-w-0 text-right text-ink">{children}</span>
    </div>
  );
}

export default function TestTransaction() {
  const router = useRouter();
  const [step, setStep] = useState(0);
  const [selection, setSelection] = useState<RecipientChoice | null>(null);
  const [amountText, setAmountText] = useState("85,000");
  const [invoiceRef, setInvoiceRef] = useState(INVOICE_REFERENCE);
  const [accountNumber, setAccountNumber] = useState("");
  const [holderName, setHolderName] = useState("");
  const [senderDomain, setSenderDomain] = useState("");
  const [quote, setQuote] = useState<Quote | null>(null);
  const [quoting, setQuoting] = useState(false);
  const [quoteError, setQuoteError] = useState<string | null>(null);
  const [sending, setSending] = useState(false);
  const [sendError, setSendError] = useState<string | null>(null);
  const [institutions, setInstitutions] = useState<Record<string, Institution> | null>(null);
  const [invoiceOpen, setInvoiceOpen] = useState(false);
  const [invoiceText, setInvoiceText] = useState("");
  const [invoiceReading, setInvoiceReading] = useState(false);
  const [invoiceError, setInvoiceError] = useState<string | null>(null);
  const [invoiceResult, setInvoiceResult] = useState<IntakeResponse | null>(null);

  const amount = parseAmount(amountText);
  const newAccountSelected = selection === "new";
  const order: OrderName | null = newAccountSelected ? "legit" : selection;
  const customTerms = amount !== INVOICE_AMOUNT || invoiceRef !== INVOICE_REFERENCE;
  const enteredBankDetailsSelected =
    newAccountSelected || (selection === "diverted" && customTerms);
  const recipient = enteredBankDetailsSelected
    ? { account: maskAccountNumber(accountNumber), holder: holderName.trim() || "Account holder" }
    : RECIPIENTS.find((item) => item.order === order) ?? null;
  const accountDetailsValid =
    validAccountNumber(accountNumber) && holderName.trim().length > 0 && holderName.trim().length <= 60;
  const invoiceRefValid = validInvoiceReference(invoiceRef);
  const chosen = quote?.routes.find((route) => route.routeId === quote.route.chosen) ?? null;
  const chosenCost = quote && chosen ? costOf(quote, chosen.routeId) : null;
  const swiftCost = quote ? costOf(quote, "R1") : null;

  function clearQuoteForChange() {
    setQuote(null);
    setQuoteError(null);
    setQuoting(false);
  }

  async function readInvoice() {
    setInvoiceReading(true);
    setInvoiceError(null);
    setInvoiceResult(null);
    try {
      const result = await submitIntake(invoiceText);
      const matched = orderForMatchedPayment(result.matchedOrder);
      setInvoiceResult(result);
      setSelection(matched);
      clearQuoteForChange();
    } catch (error) {
      setInvoiceError(
        error instanceof Error && error.message.startsWith("Engine unreachable")
          ? "Reading an invoice needs the live engine."
          : error instanceof Error
            ? error.message
            : "The engine could not read this document.",
      );
    } finally {
      setInvoiceReading(false);
    }
  }

  useEffect(() => {
    loadGeo()
      .then((geo) => setInstitutions(geo.institutions))
      .catch(() => undefined);
  }, []);

  useEffect(() => {
    if (
      !order ||
      amount === null ||
      !invoiceRefValid ||
      (enteredBankDetailsSelected && !accountDetailsValid)
    ) {
      return;
    }
    const controller = new AbortController();
    const timer = setTimeout(() => {
      setQuoting(true);
      setQuoteError(null);
      fetchQuote(order, amount, controller.signal, {
        invoiceRef,
        account: selection === "diverted" || newAccountSelected ? "new" : "verified",
        newAccountSelected,
        ...(enteredBankDetailsSelected ? { accountNumber, holderName: holderName.trim() } : {}),
        ...(senderDomain.trim() ? { senderDomain: senderDomain.trim() } : {}),
      })
        .then((next) => {
          if (!controller.signal.aborted) setQuote(next);
        })
        .catch((error: unknown) => {
          if (controller.signal.aborted) return;
          setQuote(null);
          setQuoteError(
            error instanceof EngineError && error.status === 0
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
  }, [
    order,
    amount,
    invoiceRef,
    invoiceRefValid,
    selection,
    newAccountSelected,
    enteredBankDetailsSelected,
    accountDetailsValid,
    accountNumber,
    holderName,
    senderDomain,
  ]);

  async function send() {
    if (!quote || !order) return;
    setSendError(null);
    if (quote.recorded || !quote.quoteId) {
      router.push(`/demo?scene=${newAccountSelected ? "diverted" : order}`);
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
      ? Boolean(selection) && (!enteredBankDetailsSelected || accountDetailsValid)
      : step === 1
        ? Boolean(quote) && !quoting && amount !== null && invoiceRefValid
        : step === 2
          ? Boolean(quote)
          : false;

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

      <section className="mx-auto flex w-full max-w-[540px] flex-col px-6 pb-16 pt-[6vh]">
        <nav aria-label="Steps" className="grid grid-cols-4 gap-2">
          {STEPS.map((label, index) => (
            <button
              key={label}
              type="button"
              disabled={index >= step}
              onClick={() => setStep(index)}
              className="group flex flex-col gap-2 text-left disabled:cursor-default"
            >
              <span className="relative h-[3px] overflow-hidden rounded-full bg-[var(--surface-2)]">
                <motion.span
                  className="absolute inset-y-0 left-0 rounded-full bg-ink"
                  initial={false}
                  animate={{ width: index <= step ? "100%" : "0%" }}
                  transition={{ duration: 0.45, ease }}
                />
              </span>
              <span className={cx("text-[12px] transition-colors", index <= step ? "text-ink" : "text-ink-3", index < step && "group-hover:text-accent")}>
                {label}
              </span>
            </button>
          ))}
        </nav>

        <div className="relative mt-9 min-h-[460px]">
          <AnimatePresence mode="wait" initial={false}>
            {step === 0 ? (
              <motion.div key="recipient" {...slide}>
                <h1 className="text-[28px] font-normal leading-tight tracking-[-0.04em]">Who are you paying?</h1>
                <p className="mt-2 text-[13.5px] text-ink-2">Rhône Cosmétiques SAS · invoice SSE-2026-118</p>
                <div className="mt-7 flex flex-col gap-2.5">
                  {RECIPIENTS.map((item) => {
                    const active = selection === item.order;
                    return (
                      <motion.button
                        key={item.order}
                        type="button"
                        whileTap={{ scale: 0.99 }}
                        onClick={() => {
                          setSelection(item.order);
                          clearQuoteForChange();
                        }}
                        className={cx(
                          "flex items-center gap-4 rounded-2xl border bg-white p-4 text-left transition-[border-color,box-shadow] duration-200",
                          active ? "border-ink shadow-[0_0_0_3px_rgba(10,10,10,0.06)]" : "border-[var(--line-strong)] hover:border-[rgba(0,0,0,0.3)]",
                        )}
                      >
                        <span className="grid size-10 shrink-0 place-items-center rounded-full bg-[var(--surface-2)] text-[13px] font-medium">SS</span>
                        <span className="min-w-0 flex-1">
                          <span className="flex items-center gap-2">
                            <span className="truncate text-[14px] font-medium tracking-[-0.02em]">Savanna Shea Exports Ltd</span>
                            <span className={cx("shrink-0 rounded-full px-2 py-0.5 text-[10.5px] font-medium", item.tagTone)}>{item.tag}</span>
                          </span>
                          <span className="mt-0.5 block font-mono text-[11.5px] text-ink-2">
                            {item.account} · {item.holder}
                          </span>
                          <span className="mt-0.5 block text-[11.5px] text-ink-3">{item.source}</span>
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
                  })}
                  <motion.button
                    type="button"
                    whileTap={{ scale: 0.99 }}
                    onClick={() => {
                      setSelection("new");
                      clearQuoteForChange();
                    }}
                    className={cx(
                      "flex items-center gap-4 rounded-2xl border bg-white p-4 text-left transition-[border-color,box-shadow] duration-200",
                      newAccountSelected
                        ? "border-ink shadow-[0_0_0_3px_rgba(10,10,10,0.06)]"
                        : "border-[var(--line-strong)] hover:border-[rgba(0,0,0,0.3)]",
                    )}
                  >
                    <span className="grid size-10 shrink-0 place-items-center rounded-full bg-[var(--surface-2)] text-[13px] font-medium">SS</span>
                    <span className="min-w-0 flex-1">
                      <span className="flex items-center gap-2">
                        <span className="truncate text-[14px] font-medium tracking-[-0.02em]">Savanna Shea Exports Ltd</span>
                        <span className="shrink-0 rounded-full bg-[rgba(217,119,6,0.08)] px-2 py-0.5 text-[10.5px] font-medium text-[var(--medium)]">
                          New bank details
                        </span>
                      </span>
                      <span className="mt-0.5 block font-mono text-[11.5px] text-ink-2">
                        {maskAccountNumber(accountNumber)} · {holderName.trim() || "Account holder"}
                      </span>
                      <span className="mt-0.5 block text-[11.5px] text-ink-3">Enter the details from an emailed invoice</span>
                    </span>
                    <span
                      className={cx(
                        "grid size-5 shrink-0 place-items-center rounded-full border transition-colors",
                        newAccountSelected ? "border-ink bg-ink" : "border-[var(--line-strong)]",
                      )}
                    >
                      {newAccountSelected ? <Check size={11} color="#fff" /> : null}
                    </span>
                  </motion.button>
                </div>
                {enteredBankDetailsSelected ? (
                  <div className="mt-3 grid gap-2.5 rounded-2xl border border-[var(--line)] p-4">
                    <label className="grid gap-1 text-[12px] text-ink-2">
                      Account number
                      <input
                        aria-label="Account number"
                        type="password"
                        autoComplete="off"
                        maxLength={34}
                        value={accountNumber}
                        onChange={(event) => {
                          clearQuoteForChange();
                          setAccountNumber(event.target.value);
                        }}
                        className="h-10 rounded-lg border border-[var(--line-strong)] bg-white px-3 font-mono text-[13px] text-ink outline-none focus:border-ink"
                      />
                    </label>
                    <label className="grid gap-1 text-[12px] text-ink-2">
                      Account holder
                      <input
                        aria-label="Account holder"
                        autoComplete="off"
                        maxLength={60}
                        value={holderName}
                        onChange={(event) => {
                          clearQuoteForChange();
                          setHolderName(event.target.value);
                        }}
                        className="h-10 rounded-lg border border-[var(--line-strong)] bg-white px-3 text-[13px] text-ink outline-none focus:border-ink"
                      />
                    </label>
                    <label className="grid gap-1 text-[12px] text-ink-2">
                      Sender domain <span className="text-ink-3">Optional</span>
                      <input
                        aria-label="Sender domain (optional)"
                        autoComplete="off"
                        maxLength={253}
                        placeholder="savannashea-exports.co"
                        value={senderDomain}
                        onChange={(event) => {
                          clearQuoteForChange();
                          setSenderDomain(event.target.value);
                        }}
                        className="h-10 rounded-lg border border-[var(--line-strong)] bg-white px-3 text-[13px] text-ink outline-none focus:border-ink"
                      />
                    </label>
                    {(accountNumber.length > 0 && !validAccountNumber(accountNumber)) ||
                    (holderName.length > 0 && !accountDetailsValid) ? (
                      <p className="text-[11.5px] text-[var(--danger)]">
                        Enter a valid account number and account holder to continue.
                      </p>
                    ) : null}
                  </div>
                ) : null}
                <div className="mt-4 border-t border-[var(--line)] pt-4">
                  <button
                    type="button"
                    aria-expanded={invoiceOpen}
                    onClick={() => setInvoiceOpen((open) => !open)}
                    className="text-[12.5px] font-medium text-ink-2 underline-offset-2 transition-colors hover:text-ink"
                  >
                    {invoiceOpen ? "Hide invoice reader" : "Paste an invoice or e-mail"}
                  </button>
                  {invoiceOpen ? (
                    <div className="mt-3 grid gap-3">
                      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
                        <span className="text-[11.5px] text-ink-3">Synthetic test documents</span>
                        <span className="rounded-full bg-[var(--surface-2)] px-2 py-0.5 text-[9.5px] font-medium tracking-[0.08em] text-ink-3">
                          SYNTHETIC
                        </span>
                      </div>
                      <div className="flex flex-wrap gap-x-4 gap-y-1">
                        <button
                          type="button"
                          onClick={() =>
                            setInvoiceText(
                              [
                                "From: payments@savanna-shea.com",
                                "Invoice no: SSE-2026-118",
                                "Amount due: EUR 85,000.00",
                                "Beneficiary: Savanna Shea Exports Ltd",
                                "Account: GH•• •••• 2207",
                              ].join("\n"),
                            )
                          }
                          className="text-[11.5px] text-ink-2 underline underline-offset-2 transition-colors hover:text-ink"
                        >
                          Use a legitimate invoice
                        </button>
                        <button
                          type="button"
                          onClick={() =>
                            setInvoiceText(
                              [
                                "From: accounts@savannashea-exports.com",
                                "Invoice no: SSE-2026-118",
                                "Amount due: EUR 85,000.00",
                                "Beneficiary: K. MENSAH VENTURES",
                                "Account: GH•• •••• 9083",
                                "New bank details are included on this invoice.",
                              ].join("\n"),
                            )
                          }
                          className="text-[11.5px] text-ink-2 underline underline-offset-2 transition-colors hover:text-ink"
                        >
                          Use a diverted invoice
                        </button>
                      </div>
                      <textarea
                        aria-label="Invoice or e-mail"
                        value={invoiceText}
                        onChange={(event) => setInvoiceText(event.target.value)}
                        rows={5}
                        className="w-full resize-y rounded-xl border border-[var(--line-strong)] bg-white px-3 py-2.5 text-[12px] leading-relaxed text-ink outline-none focus:border-ink"
                      />
                      <button
                        type="button"
                        disabled={invoiceReading || !invoiceText.trim()}
                        onClick={readInvoice}
                        className="h-9 justify-self-start rounded-full bg-ink px-4 text-[12px] font-medium text-white transition-colors hover:bg-[#222] disabled:cursor-not-allowed disabled:bg-[rgba(0,0,0,0.12)] disabled:text-ink-3"
                      >
                        {invoiceReading ? "Reading…" : "Read it"}
                      </button>
                      {invoiceError ? (
                        <p role="alert" className="text-[12px] text-[var(--danger)]">
                          {invoiceError}
                        </p>
                      ) : null}
                      {invoiceResult ? (
                        <div className="rounded-xl border border-[var(--line)] px-3.5">
                          {!orderForMatchedPayment(invoiceResult.matchedOrder) ? (
                            <p className="border-b border-[var(--line)] py-3 text-[12px] leading-relaxed text-[var(--danger)]">
                              No recorded order matches this document: the PoC only executes the two recorded FR → GH orders.
                            </p>
                          ) : null}
                          <Row label="Payee">
                            {invoiceResult.intake.fields.accountHolder?.value ?? "—"}
                          </Row>
                          <Row label="Account">
                            {invoiceResult.intake.fields.account?.value ?? "—"}
                            {accountDiffersFromVerified(
                              invoiceResult.intake.fields.account?.value ?? null,
                              RECIPIENTS.find((item) => item.order === "legit")?.account ?? null,
                            ) ? (
                              <span className="ml-2 inline-block rounded-full bg-[rgba(217,119,6,0.08)] px-2 py-0.5 text-[10px] font-medium text-[var(--medium)]">
                                New bank details
                              </span>
                            ) : null}
                          </Row>
                          <Row label="Amount">{invoiceResult.intake.fields.amount?.value ?? "—"}</Row>
                          <Row label="Reference">{invoiceResult.intake.fields.invoiceRef?.value ?? "—"}</Row>
                          {invoiceResult.decision ? (
                            <Row label="Engine decision">
                              {invoiceResult.decision.risk.tier} · {invoiceResult.decision.risk.score}/100
                            </Row>
                          ) : null}
                        </div>
                      ) : null}
                    </div>
                  ) : null}
                </div>
              </motion.div>
            ) : null}

            {step === 1 ? (
              <motion.div key="amount" {...slide}>
                <h1 className="text-[28px] font-normal leading-tight tracking-[-0.04em]">How much?</h1>
                <p className="mt-2 text-[13.5px] text-ink-2">Sylo prices every compliant route for this amount.</p>
                <label className="mt-7 block rounded-2xl border border-[var(--line-strong)] p-4 transition focus-within:border-ink focus-within:shadow-[0_0_0_3px_rgba(10,10,10,0.06)]">
                  <span className="text-[12px] text-ink-2">You send</span>
                  <span className="mt-1 flex items-center gap-3">
                    <input
                      inputMode="decimal"
                      value={amountText}
                      onChange={(event) => {
                        clearQuoteForChange();
                        setAmountText(formatInput(event.target.value));
                      }}
                      className="min-w-0 flex-1 bg-transparent text-[34px] font-medium tracking-[-0.04em] text-ink outline-none"
                      aria-label="Amount in euros"
                    />
                    <span className="flex h-9 shrink-0 items-center gap-2 rounded-full bg-[var(--surface-2)] px-3 text-[13px] font-medium">
                      <span className="grid size-4 place-items-center rounded-full bg-[#003399] text-[8px] text-[#ffcc00]">★</span>
                      EUR
                    </span>
                  </span>
                </label>
                <label className="mt-3 block rounded-xl border border-[var(--line)] px-4 py-3 focus-within:border-ink">
                  <span className="text-[11.5px] text-ink-2">Invoice reference</span>
                  <input
                    aria-label="Invoice reference"
                    value={invoiceRef}
                    maxLength={24}
                    onChange={(event) => {
                      clearQuoteForChange();
                      setInvoiceRef(event.target.value);
                    }}
                    className="mt-1 block w-full bg-transparent font-mono text-[14px] text-ink outline-none"
                  />
                </label>
                {!invoiceRefValid ? (
                  <p className="mt-2 text-[11.5px] text-[var(--danger)]">Use 3–24 letters, numbers or hyphens.</p>
                ) : null}
                {amount === null ? (
                  <p className="mt-2 text-[11.5px] text-[var(--danger)]">Enter an amount from €100 to €1,000,000.</p>
                ) : null}

                <ol className="relative ml-[19px] mt-1 border-l-2 border-dotted border-[var(--line-strong)] py-2 pl-6">
                  {[
                    {
                      value: chosenCost !== null ? euros(chosenCost) : "—",
                      label: chosen ? `All-in cost · ${chosen.name}` : "All-in cost",
                    },
                    ...(swiftCost !== null && chosen?.routeId !== "R1" ? [{ value: euros(swiftCost), label: "Same payment via SWIFT", muted: true }] : []),
                    { value: chosen && quote ? etaOf(quote, chosen.routeId) ?? "—" : "—", label: "Should arrive" },
                    {
                      value: quote ? `${quote.risk.tier} · ${quote.risk.score}` : "—",
                      label: "Fraud check",
                      color: quote ? TIER_COLORS[quote.risk.tier] : undefined,
                    },
                  ].map((line) => (
                    <li key={line.label} className="relative flex items-baseline gap-3 py-1.5 text-[13px]">
                      <span className="absolute -left-[30px] top-[11px] size-[9px] rounded-full border-2 border-white bg-[rgba(0,0,0,0.25)]" />
                      <span
                        className={cx("min-w-[86px] font-mono text-[12.5px]", "muted" in line && line.muted ? "text-ink-3 line-through" : "text-ink")}
                        style={line.color ? { color: line.color } : undefined}
                      >
                        {quoting ? <span className="inline-block h-3 w-14 animate-pulse rounded bg-[var(--surface-2)]" /> : line.value}
                      </span>
                      <span className="text-ink-2">{line.label}</span>
                    </li>
                  ))}
                </ol>

                {selection === "diverted" && enteredBankDetailsSelected && !accountDetailsValid ? (
                  <p className="mt-2 text-[12.5px] text-[var(--danger)]">
                    Return to the recipient step and enter the full bank details for a custom amount or reference.
                  </p>
                ) : null}
                {quoteError ? <p className="mt-2 text-[12.5px] text-[var(--danger)]">{quoteError}</p> : null}
                {amount !== INVOICE_AMOUNT && amount !== null && quote ? (
                  <p className="mt-3 rounded-xl bg-[var(--surface-2)] px-3.5 py-2.5 text-[12px] leading-relaxed text-ink-2">
                    This amount is priced by the live engine before payment.
                  </p>
                ) : null}
              </motion.div>
            ) : null}

            {step === 2 && quote ? (
              <motion.div key="route" {...slide}>
                <h1 className="text-[28px] font-normal leading-tight tracking-[-0.04em]">How it travels</h1>
                <p className="mt-2 text-[13.5px] text-ink-2">The engine picked the cheapest route that is legal and safe enough.</p>
                <div className="mt-7 flex flex-col gap-2.5">
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
                          isChosen ? "border-ink shadow-[0_0_0_3px_rgba(10,10,10,0.06)]" : "border-[var(--line)]",
                        )}
                      >
                        <div className="flex items-start justify-between gap-4">
                          <div className="min-w-0">
                            <div className="flex items-center gap-2">
                              <span className={cx("text-[13.5px] font-medium tracking-[-0.02em]", reason ? "text-ink-3" : "text-ink")}>{route.name}</span>
                              {isChosen ? (
                                <span className="rounded-full bg-[var(--accent-soft)] px-2 py-0.5 text-[10.5px] font-medium text-accent">Chosen by Sylo</span>
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

            {step === 3 && quote && recipient ? (
              <motion.div key="review" {...slide}>
                <h1 className="text-[28px] font-normal leading-tight tracking-[-0.04em]">Review and send</h1>
                <p className="mt-2 text-[13.5px] text-ink-2">Nothing moves until the signed intent is committed.</p>
                <div className="mt-6 rounded-2xl border border-[var(--line)] px-4">
                  <Row label="To">
                    Savanna Shea Exports Ltd
                    <span className="block font-mono text-[11.5px] text-ink-3">
                      {recipient.account} · {recipient.holder}
                    </span>
                  </Row>
                  <Row label="Amount">
                    <span className="font-mono">{amount !== null ? euros(amount) : "—"}</span>
                  </Row>
                  <Row label="Invoice reference">{invoiceRef}</Row>
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
                <p className="mt-3 text-[11.5px] text-ink-3">
                  Synthetic data · rails simulated{quote.recorded ? " · engine offline, recorded quote" : ""}
                </p>
                {sendError ? <p className="mt-3 text-[12.5px] text-[var(--danger)]">{sendError}</p> : null}
              </motion.div>
            ) : null}
          </AnimatePresence>
        </div>

        <div className="mt-6 flex items-center gap-2.5">
          {step > 0 ? (
            <button
              type="button"
              onClick={() => setStep(step - 1)}
              className="h-11 rounded-full border border-[var(--line-strong)] px-5 text-[13px] font-medium text-ink transition-colors hover:bg-[var(--surface-2)]"
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
              className="flex h-11 flex-1 items-center justify-center gap-2 rounded-full bg-ink text-[13px] font-medium tracking-[-0.02em] text-white transition-colors hover:bg-[#222] disabled:bg-[rgba(0,0,0,0.12)] disabled:text-ink-3"
            >
              {step === 1 && quoting ? <Spinner size={14} color="#fff" /> : null}
              Continue
            </motion.button>
          ) : (
            <motion.button
              type="button"
              whileTap={{ scale: 0.98 }}
              disabled={sending || !chosen || amount === null}
              onClick={() => void send()}
              className="flex h-11 flex-1 items-center justify-center gap-2 rounded-full bg-accent text-[13px] font-medium tracking-[-0.02em] text-white transition-colors hover:bg-[#0023d6] disabled:opacity-60"
            >
              {sending ? <Spinner size={14} color="#fff" /> : null}
              {chosen && amount !== null ? `Send ${euros(amount)}` : "No route available"}
            </motion.button>
          )}
        </div>
      </section>
    </main>
  );
}
