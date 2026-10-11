// SPDX-License-Identifier: MIT
pragma solidity ^0.8.28;

import {PaymentEscrow} from "../src/PaymentEscrow.sol";
import {PaymentRegistry} from "../src/PaymentRegistry.sol";
import {PaymentIntent, Status, Tier, VerificationResult} from "../src/SyloTypes.sol";
import {SyloTestBase} from "./SyloTestBase.sol";

/// @dev Property-based tests: one action, random inputs. The invariant suite covers random sequences.
contract EscrowFuzzTest is SyloTestBase {
    uint256 internal constant SECP256K1_N = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141;

    function _copy(PaymentIntent memory i) internal pure returns (PaymentIntent memory) {
        return abi.decode(abi.encode(i), (PaymentIntent));
    }

    function _confirmedHold() internal returns (PaymentIntent memory i) {
        i = _held();
        _verify(i, VerificationResult.CONFIRMED);
    }

    /// Invariant 3: changing any field of a committed intent makes the deposit revert.
    function testFuzz_DepositOfAnAlteredIntentReverts(uint8 field, uint256 salt) public {
        PaymentIntent memory i = _intent(Tier.MEDIUM);
        _commit(i);
        PaymentIntent memory t = _copy(i);
        bytes32 flip = keccak256(abi.encode(salt)) | bytes32(uint256(1));
        uint256 bump = 1 + salt % 1e18;
        field = field % 11;
        if (field == 0) t.paymentId ^= flip;
        else if (field == 1) t.corridorId ^= flip;
        else if (field == 2) t.beneficiary = address(uint160(t.beneficiary) ^ (uint160(salt) | 1));
        else if (field == 3) t.token = address(uint160(t.token) ^ (uint160(salt) | 1));
        else if (field == 4) t.amount += bump;
        else if (field == 5) t.offchainHash ^= flip;
        else if (field == 6) t.decisionHash ^= flip;
        else if (field == 7) t.approvalHash ^= flip;
        else if (field == 8) t.tier = uint8((t.tier + 1 + salt % 255) % 256);
        else if (field == 9) t.validUntil += uint64(1 + salt % type(uint32).max);
        else t.nonce ^= uint256(flip);

        vm.prank(relayer);
        vm.expectRevert(PaymentEscrow.CommitmentMismatch.selector);
        escrow.deposit(t, payer);
        assertEq(token.balanceOf(address(escrow)), 0);
    }

    /// Invariant 4: release pays exactly the committed beneficiary, whoever calls it.
    function testFuzz_ReleasePaysOnlyTheCommittedBeneficiary(address caller, address to, uint256 amount) public {
        vm.assume(to != address(0) && to != address(escrow) && to != payer && to != caller);
        amount = bound(amount, 1, TREASURY);
        PaymentIntent memory i = _intent(Tier.MEDIUM);
        i.beneficiary = to;
        i.amount = amount;
        _commit(i);
        _deposit(i);
        _verify(i, VerificationResult.CONFIRMED);
        uint256 callerBefore = token.balanceOf(caller);

        vm.prank(caller);
        escrow.release(i.paymentId);

        assertEq(token.balanceOf(to), amount);
        assertEq(token.balanceOf(caller), callerBefore);
        assertEq(token.balanceOf(address(escrow)), 0);
        _assertStatus(i.paymentId, Status.EXECUTED);
    }

    /// Invariant 4: release reverts once the hold has expired; the payer can still be refunded.
    function testFuzz_ReleaseAfterExpiryReverts(uint256 late) public {
        PaymentIntent memory i = _confirmedHold();
        vm.warp(block.timestamp + HOLD + bound(late, 1, 3650 days));
        vm.expectRevert(PaymentEscrow.PaymentNotReleasable.selector);
        escrow.release(i.paymentId);
        escrow.refund(i.paymentId);
        assertEq(token.balanceOf(payer), TREASURY);
    }

    /// Invariant 4: release reverts unless the registry says CONFIRMED.
    function testFuzz_ReleaseNeedsConfirmed(bool deny, bool revoke, address caller) public {
        PaymentIntent memory i = _held();
        if (deny) _verify(i, VerificationResult.DENIED);
        if (revoke) _revoke(i.paymentId);
        vm.prank(caller);
        vm.expectRevert(PaymentEscrow.PaymentNotReleasable.selector);
        escrow.release(i.paymentId);
    }

    /// Invariant 5: after a revoke, anyone may refund, and the money goes back to the payer.
    function testFuzz_RefundAfterRevokeIsPermissionless(address caller) public {
        PaymentIntent memory i = _held();
        _revoke(i.paymentId);
        vm.prank(caller);
        escrow.refund(i.paymentId);
        assertEq(token.balanceOf(payer), TREASURY);
        assertEq(escrow.totalHeld(address(token)), 0);
    }

    /// Invariant 5: after expiry, anyone may refund.
    function testFuzz_RefundAfterExpiryIsPermissionless(address caller, uint256 late) public {
        PaymentIntent memory i = _held();
        vm.warp(block.timestamp + HOLD + bound(late, 1, 3650 days));
        vm.prank(caller);
        escrow.refund(i.paymentId);
        assertEq(token.balanceOf(payer), TREASURY);
    }

    /// Before expiry and without a revoke, only the analyst may refund.
    function testFuzz_EarlyRefundNeedsRevokeOrAnalyst(address caller, uint256 elapsed) public {
        vm.assume(caller != analystSigner);
        PaymentIntent memory i = _held();
        vm.warp(block.timestamp + bound(elapsed, 0, HOLD));
        vm.prank(caller);
        vm.expectRevert(PaymentEscrow.RefundNotAllowed.selector);
        escrow.refund(i.paymentId);
    }

    /// Invariant 6: one deposit per payment.
    function testFuzz_SecondDepositReverts(uint256 amount) public {
        PaymentIntent memory i = _intent(Tier.MEDIUM);
        i.amount = bound(amount, 1, TREASURY / 2);
        _commit(i);
        _deposit(i);
        vm.prank(relayer);
        vm.expectRevert(PaymentEscrow.AlreadyDeposited.selector);
        escrow.deposit(i, payer);
    }

    /// Invariant 6: a nonce is used once per signer.
    function testFuzz_NonceIsSingleUse(uint256 nonce) public {
        PaymentIntent memory first = _intent(Tier.LOW);
        first.nonce = nonce;
        _commit(first);
        PaymentIntent memory second = _intent(Tier.LOW);
        second.nonce = nonce;
        bytes32 digest = registry.digestOf(second);
        vm.expectRevert(PaymentRegistry.NonceUsed.selector);
        registry.commit(second, _sign(routerKey, digest));
    }

    /// Only MEDIUM payments are escrowed.
    function testFuzz_OnlyMediumIsEscrowable(uint8 tier) public {
        vm.assume(tier != uint8(Tier.MEDIUM));
        PaymentIntent memory i = _intent(Tier.LOW);
        i.tier = tier;
        _commit(i);
        vm.prank(relayer);
        vm.expectRevert(PaymentEscrow.TierNotEscrowable.selector);
        escrow.deposit(i, payer);
    }

    /// Only a router-signer key can commit.
    function testFuzz_OnlyTheRouterKeyCommits(uint256 key) public {
        key = bound(key, 1, SECP256K1_N - 1);
        vm.assume(key != routerKey);
        PaymentIntent memory i = _intent(Tier.LOW);
        bytes32 digest = registry.digestOf(i);
        vm.expectRevert(PaymentRegistry.UnauthorizedSigner.selector);
        registry.commit(i, _sign(key, digest));
    }

    /// Only the router role can deposit, even with the exact committed intent.
    function testFuzz_OnlyTheRouterRoleDeposits(address caller) public {
        vm.assume(caller != relayer);
        PaymentIntent memory i = _intent(Tier.MEDIUM);
        _commit(i);
        vm.prank(caller);
        vm.expectRevert();
        escrow.deposit(i, payer);
    }
}
