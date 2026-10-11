import { createHash } from "node:crypto";
import { mkdir, writeFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import path from "node:path";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const fixturesDirectory = path.join(root, "samples/fixtures");
const startTime = Date.parse("2026-10-11T09:00:00.000Z");
const euInstitutions = new Set(["payer_rhone", "bank_fr", "casp_eu"]);
const fixtureHash = (value) =>
  `0x${createHash("sha256").update(value).digest("hex")}`;
let transactionNumber = 0;

function transactionHash() {
  transactionNumber += 1;
  return fixtureHash(`sylo-mock-${transactionNumber}`);
}

function makeTimeline(paymentId, firstSequence = 1, time = startTime) {
  let seq = firstSequence - 1;
  let currentTime = time;
  const events = [];

  function add(type, data, delayMs = 0, simulated = false) {
    currentTime += delayMs;
    seq += 1;
    events.push({
      v: 1,
      seq,
      id: `evt-${String(seq).padStart(6, "0")}`,
      ts: new Date(currentTime).toISOString(),
      type,
      paymentId,
      simulated,
      data,
    });
    return events.at(-1);
  }

  return {
    add,
    events,
    get currentTime() {
      return currentTime;
    },
    get nextSequence() {
      return seq + 1;
    },
  };
}

function writeFixture(name, events) {
  return writeFile(
    path.join(fixturesDirectory, `${name}.jsonl`),
    `${events.map((event) => JSON.stringify(event)).join("\n")}\n`,
  );
}

function hopsFor(route, creditor) {
  const common = {
    R1: [
      ["payer_rhone", "bank_fr", "bank"],
      ["bank_fr", "corr_uk", "bank"],
      ["corr_uk", creditor, "bank"],
    ],
    R2: [
      ["payer_rhone", "bank_fr", "bank"],
      ["bank_fr", "payout_nl", "bank"],
      ["payout_nl", creditor, "bank"],
    ],
    R3: [
      ["payer_rhone", "bank_fr", "bank"],
      ["bank_fr", "casp_eu", "bank"],
      ["casp_eu", "vasp_gh", "chain"],
      ["vasp_gh", creditor, "bank"],
    ],
    R4: [
      ["payer_rhone", "remit_fr", "wallet"],
      ["remit_fr", "momo_gh", "wallet"],
    ],
  }[route];
  const withHop = common.map(([from, to, kind]) => ({ from, to, kind }));
  if (route === "R3" && creditor === "bank_gh") {
    withHop.push({ from: "bank_gh", to: "supplier_ssx", kind: "bank" });
  }
  return withHop;
}

const routeDefinitions = [
  ["R1", "SWIFT correspondent", "FIAT_HOLD"],
  ["R2", "Payout provider", "NONE"],
  ["R3", "Euro stablecoin on Avalanche", "ONCHAIN_ESCROW"],
  ["R4", "Mobile wallet remittance", "NONE"],
];
const excludedReason =
  "Excluded: Ghana requires export proceeds to reach the exporter's nominated bank account, and mobile wallets cannot receive them.";
const r1Signal =
  "The requested account is not Savanna Shea's nominated export account.";
const riskReasons = {
  legit: [
    {
      ref: "B",
      text: "Known supplier: 14 successful payments to this nominated account since 2024.",
    },
    {
      ref: "V",
      text: "Bank details come from the verified supplier registry.",
    },
  ],
  diverted: [
    {
      ref: "V",
      text: "The new bank details came from an emailed invoice, not from Savanna Shea's verified records.",
    },
    {
      ref: "B",
      text: "This is the first payment ever to this account, and it is for EUR 85,000.",
    },
    {
      ref: "B",
      text: "The account holder 'K. MENSAH VENTURES' does not match the supplier 'Savanna Shea Exports Ltd' (name match 0.27).",
    },
    {
      ref: "R",
      text: "Ghanaian rules require export payments to reach the exporter's nominated bank. This account is not it.",
    },
  ],
};
const routeReasons = {
  legit:
    "R3 is the cheapest compliant route: €179 all-in against €216 via SWIFT. R4 is excluded by Ghana's export-proceeds rule.",
  diverted:
    "Risk is MEDIUM, so only routes that can hold the money are allowed (R1 bank hold, R3 escrow). R3 is the cheapest: €179 against €216. Price of safety: €0.",
};
const taxNotices = [
  {
    text: "No Ghanaian withholding tax on payments for goods by a non-resident buyer; France–Ghana tax convention signed in Accra on 5 April 1993, in force since 1 April 1997 (BOFiP BOI-INT-CVB-GHA).",
    reference: "FR-GH-DTC-1993",
  },
  {
    text: "The EU crypto-asset provider reports this leg under DAC8 (since 1 January 2026).",
    reference: "DAC8",
  },
];

function normsRoutes(creditor) {
  return routeDefinitions.map(([routeId, name, settlement]) => ({
    routeId,
    name,
    settlement,
    hops: hopsFor(routeId, creditor),
    status: routeId === "R4" ? "EXCLUDED" : "PASS",
    ...(routeId === "R4"
      ? {
          excludedBy: "GH_FX_EXPORT_PROCEEDS_NOMINATED_BANK",
          reason: excludedReason,
          legalRef: "GH_FX_EXPORT_PROCEEDS_NOMINATED_BANK",
        }
      : {}),
  }));
}

function evaluatedScores(tier) {
  return [
    { routeId: "R1", s: 216.0, excludedBy: null },
    { routeId: "R3", s: 179.21, excludedBy: null },
    {
      routeId: "R2",
      s: tier === "MEDIUM" ? null : 941.73,
      excludedBy:
        tier === "MEDIUM"
          ? "TIER_MEDIUM_REQUIRES_CONDITIONAL_SETTLEMENT"
          : null,
    },
    {
      routeId: "R4",
      s: null,
      excludedBy: "GH_FX_EXPORT_PROCEEDS_NOMINATED_BANK",
    },
  ];
}

function addDecisionEvents(timeline, scenario, paymentId, creditor) {
  const diverted = scenario === "diverted";
  const risk = diverted ? "MEDIUM" : "LOW";

  timeline.add("scenario.started", { scenario, speed: 1, auto: true });
  timeline.add(
    "payment.created",
    {
      uetr: diverted
        ? "6be7bc38-7b32-4f69-8a2d-8da4b4a2f002"
        : "f7c2e418-8a96-4c32-b9ed-9a43aa440001",
      payer: {
        id: "payer_rhone",
        name: "Rhône Cosmétiques SAS",
        institutionId: "payer_rhone",
      },
      beneficiary: {
        payeeName: "Savanna Shea Exports Ltd",
        accountHolder: diverted
          ? "K. MENSAH VENTURES"
          : "Savanna Shea Exports Ltd",
        accountMasked: diverted ? "•••• 0427" : "•••• 1184",
        institutionId: creditor,
        knownPayee: true,
        knownAccount: !diverted,
      },
      amount: { value: "85000.00", currency: "EUR" },
      purpose: "GOODS",
      invoiceRef: "SSE-2026-118",
      provenance: diverted ? "invoice_pdf_email" : "verified_registry",
      ...(diverted ? { senderDomain: "savannashea-exports.com" } : {}),
    },
    400,
  );
  timeline.add(
    "norms.checked",
    {
      packVersion: "2026-10-10",
      routes: normsRoutes(creditor),
      signals: diverted
        ? [
            {
              code: "R1",
              text: r1Signal,
              ruleId: "GH_FX_EXPORT_PROCEEDS_NOMINATED_BANK",
            },
          ]
        : [],
      taxNotices,
    },
    900,
  );
  timeline.add(
    "risk.scored",
    {
      score: diverted ? 64 : 10,
      tier: risk,
      rulesFired: diverted
        ? ["R-PV-01", "R-FL-01", "R-FL-03", "R-NM-01"]
        : [],
      reasons: riskReasons[scenario],
      model: "rules-v0",
    },
    900,
  );
  timeline.add(
    "route.selected",
    {
      routeId: "R3",
      name: "Euro stablecoin on Avalanche",
      settlement: "ONCHAIN_ESCROW",
      tier: risk,
      scores: evaluatedScores(risk),
      reason: routeReasons[scenario],
      feesEur: 170,
      etaLabel: "≈ 2 h",
      priceOfSafetyEur: 0,
    },
    900,
  );
  timeline.add(
    "approval.granted",
    {
      by: [
        { name: "Claire Martin", role: "CFO" },
        { name: "Marc Durand", role: "second approver" },
      ],
      method: "DUAL_CONTROL",
      conditional: diverted,
      approvalHash: fixtureHash(`sylo-approval-${paymentId}`),
    },
    1000,
  );
  timeline.add(
    "intent.committed",
    {
      intentHash: fixtureHash(`sylo-intent-${paymentId}`),
      tier: risk,
      txHash: transactionHash(),
      explorerUrl: null,
    },
    900,
    true,
  );
}

function addLeg(timeline, hops, index, durationMs) {
  const hop = hops[index];
  timeline.add(
    "leg.sent",
    {
      hop: index,
      from: hop.from,
      to: hop.to,
      kind: hop.kind,
      rail:
        hop.kind === "chain"
          ? "Avalanche C-Chain"
          : euInstitutions.has(hop.from) && euInstitutions.has(hop.to)
            ? "SEPA"
            : "Ghana local transfer",
      durationMs,
    },
    300,
    true,
  );
  timeline.add(
    "leg.settled",
    { hop: index, at: hop.to },
    durationMs,
    true,
  );
}

function addCredited(timeline) {
  timeline.add(
    "intent.executed",
    { txHash: transactionHash(), explorerUrl: null },
    400,
    true,
  );
  timeline.add(
    "payment.credited",
    {
      at: "supplier_ssx",
      feesEur: 170,
      routeCostEur: 179.21,
      swiftRouteCostEur: 216.0,
      elapsedLabel: "≈ 2 h (simulated)",
    },
    300,
  );
}

await mkdir(fixturesDirectory, { recursive: true });

const legitPaymentId = "PAY-2026-0001";
const legit = makeTimeline(legitPaymentId);
addDecisionEvents(legit, "legit", legitPaymentId, "bank_gh");
const legitHops = hopsFor("R3", "bank_gh");
for (let index = 0; index < legitHops.length; index += 1) {
  addLeg(legit, legitHops, index, legitHops[index].kind === "chain" ? 2200 : 1400);
}
addCredited(legit);
await writeFixture("scene1-legit", legit.events);

const divertedPaymentId = "PAY-2026-0002";
const diverted = makeTimeline(divertedPaymentId);
addDecisionEvents(diverted, "diverted", divertedPaymentId, "mule_bank");
const divertedHops = hopsFor("R3", "mule_bank");
addLeg(diverted, divertedHops, 0, 1400);
addLeg(diverted, divertedHops, 1, 1400);
diverted.add(
  "leg.sent",
  {
    hop: 2,
    from: "casp_eu",
    to: "vasp_gh",
    kind: "chain",
    rail: "Avalanche C-Chain",
    durationMs: 2200,
  },
  300,
  true,
);
const expiresAt = new Date(
  diverted.currentTime + 1100 + 24 * 60 * 60 * 1000,
).toISOString();
diverted.add(
  "escrow.deposited",
  {
    amount: "85000.00",
    token: "tEURC",
    expiresAt,
    txHash: transactionHash(),
    explorerUrl: null,
  },
  1100,
  true,
);
diverted.add(
  "payment.held",
  {
    hop: 2,
    at: "escrow",
    tier: "MEDIUM",
    headline: "Payment held: possible supplier impersonation",
    reasons: riskReasons.diverted,
    protection:
      "EUR 85,000 is locked in the escrow smart contract on Avalanche. It can only go to the account fixed in the signed payment or back to Rhône Cosmétiques. Automatic refund in 24 h if nobody confirms.",
    nextStep:
      "We are asking Savanna Shea on the number already on file for Kwame Asante, after checking that it was not SIM-swapped.",
    expiresAt,
  },
  200,
);
diverted.add(
  "verification.requested",
  {
    contactName: "Kwame Asante",
    contactMasked: "+233 •• ••• 4471",
    contactSince: "2024-03-12",
    channel: "SMS",
    simSwapChecked: true,
    simSwapRecent: false,
  },
  1500,
  true,
);
await writeFixture("scene2-diverted", diverted.events);

const deny = makeTimeline(
  divertedPaymentId,
  diverted.nextSequence,
  diverted.currentTime,
);
deny.add(
  "verification.recorded",
  {
    result: "DENIED",
    answerText:
      'Kwame Asante: "We have not changed our bank details. Do not pay this account."',
    txHash: transactionHash(),
    explorerUrl: null,
  },
  3000 + 800,
  true,
);
deny.add(
  "intent.revoked",
  {
    reasonCode: "SUPPLIER_DENIED",
    by: "Analyst (auto-confirmed in v0)",
    txHash: transactionHash(),
    explorerUrl: null,
  },
  1500,
  true,
);
deny.add(
  "escrow.refunded",
  {
    to: "payer_rhone",
    amount: "85000.00",
    txHash: transactionHash(),
    explorerUrl: null,
  },
  1000,
  true,
);
deny.add(
  "payment.stopped",
  {
    headline: "Payment stopped. EUR 85,000 returned to Rhône Cosmétiques.",
    detail:
      "The supplier denied the new bank details. The payment was revoked on-chain and refunded from escrow. A case was opened for the analyst.",
  },
  3200,
);
await writeFixture("scene2-deny", deny.events);

const confirm = makeTimeline(
  divertedPaymentId,
  diverted.nextSequence,
  diverted.currentTime,
);
confirm.add(
  "verification.recorded",
  {
    result: "CONFIRMED",
    answerText: 'Kwame Asante: "Yes, this is our new account."',
    txHash: transactionHash(),
    explorerUrl: null,
  },
  3000 + 800,
  true,
);
confirm.add(
  "escrow.released",
  {
    to: "vasp_gh",
    amount: "85000.00",
    txHash: transactionHash(),
    explorerUrl: null,
  },
  1000,
  true,
);
confirm.add(
  "intent.executed",
  { txHash: transactionHash(), explorerUrl: null },
  300,
  true,
);
confirm.add("leg.settled", { hop: 2, at: "vasp_gh" }, 1100, true);
addLeg(confirm, divertedHops, 3, 1400);
  confirm.add(
    "payment.credited",
    {
      at: "mule_bank",
      feesEur: 170,
      routeCostEur: 179.21,
    swiftRouteCostEur: 216.0,
    elapsedLabel: "≈ 2 h (simulated)",
  },
  300,
);
await writeFixture("scene2-confirm", confirm.events);

const attack = makeTimeline(
  divertedPaymentId,
  deny.nextSequence,
  deny.currentTime,
);
attack.add(
  "attack.attempted",
  {
    attack: "release_revoked",
    description:
      "An attacker calls release() on the revoked payment to push the money to the mule account.",
    by: "attacker",
  },
);
attack.add(
  "tx.reverted",
  {
    function: "release",
    reason: "PaymentNotReleasable",
    txHash: transactionHash(),
    explorerUrl: null,
  },
  900,
  true,
);
await writeFixture("scene2b-release-revoked", attack.events);
