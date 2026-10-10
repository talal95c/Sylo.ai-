// SPDX-License-Identifier: MIT
pragma solidity ^0.8.28;

import {AccessControl} from "@openzeppelin/contracts/access/AccessControl.sol";
import {ECDSA} from "@openzeppelin/contracts/utils/cryptography/ECDSA.sol";
import {EIP712} from "@openzeppelin/contracts/utils/cryptography/EIP712.sol";
import {SignatureChecker} from "@openzeppelin/contracts/utils/cryptography/SignatureChecker.sol";

import {
    PAYMENT_INTENT_TYPEHASH,
    REVOCATION_TYPEHASH,
    VERIFICATION_ATTESTATION_TYPEHASH,
    PaymentIntent,
    Revocation,
    Status,
    Tier,
    VerificationAttestation,
    VerificationResult
} from "./SyloTypes.sol";

/// @title PaymentRegistry
/// @notice Records the signed EIP-712 attestations of every payment and its status.
/// Status machine: NONE -> COMMITTED -> CONFIRMED | DENIED; COMMITTED | CONFIRMED | DENIED -> REVOKED (final);
/// CONFIRMED -> EXECUTED; COMMITTED -> EXECUTED for LOW payments. Any other transition reverts.
/// @dev Signatures are 65-byte ECDSA signatures, or `abi.encodePacked(signer, signature)` for a contract
/// signer such as a multisig (ERC-1271). Nonces are single-use per signer.
contract PaymentRegistry is EIP712, AccessControl {
    bytes32 public constant ROUTER_SIGNER_ROLE = keccak256("ROUTER_SIGNER_ROLE");
    bytes32 public constant VERIFIER_SIGNER_ROLE = keccak256("VERIFIER_SIGNER_ROLE");
    bytes32 public constant ANALYST_SIGNER_ROLE = keccak256("ANALYST_SIGNER_ROLE");
    bytes32 public constant EXECUTOR_ROLE = keccak256("EXECUTOR_ROLE");

    struct Payment {
        bytes32 intentHash;
        Status status;
        uint8 tier;
        address beneficiary;
        address token;
        uint256 amount;
        bytes32 corridorId;
    }

    mapping(bytes32 paymentId => Payment) private _payments;
    mapping(address signer => mapping(uint256 nonce => bool)) public nonceUsed;

    event PaymentCommitted(bytes32 indexed paymentId, bytes32 indexed corridorId, bytes32 intentHash, address signer);
    event VerificationRecorded(bytes32 indexed paymentId, uint8 result, bytes32 evidenceHash, address signer);
    event PaymentRevoked(bytes32 indexed paymentId, uint8 reasonCode, address signer);
    event PaymentExecuted(bytes32 indexed paymentId, bytes32 executionRef);

    error InvalidTransition();
    error IntentExpired();
    error UnauthorizedSigner();
    error NonceUsed();
    error CommitmentMismatch();
    error InvalidResult();

    constructor(address admin) EIP712("SyloPaymentRegistry", "1") {
        _grantRole(DEFAULT_ADMIN_ROLE, admin);
    }

    /// @notice Commits a router-signed intent. Its EIP-712 digest is the payment's intent hash.
    function commit(PaymentIntent calldata i, bytes calldata routerSig) external {
        if (_payments[i.paymentId].status != Status.NONE) revert InvalidTransition();
        if (block.timestamp > i.validUntil) revert IntentExpired();
        bytes32 digest = _hashTypedDataV4(hashIntent(i));
        address signer = _signer(digest, routerSig, ROUTER_SIGNER_ROLE);
        _useNonce(signer, i.nonce);

        Payment storage p = _payments[i.paymentId];
        p.intentHash = digest;
        p.status = Status.COMMITTED;
        p.tier = i.tier;
        p.beneficiary = i.beneficiary;
        p.token = i.token;
        p.amount = i.amount;
        p.corridorId = i.corridorId;
        emit PaymentCommitted(i.paymentId, i.corridorId, digest, signer);
    }

    /// @notice Records the supplier's answer, checked out of band by the verifier service.
    function recordVerification(VerificationAttestation calldata v, bytes calldata verifierSig) external {
        Payment storage p = _payments[v.paymentId];
        if (p.status != Status.COMMITTED) revert InvalidTransition();
        if (v.intentHash != p.intentHash) revert CommitmentMismatch();
        if (v.result != uint8(VerificationResult.CONFIRMED) && v.result != uint8(VerificationResult.DENIED)) {
            revert InvalidResult();
        }
        address signer = _signer(_hashTypedDataV4(hashVerification(v)), verifierSig, VERIFIER_SIGNER_ROLE);
        _useNonce(signer, v.nonce);

        p.status = v.result == uint8(VerificationResult.CONFIRMED) ? Status.CONFIRMED : Status.DENIED;
        emit VerificationRecorded(v.paymentId, v.result, v.evidenceHash, signer);
    }

    /// @notice Revokes a payment that has not been executed. Final.
    function revoke(Revocation calldata r, bytes calldata revokerSig) external {
        Payment storage p = _payments[r.paymentId];
        Status s = p.status;
        if (s != Status.COMMITTED && s != Status.CONFIRMED && s != Status.DENIED) revert InvalidTransition();
        address signer = _signer(_hashTypedDataV4(hashRevocation(r)), revokerSig, ANALYST_SIGNER_ROLE);
        _useNonce(signer, r.nonce);

        p.status = Status.REVOKED;
        emit PaymentRevoked(r.paymentId, r.reasonCode, signer);
    }

    /// @notice Marks a payment executed: a confirmed payment, or a LOW payment straight after its commit.
    function markExecuted(bytes32 paymentId, bytes32 executionRef) external onlyRole(EXECUTOR_ROLE) {
        Payment storage p = _payments[paymentId];
        bool lowCommitted = p.status == Status.COMMITTED && p.tier == uint8(Tier.LOW);
        if (!lowCommitted && p.status != Status.CONFIRMED) revert InvalidTransition();

        p.status = Status.EXECUTED;
        emit PaymentExecuted(paymentId, executionRef);
    }

    function statusOf(bytes32 paymentId) external view returns (Status) {
        return _payments[paymentId].status;
    }

    function intentOf(bytes32 paymentId) external view returns (bytes32 intentHash) {
        return _payments[paymentId].intentHash;
    }

    function paymentOf(bytes32 paymentId) external view returns (Payment memory) {
        return _payments[paymentId];
    }

    /// @notice The intent hash this registry would store for `i` (its EIP-712 digest).
    function digestOf(PaymentIntent calldata i) external view returns (bytes32) {
        return _hashTypedDataV4(hashIntent(i));
    }

    function domainSeparator() external view returns (bytes32) {
        return _domainSeparatorV4();
    }

    // Every field of the three structs is a static 32-byte word, so abi.encode(typehash, struct)
    // is exactly the EIP-712 encodeData of the struct.

    function hashIntent(PaymentIntent calldata i) public pure returns (bytes32) {
        return keccak256(abi.encode(PAYMENT_INTENT_TYPEHASH, i));
    }

    function hashVerification(VerificationAttestation calldata v) public pure returns (bytes32) {
        return keccak256(abi.encode(VERIFICATION_ATTESTATION_TYPEHASH, v));
    }

    function hashRevocation(Revocation calldata r) public pure returns (bytes32) {
        return keccak256(abi.encode(REVOCATION_TYPEHASH, r));
    }

    function _signer(bytes32 digest, bytes calldata sig, bytes32 role) private view returns (address signer) {
        if (sig.length == 65) {
            (address recovered, ECDSA.RecoverError err,) = ECDSA.tryRecoverCalldata(digest, sig);
            if (err == ECDSA.RecoverError.NoError) signer = recovered;
        } else if (sig.length > 20) {
            address claimed = address(bytes20(sig[:20]));
            if (SignatureChecker.isValidERC1271SignatureNowCalldata(claimed, digest, sig[20:])) signer = claimed;
        }
        if (signer == address(0) || !hasRole(role, signer)) revert UnauthorizedSigner();
    }

    function _useNonce(address signer, uint256 nonce) private {
        if (nonceUsed[signer][nonce]) revert NonceUsed();
        nonceUsed[signer][nonce] = true;
    }
}
