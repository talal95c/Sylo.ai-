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
/// @notice Records the EIP-712 attestations of every payment and its status, whatever the rail.
///
/// Status machine (any other transition reverts with `InvalidTransition`):
///   NONE -> COMMITTED                          `commit`             (router signature)
///   COMMITTED -> CONFIRMED | DENIED            `recordVerification` (verifier signature)
///   COMMITTED | CONFIRMED | DENIED -> REVOKED  `revoke`             (analyst signature), final
///   CONFIRMED -> EXECUTED                      `markExecuted`       (EXECUTOR_ROLE), final
///   COMMITTED -> EXECUTED (tier LOW only)      `markExecuted`       (EXECUTOR_ROLE), final
///
/// Anyone may relay a signed message: authority comes from the signature, not from `msg.sender`.
///
/// Signature formats accepted by `commit`, `recordVerification` and `revoke`:
///   - 65 bytes `r ‖ s ‖ v` (v = 27 or 28, low s): ECDSA signature of a plain key. This is the path of the PoC.
///   - any other length: `abi.encodePacked(address wallet, bytes walletSignature)` for a contract signer such as a
///     multisig; `walletSignature` is checked with ERC-1271 through OpenZeppelin's `SignatureChecker`.
///     (A wallet signature of exactly 45 bytes cannot be used: the packed form would be 65 bytes long.)
/// Whatever is wrong with a signature (malformed, wrong key, wrong domain, signer without the role), the call
/// reverts with `UnauthorizedSigner`.
///
/// About the `forge-lint: disable-next-line(reentrancy-events)` comments: the linter reports the three events of
/// the signed functions as "emitted after an external call". What runs before them is hashing and ECDSA recovery
/// (pure OpenZeppelin library code) and, for a contract signer only, a STATICCALL to a wallet that an admin
/// registered. None of it can change state or emit a log, so no reentrancy can reorder these events.
contract PaymentRegistry is EIP712, AccessControl {
    /// @notice What the registry keeps for one payment.
    struct Payment {
        bytes32 intentHash; // EIP-712 digest of the committed PaymentIntent (zero while status is NONE)
        bytes32 corridorId;
        address beneficiary;
        Status status;
        uint8 tier; // Tier number as signed in the intent
        address token;
        uint256 amount;
    }

    /// @notice Keys allowed to sign a `PaymentIntent`.
    bytes32 public constant ROUTER_SIGNER_ROLE = keccak256("ROUTER_SIGNER_ROLE");
    /// @notice Keys allowed to sign a `VerificationAttestation`.
    bytes32 public constant VERIFIER_SIGNER_ROLE = keccak256("VERIFIER_SIGNER_ROLE");
    /// @notice Keys allowed to sign a `Revocation`.
    bytes32 public constant ANALYST_SIGNER_ROLE = keccak256("ANALYST_SIGNER_ROLE");
    /// @notice Callers allowed to mark a payment executed (the escrow contract and the relayer).
    bytes32 public constant EXECUTOR_ROLE = keccak256("EXECUTOR_ROLE");

    /// @notice True once `signer` has used `nonce`. One nonce space per signer, shared by the three message types.
    mapping(address signer => mapping(uint256 nonce => bool used)) public nonceUsed;

    mapping(bytes32 paymentId => Payment) private _payments;

    event PaymentCommitted(bytes32 indexed paymentId, bytes32 indexed corridorId, bytes32 intentHash, address signer);
    event VerificationRecorded(bytes32 indexed paymentId, uint8 result, bytes32 evidenceHash, address signer);
    event PaymentRevoked(bytes32 indexed paymentId, uint8 reasonCode, address signer);
    event PaymentExecuted(bytes32 indexed paymentId, bytes32 executionRef);

    /// @notice The payment is not in a status that allows this action.
    error InvalidTransition();
    /// @notice `block.timestamp` is after the intent's `validUntil`.
    error IntentExpired();
    /// @notice The signature is not a valid signature of a holder of the required role.
    error UnauthorizedSigner();
    /// @notice This signer already used this nonce.
    error NonceUsed();
    /// @notice The attestation does not reference the committed intent digest.
    error CommitmentMismatch();

    /// @param admin Receives `DEFAULT_ADMIN_ROLE`: it grants and revokes the four roles.
    constructor(address admin) EIP712("SyloPaymentRegistry", "1") {
        _grantRole(DEFAULT_ADMIN_ROLE, admin);
    }

    // -----------------------------------------------------------------------------------------
    // State changes
    // -----------------------------------------------------------------------------------------

    /// @notice Seals a signed payment intent before any money moves: NONE -> COMMITTED.
    /// @dev Checks, in order: status NONE, not expired, router signature, nonce unused.
    function commit(PaymentIntent calldata i, bytes calldata routerSig) external {
        Payment storage p = _payments[i.paymentId];
        if (p.status != Status.NONE) revert InvalidTransition();
        // An intent is valid for minutes: the few seconds a validator can shift a timestamp do not matter.
        // forge-lint: disable-next-line(block-timestamp)
        if (block.timestamp > i.validUntil) revert IntentExpired();

        bytes32 digest = digestOf(i);
        address signer = _consumeSignature(ROUTER_SIGNER_ROLE, digest, i.nonce, routerSig);

        p.intentHash = digest;
        p.corridorId = i.corridorId;
        p.beneficiary = i.beneficiary;
        p.status = Status.COMMITTED;
        p.tier = i.tier;
        p.token = i.token;
        p.amount = i.amount;

        // forge-lint: disable-next-line(reentrancy-events)
        emit PaymentCommitted(i.paymentId, i.corridorId, digest, signer);
    }

    /// @notice Records the supplier's answer: COMMITTED -> CONFIRMED (result 1) or DENIED (result 2).
    /// @dev Checks, in order: status COMMITTED, `intentHash` equals the committed digest, verifier signature,
    /// nonce unused, result is 1 or 2 (any other result reverts with `InvalidTransition`).
    function recordVerification(VerificationAttestation calldata v, bytes calldata verifierSig) external {
        Payment storage p = _payments[v.paymentId];
        if (p.status != Status.COMMITTED) revert InvalidTransition();
        if (v.intentHash != p.intentHash) revert CommitmentMismatch();

        address signer =
            _consumeSignature(VERIFIER_SIGNER_ROLE, _hashTypedDataV4(hashVerification(v)), v.nonce, verifierSig);

        if (v.result == uint8(VerificationResult.CONFIRMED)) {
            p.status = Status.CONFIRMED;
        } else if (v.result == uint8(VerificationResult.DENIED)) {
            p.status = Status.DENIED;
        } else {
            revert InvalidTransition();
        }

        // forge-lint: disable-next-line(reentrancy-events)
        emit VerificationRecorded(v.paymentId, v.result, v.evidenceHash, signer);
    }

    /// @notice Stops a payment for good: COMMITTED | CONFIRMED | DENIED -> REVOKED.
    /// @dev Checks, in order: status, analyst signature, nonce unused.
    function revoke(Revocation calldata r, bytes calldata revokerSig) external {
        Payment storage p = _payments[r.paymentId];
        Status status = p.status;
        if (status != Status.COMMITTED && status != Status.CONFIRMED && status != Status.DENIED) {
            revert InvalidTransition();
        }

        address signer =
            _consumeSignature(ANALYST_SIGNER_ROLE, _hashTypedDataV4(hashRevocation(r)), r.nonce, revokerSig);

        p.status = Status.REVOKED;

        // forge-lint: disable-next-line(reentrancy-events)
        emit PaymentRevoked(r.paymentId, r.reasonCode, signer);
    }

    /// @notice Marks a payment executed: CONFIRMED -> EXECUTED, or COMMITTED -> EXECUTED for a LOW intent.
    /// @param executionRef Reference of the execution (rail settlement reference, or the escrow's release tag).
    function markExecuted(bytes32 paymentId, bytes32 executionRef) external onlyRole(EXECUTOR_ROLE) {
        Payment storage p = _payments[paymentId];
        Status status = p.status;
        bool allowed = status == Status.CONFIRMED || (status == Status.COMMITTED && p.tier == uint8(Tier.LOW));
        if (!allowed) revert InvalidTransition();

        p.status = Status.EXECUTED;

        emit PaymentExecuted(paymentId, executionRef);
    }

    // -----------------------------------------------------------------------------------------
    // Views
    // -----------------------------------------------------------------------------------------

    /// @notice Status of a payment (`NONE` if it was never committed).
    function statusOf(bytes32 paymentId) external view returns (Status) {
        return _payments[paymentId].status;
    }

    /// @notice The committed intent hash: the EIP-712 digest of the PaymentIntent (zero if never committed).
    function intentOf(bytes32 paymentId) external view returns (bytes32 intentHash) {
        return _payments[paymentId].intentHash;
    }

    /// @notice Everything the registry keeps for a payment.
    function paymentOf(bytes32 paymentId) external view returns (Payment memory) {
        return _payments[paymentId];
    }

    /// @notice EIP-712 digest of an intent under this registry's domain: keccak256(0x1901 ‖ domainSeparator ‖ structHash).
    function digestOf(PaymentIntent calldata i) public view returns (bytes32) {
        return _hashTypedDataV4(hashIntent(i));
    }

    /// @notice EIP-712 struct hash of a PaymentIntent.
    function hashIntent(PaymentIntent calldata i) public pure returns (bytes32) {
        return keccak256(
            abi.encode(
                PAYMENT_INTENT_TYPEHASH,
                i.paymentId,
                i.corridorId,
                i.beneficiary,
                i.token,
                i.amount,
                i.offchainHash,
                i.decisionHash,
                i.approvalHash,
                i.tier,
                i.validUntil,
                i.nonce
            )
        );
    }

    /// @notice EIP-712 struct hash of a VerificationAttestation.
    function hashVerification(VerificationAttestation calldata v) public pure returns (bytes32) {
        return keccak256(
            abi.encode(
                VERIFICATION_ATTESTATION_TYPEHASH,
                v.paymentId,
                v.intentHash,
                v.method,
                v.result,
                v.simSwapChecked,
                v.evidenceHash,
                v.verifiedAt,
                v.nonce
            )
        );
    }

    /// @notice EIP-712 struct hash of a Revocation.
    function hashRevocation(Revocation calldata r) public pure returns (bytes32) {
        return keccak256(abi.encode(REVOCATION_TYPEHASH, r.paymentId, r.reasonCode, r.caseHash, r.nonce));
    }

    /// @notice EIP-712 domain separator of this registry on this chain.
    function domainSeparator() external view returns (bytes32) {
        return _domainSeparatorV4();
    }

    // -----------------------------------------------------------------------------------------
    // Internals
    // -----------------------------------------------------------------------------------------

    /// @dev Requires `signature` over `digest` to come from a holder of `role`, then uses up `nonce` for that signer.
    function _consumeSignature(bytes32 role, bytes32 digest, uint256 nonce, bytes calldata signature)
        private
        returns (address signer)
    {
        signer = _signerOf(role, digest, signature);
        if (signer == address(0) || !hasRole(role, signer)) revert UnauthorizedSigner();
        if (nonceUsed[signer][nonce]) revert NonceUsed();
        nonceUsed[signer][nonce] = true;
    }

    /// @dev Returns who signed `digest`, or the zero address when `signature` is not valid. Never reverts.
    /// Nothing here can change state: ECDSA recovery is pure, and a wallet is asked with a STATICCALL.
    function _signerOf(bytes32 role, bytes32 digest, bytes calldata signature) private view returns (address) {
        if (signature.length == 65) {
            // Plain key. OpenZeppelin rejects malleable signatures: s must be in the lower half, v must be 27 or 28.
            (address recovered, ECDSA.RecoverError err,) = ECDSA.tryRecoverCalldata(digest, signature);
            return err == ECDSA.RecoverError.NoError ? recovered : address(0);
        }
        if (signature.length > 20) {
            // Contract signer: 20 bytes of wallet address, then the signature the wallet validates (ERC-1271).
            // The role is checked first, so the registry only ever calls wallets that an admin registered.
            address wallet = address(bytes20(signature[:20]));
            if (
                hasRole(role, wallet)
                    && SignatureChecker.isValidERC1271SignatureNowCalldata(wallet, digest, signature[20:])
            ) {
                return wallet;
            }
        }
        return address(0);
    }
}
