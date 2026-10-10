import json

from sylo.config import Settings
from sylo.signer import Signer
from sylo_spec import EIP712_VECTOR_PATH, eip712
from sylo_spec import scenarios as sc
from sylo_spec.canonical import payment_id_bytes
from sylo_spec.devkeys import dev_address
from sylo_spec.models import PaymentIntent, Revocation, Tier, VerificationAttestation

MODELS = {"PaymentIntent": PaymentIntent, "VerificationAttestation": VerificationAttestation, "Revocation": Revocation}


def test_vector_digests_match_the_spec_file():
    vector = json.loads(EIP712_VECTOR_PATH.read_text(encoding="utf-8"))
    domain = eip712.Eip712Domain.model_validate(vector["domain"])
    assert "0x" + eip712.domain_separator(domain).hex() == vector["domainSeparator"]
    for name, entry in vector["vectors"].items():
        message = MODELS[name].model_validate(entry["message"])  # rebuilt from the JSON file alone
        assert "0x" + eip712.struct_hash(message).hex() == entry["structHash"]
        assert "0x" + eip712.digest(domain, message).hex() == entry["digest"]


def test_signer_builds_and_signs_the_demo_intent():
    signer = Signer(Settings())
    order = sc.order("diverted")
    domain = eip712.VECTOR_DOMAIN
    intent = signer.build_intent(order, Tier.MEDIUM, {"decision": 1}, {"approval": 1}, now_ts=1_791_709_200)
    assert intent.payment_id == payment_id_bytes("PAY-2026-0002")
    assert intent.amount == 85_000 * 10**6 and intent.valid_until == 1_791_709_800 and intent.nonce == 1
    assert intent.beneficiary == dev_address("gh_vasp")
    assert eip712.recover(domain, intent, signer.sign_intent(domain, intent)) == dev_address("router_signer")
    # A second intent gets the next nonce; the salt is stable per payment and differs between payments.
    assert signer.build_intent(order, Tier.MEDIUM, {}, {}, 0).nonce == 2
    assert signer.salt_for("PAY-2026-0002") == signer.salt_for("PAY-2026-0002") != signer.salt_for("PAY-2026-0001")


def test_real_keys_are_required_outside_mock_mode():
    try:
        Signer(Settings(chain_mode="fuji"))
    except RuntimeError as err:
        assert "ROUTER_SIGNER_PK" in str(err)
    else:
        raise AssertionError("dev keys must not be used when CHAIN_MODE=fuji")
