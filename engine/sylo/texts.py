"""Every user-facing sentence of the engine (build spec, section 5.11).

The web app shows these texts as they are: it never writes a decision sentence itself.
"""


def eur(amount: float) -> str:
    """EUR 85,000"""
    return f"EUR {amount:,.0f}"


def euros(amount: float) -> str:
    """€179"""
    return f"€{amount:,.0f}"


# --- norms -------------------------------------------------------------------

EXCLUDED_WALLET_EXPORT_PROCEEDS = (
    "Excluded: Ghana requires export proceeds to reach the exporter's nominated bank account, "
    "and mobile wallets cannot receive them."
)
EXCLUDED_MISSING_LOC = "Excluded: Ghana requires a Letter of Commitment (LOC) reference for export proceeds."
EXCLUDED_WALLET_CAP = "Excluded: the amount is above the daily cap of Ghanaian mobile wallets (GHS 25,000, enhanced KYC)."
EXCLUDED_GENERIC = "Excluded: the route does not pass rule {rule_id}."


def signal_r1(supplier: str) -> str:
    return f"The requested account is not {supplier}'s nominated export account."


TAX_NO_WITHHOLDING = (
    "No Ghanaian withholding tax on payments for goods by a non-resident buyer; "
    "France–Ghana tax convention (1993) in force."
)
TAX_DAC8 = "The EU crypto-asset provider reports this leg under DAC8 (since 1 January 2026)."

# --- risk reasons --------------------------------------------------------------


def reason_pv_01(supplier: str) -> str:
    return f"The new bank details came from an emailed invoice, not from {supplier}'s verified records."


def reason_fl_01(amount: float) -> str:
    return f"This is the first payment ever to this account, and it is for {eur(amount)}."


def reason_fl_02(amount: float) -> str:
    return f"The account was opened less than 72 hours ago, and the payment is for {eur(amount)}."


def reason_fl_03(holder: str, supplier_legal_name: str, score: float) -> str:
    return f"The account holder '{holder}' does not match the supplier '{supplier_legal_name}' (name match {score:.2f})."


REASON_NM_01 = "Ghanaian rules require export payments to reach the exporter's nominated bank. This account is not it."
REASON_HB_01 = "The beneficiary matches the sanctions list (synthetic list)."


def reason_known_supplier(payments: int, since_year: int) -> str:
    return f"Known supplier: {payments} successful payments to this nominated account since {since_year}."


REASON_VERIFIED_REGISTRY = "Bank details come from the verified supplier registry."
REASON_NO_RULE = "No risk rule fired for this payment."

# --- route ---------------------------------------------------------------------


def route_reason_low(route_id: str, cost: float, swift_cost: float, wallet_excluded: bool) -> str:
    text = f"{route_id} is the cheapest compliant route: {euros(cost)} all-in against {euros(swift_cost)} via SWIFT."
    if wallet_excluded:
        text += " R4 is excluded by Ghana's export-proceeds rule."
    return text


def route_reason_medium(route_id: str, cost: float, other_cost: float, price_of_safety: float) -> str:
    return (
        "Risk is MEDIUM, so only routes that can hold the money are allowed (R1 bank hold, R3 escrow). "
        f"{route_id} is the cheapest: {euros(cost)} against {euros(other_cost)}. "
        f"Price of safety: {euros(price_of_safety)}."
    )


ROUTE_REASON_NONE = "Risk is {tier}: no route is allowed until an analyst decides."

# --- hold, verification, outcome -------------------------------------------------

HELD_HEADLINE = "Payment held: possible supplier impersonation"


def protection(amount: float, payer: str) -> str:
    return (
        f"{eur(amount)} is locked in the escrow smart contract on Avalanche. It can only go to the account fixed "
        f"in the signed payment or back to {payer}. Automatic refund in 24 h if nobody confirms."
    )


def next_step(supplier: str, contact: str) -> str:
    return (
        f"We are asking {supplier} on the number already on file for {contact}, "
        "after checking that it was not SIM-swapped."
    )


def answer_deny(contact: str) -> str:
    return f'{contact}: "We have not changed our bank details. Do not pay this account."'


def answer_confirm(contact: str) -> str:
    return f'{contact}: "Yes, this is our new account."'


ANALYST_AUTO = "Analyst (auto-confirmed in v0)"


def stopped_headline(amount: float, payer: str) -> str:
    return f"Payment stopped. {eur(amount)} returned to {payer}."


STOPPED_DETAIL = (
    "The supplier denied the new bank details. The payment was revoked on-chain and refunded from escrow. "
    "A case was opened for the analyst."
)

ELAPSED_SIMULATED = "{eta} (simulated)"

# --- attacks ---------------------------------------------------------------------

ATTACK_RELEASE_REVOKED = "An attacker calls release() on the revoked payment to push the money to the mule account."


def reverted(reason: str) -> str:
    return f"Rejected by the smart contract: {reason}."
