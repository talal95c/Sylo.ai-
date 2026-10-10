// SPDX-License-Identifier: MIT
pragma solidity ^0.8.28;

import {Test} from "forge-std/Test.sol";

import {IAccessControl} from "@openzeppelin/contracts/access/IAccessControl.sol";
import {IERC1271} from "@openzeppelin/contracts/interfaces/IERC1271.sol";
import {ECDSA} from "@openzeppelin/contracts/utils/cryptography/ECDSA.sol";
import {MessageHashUtils} from "@openzeppelin/contracts/utils/cryptography/MessageHashUtils.sol";

import {PaymentRegistry} from "../src/PaymentRegistry.sol";
import {
    PAYMENT_INTENT_TYPEHASH,
    REVOCATION_TYPEHASH,
    VERIFICATION_ATTESTATION_TYPEHASH,
    PaymentIntent,
    Revocation,
    RevocationReason,
    Status,
    Tier,
    VerificationAttestation,
    VerificationMethod,
    VerificationResult
} from "../src/SyloTypes.sol";

/// @dev Shared fixture (also used by PaymentEscrow.t.sol): a registry whose three signer roles are held by
/// `vm.addr` keys, and helpers that build and sign valid messages.
///
/// `_deployRegistry` builds the default setup with throwaway keys. A test can instead point `registry`, the
/// addresses and `routerPk` / `verifierPk` / `analystPk` at another deployment and reuse every helper.
///
/// Rule followed in every test: build the message and its signature BEFORE `vm.expectRevert`, `vm.expectEmit`
/// or `vm.prank`, because these cheatcodes apply to the next call and the helpers call the registry.
abstract contract SyloFixture is Test {
    // Throwaway test keys. `vm.addr(key)` is the signer's address.
    uint256 internal constant ROUTER_PK = 0xA11CE;
    uint256 internal constant VERIFIER_PK = 0xB0B;
    uint256 internal constant ANALYST_PK = 0xCA11ED;
    uint256 internal constant OUTSIDER_PK = 0xBAD;

    uint256 internal constant START = 1_791_709_200; // 2026-10-11T09:00:00Z
    uint64 internal constant VALIDITY = 600;
    bytes32 internal constant CORRIDOR = keccak256("FR-GH");
    uint256 internal constant AMOUNT = 85_000e6; // EUR 85,000 with 6 decimals
    bytes32 internal constant EXECUTION_REF = keccak256("rail-settlement-reference");

    PaymentRegistry internal registry;

    // The keys that hold the three signer roles on `registry`: used by `_commit`, `_verify` and `_revoke`.
    uint256 internal routerPk = ROUTER_PK;
    uint256 internal verifierPk = VERIFIER_PK;
    uint256 internal analystPk = ANALYST_PK;

    address internal admin;
    address internal relayer; // holds EXECUTOR_ROLE on the registry, as in the deployment
    address internal routerSigner;
    address internal verifierSigner;
    address internal analystSigner;
    address internal outsider; // holds no role
    address internal beneficiary;
    address internal token; // the escrow tests replace it with a real token

    uint256 private _counter;

    function _deployRegistry() internal {
        vm.warp(START);

        admin = makeAddr("admin");
        relayer = makeAddr("relayer");
        beneficiary = makeAddr("beneficiary");
        token = makeAddr("token");
        routerSigner = vm.addr(ROUTER_PK);
        verifierSigner = vm.addr(VERIFIER_PK);
        analystSigner = vm.addr(ANALYST_PK);
        outsider = vm.addr(OUTSIDER_PK);

        registry = new PaymentRegistry(admin);

        vm.startPrank(admin);
        registry.grantRole(registry.ROUTER_SIGNER_ROLE(), routerSigner);
        registry.grantRole(registry.VERIFIER_SIGNER_ROLE(), verifierSigner);
        registry.grantRole(registry.ANALYST_SIGNER_ROLE(), analystSigner);
        registry.grantRole(registry.EXECUTOR_ROLE(), relayer);
        vm.stopPrank();
    }

    // ------------------------------------------------------------------ builders

    /// @dev A number never used before in this test: unique nonces and payment references.
    function _fresh() internal returns (uint256) {
        return ++_counter;
    }

    /// @dev The current block time. Read through the cheatcode so that it is always the value set by `vm.warp`.
    function _now() internal view returns (uint64) {
        return uint64(vm.getBlockTimestamp());
    }

    function _freshRef() internal returns (string memory) {
        return string.concat("PAY-TEST-", vm.toString(_fresh()));
    }

    /// @dev A valid intent: unique payment, unique nonce, valid for 10 minutes.
    function _intent(string memory ref, Tier tier) internal returns (PaymentIntent memory) {
        return PaymentIntent({
            paymentId: keccak256(bytes(ref)),
            corridorId: CORRIDOR,
            beneficiary: beneficiary,
            token: token,
            amount: AMOUNT,
            offchainHash: keccak256(abi.encode("offchain", ref)),
            decisionHash: keccak256(abi.encode("decision", ref)),
            approvalHash: keccak256(abi.encode("approval", ref)),
            tier: uint8(tier),
            validUntil: _now() + VALIDITY,
            nonce: _fresh()
        });
    }

    /// @dev A valid attestation that references the digest of `i`.
    function _attestation(PaymentIntent memory i, VerificationResult result)
        internal
        returns (VerificationAttestation memory)
    {
        return VerificationAttestation({
            paymentId: i.paymentId,
            intentHash: registry.digestOf(i),
            method: uint8(VerificationMethod.OOB_KNOWN_CONTACT),
            result: uint8(result),
            simSwapChecked: true,
            evidenceHash: keccak256(abi.encode("evidence", i.paymentId, result)),
            verifiedAt: _now(),
            nonce: _fresh()
        });
    }

    function _revocation(PaymentIntent memory i) internal returns (Revocation memory) {
        return Revocation({
            paymentId: i.paymentId,
            reasonCode: uint8(RevocationReason.SUPPLIER_DENIED),
            caseHash: keccak256(abi.encode("case", i.paymentId)),
            nonce: _fresh()
        });
    }

    // ------------------------------------------------------------------ signing

    /// @dev 65-byte signature r ‖ s ‖ v, as OpenZeppelin's ECDSA expects.
    function _sign(uint256 privateKey, bytes32 digest) internal pure returns (bytes memory) {
        (uint8 v, bytes32 r, bytes32 s) = vm.sign(privateKey, digest);
        return abi.encodePacked(r, s, v);
    }

    function _digest(VerificationAttestation memory v) internal view returns (bytes32) {
        return MessageHashUtils.toTypedDataHash(registry.domainSeparator(), registry.hashVerification(v));
    }

    function _digest(Revocation memory r) internal view returns (bytes32) {
        return MessageHashUtils.toTypedDataHash(registry.domainSeparator(), registry.hashRevocation(r));
    }

    function _signIntent(uint256 privateKey, PaymentIntent memory i) internal view returns (bytes memory) {
        return _sign(privateKey, registry.digestOf(i));
    }

    function _signAttestation(uint256 privateKey, VerificationAttestation memory v)
        internal
        view
        returns (bytes memory)
    {
        return _sign(privateKey, _digest(v));
    }

    function _signRevocation(uint256 privateKey, Revocation memory r) internal view returns (bytes memory) {
        return _sign(privateKey, _digest(r));
    }

    // ------------------------------------------------------------------ valid actions

    function _commit(PaymentIntent memory i) internal {
        registry.commit(i, _signIntent(routerPk, i));
    }

    function _committed(Tier tier) internal returns (PaymentIntent memory i) {
        i = _intent(_freshRef(), tier);
        _commit(i);
    }

    function _verify(PaymentIntent memory i, VerificationResult result) internal {
        VerificationAttestation memory v = _attestation(i, result);
        registry.recordVerification(v, _signAttestation(verifierPk, v));
    }

    function _revoke(PaymentIntent memory i) internal {
        Revocation memory r = _revocation(i);
        registry.revoke(r, _signRevocation(analystPk, r));
    }

    /// @dev Brings a fresh MEDIUM payment to `target` through valid transitions and returns its intent.
    function _reach(Status target) internal returns (PaymentIntent memory i) {
        i = _intent(_freshRef(), Tier.MEDIUM);
        if (target == Status.NONE) return i;
        _commit(i);
        if (target == Status.CONFIRMED || target == Status.EXECUTED) _verify(i, VerificationResult.CONFIRMED);
        if (target == Status.DENIED) _verify(i, VerificationResult.DENIED);
        if (target == Status.REVOKED) _revoke(i);
        if (target == Status.EXECUTED) {
            vm.prank(relayer);
            registry.markExecuted(i.paymentId, EXECUTION_REF);
        }
        _assertStatus(i.paymentId, target);
    }

    function _assertStatus(bytes32 paymentId, Status expected) internal view {
        assertEq(uint256(registry.statusOf(paymentId)), uint256(expected), "registry status");
    }
}

