"""Every user-facing sentence of the engine (v0 spec §5.11). Text is shown as written; never interpreted."""

from __future__ import annotations

from collections.abc import Mapping

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
    "EU_HIGH_RISK_EDD": (
        "Excluded: an institution on this route is in a country on the EU high-risk list, "
        "and no enhanced due diligence file is attached."
    ),
}

RULE_LABELS = {
    "GH_FX_EXPORT_PROCEEDS_NOMINATED_BANK": "Ghana's export-proceeds rule",
    "GH_WALLET_DAILY_CAP": "Ghana's wallet daily cap",
    "GH_VASP_LICENSED": "Ghana's VASP licensing rule",
    "EU_MICA_EMT_CASP": "MiCA",
    "EU_TRAVEL_RULE": "the travel rule",
    "SANCTIONS_SCREEN": "sanctions screening",
    "EU_HIGH_RISK_EDD": "the EU high-risk country rule",
    "EU_VOP_SCOPE": "the scope of Verification of Payee",
}

SIGNAL_R1 = "The requested account is not {payee_short}'s nominated export account."
SIGNAL_R4 = "The requested account is held in {country}, a country on the EU high-risk list, while the payee is in {expected}."
CONTROL_NOTICES = {
    "EU_VOP_SCOPE": (
        "The bank's Verification of Payee does not reach this account (outside SEPA): new or changed bank "
        "details need an out-of-band check on a known contact."
    ),
}

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


def route_reason_low(
    best_id: str, best_s: float, swift_s: float | None, excluded: list[tuple[str, str]], symbol: str = "€"
) -> str:
    if swift_s is None or best_id == "R1":
        text = f"{best_id} is the cheapest compliant route: {symbol}{best_s:,.0f} all-in (fees, FX margin and delay)."
    else:
        text = (
            f"{best_id} is the cheapest compliant route: {symbol}{best_s:,.0f} all-in (fees, FX margin and delay) "
            f"against {symbol}{swift_s:,.0f} via SWIFT."
        )
    for route_id, rule_id in excluded:
        text += f" {route_id} is excluded by {RULE_LABELS.get(rule_id, rule_id)}."
    return text


def route_reason_medium(
    best_id: str,
    best_s: float,
    swift_s: float | None,
    holding: list[tuple[str, str]],
    price_of_safety: float,
    symbol: str = "€",
) -> str:
    allowed = ", ".join(f"{rid} {SETTLEMENT_LABELS.get(settlement, settlement)}" for rid, settlement in holding)
    comparison = (
        f"{symbol}{best_s:,.0f}"
        if swift_s is None or best_id == "R1"
        else f"{symbol}{best_s:,.0f} against {symbol}{swift_s:,.0f}"
    )
    return (
        f"Risk is MEDIUM, so only routes that can hold the money are allowed ({allowed}). "
        f"{best_id} is the cheapest: {comparison}. Price of safety: {symbol}{price_of_safety:,.0f}."
    )


RAIL_UNAVAILABLE = {"RAIL_DOWN": "its rail is down", "KILL_SWITCH": "its adapter was cut by the kill switch"}


def rails_unavailable(unavailable: Mapping[str, str]) -> str:
    """Sentence added to the route reason when a rail could not be considered. Empty when all rails are up."""
    return "".join(
        f" {route_id} is not available: {RAIL_UNAVAILABLE.get(why, why)}." for route_id, why in sorted(unavailable.items())
    )


NO_ROUTE_HEADLINE = "Payment blocked: no route is allowed at this risk level"
NO_ROUTE_RAILS = (
    "No usable route is left ({routes} unavailable). The payment is not sent and a case is opened for the analyst."
)
NO_ROUTE_LIMITS_HEADLINE = "Payment waiting: no replacement route within the payer's limits"
NO_ROUTE_LIMITS = (
    "{usual} cannot be used right now, and the replacement ({routes}) is above what the payer accepts without "
    "being asked (fees up to {symbol}{fees:.0f}, at most {days:.0f} days). Nothing is sent: the payment waits for "
    "{usual} to come back, or for the payer to accept the other route."
)
ALERT_WAITING_ROUTE = "Your payment is waiting: its usual route is unavailable and the other one costs more than your limit."
NO_ROUTE_DETAIL = "Risk is {tier}. The payment is blocked before any money moves and a case is opened for the analyst."

