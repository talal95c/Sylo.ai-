"""The shared EIP-712 vector: the file matches the code, and the code matches eth-account."""

import json

from eth_account.messages import encode_typed_data
from eth_utils import keccak

from sylo_spec import EIP712_VECTOR_PATH, eip712
from sylo_spec.devkeys import dev_address, dev_key, dev_keys

PRD_TYPE_STRINGS = {
    "PaymentIntent": "PaymentIntent(bytes32 paymentId,bytes32 corridorId,address beneficiary,address token,uint256 amount,bytes32 offchainHash,bytes32 decisionHash,bytes32 approvalHash,uint8 tier,uint64 validUntil,uint256 nonce)",
    "VerificationAttestation": "VerificationAttestation(bytes32 paymentId,bytes32 intentHash,uint8 method,uint8 result,bool simSwapChecked,bytes32 evidenceHash,uint64 verifiedAt,uint256 nonce)",
    "Revocation": "Revocation(bytes32 paymentId,uint8 reasonCode,bytes32 caseHash,uint256 nonce)",
}


def test_type_strings_match_the_prd():
    for name, expected in PRD_TYPE_STRINGS.items():
        assert eip712.type_string(name) == expected


def test_vector_file_is_generated_by_the_code():
    assert EIP712_VECTOR_PATH.read_text(encoding="utf-8") == eip712.render_vector()


def test_vector_hashes_match_eth_account():
    vector = json.loads(EIP712_VECTOR_PATH.read_text(encoding="utf-8"))
    separator = eip712.domain_separator(eip712.VECTOR_DOMAIN)
    assert vector["domainSeparator"] == "0x" + separator.hex()
    for name, message in eip712.vector_messages().items():
        signable = encode_typed_data(full_message=eip712.typed_data(eip712.VECTOR_DOMAIN, message))
        assert signable.header == separator
        assert signable.body == eip712.struct_hash(message)
        expected_digest = keccak(b"\x19" + signable.version + signable.header + signable.body)
        entry = vector["vectors"][name]
        assert entry["structHash"] == "0x" + eip712.struct_hash(message).hex()
        assert entry["digest"] == "0x" + expected_digest.hex()
        assert vector["typeHashes"][name] == "0x" + keccak(text=PRD_TYPE_STRINGS[name]).hex()


def test_attestation_references_the_intent_digest():
    messages = eip712.vector_messages()
    intent_digest = eip712.digest(eip712.VECTOR_DOMAIN, messages["PaymentIntent"])
    assert messages["VerificationAttestation"].intent_hash == intent_digest


def test_sign_and_recover_with_each_role_key():
    messages = eip712.vector_messages()
    for role, name in (
        ("router_signer", "PaymentIntent"),
        ("verifier_signer", "VerificationAttestation"),
        ("analyst_signer", "Revocation"),
    ):
        signature = eip712.sign(eip712.VECTOR_DOMAIN, messages[name], dev_key(role).private_key)
        assert len(signature) == 65 and signature[64] in (27, 28)
        assert eip712.recover(eip712.VECTOR_DOMAIN, messages[name], signature) == dev_address(role)


def test_dev_keys_are_the_public_anvil_accounts():
    keys = dev_keys()
    assert keys["deployer"].address == "0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266"
    assert keys["gh_vasp"].address == eip712.VECTOR_BENEFICIARY
    assert [k.index for k in keys.values()] == list(range(9))
    assert len({k.address for k in keys.values()}) == 9
