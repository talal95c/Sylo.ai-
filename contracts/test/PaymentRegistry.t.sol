// SPDX-License-Identifier: MIT
pragma solidity ^0.8.28;

import {IAccessControl} from "@openzeppelin/contracts/access/IAccessControl.sol";
import {IERC1271} from "@openzeppelin/contracts/interfaces/IERC1271.sol";
import {ECDSA} from "@openzeppelin/contracts/utils/cryptography/ECDSA.sol";

import {PaymentRegistry} from "../src/PaymentRegistry.sol";
import {
    PaymentIntent,
    Revocation,
    RevocationReason,
    Status,
    Tier,
    VerificationAttestation,
    VerificationResult
} from "../src/SyloTypes.sol";
import {SyloTestBase} from "./SyloTestBase.sol";

/// @dev A one-owner smart wallet standing in for a multisig signer.
contract MockContractSigner is IERC1271 {
    address private immutable OWNER;

    constructor(address owner) {
        OWNER = owner;
    }

    function isValidSignature(bytes32 hash, bytes calldata signature) external view returns (bytes4) {
        (address recovered, ECDSA.RecoverError err,) = ECDSA.tryRecoverCalldata(hash, signature);
        bool valid = err == ECDSA.RecoverError.NoError && recovered == OWNER;
        return valid ? IERC1271.isValidSignature.selector : bytes4(0xffffffff);
    }
}