/// @dev Minimal ERC-1271 wallet: a signature is valid when its owner key made it. Stands in for a multisig.
contract OwnedWalletMock is IERC1271 {
    address public immutable owner;

    constructor(address owner_) {
        owner = owner_;
    }

    function isValidSignature(bytes32 hash, bytes calldata signature) external view returns (bytes4) {
        (address recovered, ECDSA.RecoverError err,) = ECDSA.tryRecoverCalldata(hash, signature);
        if (err == ECDSA.RecoverError.NoError && recovered == owner) return IERC1271.isValidSignature.selector;
        return 0xffffffff;
    }
}

contract PaymentRegistryTest is SyloFixture {
    uint256 internal constant SECP256K1_N = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141;

    function setUp() public {
        _deployRegistry();
    }

    // =================================================================== deployment and views

    function test_Constructor_AdminAndDomain() public view {
        assertTrue(registry.hasRole(registry.DEFAULT_ADMIN_ROLE(), admin));
        assertFalse(registry.hasRole(registry.DEFAULT_ADMIN_ROLE(), address(this)));

        (, string memory name, string memory version, uint256 chainId, address verifyingContract,,) =
            registry.eip712Domain();
        assertEq(name, "SyloPaymentRegistry");
        assertEq(version, "1");
        assertEq(chainId, vm.getChainId());
        assertEq(verifyingContract, address(registry));
    }

    function test_UnknownPayment_IsNoneWithZeroIntentHash() public view {
        bytes32 paymentId = keccak256("never committed");
        _assertStatus(paymentId, Status.NONE);
        assertEq(registry.intentOf(paymentId), bytes32(0));
        assertEq(registry.paymentOf(paymentId).amount, 0);
    }

    function test_DigestOf_IsTheEip712Digest() public {
        PaymentIntent memory i = _intent("PAY-DIGEST", Tier.MEDIUM);
        bytes32 expected = keccak256(abi.encodePacked("\x19\x01", registry.domainSeparator(), registry.hashIntent(i)));
        assertEq(registry.digestOf(i), expected);
    }

    function testFuzz_HashIntent_EncodesEveryFieldInOrder(PaymentIntent memory i) public view {
        assertEq(registry.hashIntent(i), keccak256(abi.encode(PAYMENT_INTENT_TYPEHASH, i)));
    }

    function testFuzz_HashVerification_EncodesEveryFieldInOrder(VerificationAttestation memory v) public view {
        assertEq(registry.hashVerification(v), keccak256(abi.encode(VERIFICATION_ATTESTATION_TYPEHASH, v)));
    }

    function testFuzz_HashRevocation_EncodesEveryFieldInOrder(Revocation memory r) public view {
        assertEq(registry.hashRevocation(r), keccak256(abi.encode(REVOCATION_TYPEHASH, r)));
    }

    // =================================================================== allowed transitions

    function test_Commit_NoneToCommitted() public {
        PaymentIntent memory i = _intent("PAY-2026-0001", Tier.MEDIUM);
        bytes32 digest = registry.digestOf(i);
        bytes memory sig = _sign(ROUTER_PK, digest);

        vm.expectEmit(address(registry));
        emit PaymentRegistry.PaymentCommitted(i.paymentId, i.corridorId, digest, routerSigner);
        registry.commit(i, sig);

        _assertStatus(i.paymentId, Status.COMMITTED);
        assertEq(registry.intentOf(i.paymentId), digest, "the registry stores the EIP-712 digest");
        assertTrue(registry.nonceUsed(routerSigner, i.nonce));

        PaymentRegistry.Payment memory p = registry.paymentOf(i.paymentId);
        assertEq(p.intentHash, digest);
        assertEq(p.corridorId, i.corridorId);
        assertEq(p.beneficiary, i.beneficiary);
        assertEq(uint256(p.status), uint256(Status.COMMITTED));
        assertEq(p.tier, i.tier);
        assertEq(p.token, i.token);
        assertEq(p.amount, i.amount);
    }

    function test_Commit_AnyoneCanRelayASignedIntent() public {
        PaymentIntent memory i = _intent("PAY-RELAYED", Tier.LOW);
        bytes memory sig = _signIntent(ROUTER_PK, i);

        vm.prank(outsider);
        registry.commit(i, sig);

        _assertStatus(i.paymentId, Status.COMMITTED);
    }

    function test_Commit_AcceptsEveryTier() public {
        for (uint8 tier = 0; tier <= uint8(Tier.CRITICAL); ++tier) {
            PaymentIntent memory i = _intent(_freshRef(), Tier(tier));
            _commit(i);
            _assertStatus(i.paymentId, Status.COMMITTED);
            assertEq(registry.paymentOf(i.paymentId).tier, tier);
        }
    }

    function test_RecordVerification_CommittedToConfirmed() public {
        PaymentIntent memory i = _committed(Tier.MEDIUM);
        VerificationAttestation memory v = _attestation(i, VerificationResult.CONFIRMED);
        bytes memory sig = _signAttestation(VERIFIER_PK, v);

        vm.expectEmit(address(registry));
        emit PaymentRegistry.VerificationRecorded(i.paymentId, 1, v.evidenceHash, verifierSigner);
        registry.recordVerification(v, sig);

        _assertStatus(i.paymentId, Status.CONFIRMED);
        assertTrue(registry.nonceUsed(verifierSigner, v.nonce));
    }

    function test_RecordVerification_CommittedToDenied() public {
        PaymentIntent memory i = _committed(Tier.MEDIUM);
        VerificationAttestation memory v = _attestation(i, VerificationResult.DENIED);
        bytes memory sig = _signAttestation(VERIFIER_PK, v);

        vm.expectEmit(address(registry));
        emit PaymentRegistry.VerificationRecorded(i.paymentId, 2, v.evidenceHash, verifierSigner);
        registry.recordVerification(v, sig);

        _assertStatus(i.paymentId, Status.DENIED);
    }

    function test_Revoke_FromCommittedConfirmedAndDenied() public {
        Status[3] memory from = [Status.COMMITTED, Status.CONFIRMED, Status.DENIED];
        for (uint256 k = 0; k < from.length; ++k) {
            PaymentIntent memory i = _reach(from[k]);
            Revocation memory r = _revocation(i);
            bytes memory sig = _signRevocation(ANALYST_PK, r);

            vm.expectEmit(address(registry));
            emit PaymentRegistry.PaymentRevoked(i.paymentId, r.reasonCode, analystSigner);
            registry.revoke(r, sig);

            _assertStatus(i.paymentId, Status.REVOKED);
            assertTrue(registry.nonceUsed(analystSigner, r.nonce));
        }
    }

    function test_MarkExecuted_CommittedLowToExecuted() public {
        PaymentIntent memory i = _committed(Tier.LOW);

        vm.expectEmit(address(registry));
        emit PaymentRegistry.PaymentExecuted(i.paymentId, EXECUTION_REF);
        vm.prank(relayer);
        registry.markExecuted(i.paymentId, EXECUTION_REF);

        _assertStatus(i.paymentId, Status.EXECUTED);
    }

    function test_MarkExecuted_ConfirmedToExecuted() public {
        PaymentIntent memory i = _reach(Status.CONFIRMED);

        vm.expectEmit(address(registry));
        emit PaymentRegistry.PaymentExecuted(i.paymentId, EXECUTION_REF);
        vm.prank(relayer);
        registry.markExecuted(i.paymentId, EXECUTION_REF);

        _assertStatus(i.paymentId, Status.EXECUTED);
    }

    function test_VerificationAndRevocation_AreNotBoundByValidUntil() public {
        // `validUntil` limits when an intent can be committed, not what happens to it afterwards.
        PaymentIntent memory confirmed = _committed(Tier.MEDIUM);
        PaymentIntent memory revoked = _committed(Tier.MEDIUM);
        skip(VALIDITY + 1 days);

        _verify(confirmed, VerificationResult.CONFIRMED);
        _revoke(revoked);

        _assertStatus(confirmed.paymentId, Status.CONFIRMED);
        _assertStatus(revoked.paymentId, Status.REVOKED);
    }

    // =================================================================== forbidden transitions

    function test_RevertWhen_SameIntentIsCommittedTwice() public {
        PaymentIntent memory i = _intent("PAY-TWICE", Tier.MEDIUM);
        bytes memory sig = _signIntent(ROUTER_PK, i);
        registry.commit(i, sig);

        // The status is checked before the nonce, so the error is InvalidTransition and not NonceUsed.
        vm.expectRevert(PaymentRegistry.InvalidTransition.selector);
        registry.commit(i, sig);
    }

    function test_RevertWhen_CommitFromAnyStatusButNone() public {
        Status[5] memory from = [Status.COMMITTED, Status.CONFIRMED, Status.DENIED, Status.REVOKED, Status.EXECUTED];
        for (uint256 k = 0; k < from.length; ++k) {
            PaymentIntent memory i = _reach(from[k]);
            // Same payment, new nonce, valid signature: only the status is wrong.
            i.nonce = _fresh();
            bytes memory sig = _signIntent(ROUTER_PK, i);

            vm.expectRevert(PaymentRegistry.InvalidTransition.selector);
            registry.commit(i, sig);

            _assertStatus(i.paymentId, from[k]);
        }
    }

    function test_RevertWhen_VerificationFromAnyStatusButCommitted() public {
        Status[5] memory from = [Status.NONE, Status.CONFIRMED, Status.DENIED, Status.REVOKED, Status.EXECUTED];
        for (uint256 k = 0; k < from.length; ++k) {
            PaymentIntent memory i = _reach(from[k]);
            VerificationAttestation memory v = _attestation(i, VerificationResult.CONFIRMED);
            bytes memory sig = _signAttestation(VERIFIER_PK, v);

            vm.expectRevert(PaymentRegistry.InvalidTransition.selector);
            registry.recordVerification(v, sig);

            _assertStatus(i.paymentId, from[k]);
        }
    }

    function test_RevertWhen_RevokeFromNoneRevokedOrExecuted() public {
        Status[3] memory from = [Status.NONE, Status.REVOKED, Status.EXECUTED];
        for (uint256 k = 0; k < from.length; ++k) {
            PaymentIntent memory i = _reach(from[k]);
            Revocation memory r = _revocation(i);
            bytes memory sig = _signRevocation(ANALYST_PK, r);

            vm.expectRevert(PaymentRegistry.InvalidTransition.selector);
            registry.revoke(r, sig);

            _assertStatus(i.paymentId, from[k]);
        }
    }

    function test_RevertWhen_MarkExecutedFromAStatusThatDoesNotAllowIt() public {
        // COMMITTED here is a MEDIUM intent: it must be CONFIRMED first.
        Status[5] memory from = [Status.NONE, Status.COMMITTED, Status.DENIED, Status.REVOKED, Status.EXECUTED];
        for (uint256 k = 0; k < from.length; ++k) {
            PaymentIntent memory i = _reach(from[k]);

            vm.expectRevert(PaymentRegistry.InvalidTransition.selector);
            vm.prank(relayer);
            registry.markExecuted(i.paymentId, EXECUTION_REF);

            _assertStatus(i.paymentId, from[k]);
        }
    }

    function test_RevertWhen_MarkExecutedOnCommittedHighOrCritical() public {
        Tier[2] memory tiers = [Tier.HIGH, Tier.CRITICAL];
        for (uint256 k = 0; k < tiers.length; ++k) {
            PaymentIntent memory i = _committed(tiers[k]);

            vm.expectRevert(PaymentRegistry.InvalidTransition.selector);
            vm.prank(relayer);
            registry.markExecuted(i.paymentId, EXECUTION_REF);

            _assertStatus(i.paymentId, Status.COMMITTED);
        }
    }

    function test_RevertWhen_MarkExecutedByNonExecutor() public {
        PaymentIntent memory i = _committed(Tier.LOW);
        bytes32 executorRole = registry.EXECUTOR_ROLE();

        vm.expectRevert(
            abi.encodeWithSelector(IAccessControl.AccessControlUnauthorizedAccount.selector, outsider, executorRole)
        );
        vm.prank(outsider);
        registry.markExecuted(i.paymentId, EXECUTION_REF);

        // Not even the admin or a signer: only EXECUTOR_ROLE.
        vm.expectRevert(
            abi.encodeWithSelector(IAccessControl.AccessControlUnauthorizedAccount.selector, admin, executorRole)
        );
        vm.prank(admin);
        registry.markExecuted(i.paymentId, EXECUTION_REF);

        _assertStatus(i.paymentId, Status.COMMITTED);
    }

    function test_RevertWhen_VerificationResultIsNotConfirmedOrDenied() public {
        PaymentIntent memory i = _committed(Tier.MEDIUM);
        uint8[3] memory results = [0, 3, 255];
        for (uint256 k = 0; k < results.length; ++k) {
            VerificationAttestation memory v = _attestation(i, VerificationResult.CONFIRMED);
            v.result = results[k];
            bytes memory sig = _signAttestation(VERIFIER_PK, v);

            vm.expectRevert(PaymentRegistry.InvalidTransition.selector);
            registry.recordVerification(v, sig);

            assertFalse(registry.nonceUsed(verifierSigner, v.nonce), "a reverted call uses no nonce");
        }
        _assertStatus(i.paymentId, Status.COMMITTED);
    }

    function test_RevertWhen_VerificationReferencesAnotherIntent() public {
        PaymentIntent memory i = _committed(Tier.MEDIUM);
        PaymentIntent memory other = _committed(Tier.MEDIUM);

        VerificationAttestation memory v = _attestation(i, VerificationResult.CONFIRMED);
        v.intentHash = registry.digestOf(other);
        bytes memory sig = _signAttestation(VERIFIER_PK, v);

        vm.expectRevert(PaymentRegistry.CommitmentMismatch.selector);
        registry.recordVerification(v, sig);

        // The struct hash is not the intent hash either: only the full EIP-712 digest is accepted.
        v.intentHash = registry.hashIntent(i);
        sig = _signAttestation(VERIFIER_PK, v);
        vm.expectRevert(PaymentRegistry.CommitmentMismatch.selector);
        registry.recordVerification(v, sig);

        _assertStatus(i.paymentId, Status.COMMITTED);
    }

    // =================================================================== signers

    function test_RevertWhen_CommitIsNotSignedByARouterSigner() public {
        uint256[3] memory keys = [OUTSIDER_PK, VERIFIER_PK, ANALYST_PK];
        for (uint256 k = 0; k < keys.length; ++k) {
            PaymentIntent memory i = _intent(_freshRef(), Tier.LOW);
            bytes memory sig = _signIntent(keys[k], i);

            vm.expectRevert(PaymentRegistry.UnauthorizedSigner.selector);
            registry.commit(i, sig);

            _assertStatus(i.paymentId, Status.NONE);
            assertFalse(registry.nonceUsed(vm.addr(keys[k]), i.nonce));
        }
    }

    function test_RevertWhen_VerificationIsNotSignedByAVerifierSigner() public {
        PaymentIntent memory i = _committed(Tier.MEDIUM);
        uint256[3] memory keys = [OUTSIDER_PK, ROUTER_PK, ANALYST_PK];
        for (uint256 k = 0; k < keys.length; ++k) {
            VerificationAttestation memory v = _attestation(i, VerificationResult.CONFIRMED);
            bytes memory sig = _signAttestation(keys[k], v);

            vm.expectRevert(PaymentRegistry.UnauthorizedSigner.selector);
            registry.recordVerification(v, sig);
        }
        _assertStatus(i.paymentId, Status.COMMITTED);
    }

    function test_RevertWhen_RevocationIsNotSignedByAnAnalystSigner() public {
        PaymentIntent memory i = _committed(Tier.MEDIUM);
        uint256[3] memory keys = [OUTSIDER_PK, ROUTER_PK, VERIFIER_PK];
        for (uint256 k = 0; k < keys.length; ++k) {
            Revocation memory r = _revocation(i);
            bytes memory sig = _signRevocation(keys[k], r);

            vm.expectRevert(PaymentRegistry.UnauthorizedSigner.selector);
            registry.revoke(r, sig);
        }
        _assertStatus(i.paymentId, Status.COMMITTED);
    }

    function test_RevertWhen_IntentIsChangedAfterSigning() public {
        PaymentIntent memory i = _intent("PAY-TAMPERED", Tier.MEDIUM);
        bytes memory sig = _signIntent(ROUTER_PK, i);

        // The diverted-invoice attack: same signature, another beneficiary.
        i.beneficiary = outsider;
        vm.expectRevert(PaymentRegistry.UnauthorizedSigner.selector);
        registry.commit(i, sig);

        i.beneficiary = beneficiary;
        i.amount += 1;
        vm.expectRevert(PaymentRegistry.UnauthorizedSigner.selector);
        registry.commit(i, sig);

        // Unchanged, the same signature is accepted.
        i.amount -= 1;
        registry.commit(i, sig);
        _assertStatus(i.paymentId, Status.COMMITTED);
    }

    function test_RevertWhen_SignatureIsMalformed() public {
        PaymentIntent memory i = _intent("PAY-MALFORMED", Tier.LOW);
        (uint8 v, bytes32 r, bytes32 s) = vm.sign(ROUTER_PK, registry.digestOf(i));
        uint8 flippedV = v == 27 ? 28 : 27;

        _expectCommitUnauthorized(i, ""); // empty
        _expectCommitUnauthorized(i, abi.encodePacked(r, s)); // 64 bytes
        _expectCommitUnauthorized(i, abi.encodePacked(r, s, v, uint8(0))); // 66 bytes
        _expectCommitUnauthorized(i, abi.encodePacked(r, s, v - 27)); // v = 0 or 1 instead of 27 or 28
        _expectCommitUnauthorized(i, abi.encodePacked(r, s, flippedV)); // recovers another address
        // The malleable twin (same signer for ecrecover) is rejected by OpenZeppelin because s is in the upper half.
        _expectCommitUnauthorized(i, abi.encodePacked(r, bytes32(SECP256K1_N - uint256(s)), flippedV));
        _expectCommitUnauthorized(i, abi.encodePacked(bytes32(0), bytes32(0), uint8(27))); // ecrecover returns zero

        registry.commit(i, abi.encodePacked(r, s, v));
        _assertStatus(i.paymentId, Status.COMMITTED);
    }

    function test_RevertWhen_SignatureIsForAnotherRegistry() public {
        PaymentRegistry other = new PaymentRegistry(admin);
        PaymentIntent memory i = _intent("PAY-OTHER-REGISTRY", Tier.LOW);
        bytes memory sig = _sign(ROUTER_PK, other.digestOf(i));

        vm.expectRevert(PaymentRegistry.UnauthorizedSigner.selector);
        registry.commit(i, sig);
    }

    function test_RevertWhen_SignatureIsForAnotherChain() public {
        PaymentIntent memory i = _intent("PAY-OTHER-CHAIN", Tier.LOW);
        bytes memory sig = _signIntent(ROUTER_PK, i);

        vm.chainId(vm.getChainId() + 1);

        vm.expectRevert(PaymentRegistry.UnauthorizedSigner.selector);
        registry.commit(i, sig);
    }

    function test_RevertWhen_SignerLostItsRole() public {
        PaymentIntent memory i = _intent("PAY-ROLE-REVOKED", Tier.LOW);
        bytes memory sig = _signIntent(ROUTER_PK, i);
        bytes32 routerRole = registry.ROUTER_SIGNER_ROLE();

        vm.prank(admin);
        registry.revokeRole(routerRole, routerSigner);

        vm.expectRevert(PaymentRegistry.UnauthorizedSigner.selector);
        registry.commit(i, sig);
    }

    // =================================================================== contract signers (ERC-1271)

    function test_ContractSigner_CanSignWithTheWalletPrefixedForm() public {
        OwnedWalletMock wallet = _routerWallet();
        PaymentIntent memory i = _intent("PAY-MULTISIG", Tier.MEDIUM);
        bytes32 digest = registry.digestOf(i);
        bytes memory sig = abi.encodePacked(address(wallet), _sign(OUTSIDER_PK, digest));

        vm.expectEmit(address(registry));
        emit PaymentRegistry.PaymentCommitted(i.paymentId, i.corridorId, digest, address(wallet));
        registry.commit(i, sig);

        _assertStatus(i.paymentId, Status.COMMITTED);
        assertTrue(registry.nonceUsed(address(wallet), i.nonce), "the nonce belongs to the wallet");
    }

    function test_RevertWhen_ContractSignerRejectsTheSignature() public {
        OwnedWalletMock wallet = _routerWallet();
        PaymentIntent memory i = _intent("PAY-MULTISIG-BAD", Tier.MEDIUM);
        // Signed by a key that is not the wallet's owner.
        bytes memory sig = abi.encodePacked(address(wallet), _signIntent(VERIFIER_PK, i));

        vm.expectRevert(PaymentRegistry.UnauthorizedSigner.selector);
        registry.commit(i, sig);
    }

    function test_RevertWhen_ContractSignerHasNoRole() public {
        OwnedWalletMock wallet = new OwnedWalletMock(outsider); // valid wallet, never granted the role
        PaymentIntent memory i = _intent("PAY-MULTISIG-NO-ROLE", Tier.MEDIUM);
        bytes memory sig = abi.encodePacked(address(wallet), _signIntent(OUTSIDER_PK, i));

        vm.expectRevert(PaymentRegistry.UnauthorizedSigner.selector);
        registry.commit(i, sig);
    }

    function test_RevertWhen_WalletPrefixedFormIsUsedForAPlainKey() public {
        PaymentIntent memory i = _intent("PAY-PREFIXED-EOA", Tier.MEDIUM);
        bytes memory plain = _signIntent(ROUTER_PK, i);

        // A plain key has exactly one accepted form: the 65-byte signature.
        vm.expectRevert(PaymentRegistry.UnauthorizedSigner.selector);
        registry.commit(i, abi.encodePacked(routerSigner, plain));

        registry.commit(i, plain);
        _assertStatus(i.paymentId, Status.COMMITTED);
    }

    // =================================================================== nonces

    function test_RevertWhen_RouterNonceIsReused() public {
        PaymentIntent memory first = _committed(Tier.LOW);
        PaymentIntent memory second = _intent("PAY-SAME-NONCE", Tier.LOW);
        second.nonce = first.nonce;
        bytes memory sig = _signIntent(ROUTER_PK, second);

        vm.expectRevert(PaymentRegistry.NonceUsed.selector);
        registry.commit(second, sig);

        _assertStatus(second.paymentId, Status.NONE);
    }

    function test_RevertWhen_VerifierNonceIsReused() public {
        PaymentIntent memory first = _committed(Tier.MEDIUM);
        PaymentIntent memory second = _committed(Tier.MEDIUM);

        VerificationAttestation memory v1 = _attestation(first, VerificationResult.CONFIRMED);
        registry.recordVerification(v1, _signAttestation(VERIFIER_PK, v1));

        VerificationAttestation memory v2 = _attestation(second, VerificationResult.CONFIRMED);
        v2.nonce = v1.nonce;
        bytes memory sig = _signAttestation(VERIFIER_PK, v2);

        vm.expectRevert(PaymentRegistry.NonceUsed.selector);
        registry.recordVerification(v2, sig);

        _assertStatus(second.paymentId, Status.COMMITTED);
    }

    function test_RevertWhen_AnalystNonceIsReused() public {
        PaymentIntent memory first = _committed(Tier.MEDIUM);
        PaymentIntent memory second = _committed(Tier.MEDIUM);

        Revocation memory r1 = _revocation(first);
        registry.revoke(r1, _signRevocation(ANALYST_PK, r1));

        Revocation memory r2 = _revocation(second);
        r2.nonce = r1.nonce;
        bytes memory sig = _signRevocation(ANALYST_PK, r2);

        vm.expectRevert(PaymentRegistry.NonceUsed.selector);
        registry.revoke(r2, sig);

        _assertStatus(second.paymentId, Status.COMMITTED);
    }

    function test_Nonce_SameValueIsFineForDifferentSigners() public {
        uint256 shared = 7_777;

        PaymentIntent memory i = _intent("PAY-SHARED-NONCE", Tier.MEDIUM);
        i.nonce = shared;
        _commit(i);

        VerificationAttestation memory v = _attestation(i, VerificationResult.DENIED);
        v.nonce = shared;
        registry.recordVerification(v, _signAttestation(VERIFIER_PK, v));

        Revocation memory r = _revocation(i);
        r.nonce = shared;
        registry.revoke(r, _signRevocation(ANALYST_PK, r));

        _assertStatus(i.paymentId, Status.REVOKED);
        assertTrue(registry.nonceUsed(routerSigner, shared));
        assertTrue(registry.nonceUsed(verifierSigner, shared));
        assertTrue(registry.nonceUsed(analystSigner, shared));
        assertFalse(registry.nonceUsed(outsider, shared));
    }

    function test_RevertWhen_NonceIsReusedAcrossMessageTypes() public {
        // One key holds two roles: its nonces are shared by the intent and the attestation.
        bytes32 verifierRole = registry.VERIFIER_SIGNER_ROLE();
        vm.prank(admin);
        registry.grantRole(verifierRole, routerSigner);

        PaymentIntent memory i = _committed(Tier.MEDIUM);
        VerificationAttestation memory v = _attestation(i, VerificationResult.CONFIRMED);
        v.nonce = i.nonce;
        bytes memory sig = _signAttestation(ROUTER_PK, v);

        vm.expectRevert(PaymentRegistry.NonceUsed.selector);
        registry.recordVerification(v, sig);

        v.nonce = _fresh();
        registry.recordVerification(v, _signAttestation(ROUTER_PK, v));
        _assertStatus(i.paymentId, Status.CONFIRMED);
    }

    // =================================================================== expiry

    function test_Commit_AtValidUntilIsStillValid() public {
        PaymentIntent memory i = _intent("PAY-LAST-SECOND", Tier.LOW);
        bytes memory sig = _signIntent(ROUTER_PK, i);

        vm.warp(i.validUntil);
        registry.commit(i, sig);

        _assertStatus(i.paymentId, Status.COMMITTED);
    }

    function test_RevertWhen_IntentExpired() public {
        PaymentIntent memory i = _intent("PAY-EXPIRED", Tier.LOW);
        bytes memory sig = _signIntent(ROUTER_PK, i);

        vm.warp(uint256(i.validUntil) + 1);
        vm.expectRevert(PaymentRegistry.IntentExpired.selector);
        registry.commit(i, sig);

        _assertStatus(i.paymentId, Status.NONE);
        assertFalse(registry.nonceUsed(routerSigner, i.nonce));
    }

    // =================================================================== order of the checks
    // The Python MockChain mirrors this order: when several things are wrong, the first failing check names the error.

    function test_CheckOrder_Commit() public {
        // 1. status, before expiry, signer and nonce
        PaymentIntent memory committed = _committed(Tier.LOW);
        bytes memory outsiderSig = _signIntent(OUTSIDER_PK, committed);
        vm.warp(uint256(committed.validUntil) + 1);
        vm.expectRevert(PaymentRegistry.InvalidTransition.selector);
        registry.commit(committed, outsiderSig);

        // 2. expiry, before signer and nonce
        PaymentIntent memory expired = _intent("PAY-ORDER-EXPIRED", Tier.LOW);
        expired.validUntil = _now() - 1;
        expired.nonce = committed.nonce;
        outsiderSig = _signIntent(OUTSIDER_PK, expired);
        vm.expectRevert(PaymentRegistry.IntentExpired.selector);
        registry.commit(expired, outsiderSig);

        // 3. signer, before nonce
        PaymentIntent memory unsigned = _intent("PAY-ORDER-SIGNER", Tier.LOW);
        unsigned.nonce = committed.nonce;
        outsiderSig = _signIntent(OUTSIDER_PK, unsigned);
        vm.expectRevert(PaymentRegistry.UnauthorizedSigner.selector);
        registry.commit(unsigned, outsiderSig);

        // 4. nonce
        bytes memory routerSig = _signIntent(ROUTER_PK, unsigned);
        vm.expectRevert(PaymentRegistry.NonceUsed.selector);
        registry.commit(unsigned, routerSig);
    }

    function test_CheckOrder_RecordVerification() public {
        PaymentIntent memory i = _committed(Tier.MEDIUM);
        PaymentIntent memory done = _reach(Status.CONFIRMED);
        uint256 usedNonce = _usedVerifierNonce();

        // 1. status, before the intent hash
        VerificationAttestation memory v = _attestation(done, VerificationResult.CONFIRMED);
        v.intentHash = bytes32(0);
        bytes memory sig = _signAttestation(OUTSIDER_PK, v);
        vm.expectRevert(PaymentRegistry.InvalidTransition.selector);
        registry.recordVerification(v, sig);

        // 2. intent hash, before the signer
        v = _attestation(i, VerificationResult.CONFIRMED);
        v.intentHash = bytes32(0);
        sig = _signAttestation(OUTSIDER_PK, v);
        vm.expectRevert(PaymentRegistry.CommitmentMismatch.selector);
        registry.recordVerification(v, sig);

        // 3. signer, before the nonce and the result
        v = _attestation(i, VerificationResult.CONFIRMED);
        v.nonce = usedNonce;
        v.result = 0;
        sig = _signAttestation(OUTSIDER_PK, v);
        vm.expectRevert(PaymentRegistry.UnauthorizedSigner.selector);
        registry.recordVerification(v, sig);

        // 4. nonce, before the result
        sig = _signAttestation(VERIFIER_PK, v);
        vm.expectRevert(PaymentRegistry.NonceUsed.selector);
        registry.recordVerification(v, sig);

        // 5. result
        v.nonce = _fresh();
        sig = _signAttestation(VERIFIER_PK, v);
        vm.expectRevert(PaymentRegistry.InvalidTransition.selector);
        registry.recordVerification(v, sig);

        _assertStatus(i.paymentId, Status.COMMITTED);
    }

    function test_CheckOrder_Revoke() public {
        PaymentIntent memory i = _committed(Tier.MEDIUM);
        PaymentIntent memory revoked = _committed(Tier.MEDIUM);
        Revocation memory first = _revocation(revoked);
        registry.revoke(first, _signRevocation(ANALYST_PK, first));

        // 1. status, before the signer
        Revocation memory r = _revocation(revoked);
        bytes memory sig = _signRevocation(OUTSIDER_PK, r);
        vm.expectRevert(PaymentRegistry.InvalidTransition.selector);
        registry.revoke(r, sig);

        // 2. signer, before the nonce
        r = _revocation(i);
        r.nonce = first.nonce;
        sig = _signRevocation(OUTSIDER_PK, r);
        vm.expectRevert(PaymentRegistry.UnauthorizedSigner.selector);
        registry.revoke(r, sig);

        // 3. nonce
        sig = _signRevocation(ANALYST_PK, r);
        vm.expectRevert(PaymentRegistry.NonceUsed.selector);
        registry.revoke(r, sig);

        _assertStatus(i.paymentId, Status.COMMITTED);
    }

    // =================================================================== helpers

    function _expectCommitUnauthorized(PaymentIntent memory i, bytes memory sig) internal {
        vm.expectRevert(PaymentRegistry.UnauthorizedSigner.selector);
        registry.commit(i, sig);
    }

    /// @dev A wallet owned by the outsider key, registered as a router signer.
    function _routerWallet() internal returns (OwnedWalletMock wallet) {
        wallet = new OwnedWalletMock(outsider);
        bytes32 routerRole = registry.ROUTER_SIGNER_ROLE();
        vm.prank(admin);
        registry.grantRole(routerRole, address(wallet));
    }

    /// @dev Makes the verifier use a nonce and returns it.
    function _usedVerifierNonce() internal returns (uint256) {
        PaymentIntent memory i = _committed(Tier.MEDIUM);
        VerificationAttestation memory v = _attestation(i, VerificationResult.DENIED);
        registry.recordVerification(v, _signAttestation(VERIFIER_PK, v));
        return v.nonce;
    }
}
