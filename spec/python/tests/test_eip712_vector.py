import json

from sylo_spec.canonical import to_hex
from sylo_spec.devkeys import dev_address, dev_key
from sylo_spec.eip712 import (
    VECTOR_DOMAIN,
    VECTOR_PATH,
    digest,
    eth_account_digest,
    recover,
    render_vector,
    sign,
    vector_messages,
)

EXPECTED_TYPES = {
    "PaymentIntent": (
        "PaymentIntent(bytes32 paymentId,bytes32 corridorId,address beneficiary,address token,uint256 amount,"
        "bytes32 offchainHash,bytes32 decisionHash,bytes32 approvalHash,uint8 tier,uint64 validUntil,uint256 nonce)"
    ),
    "VerificationAttestation": (
        "VerificationAttestation(bytes32 paymentId,bytes32 intentHash,uint8 method,uint8 result,bool simSwapChecked,"
        "bytes32 evidenceHash,uint64 verifiedAt,uint256 nonce)"
    ),
    "Revocation": "Revocation(bytes32 paymentId,uint8 reasonCode,bytes32 caseHash,uint256 nonce)",
}


def test_vector_file_is_generated_from_code():
    assert VECTOR_PATH.read_text(encoding="utf-8") == render_vector(), "run: uv run python -m sylo_spec.eip712 --write"


def test_type_strings_match_the_spec():
    assert json.loads(VECTOR_PATH.read_text(encoding="utf-8"))["types"] == EXPECTED_TYPES


def test_manual_digest_matches_eth_account():
    for name, msg in vector_messages().items():
        assert digest(msg, VECTOR_DOMAIN) == eth_account_digest(msg, VECTOR_DOMAIN), name


def test_attestation_binds_the_intent_digest():
    messages = vector_messages()
    assert messages["VerificationAttestation"].intent_hash == to_hex(digest(messages["PaymentIntent"], VECTOR_DOMAIN))


def test_sign_and_recover_roundtrip():
    intent = vector_messages()["PaymentIntent"]
    for role in ("router_signer", "verifier_signer", "analyst_signer"):
        signature = sign(intent, VECTOR_DOMAIN, dev_key(role))
        assert len(signature) == 65 and signature[-1] in (27, 28)
        assert recover(intent, VECTOR_DOMAIN, signature) == dev_address(role)


def test_dev_keys_are_the_public_anvil_accounts():
    assert dev_address("deployer") == "0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266"
    assert dev_address("relayer") == "0x70997970C51812dc3A010C7d01b50e0d17dc79C8"
    assert dev_address("gh_vasp") == "0x14dC79964da2C08b23698B3D3cc7Ca32193d9955"