# --- Approval --------------------------------------------------------------------------------

APPROVER_ROLES = {"claire": "CFO (strong customer authentication)", "marc": "Second approver (dual control, ≥ €20,000)"}
APPROVAL_NOTE_CONDITIONAL = "Funds are released only after the supplier confirms on a known contact"
APPROVAL_NOTE_DIRECT = "The payment is sent as soon as it is approved"
APPROVAL_WARNING_UNTRUSTED = "Account seen for the first time, details from an emailed invoice: verification required."
APPROVAL_AUTHOR_FIRST = "{author} created this payment and approves first"
APPROVAL_AUTHOR_TWICE = "The author of a payment cannot be its second approver"

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
REVOKED_BY = "Analyst (auto-confirmed)"
ANALYST = "Julien (fraud analyst)"
STOPPED_HEADLINE = "Payment stopped. EUR 85,000 returned to Rhône Cosmétiques."
STOPPED_DETAIL = (
    "The supplier denied the new bank details. The payment was revoked on-chain and refunded from escrow. "
    "A case was opened for the analyst."
)
CHAIN_REFUSED_HEADLINE = "Payment stopped: the smart contract refused a step"
CHAIN_REFUSED_DETAIL = "The chain rejected {function} with {reason}. No money moved beyond the last confirmed step."
CHAIN_REFUSED_HELD = "{detail} The money stays in the hold until an analyst decides."
CHAIN_DOWN_HEADLINE = "Chain unavailable: the payment stays where it is"
CHAIN_DOWN_DETAIL = (
    "The chain did not answer during {step}. Nothing is released by default: the payment stays held "
    "until the chain is back and an analyst decides."
)

# Bank hold (R1, when the escrow route cannot be used)
PROTECTION_BANK = (
    "EUR {amount} is held at {bank} before it leaves France. It can only go to the account fixed in the "
    "signed payment or stay with {payer}. The hold ends in 24 h if nobody confirms."
)
STOPPED_DETAIL_BANK = (
    "The supplier denied the new bank details. The payment was revoked on-chain and the bank hold was lifted: "
    "the money never left {bank}. A case was opened for the analyst."
)

# Out-of-band check when the known contact cannot be trusted (rule R-OOB-01)
NEXT_STEP_ANALYST = (
    "The SIM card behind Kwame Asante's number changed {hours:.0f} hours ago, so we do not text it (rule R-OOB-01). "
    "The analyst decides."
)
NEXT_STEP_ANALYST_UNAVAILABLE = (
    "The SIM-swap check was unavailable, so the known contact cannot be trusted and we do not text it "
    "(rule R-OOB-01). The analyst decides."
)
STOPPED_DETAIL_ANALYST = (
    "The out-of-band check could not be trusted, and the analyst revoked the payment. It was refunded from escrow."
)
STOPPED_DETAIL_ANALYST_BANK = (
    "The analyst revoked the payment and the bank hold was lifted: the money never left {bank}."
)
FROZEN_DETAIL = "The analyst froze this payment: it cannot be released. Only a refund to the payer is possible."

# Payee verification before any payment (PRD §6.3 "protect before approval", §12.3)
PAYEE_VERIFICATION_REQUESTED = "Out-of-band check of {account} ({holder}) with {contact}, on a number on file since {since}."
PAYEE_VERIFICATION_ANALYST = (
    "The known contact of {payee} cannot be used ({why}): nobody is texted and an analyst checks {account}."
)
PAYEE_VERIFICATION_RECORDED = {
    "CONFIRMED": "{contact} confirmed that {account} ({holder}) belongs to {payee}.",
    "DENIED": "{contact} denied that {account} ({holder}) belongs to {payee}.",
}
CONTACT_TOO_RECENT = "it was registered less than {days} days ago"
CONTACT_SIM_SWAP = "its SIM card changed recently"
DENIED_ACCOUNT_HEADLINE = "Payment blocked: the supplier denied this account"
DENIED_ACCOUNT_DETAIL = (
    "{payee} said on {at} that {account} ({holder}) is not theirs. Nothing was sent and no approval was asked."
)
ALERT_DENIED_ACCOUNT = "Payment not sent: your supplier told us this bank account is not theirs."

