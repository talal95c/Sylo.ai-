// SPDX-License-Identifier: MIT
pragma solidity ^0.8.28;

// Shared types of the Sylo.ai contracts: the three EIP-712 messages, the enumerations and the typehashes.
//
// The same types, numbers and hashes exist in Python (`sylo_spec.eip712`) and TypeScript. The file
// `spec/eip712.json` pins them; `test/Eip712Vector.t.sol` asserts that this file agrees with it.
//
// BINDING: the order and the Solidity type of every struct field below must match its type string
// character for character. Reordering a field changes every hash and breaks every signature.

// ---------------------------------------------------------------------------------------------
// Enumerations (same numbers in Python, Solidity and TypeScript)
// ---------------------------------------------------------------------------------------------

/// @notice Risk tier decided off-chain and sealed in the signed intent.
enum Tier {
    LOW, // 0: executed directly on the chosen rail
    MEDIUM, // 1: conditional settlement only (escrow), released after the supplier confirms
    HIGH, // 2: no route
    CRITICAL // 3: no route
}

/// @notice Status of a payment in `PaymentRegistry`.
/// NONE -> COMMITTED -> CONFIRMED | DENIED; COMMITTED | CONFIRMED | DENIED -> REVOKED (final);
/// CONFIRMED -> EXECUTED; COMMITTED -> EXECUTED (tier LOW only). Any other transition reverts.
enum Status {
    NONE, // 0
    COMMITTED, // 1
    CONFIRMED, // 2
    DENIED, // 3
    REVOKED, // 4 (final)
    EXECUTED // 5 (final)
}

/// @notice How the supplier was verified (`VerificationAttestation.method`). 0 is not a valid method.
enum VerificationMethod {
    UNSPECIFIED, // 0: placeholder so that the valid values start at 1
    OOB_KNOWN_CONTACT, // 1
    PSP_ATTESTATION // 2
}

/// @notice Answer of the verification (`VerificationAttestation.result`). 0 is not a valid result.
/// @dev Do not confuse with `Status`: result CONFIRMED is 1 and DENIED is 2, status CONFIRMED is 2 and DENIED is 3.
enum VerificationResult {
    UNSPECIFIED, // 0: placeholder so that the valid values start at 1
    CONFIRMED, // 1
    DENIED // 2
}

/// @notice Why a payment was revoked (`Revocation.reasonCode`). 0 is not a valid reason.
enum RevocationReason {
    UNSPECIFIED, // 0: placeholder so that the valid values start at 1
    SUPPLIER_DENIED, // 1
    ANALYST_DECISION, // 2
    KILL_SWITCH, // 3
    EXPIRED // 4
}

// ---------------------------------------------------------------------------------------------
// EIP-712 messages (domain: name "SyloPaymentRegistry", version "1", chainId, verifyingContract)
// ---------------------------------------------------------------------------------------------

/// @notice "The payer approved this beneficiary and amount, under this decision, valid until this time."
/// Signed by the router service of the sending bank (`ROUTER_SIGNER_ROLE`).
/// @dev `tier` holds a `Tier` number. It is a `uint8`, as in the type string, so any signed value can be hashed.
struct PaymentIntent {
    bytes32 paymentId; // keccak256(utf8("PAY-2026-0001"))
    bytes32 corridorId; // keccak256(utf8("FR-GH"))
    address beneficiary; // the only address an escrow release can pay
    address token; // settlement token (6 decimals in the PoC)
    uint256 amount; // in token units
    bytes32 offchainHash; // salted hash of the off-chain payment details
    bytes32 decisionHash; // hash of the routing and risk decision record
    bytes32 approvalHash; // hash of the payer's approval record
    uint8 tier; // Tier
    uint64 validUntil; // last second at which the intent may be committed
    uint256 nonce; // one use per signer
}

/// @notice "The supplier's known contact confirmed or denied, after a SIM-swap check."
/// Signed by the verifier service of the sending bank (`VERIFIER_SIGNER_ROLE`).
struct VerificationAttestation {
    bytes32 paymentId;
    bytes32 intentHash; // must equal the EIP-712 digest stored at commit
    uint8 method; // VerificationMethod
    uint8 result; // VerificationResult
    bool simSwapChecked;
    bytes32 evidenceHash; // hash of the verification evidence record
    uint64 verifiedAt;
    uint256 nonce; // one use per signer
}

/// @notice "This payment must not proceed", with the reason. Signed by the analyst (`ANALYST_SIGNER_ROLE`).
struct Revocation {
    bytes32 paymentId;
    uint8 reasonCode; // RevocationReason
    bytes32 caseHash; // hash of the case record
    uint256 nonce; // one use per signer
}

// ---------------------------------------------------------------------------------------------
// Typehashes: keccak256 of the type strings of build spec section 4.4 (field order is binding)
// ---------------------------------------------------------------------------------------------

bytes32 constant PAYMENT_INTENT_TYPEHASH = keccak256(
    "PaymentIntent(bytes32 paymentId,bytes32 corridorId,address beneficiary,address token,uint256 amount,bytes32 offchainHash,bytes32 decisionHash,bytes32 approvalHash,uint8 tier,uint64 validUntil,uint256 nonce)"
);

bytes32 constant VERIFICATION_ATTESTATION_TYPEHASH = keccak256(
    "VerificationAttestation(bytes32 paymentId,bytes32 intentHash,uint8 method,uint8 result,bool simSwapChecked,bytes32 evidenceHash,uint64 verifiedAt,uint256 nonce)"
);

bytes32 constant REVOCATION_TYPEHASH =
    keccak256("Revocation(bytes32 paymentId,uint8 reasonCode,bytes32 caseHash,uint256 nonce)");
