"""The event schema, the scenarios and the recorded fixtures agree with each other."""

import pytest
from jsonschema import ValidationError

from sylo_spec import FIXTURE_FILES, FIXTURES_DIR, institution_ids, load_event_schema, read_fixture, validate_event
from sylo_spec.models import PayerSession, RiskResult, Tier
from sylo_spec.scenarios import ACCOUNTS, PAYER, SUPPLIER, SUPPLIER_INSTITUTION_ID, golden_case

V0_TYPES = {
    "session.reset", "system.mode", "scenario.started", "payment.created", "norms.checked", "risk.scored",
    "route.selected", "approval.granted", "intent.committed", "leg.sent", "leg.settled", "escrow.deposited",
    "payment.held", "verification.requested", "verification.recorded", "intent.revoked", "escrow.refunded",
    "escrow.released", "intent.executed", "payment.credited", "payment.stopped", "attack.attempted", "tx.reverted",
}


def _envelope(**overrides):
    event = {
        "v": 1, "seq": 1, "id": "evt-000001", "ts": "2026-10-11T09:00:00.000Z",
        "type": "session.reset", "paymentId": None, "simulated": False, "data": {},
    }
    event.update(overrides)
    return event


def test_schema_declares_every_v0_type_and_the_reserved_ones():
    schema = load_event_schema()
    declared = set(schema["properties"]["type"]["enum"])
    assert V0_TYPES <= declared
    assert set(schema["x-reserved"]["types"]) <= declared
    assert {entry["if"]["properties"]["type"]["const"] for entry in schema["allOf"]} == V0_TYPES


def test_envelope_rules():
    validate_event(_envelope())
    validate_event(_envelope(type="breaker.on", data={"anything": 1}))  # reserved: free-form data
    validate_event(_envelope(extra="ignored"))  # unknown fields are allowed
    for bad in (
        _envelope(v=2),
        _envelope(id="event-1"),
        _envelope(ts="2026-10-11 09:00:00"),
        _envelope(type="not.a.type"),
        _envelope(type="risk.scored", data={"score": 64}),  # missing required data fields
        _envelope(type="leg.sent", data={"hop": 0, "from": "a", "to": "b", "kind": "boat", "rail": "R3", "durationMs": 1}),
    ):
        with pytest.raises(ValidationError):
            validate_event(bad)


def test_model_aliases_are_camel_case():
    assert PayerSession().to_json() == {"simSwap72h": False, "newDevice24h": False, "country": "FR"}
    result = RiskResult(score=64, tier="MEDIUM", floor_tier=Tier.MEDIUM, rules_fired=["R-PV-01"], model="rules-v0")
    assert result.to_json()["floorTier"] == "MEDIUM" and result.tier is Tier.MEDIUM


def test_scenarios_use_known_institutions_and_golden_values():
    known = institution_ids()
    assert {PAYER.institution_id, PAYER.bank_institution_id, SUPPLIER_INSTITUTION_ID} <= known
    assert {a.institution_id for a in ACCOUNTS.values()} <= known
    assert SUPPLIER.nominated_account().successful_payments == 14
    legit_order, legit_ctx = golden_case("legit")
    assert legit_order.payment_id == "PAY-2026-0001" and legit_ctx.name_match == 1.0
    diverted_order, diverted_ctx = golden_case("diverted")
    assert diverted_order.payment_id == "PAY-2026-0002"
    assert diverted_order.provenance == "invoice_pdf_email" and diverted_ctx.norm_signals == ["R1"]
    assert diverted_ctx.name_match < 0.85 and diverted_ctx.account_age_hours >= 72
    assert diverted_ctx.account.successful_payments == 0


@pytest.mark.parametrize("name", FIXTURE_FILES)
def test_fixture_is_schema_valid(name):
    assert (FIXTURES_DIR / name).exists(), f"{name} is missing: run `make fixtures`"
    events = read_fixture(name)
    assert events, f"{name} is empty"
    for event in events:
        validate_event(event)
    seqs = [e["seq"] for e in events]
    assert seqs == list(range(seqs[0], seqs[0] + len(seqs)))