# Confidential chain leg with eERC (PRD §13.6)
CONFIDENTIAL_TRANSFER = (
    "Sent as an eERC confidential transfer: the amount is not readable on-chain. The designated auditor "
    "decrypted EUR {amount}, which matches the payment."
)
CONFIDENTIAL_FALLBACK = (
    "The confidential leg is unavailable ({why}). This leg was sent as a public transfer instead: "
    "the amount is visible on-chain."
)
CONFIDENTIAL_MISMATCH_HEADLINE = "Payment stopped: the confidential leg does not match the payment"
CONFIDENTIAL_MISMATCH = (
    "The auditor decrypted EUR {seen} for a payment of EUR {expected}. The next leg is not sent and an analyst is alerted."
)

# Hold expiry and time-lock (PRD §12.3), shown in seconds with the demo clock
EXPIRY_BY = "Hold expiry (automatic)"
STOPPED_DETAIL_EXPIRED = (
    "Nobody confirmed the new bank details before the hold expired. The payment was revoked on-chain and "
    "refunded from escrow."
)
STOPPED_DETAIL_EXPIRED_BANK = (
    "Nobody confirmed the new bank details before the hold expired. The payment was revoked and the money "
    "never left {bank}."
)
ALERT_STOPPED_EXPIRED = "Payment returned: your supplier did not confirm the new account in time. Funds returned."
TIME_LOCK_ON = (
    "First payment to a new account: EUR {amount} stays at {bank} until {hours:g} h after the hold started, "
    "even though the supplier confirmed."
)
CLOCK_ADVANCED = "Demo clock: {hours:g} h later."

# --- Alerts (payer and supplier are told in the app or by SMS, never by e-mail) ---------------

ALERT_CHANNELS = ("IN_APP", "SMS", "NETWORK")
ALERT_HELD = "Payment held: we are checking the new bank details with your supplier. Your money is protected."
ALERT_STOPPED = "Payment stopped: the supplier did not confirm the new account. Funds returned."
ALERT_STOPPED_ANALYST = "Payment stopped by your bank's fraud team. Funds returned."
ALERT_FREEZE_REQUEST = (
    "Fraud alert on UETR {uetr}: please freeze account {account} ({holder}). A payment to it was revoked "
    "{cause}."
)
FREEZE_CAUSE_DENIED = "after the real supplier denied the bank details"
FREEZE_CAUSE_ANALYST = "by the sender's fraud team"
FREEZE_CAUSE_KILL = "after the route it used was cut"
FREEZE_CAUSE_GUARDIAN = "after a confirmation that the supplier never gave"

# --- Rails -----------------------------------------------------------------------------------

LEG_REJECTED = {
    "INTENT_HASH_MISMATCH": "The leg does not match the payment sealed in the registry.",
    "NONCE_USED": "This leg was already executed: a replay is refused.",
    "REVOKED": "The payment was revoked: no leg can be sent.",
    "EXPIRED": "The payment's validity window has passed.",
    "NOT_CONFIRMED": "The supplier has not confirmed: money cannot move towards the beneficiary.",
    "RAIL_DOWN": "The rail is down.",
    "KILL_SWITCH": "The adapter was cut by the kill switch.",
}
LEG_REJECTED_HEADLINE = "Payment stopped: a rail refused a leg"
LEG_REJECTED_DETAIL = "{rail} refused hop {hop} ({reason}). Nothing was sent on this leg."

# --- Network defence and incidents (v2) -------------------------------------------------------

