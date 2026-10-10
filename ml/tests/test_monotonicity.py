from sylo_spec.scenarios import golden_case

from sylo_risk import ModelRisk
from sylo_risk.sim import generate_dataset, row_to_order_ctx


def test_untrusted_provenance_never_reduces_score_on_simulated_rows():
    risk = ModelRisk()
    frame = generate_dataset("A", small=True).sample(n=200, random_state=41)
    for _, row in frame.iterrows():
        order, context = row_to_order_ctx(row)
        trusted_order = order.model_copy(
            update={"provenance": {"creditorAccount": "payment_history"}}
        )
        untrusted_order = trusted_order.model_copy(
            update={"provenance": {"creditorAccount": "invoice_pdf_email"}}
        )
        assert risk.score(untrusted_order, context).score >= risk.score(trusted_order, context).score


def test_demo_history_is_present_for_golden_supplier():
    risk = ModelRisk()
    order, _ = golden_case("legit")
    entry = risk._history.get(order.debtor.id, order.payee_id)
    assert entry is not None
    assert entry.count == 14
    assert entry.median_amount == 85_000
