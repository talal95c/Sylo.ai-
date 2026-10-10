// SPDX-License-Identifier: MIT
pragma solidity ^0.8.28;

import {IAccessControl} from "@openzeppelin/contracts/access/IAccessControl.sol";

import {PaymentEscrow} from "../src/PaymentEscrow.sol";
import {PaymentIntent, Status, Tier, VerificationResult} from "../src/SyloTypes.sol";
import {SyloTestBase} from "./SyloTestBase.sol";

contract PaymentEscrowTest is SyloTestBase {
    // --- deposit -------------------------------------------------------------------------------

    function test_Deposit_HoldsTheMoney() public {
        PaymentIntent memory i = _intent(Tier.MEDIUM);
        bytes32 intentHash = _commit(i);
        uint64 expiresAt = uint64(block.timestamp) + HOLD;

        vm.expectEmit(address(escrow));
        emit PaymentEscrow.Deposited(i.paymentId, payer, beneficiary, AMOUNT, expiresAt, intentHash);
        _deposit(i);

        assertEq(token.balanceOf(address(escrow)), AMOUNT);
        assertEq(token.balanceOf(payer), TREASURY - AMOUNT);
        assertEq(escrow.totalHeld(address(token)), AMOUNT);
        PaymentEscrow.Hold memory h = escrow.holdOf(i.paymentId);
        assertEq(h.payer, payer);
        assertEq(h.beneficiary, beneficiary);
        assertEq(h.token, address(token));
        assertEq(h.amount, AMOUNT);
        assertEq(h.corridorId, CORRIDOR);
        assertEq(h.expiresAt, expiresAt);
        assertFalse(h.frozen);
        assertFalse(h.settled);
        _assertStatus(i.paymentId, Status.COMMITTED);
    }

    function test_Deposit_AmountDiffersFromIntent_Reverts() public {
        PaymentIntent memory i = _intent(Tier.MEDIUM);
        _commit(i);
        i.amount += 1;

        vm.prank(relayer);
        vm.expectRevert(PaymentEscrow.CommitmentMismatch.selector);
        escrow.deposit(i, payer);
    }

    function testFuzz_Deposit_AnyOtherAmount_Reverts(uint256 amount) public {
        vm.assume(amount != AMOUNT);
        PaymentIntent memory i = _intent(Tier.MEDIUM);
        _commit(i);
        i.amount = amount;

        vm.prank(relayer);
        vm.expectRevert(PaymentEscrow.CommitmentMismatch.selector);
        escrow.deposit(i, payer);
    }

    function test_Deposit_BeneficiaryDiffersFromIntent_Reverts() public {
        PaymentIntent memory i = _intent(Tier.MEDIUM);
        _commit(i);
        i.beneficiary = attacker;

        vm.prank(relayer);
        vm.expectRevert(PaymentEscrow.CommitmentMismatch.selector);
        escrow.deposit(i, payer);
    }

    function test_Deposit_Uncommitted_Reverts() public {
        PaymentIntent memory i = _intent(Tier.MEDIUM);

        vm.prank(relayer);
        vm.expectRevert(PaymentEscrow.CommitmentMismatch.selector);
        escrow.deposit(i, payer);
    }

    function test_Deposit_LowOrHighTier_Reverts() public {
        PaymentIntent memory low = _intent(Tier.LOW);
        _commit(low);
        PaymentIntent memory high = _intent(Tier.HIGH);
        _commit(high);

        vm.prank(relayer);
        vm.expectRevert(PaymentEscrow.TierNotEscrowable.selector);
        escrow.deposit(low, payer);
        vm.prank(relayer);
        vm.expectRevert(PaymentEscrow.TierNotEscrowable.selector);
        escrow.deposit(high, payer);
    }

    function test_Deposit_Twice_Reverts() public {
        PaymentIntent memory i = _held();

        vm.prank(relayer);
        vm.expectRevert(PaymentEscrow.AlreadyDeposited.selector);
        escrow.deposit(i, payer);
    }

    function test_Deposit_AfterVerification_Reverts() public {
        PaymentIntent memory i = _intent(Tier.MEDIUM);
        _commit(i);
        _verify(i, VerificationResult.CONFIRMED);

        vm.prank(relayer);
        vm.expectRevert(PaymentEscrow.InvalidTransition.selector);
        escrow.deposit(i, payer);
    }

    function test_Deposit_WithoutRouterRole_Reverts() public {
        PaymentIntent memory i = _intent(Tier.MEDIUM);
        _commit(i);
        bytes32 role = escrow.ROUTER_ROLE();

        vm.prank(attacker);
        vm.expectRevert(abi.encodeWithSelector(IAccessControl.AccessControlUnauthorizedAccount.selector, attacker, role));
        escrow.deposit(i, payer);
    }

    // --- release -------------------------------------------------------------------------------

    function test_Release_Confirmed_PaysTheBeneficiary() public {
        PaymentIntent memory i = _held();
        _verify(i, VerificationResult.CONFIRMED);

        vm.expectEmit(address(escrow));
        emit PaymentEscrow.Released(i.paymentId);
        vm.prank(attacker);
        escrow.release(i.paymentId);

        assertEq(token.balanceOf(beneficiary), AMOUNT);
        assertEq(token.balanceOf(address(escrow)), 0);
        assertEq(escrow.totalHeld(address(token)), 0);
        assertTrue(escrow.holdOf(i.paymentId).settled);
        _assertStatus(i.paymentId, Status.EXECUTED);
    }

    function test_Release_UnlessConfirmed_Reverts() public {
        PaymentIntent memory committed = _held();
        PaymentIntent memory denied = _held();
        _verify(denied, VerificationResult.DENIED);
        PaymentIntent memory revoked = _held();
        _verify(revoked, VerificationResult.DENIED);
        _revoke(revoked.paymentId);

        _expectNotReleasable(committed.paymentId);
        _expectNotReleasable(denied.paymentId);
        _expectNotReleasable(revoked.paymentId);
        assertEq(token.balanceOf(beneficiary), 0);
    }

    /// Scene 2b: the supplier denied, the analyst revoked, then someone tries to release the money anyway.
    function test_Attack_ReleaseOfRevokedPayment_RevertsAndThePayerIsRefunded() public {
        PaymentIntent memory i = _held();
        _verify(i, VerificationResult.DENIED);
        _revoke(i.paymentId);

        _expectNotReleasable(i.paymentId);
        vm.prank(attacker);
        escrow.refund(i.paymentId);

        assertEq(token.balanceOf(payer), TREASURY);
        assertEq(token.balanceOf(beneficiary), 0);
        assertEq(token.balanceOf(attacker), 0);
        _assertStatus(i.paymentId, Status.REVOKED);
    }

    function test_Release_WhenFrozen_Reverts() public {
        PaymentIntent memory i = _held();
        _verify(i, VerificationResult.CONFIRMED);
        vm.prank(guardian);
        escrow.freeze(i.paymentId);

        _expectNotReleasable(i.paymentId);
    }

    function test_Release_AfterExpiry_Reverts() public {
        PaymentIntent memory i = _held();
        _verify(i, VerificationResult.CONFIRMED);
        vm.warp(uint256(escrow.holdOf(i.paymentId).expiresAt) + 1);

        _expectNotReleasable(i.paymentId);
    }

    function test_Release_AtExpiry_Succeeds() public {
        PaymentIntent memory i = _held();
        _verify(i, VerificationResult.CONFIRMED);
        vm.warp(escrow.holdOf(i.paymentId).expiresAt);

        escrow.release(i.paymentId);
        assertEq(token.balanceOf(beneficiary), AMOUNT);
    }

    function test_Release_OnPausedCorridor_RevertsUntilUnpaused() public {
        PaymentIntent memory i = _held();
        _verify(i, VerificationResult.CONFIRMED);
        vm.prank(guardian);
        escrow.pauseCorridor(CORRIDOR);

        _expectNotReleasable(i.paymentId);

        vm.prank(admin);
        escrow.unpauseCorridor(CORRIDOR);
        escrow.release(i.paymentId);
        assertEq(token.balanceOf(beneficiary), AMOUNT);
    }

    function test_Release_Twice_Reverts() public {
        PaymentIntent memory i = _held();
        _verify(i, VerificationResult.CONFIRMED);
        escrow.release(i.paymentId);

        _expectNotReleasable(i.paymentId);
    }

    function test_Release_WithoutHold_Reverts() public {
        PaymentIntent memory i = _intent(Tier.MEDIUM);
        _commit(i);
        _verify(i, VerificationResult.CONFIRMED);

        _expectNotReleasable(i.paymentId);
    }

    // --- refund --------------------------------------------------------------------------------

    function test_Refund_ByAnyoneAfterRevocation() public {
        PaymentIntent memory i = _held();
        _revoke(i.paymentId);

        vm.expectEmit(address(escrow));
        emit PaymentEscrow.Refunded(i.paymentId, false);
        vm.prank(attacker);
        escrow.refund(i.paymentId);

        assertEq(token.balanceOf(payer), TREASURY);
        assertEq(escrow.totalHeld(address(token)), 0);
        assertTrue(escrow.holdOf(i.paymentId).settled);
    }

    function test_Refund_ByAnyoneAfterExpiry() public {
        PaymentIntent memory i = _held();
        vm.warp(uint256(escrow.holdOf(i.paymentId).expiresAt) + 1);

        vm.expectEmit(address(escrow));
        emit PaymentEscrow.Refunded(i.paymentId, true);
        vm.prank(attacker);
        escrow.refund(i.paymentId);

        assertEq(token.balanceOf(payer), TREASURY);
    }

    function test_Refund_ByAnalystAtAnyTime() public {
        PaymentIntent memory i = _held();

        vm.prank(analystSigner);
        escrow.refund(i.paymentId);
        assertEq(token.balanceOf(payer), TREASURY);
    }

    function test_Refund_BeforeRevocationOrExpiry_Reverts() public {
        PaymentIntent memory committed = _held();
        PaymentIntent memory denied = _held();
        _verify(denied, VerificationResult.DENIED);

        vm.prank(attacker);
        vm.expectRevert(PaymentEscrow.RefundNotAllowed.selector);
        escrow.refund(committed.paymentId);
        vm.prank(attacker);
        vm.expectRevert(PaymentEscrow.RefundNotAllowed.selector);
        escrow.refund(denied.paymentId);
    }

    function test_Refund_Twice_Reverts() public {
        PaymentIntent memory i = _held();
        _revoke(i.paymentId);
        escrow.refund(i.paymentId);

        vm.expectRevert(PaymentEscrow.AlreadySettled.selector);
        escrow.refund(i.paymentId);
    }

    function test_Refund_AfterRelease_Reverts() public {
        PaymentIntent memory i = _held();
        _verify(i, VerificationResult.CONFIRMED);
        escrow.release(i.paymentId);

        vm.prank(analystSigner);
        vm.expectRevert(PaymentEscrow.AlreadySettled.selector);
        escrow.refund(i.paymentId);
    }

    function test_Refund_WithoutHold_Reverts() public {
        vm.expectRevert(PaymentEscrow.NoHold.selector);
        escrow.refund(keccak256("no such payment"));
    }

    // --- guardian and admin ----------------------------------------------------------------------

    function test_Freeze_ByAnalystOrGuardian() public {
        PaymentIntent memory first = _held();
        PaymentIntent memory second = _held();

        vm.expectEmit(address(escrow));
        emit PaymentEscrow.Frozen(first.paymentId, guardian);
        vm.prank(guardian);
        escrow.freeze(first.paymentId);
        vm.prank(analystSigner);
        escrow.freeze(second.paymentId);

        assertTrue(escrow.holdOf(first.paymentId).frozen);
        assertTrue(escrow.holdOf(second.paymentId).frozen);
    }

    function test_Freeze_ByOutsider_Reverts() public {
        PaymentIntent memory i = _held();
        bytes32 role = escrow.GUARDIAN_ROLE();

        vm.prank(attacker);
        vm.expectRevert(abi.encodeWithSelector(IAccessControl.AccessControlUnauthorizedAccount.selector, attacker, role));
        escrow.freeze(i.paymentId);
    }

    function test_Freeze_WithoutHold_Reverts() public {
        vm.prank(guardian);
        vm.expectRevert(PaymentEscrow.NoHold.selector);
        escrow.freeze(keccak256("no such payment"));
    }

    function test_PauseCorridor_OnlyGuardian_UnpauseOnlyAdmin() public {
        bytes32 guardianRole = escrow.GUARDIAN_ROLE();
        bytes32 adminRole = escrow.DEFAULT_ADMIN_ROLE();

        vm.prank(attacker);
        vm.expectRevert(abi.encodeWithSelector(IAccessControl.AccessControlUnauthorizedAccount.selector, attacker, guardianRole));
        escrow.pauseCorridor(CORRIDOR);

        vm.expectEmit(address(escrow));
        emit PaymentEscrow.CorridorPaused(CORRIDOR, guardian);
        vm.prank(guardian);
        escrow.pauseCorridor(CORRIDOR);
        assertTrue(escrow.corridorPaused(CORRIDOR));

        vm.prank(guardian);
        vm.expectRevert(abi.encodeWithSelector(IAccessControl.AccessControlUnauthorizedAccount.selector, guardian, adminRole));
        escrow.unpauseCorridor(CORRIDOR);

        vm.prank(admin);
        escrow.unpauseCorridor(CORRIDOR);
        assertFalse(escrow.corridorPaused(CORRIDOR));
    }

    function test_SetHoldSeconds() public {
        bytes32 adminRole = escrow.DEFAULT_ADMIN_ROLE();

        vm.prank(admin);
        escrow.setHoldSeconds(2 hours);
        assertEq(escrow.holdSeconds(), 2 hours);

        vm.prank(admin);
        vm.expectRevert(PaymentEscrow.InvalidHoldSeconds.selector);
        escrow.setHoldSeconds(0);

        vm.prank(attacker);
        vm.expectRevert(abi.encodeWithSelector(IAccessControl.AccessControlUnauthorizedAccount.selector, attacker, adminRole));
        escrow.setHoldSeconds(1);
    }

    function test_Constructor_ZeroHold_Reverts() public {
        vm.expectRevert(PaymentEscrow.InvalidHoldSeconds.selector);
        new PaymentEscrow(registry, admin, 0);
    }

    // --- accounting ----------------------------------------------------------------------------

    /// The escrow's balance always equals the sum of its open holds, and no money leaves the
    /// payer -> escrow -> beneficiary circuit, whatever happens to each payment.
    function testFuzz_BalanceEqualsOpenHolds(uint256[6] calldata amounts, uint8[6] calldata outcomes) public {
        uint256 open;
        for (uint256 k; k < amounts.length; ++k) {
            PaymentIntent memory i = _intent(Tier.MEDIUM);
            i.amount = bound(amounts[k], 1, 1_000_000e6);
            _commit(i);
            _deposit(i);
            open += i.amount;

            uint8 outcome = outcomes[k] % 4;
            if (outcome == 1) {
                _verify(i, VerificationResult.CONFIRMED);
                escrow.release(i.paymentId);
                open -= i.amount;
            } else if (outcome == 2) {
                _verify(i, VerificationResult.DENIED);
                _revoke(i.paymentId);
                escrow.refund(i.paymentId);
                open -= i.amount;
            } else if (outcome == 3) {
                vm.prank(guardian);
                escrow.freeze(i.paymentId);
            }

            assertEq(token.balanceOf(address(escrow)), open, "escrow balance");
            assertEq(escrow.totalHeld(address(token)), open, "totalHeld");
        }
        uint256 circuit = token.balanceOf(payer) + token.balanceOf(beneficiary) + token.balanceOf(address(escrow));
        assertEq(circuit, TREASURY, "money left the circuit");
    }

    function _expectNotReleasable(bytes32 paymentId) private {
        vm.prank(attacker);
        vm.expectRevert(PaymentEscrow.PaymentNotReleasable.selector);
        escrow.release(paymentId);
    }
}