BREAKER_PROPOSED = (
    "Proposed circuit breaker: for {hours} h, payments to {region} are at least MEDIUM and thresholds drop by 20 points."
)
BREAKER_ON = (
    "Circuit breaker on {region}: payments there are at least MEDIUM and thresholds are {points} points lower for {hours} h."
)
REASON_BREAKER = (
    "A circuit breaker is active on {region} after a wave of linked payments: at least MEDIUM, thresholds {points} points lower."
)
REASON_DEGRADED = "A dependency is down ({what}): a payment to an account that is not on file is at least MEDIUM."
RAIL_DOWN_REASON = "Off-ramp unavailable (simulated outage)"
WAVE_PAYMENT = "Seen on the network: {payer} pays EUR {amount} to a new account held by {holder}."
KILL_SWITCH_REASON = "{refusals} legs changed or replayed on this adapter within {minutes:.0f} minutes"
KILL_SWITCH_BY = "Kill switch (automatic)"
STOPPED_DETAIL_KILL = (
    "The adapter of this route was cut by the kill switch. The payment was revoked on-chain and refunded from escrow."
)
STOPPED_DETAIL_KILL_BANK = (
    "The adapter of this route was cut by the kill switch. The payment was revoked and the money never left {bank}."
)
ALERT_STOPPED_KILL = "Payment stopped for safety: the route it was using was cut. Funds returned."
GUARDIAN_HEADLINE = "On-chain incident: {rule}"
GUARDIAN_PAUSE_REASON = "Corridor paused by the guardian (incident {incident}): no escrow release until it is reopened"
ALERT_GUARDIAN_FROZEN = (
    "The guardian froze this hold ({rule}): a confirmation reached the registry that the engine never signed. "
    "The supplier's answer is no longer waited for. Revoke the payment to refund the payer."
)
STOPPED_DETAIL_GUARDIAN = (
    "A confirmation reached the registry that the engine never signed, so the guardian froze the hold. "
    "The analyst revoked the payment and it was refunded from escrow."
)
ALERT_REGISTRY_REFUSED = (
    "The registry refused the supplier's answer ({reason}): its state changed outside the engine. "
    "Nothing is released. Revoke the payment to refund the payer."
)
DORA_CRITICALITY = "Payment execution (critical function)"

# --- Case file built from the rules (used when no case writer is available) -----------------

CASE_OPENING = "{payment}: EUR {amount} to {payee} is rated {tier} (score {score}/100)"
CASE_CLOSING_HELD = "The money is stopped before it reaches the beneficiary, until the supplier answers on a known contact"
CASE_CLOSING_ANALYST = "The supplier's known number cannot be trusted, so the decision is the analyst's"
CASE_CLOSING_BLOCKED = "No route is allowed at this risk level: nothing was sent"
CASE_EXPLANATION_NEUTRAL = "No risk rule fired for this payment."
CASE_TIMELINE = {
    "payment.created": "Payment order received.",
    "risk.scored": "Risk scored {tier} ({score}/100).",
    "route.selected": "Route {routeId} selected.",
    "intent.committed": "Signed intent committed to the registry.",
    "escrow.deposited": "Funds locked in escrow.",
    "payment.held": "Payment held.",
    "payment.stopped": "Payment stopped.",
}
CASE_EXPLANATION = (
    "We paused this payment because the bank details changed and do not match your supplier's verified records. "
    "Your money is protected while we check with the supplier on a number we already know. "
    "You do not need to do anything; we will tell you the result in the app."
)
CASE_REPORT_DRAFT = (
    "DRAFT for the analyst, not filed. Possible supplier impersonation on {payment} (UETR {uetr}). "
    "Payer: {payer}. Amount: EUR {amount}. Expected beneficiary: {payee}. Requested account: {account} at {bank}, "
    "held by {holder}. Rules fired: {rules}. To file with TRACFIN if the supplier denies the change."
)

# --- Attacks ---------------------------------------------------------------------------------

ATTACK_RELEASE_REVOKED = "An attacker calls release() on the revoked payment to push the money to the mule account."
ATTACK_SWAP_BENEFICIARY = (
    "An attacker changes the beneficiary of a leg in transit to their own account, then tries to fund the escrow "
    "with the modified payment."
)
ATTACK_REPLAY = "An attacker replays the signed payment to commit it a second time."
ATTACK_STOLEN_KEY = (
    "A thief holding the verifier's signing key confirms the held payment without the supplier, "
    "then calls release() to push the money out of escrow."
)
ATTACK_DESCRIPTIONS = {
    "release_revoked": ATTACK_RELEASE_REVOKED,
    "swap_beneficiary": ATTACK_SWAP_BENEFICIARY,
    "replay": ATTACK_REPLAY,
    "stolen_verifier_key": ATTACK_STOLEN_KEY,
}
ATTACKER_ACCOUNT = {"name": "K. MENSAH VENTURES (attacker)", "account": "GH•• •••• 6660", "bank": "mule_bank"}
REVERTED = "Rejected by the smart contract: {reason}."

# --- Tax -------------------------------------------------------------------------------------

ELAPSED_SUFFIX = " (simulated)"
