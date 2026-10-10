// SPDX-License-Identifier: MIT
pragma solidity ^0.8.28;

// EIP-712 structs, enums and type hashes shared by the registry and the escrow (docs/v0-build-spec.md §4.4).
// Field order and enum numbers are binding: they must match spec/eip712.json and sylo_spec.eip712.

enum Tier {
    LOW,
    MEDIUM,
    HIGH,
    CRITICAL
}

enum Status {
    NONE,
    COMMITTED,
    CONFIRMED,
    DENIED,
    REVOKED,
    EXECUTED
}

enum VerificationMethod {
    UNSPECIFIED,
    OOB_KNOWN_CONTACT,
    PSP_ATTESTATION
}

enum VerificationResult {
    UNSPECIFIED,
    CONFIRMED,
    DENIED
}

enum RevocationReason {
    UNSPECIFIED,
    SUPPLIER_DENIED,
    ANALYST_DECISION,
    KILL_SWITCH,
    EXPIRED
}

struct PaymentIntent {
    bytes32 paymentId;
    bytes32 corridorId;
    address beneficiary;
    address token;
    uint256 amount;
    bytes32 offchainHash;
    bytes32 decisionHash;
    bytes32 approvalHash;
    uint8 tier;
    uint64 validUntil;
    uint256 nonce;
}

struct VerificationAttestation {
    bytes32 paymentId;
    bytes32 intentHash;
    uint8 method;
    uint8 result;
    bool simSwapChecked;
    bytes32 evidenceHash;
    uint64 verifiedAt;
    uint256 nonce;
}

struct Revocation {
    bytes32 paymentId;
    uint8 reasonCode;
    bytes32 caseHash;
    uint256 nonce;
}

bytes32 constant PAYMENT_INTENT_TYPEHASH = keccak256(
    "PaymentIntent(bytes32 paymentId,bytes32 corridorId,address beneficiary,address token,uint256 amount,bytes32 offchainHash,bytes32 decisionHash,bytes32 approvalHash,uint8 tier,uint64 validUntil,uint256 nonce)"
);

bytes32 constant VERIFICATION_ATTESTATION_TYPEHASH = keccak256(
    "VerificationAttestation(bytes32 paymentId,bytes32 intentHash,uint8 method,uint8 result,bool simSwapChecked,bytes32 evidenceHash,uint64 verifiedAt,uint256 nonce)"
);

bytes32 constant REVOCATION_TYPEHASH = keccak256("Revocation(bytes32 paymentId,uint8 reasonCode,bytes32 caseHash,uint256 nonce)");