contract PaymentRegistryTest is SyloTestBase {
    uint256 private constant SECP256K1_N = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141;

    // --- commit -------------------------------------------------------------------------------

    function test_Commit_StoresTheIntent() public {
        PaymentIntent memory i = _intent(Tier.MEDIUM);
        bytes32 digest = registry.digestOf(i);
        bytes memory sig = _sign(routerKey, digest);

        vm.expectEmit(address(registry));
        emit PaymentRegistry.PaymentCommitted(i.paymentId, CORRIDOR, digest, routerSigner);
        registry.commit(i, sig);

        _assertStatus(i.paymentId, Status.COMMITTED);
        assertEq(registry.intentOf(i.paymentId), digest);
        PaymentRegistry.Payment memory p = registry.paymentOf(i.paymentId);
        assertEq(p.intentHash, digest);
        assertEq(p.beneficiary, beneficiary);
        assertEq(p.token, address(token));
        assertEq(p.amount, AMOUNT);
        assertEq(p.tier, uint8(Tier.MEDIUM));
        assertEq(p.corridorId, CORRIDOR);
        assertTrue(registry.nonceUsed(routerSigner, i.nonce));
    }

    function test_Commit_Twice_Reverts() public {
        PaymentIntent memory i = _intent(Tier.LOW);
        _commit(i);
        i.nonce = _next();
        bytes memory sig = _sign(routerKey, registry.digestOf(i));

        vm.expectRevert(PaymentRegistry.InvalidTransition.selector);
        registry.commit(i, sig);
    }

    function test_Commit_AfterValidUntil_Reverts() public {
        PaymentIntent memory i = _intent(Tier.LOW);
        bytes memory sig = _sign(routerKey, registry.digestOf(i));
        vm.warp(uint256(i.validUntil) + 1);

        vm.expectRevert(PaymentRegistry.IntentExpired.selector);
        registry.commit(i, sig);
    }

    function test_Commit_AtValidUntil_Succeeds() public {
        PaymentIntent memory i = _intent(Tier.LOW);
        vm.warp(i.validUntil);
        _commit(i);
        _assertStatus(i.paymentId, Status.COMMITTED);
    }

    function test_Commit_SignerWithoutRouterRole_Reverts() public {
        PaymentIntent memory i = _intent(Tier.LOW);
        bytes32 digest = registry.digestOf(i);
        bytes memory byOutsider = _sign(outsiderKey, digest);
        bytes memory byVerifier = _sign(verifierKey, digest);

        vm.expectRevert(PaymentRegistry.UnauthorizedSigner.selector);
        registry.commit(i, byOutsider);
        vm.expectRevert(PaymentRegistry.UnauthorizedSigner.selector);
        registry.commit(i, byVerifier);
    }

    function testFuzz_Commit_UnknownKey_Reverts(uint256 key) public {
        key = bound(key, 1, SECP256K1_N - 1);
        vm.assume(key != routerKey);
        PaymentIntent memory i = _intent(Tier.LOW);
        bytes memory sig = _sign(key, registry.digestOf(i));

        vm.expectRevert(PaymentRegistry.UnauthorizedSigner.selector);
        registry.commit(i, sig);
    }

    function test_Commit_IntentChangedAfterSigning_Reverts() public {
        PaymentIntent memory i = _intent(Tier.MEDIUM);
        bytes memory sig = _sign(routerKey, registry.digestOf(i));
        i.beneficiary = attacker;

        vm.expectRevert(PaymentRegistry.UnauthorizedSigner.selector);
        registry.commit(i, sig);
    }

    function test_Commit_MalformedSignature_Reverts() public {
        PaymentIntent memory i = _intent(Tier.LOW);

        vm.expectRevert(PaymentRegistry.UnauthorizedSigner.selector);
        registry.commit(i, hex"deadbeef");
        vm.expectRevert(PaymentRegistry.UnauthorizedSigner.selector);
        registry.commit(i, new bytes(65));
        vm.expectRevert(PaymentRegistry.UnauthorizedSigner.selector);
        registry.commit(i, new bytes(64));
    }

    function test_Commit_NonceReuse_Reverts() public {
        PaymentIntent memory first = _intent(Tier.LOW);
        _commit(first);
        PaymentIntent memory second = _intent(Tier.LOW);
        second.nonce = first.nonce;
        bytes memory sig = _sign(routerKey, registry.digestOf(second));

        vm.expectRevert(PaymentRegistry.NonceUsed.selector);
        registry.commit(second, sig);
    }

    function test_Commit_ContractSigner() public {
        (address owner, uint256 ownerKey) = makeAddrAndKey("multisigOwner");
        MockContractSigner wallet = new MockContractSigner(owner);
        bytes32 role = registry.ROUTER_SIGNER_ROLE();
        vm.prank(admin);
        registry.grantRole(role, address(wallet));

        PaymentIntent memory i = _intent(Tier.LOW);
        bytes32 digest = registry.digestOf(i);
        bytes memory sig = abi.encodePacked(address(wallet), _sign(ownerKey, digest));

        vm.expectEmit(address(registry));
        emit PaymentRegistry.PaymentCommitted(i.paymentId, CORRIDOR, digest, address(wallet));
        registry.commit(i, sig);
        assertTrue(registry.nonceUsed(address(wallet), i.nonce));
    }

    function test_Commit_ContractSignerRejectingTheSignature_Reverts() public {
        (address owner,) = makeAddrAndKey("multisigOwner");
        MockContractSigner wallet = new MockContractSigner(owner);
        bytes32 role = registry.ROUTER_SIGNER_ROLE();
        vm.prank(admin);
        registry.grantRole(role, address(wallet));

        PaymentIntent memory i = _intent(Tier.LOW);
        bytes memory sig = abi.encodePacked(address(wallet), _sign(outsiderKey, registry.digestOf(i)));

        vm.expectRevert(PaymentRegistry.UnauthorizedSigner.selector);
        registry.commit(i, sig);
    }

    // --- recordVerification --------------------------------------------------------------------

    function test_Verification_Confirmed() public {
        PaymentIntent memory i = _intent(Tier.MEDIUM);
        _commit(i);
        VerificationAttestation memory v = _attestation(i, VerificationResult.CONFIRMED);
        bytes memory sig = _signVerification(verifierKey, v);

        vm.expectEmit(address(registry));
        emit PaymentRegistry.VerificationRecorded(i.paymentId, v.result, v.evidenceHash, verifierSigner);
        registry.recordVerification(v, sig);
        _assertStatus(i.paymentId, Status.CONFIRMED);
    }

    function test_Verification_Denied() public {
        PaymentIntent memory i = _intent(Tier.MEDIUM);
        _commit(i);
        _verify(i, VerificationResult.DENIED);
        _assertStatus(i.paymentId, Status.DENIED);
    }

    function test_Verification_OfAnotherIntent_Reverts() public {
        PaymentIntent memory i = _intent(Tier.MEDIUM);
        _commit(i);
        VerificationAttestation memory v = _attestation(i, VerificationResult.CONFIRMED);
        v.intentHash = keccak256("a different intent");
        bytes memory sig = _signVerification(verifierKey, v);

        vm.expectRevert(PaymentRegistry.CommitmentMismatch.selector);
        registry.recordVerification(v, sig);
    }

    function test_Verification_BeforeCommit_Reverts() public {
        PaymentIntent memory i = _intent(Tier.MEDIUM);
        VerificationAttestation memory v = _attestation(i, VerificationResult.CONFIRMED);
        bytes memory sig = _signVerification(verifierKey, v);

        vm.expectRevert(PaymentRegistry.InvalidTransition.selector);
        registry.recordVerification(v, sig);
    }

    function test_Verification_Twice_Reverts() public {
        PaymentIntent memory i = _intent(Tier.MEDIUM);
        _commit(i);
        _verify(i, VerificationResult.DENIED);
        VerificationAttestation memory v = _attestation(i, VerificationResult.CONFIRMED);
        bytes memory sig = _signVerification(verifierKey, v);

        vm.expectRevert(PaymentRegistry.InvalidTransition.selector);
        registry.recordVerification(v, sig);
    }

    function test_Verification_UnknownResult_Reverts() public {
        PaymentIntent memory i = _intent(Tier.MEDIUM);
        _commit(i);
        VerificationAttestation memory v = _attestation(i, VerificationResult.CONFIRMED);
        v.result = 3;
        bytes memory sig = _signVerification(verifierKey, v);

        vm.expectRevert(PaymentRegistry.InvalidResult.selector);
        registry.recordVerification(v, sig);
    }

    function test_Verification_SignerWithoutVerifierRole_Reverts() public {
        PaymentIntent memory i = _intent(Tier.MEDIUM);
        _commit(i);
        VerificationAttestation memory v = _attestation(i, VerificationResult.CONFIRMED);
        bytes memory sig = _signVerification(routerKey, v);

        vm.expectRevert(PaymentRegistry.UnauthorizedSigner.selector);
        registry.recordVerification(v, sig);
    }

    function test_Verification_NonceReuse_Reverts() public {
        PaymentIntent memory first = _intent(Tier.MEDIUM);
        PaymentIntent memory second = _intent(Tier.MEDIUM);
        _commit(first);
        _commit(second);
        VerificationAttestation memory a = _attestation(first, VerificationResult.CONFIRMED);
        registry.recordVerification(a, _signVerification(verifierKey, a));
        VerificationAttestation memory b = _attestation(second, VerificationResult.CONFIRMED);
        b.nonce = a.nonce;
        bytes memory sig = _signVerification(verifierKey, b);

        vm.expectRevert(PaymentRegistry.NonceUsed.selector);
        registry.recordVerification(b, sig);
    }

    // --- revoke --------------------------------------------------------------------------------

    function test_Revoke_FromCommittedConfirmedOrDenied() public {
        PaymentIntent memory committed = _intent(Tier.MEDIUM);
        _commit(committed);
        PaymentIntent memory confirmed = _intent(Tier.MEDIUM);
        _commit(confirmed);
        _verify(confirmed, VerificationResult.CONFIRMED);
        PaymentIntent memory denied = _intent(Tier.MEDIUM);
        _commit(denied);
        _verify(denied, VerificationResult.DENIED);

        Revocation memory r = _revocation(denied.paymentId);
        bytes memory sig = _signRevocation(analystKey, r);
        vm.expectEmit(address(registry));
        emit PaymentRegistry.PaymentRevoked(denied.paymentId, uint8(RevocationReason.SUPPLIER_DENIED), analystSigner);
        registry.revoke(r, sig);
        _revoke(committed.paymentId);
        _revoke(confirmed.paymentId);

        _assertStatus(committed.paymentId, Status.REVOKED);
        _assertStatus(confirmed.paymentId, Status.REVOKED);
        _assertStatus(denied.paymentId, Status.REVOKED);
    }

    function test_Revoke_FromNoneRevokedOrExecuted_Reverts() public {
        PaymentIntent memory unknown = _intent(Tier.MEDIUM);
        PaymentIntent memory revoked = _intent(Tier.MEDIUM);
        _commit(revoked);
        _revoke(revoked.paymentId);
        PaymentIntent memory executed = _intent(Tier.LOW);
        _commit(executed);
        vm.prank(relayer);
        registry.markExecuted(executed.paymentId, bytes32("rail-ref"));

        bytes32[3] memory ids = [unknown.paymentId, revoked.paymentId, executed.paymentId];
        for (uint256 k; k < ids.length; ++k) {
            Revocation memory r = _revocation(ids[k]);
            bytes memory sig = _signRevocation(analystKey, r);
            vm.expectRevert(PaymentRegistry.InvalidTransition.selector);
            registry.revoke(r, sig);
        }
    }

    function test_Revoke_SignerWithoutAnalystRole_Reverts() public {
        PaymentIntent memory i = _intent(Tier.MEDIUM);
        _commit(i);
        Revocation memory r = _revocation(i.paymentId);
        bytes memory sig = _signRevocation(verifierKey, r);

        vm.expectRevert(PaymentRegistry.UnauthorizedSigner.selector);
        registry.revoke(r, sig);
    }

    function test_Revoke_NonceReuse_Reverts() public {
        PaymentIntent memory first = _intent(Tier.MEDIUM);
        PaymentIntent memory second = _intent(Tier.MEDIUM);
        _commit(first);
        _commit(second);
        Revocation memory a = _revocation(first.paymentId);
        registry.revoke(a, _signRevocation(analystKey, a));
        Revocation memory b = _revocation(second.paymentId);
        b.nonce = a.nonce;
        bytes memory sig = _signRevocation(analystKey, b);

        vm.expectRevert(PaymentRegistry.NonceUsed.selector);
        registry.revoke(b, sig);
    }

    // --- markExecuted --------------------------------------------------------------------------

    function test_MarkExecuted_LowRightAfterCommit() public {
        PaymentIntent memory i = _intent(Tier.LOW);
        _commit(i);

        vm.expectEmit(address(registry));
        emit PaymentRegistry.PaymentExecuted(i.paymentId, bytes32("rail-ref"));
        vm.prank(relayer);
        registry.markExecuted(i.paymentId, bytes32("rail-ref"));
        _assertStatus(i.paymentId, Status.EXECUTED);
    }

    function test_MarkExecuted_AfterConfirmation() public {
        PaymentIntent memory i = _intent(Tier.MEDIUM);
        _commit(i);
        _verify(i, VerificationResult.CONFIRMED);

        vm.prank(relayer);
        registry.markExecuted(i.paymentId, bytes32("rail-ref"));
        _assertStatus(i.paymentId, Status.EXECUTED);
    }

    function test_MarkExecuted_ForbiddenTransitions_Revert() public {
        PaymentIntent memory unknown = _intent(Tier.LOW);
        PaymentIntent memory mediumCommitted = _intent(Tier.MEDIUM);
        _commit(mediumCommitted);
        PaymentIntent memory denied = _intent(Tier.MEDIUM);
        _commit(denied);
        _verify(denied, VerificationResult.DENIED);
        PaymentIntent memory revoked = _intent(Tier.LOW);
        _commit(revoked);
        _revoke(revoked.paymentId);
        PaymentIntent memory executed = _intent(Tier.LOW);
        _commit(executed);
        vm.prank(relayer);
        registry.markExecuted(executed.paymentId, bytes32("rail-ref"));

        bytes32[5] memory ids =
            [unknown.paymentId, mediumCommitted.paymentId, denied.paymentId, revoked.paymentId, executed.paymentId];
        for (uint256 k; k < ids.length; ++k) {
            vm.prank(relayer);
            vm.expectRevert(PaymentRegistry.InvalidTransition.selector);
            registry.markExecuted(ids[k], bytes32("rail-ref"));
        }
    }

    function test_MarkExecuted_WithoutExecutorRole_Reverts() public {
        PaymentIntent memory i = _intent(Tier.LOW);
        _commit(i);
        bytes32 role = registry.EXECUTOR_ROLE();

        vm.prank(attacker);
        vm.expectRevert(abi.encodeWithSelector(IAccessControl.AccessControlUnauthorizedAccount.selector, attacker, role));
        registry.markExecuted(i.paymentId, bytes32("rail-ref"));
    }
}
