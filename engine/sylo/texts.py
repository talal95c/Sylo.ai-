"""Every user-facing sentence of the engine (v0 spec §5.11). Text is shown as written; never interpreted."""

from __future__ import annotations

from sylo_spec.models import Account, Payee

# --- Norms -----------------------------------------------------------------------------------

EXCLUSION_REASONS = {
    "GH_FX_EXPORT_PROCEEDS_NOMINATED_BANK": (
        "Excluded: Ghana requires export proceeds to reach the exporter's nominated bank account, "
        "and mobile wallets cannot receive them."
    ),
    "GH_WALLET_DAILY_CAP": "Excluded: the amount is above the Ghanaian mobile wallet daily cap (GHS 25,000).",
    "GH_VASP_LICENSED": "Excluded: the Ghanaian virtual-asset provider on this route is not licensed.",
    "EU_MICA_EMT_CASP": "Excluded: the EU crypto-asset provider or token on this route is not authorised under MiCA.",
    "EU_TRAVEL_RULE": "Excluded: the originator or beneficiary information required by the travel rule is missing.",
    "SANCTIONS_SCREEN": "Excluded: a party is on the sanctions list.",
}

RULE_LABELS = {
    "GH_FX_EXPORT_PROCEEDS_NOMINATED_BANK": "Ghana's export-proceeds rule",
    "GH_WALLET_DAILY_CAP": "Ghana's wallet daily cap",
    "GH_VASP_LICENSED": "Ghana's VASP licensing rule",
    "EU_MICA_EMT_CASP": "MiCA",
    "EU_TRAVEL_RULE": "the travel rule",
    "SANCTIONS_SCREEN": "sanctions screening",
}

SIGNAL_R1 = "The requested account is not {payee_short}'s nominated export account."

# --- Risk ------------------------------------------------------------------------------------

PAYEE_SHORT_NAMES = {"payee-ssx": "Savanna Shea"}


def payee_short(payee: Payee | None) -> str:
    if payee is None:
        return "the supplier"
    return PAYEE_SHORT_NAMES.get(payee.id, payee.legal_name)


def eur(amount: float) -> str:
    return f"{amount:,.0f}"


def reason_untrusted_provenance(provenance: str, payee: Payee | None) -> str:
    if provenance == "invoice_pdf_email":
        return f"The new bank details came from an emailed invoice, not from {payee_short(payee)}'s verified records."
    return f"The bank details come from an unverified source ({provenance}), not from {payee_short(payee)}'s verified records."


def reason_first_payment(amount_eur: float) -> str:
    return f"This is the first payment ever to this account, and it is for EUR {eur(amount_eur)}."


def reason_young_account(hours: float, amount_eur: float) -> str:
    return f"The account was opened {hours:.0f} hours ago and receives EUR {eur(amount_eur)}."


def reason_name_mismatch(holder: str, payee_name: str, score: float) -> str:
    return f"The account holder '{holder}' does not match the supplier '{payee_name}' (name match {score:.2f})."


REASON_NOT_NOMINATED = (
    "Ghanaian rules require export payments to reach the exporter's nominated bank. This account is not it."
)
REASON_SANCTIONS = "A party matches the sanctions list (synthetic list)."
REASON_MODEL_UNAVAILABLE = "Risk model unavailable: held for verification as a precaution."
REASON_VERIFIED_REGISTRY = "Bank details come from the verified supplier registry."


def reason_known_supplier(account: Account) -> str:
    return (
        f"Known supplier: {account.successful_payments} successful payments to this nominated account "
        f"since {account.first_seen[:4]}."
    )


# --- Routing ---------------------------------------------------------------------------------

SETTLEMENT_LABELS = {"FIAT_HOLD": "bank hold", "ONCHAIN_ESCROW": "escrow"}


def route_reason_low(best_id: str, best_s: float, swift_s: float | None, excluded: list[tuple[str, str]]) -> str:
    if swift_s is None or best_id == "R1":
        text = f"{best_id} is the cheapest compliant route: €{best_s:.0f} all-in."
    else:
        text = f"{best_id} is the cheapest compliant route: €{best_s:.0f} all-in against €{swift_s:.0f} via SWIFT."
    for route_id, rule_id in excluded:
        text += f" {route_id} is excluded by {RULE_LABELS.get(rule_id, rule_id)}."
    return text


def route_reason_medium(
    best_id: str, best_s: float, swift_s: float | None, holding: list[tuple[str, str]], price_of_safety: float
) -> str:
    allowed = ", ".join(f"{rid} {SETTLEMENT_LABELS.get(settlement, settlement)}" for rid, settlement in holding)
    comparison = f"€{best_s:.0f}" if swift_s is None or best_id == "R1" else f"€{best_s:.0f} against €{swift_s:.0f}"
    return (
        f"Risk is MEDIUM, so only routes that can hold the money are allowed ({allowed}). "
        f"{best_id} is the cheapest: {comparison}. Price of safety: €{price_of_safety:.0f}."
    )


NO_ROUTE_HEADLINE = "Payment blocked: no route is allowed at this risk level"
NO_ROUTE_DETAIL = "Risk is {tier}. The payment is blocked before any money moves and a case is opened for the analyst."

# --- Approval --------------------------------------------------------------------------------

APPROVER_ROLES = {"claire": "CFO (strong customer authentication)", "marc": "Second approver (dual control, ≥ €20,000)"}

# --- Hold, verification, outcome -------------------------------------------------------------

HELD_HEADLINE = "Payment held: possible supplier impersonation"
PROTECTION = (
    "EUR 85,000 is locked in the escrow smart contract on Avalanche. It can only go to the account fixed in "
    "the signed payment or back to Rhône Cosmétiques. Automatic refund in 24 h if nobody confirms."
)
NEXT_STEP = (
    "We are asking Savanna Shea on the number already on file for Kwame Asante, after checking that it was "
    "not SIM-swapped."
)
HIGH_IDENTITY_ONLY_HOLD = (
    "High risk on the beneficiary's identity only: held in escrow until out-of-band confirmation"
)
ANSWER_DENY = 'Kwame Asante: "We have not changed our bank details. Do not pay this account."'
ANSWER_CONFIRM = 'Kwame Asante: "Yes, this is our new account."'
REVOKED_BY = "Analyst (auto-confirmed in v0)"
STOPPED_HEADLINE = "Payment stopped. EUR 85,000 returned to Rhône Cosmétiques."
STOPPED_DETAIL = (
    "The supplier denied the new bank details. The payment was revoked on-chain and refunded from escrow. "
    "A case was opened for the analyst."
)
CHAIN_REFUSED_HEADLINE = "Payment stopped: the smart contract refused a step"
CHAIN_REFUSED_DETAIL = "The chain rejected {function} with {reason}. No money moved beyond the last confirmed step."

# --- Attacks ---------------------------------------------------------------------------------

ATTACK_RELEASE_REVOKED = "An attacker calls release() on the revoked payment to push the money to the mule account."
REVERTED = "Rejected by the smart contract: {reason}."

# --- Tax -------------------------------------------------------------------------------------

ELAPSED_SUFFIX = " (simulated)"
