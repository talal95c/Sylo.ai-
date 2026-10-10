import json

from sylo_spec.devkeys import dev_address, dev_key
from sylo_spec.eip712 import digest, recover, struct_hash
from sylo_spec.models import Eip712Domain, PaymentIntent, Revocation, VerificationAttestation

from sylo import REPO_DIR
from sylo.signer import Signer

VECTOR = json.loads((REPO_DIR / "spec" / "eip712.json").read_text(encoding="utf-8"))
DOMAIN = Eip712Domain(
    chain_id=int(VECTOR["domain"]["chainId"]), verifying_contract=VECTOR["domain"]["verifyingContract"]
)
MODELS = {"PaymentIntent": PaymentIntent, "VerificationAttestation": VerificationAttestation, "Revocation": Revocation}


def test_vector_digests_match_spec_file():
    for name, model in MODELS.items():
        entry = VECTOR["vectors"][name]
        message = model.model_validate(entry["message"])
        assert "0x" + struct_hash(message).hex() == entry["structHash"], name
        assert "0x" + digest(message, DOMAIN).hex() == entry["digest"], name


def test_signer_uses_dev_keys_when_the_environment_is_empty():
    signer = Signer({})
    assert signer.uses_dev_keys
    assert signer.address("router_signer") == dev_address("router_signer")
    intent = PaymentIntent.model_validate(VECTOR["vectors"]["PaymentIntent"]["message"])
    assert recover(intent, DOMAIN, signer.sign("router_signer", intent, DOMAIN)) == dev_address("router_signer")


def test_signer_prefers_keys_from_the_environment():
    signer = Signer({"ROUTER_SIGNER_PK": dev_key("guardian")})
    assert signer.address("router_signer") == dev_address("guardian")


def test_nonces_increase_per_role():
    signer = Signer({})
    assert [signer.next_nonce("router_signer") for _ in range(3)] == [1, 2, 3]
    assert signer.next_nonce("verifier_signer") == 1
