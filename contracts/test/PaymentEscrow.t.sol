// SPDX-License-Identifier: MIT
pragma solidity ^0.8.28;

import {IAccessControl} from "@openzeppelin/contracts/access/IAccessControl.sol";
import {IERC20Errors} from "@openzeppelin/contracts/interfaces/draft-IERC6093.sol";
import {ReentrancyGuard} from "@openzeppelin/contracts/utils/ReentrancyGuard.sol";

import {Deploy} from "../script/Deploy.s.sol";
import {MockEURC} from "../src/MockEURC.sol";
import {PaymentEscrow} from "../src/PaymentEscrow.sol";
import {PaymentRegistry} from "../src/PaymentRegistry.sol";
import {PaymentIntent, Status, Tier, VerificationResult} from "../src/SyloTypes.sol";
import {SyloFixture} from "./PaymentRegistry.t.sol";

/// @dev A hostile settlement token: when the escrow pays out, it calls back into the escrow.
contract ReentrantTokenMock {
    address public target;
    bytes public attack;
    bool public swallowFailure;
    uint256 public payouts;
    bool public lastAttackSucceeded;

    function arm(address target_, bytes calldata attack_, bool swallowFailure_) external {
        target = target_;
        attack = attack_;
        swallowFailure = swallowFailure_;
    }

    function transferFrom(address, address, uint256) external pure returns (bool) {
        return true;
    }

    function transfer(address, uint256) external returns (bool) {
        payouts += 1;
        if (attack.length != 0) {
            (bool ok, bytes memory data) = target.call(attack);
            lastAttackSucceeded = ok;
            if (!ok && !swallowFailure) {
                assembly ("memory-safe") {
                    revert(add(data, 0x20), mload(data))
                }
            }
        }
        return true;
    }
}

contract PaymentEscrowTest is SyloFixture {
    uint64 internal constant HOLD_SECONDS = 86_400;
    uint256 internal constant TREASURY = 10_000_000e6;

    MockEURC internal eurc;
    PaymentEscrow internal escrow;

    address internal payer; // the EU CASP treasury that funds the escrow
    address internal guardian;
    address internal anyone; // no role at all: stands for "the public" and for the attacker

    function setUp() public {
        _deployRegistry();

        payer = makeAddr("payer");
        guardian = makeAddr("guardian");
        anyone = makeAddr("anyone");

        eurc = new MockEURC(admin);
        token = address(eurc);
        escrow = new PaymentEscrow(registry, admin, HOLD_SECONDS);

        vm.startPrank(admin);
        registry.grantRole(registry.EXECUTOR_ROLE(), address(escrow));
        escrow.grantRole(escrow.ROUTER_ROLE(), relayer);
        escrow.grantRole(escrow.ANALYST_ROLE(), analystSigner);
        escrow.grantRole(escrow.GUARDIAN_ROLE(), guardian);
        eurc.mint(payer, TREASURY);
        vm.stopPrank();

        vm.prank(payer);
        eurc.approve(address(escrow), type(uint256).max);
    }

    // =================================================================== deployment

    function test_Constructor_SetsRegistryAdminAndHoldSeconds() public view {
        assertEq(address(escrow.registry()), address(registry));
        assertEq(escrow.holdSeconds(), HOLD_SECONDS);
        assertTrue(escrow.hasRole(escrow.DEFAULT_ADMIN_ROLE(), admin));
        assertFalse(escrow.hasRole(escrow.DEFAULT_ADMIN_ROLE(), address(this)));
        assertEq(escrow.RELEASE_EXECUTION_REF(), keccak256("SYLO_ESCROW_RELEASE"));
    }

    function test_MockEURC_IsATestEuroWithSixDecimalsMintedByItsOwnerOnly() public {
        assertEq(eurc.name(), "Sylo Test Euro");
        assertEq(eurc.symbol(), "tEURC");
        assertEq(eurc.decimals(), 6);
        assertEq(eurc.owner(), admin);

        vm.expectRevert();
        vm.prank(anyone);
        eurc.mint(anyone, 1);

        vm.prank(admin);
        eurc.mint(anyone, 1);
        assertEq(eurc.balanceOf(anyone), 1);
    }

    // =================================================================== deposit

    function test_Deposit_PullsTheAmountAndOpensAHold() public {
        PaymentIntent memory i = _committed(Tier.MEDIUM);
        bytes32 intentHash = registry.intentOf(i.paymentId);
        uint64 expiresAt = _now() + HOLD_SECONDS;

        vm.expectEmit(address(escrow));
        emit PaymentEscrow.Deposited(i.paymentId, payer, beneficiary, AMOUNT, expiresAt, intentHash);
        vm.prank(relayer);
        escrow.deposit(i, payer);

        assertEq(eurc.balanceOf(address(escrow)), AMOUNT);
        assertEq(eurc.balanceOf(payer), TREASURY - AMOUNT);
        assertEq(eurc.balanceOf(beneficiary), 0);
        assertEq(escrow.totalHeld(address(eurc)), AMOUNT);

        PaymentEscrow.Hold memory h = escrow.holdOf(i.paymentId);
        assertEq(h.payer, payer);
        assertEq(h.expiresAt, expiresAt);
        assertEq(uint256(h.state), uint256(PaymentEscrow.HoldState.HELD));
        assertFalse(h.frozen);
        assertEq(h.beneficiary, beneficiary);
        assertEq(h.token, address(eurc));
        assertEq(h.amount, AMOUNT);
        assertEq(h.corridorId, CORRIDOR);

        // A deposit does not change the registry status.
        _assertStatus(i.paymentId, Status.COMMITTED);
    }

    function test_RevertWhen_DepositAmountDiffersFromTheCommittedIntent() public {
        PaymentIntent memory i = _committed(Tier.MEDIUM);

        i.amount = AMOUNT + 1;
        _expectDepositRevert(i, PaymentEscrow.CommitmentMismatch.selector);

        i.amount = AMOUNT - 1;
        _expectDepositRevert(i, PaymentEscrow.CommitmentMismatch.selector);

        _assertNothingHeld();
    }

    function test_RevertWhen_DepositBeneficiaryDiffersFromTheCommittedIntent() public {
        PaymentIntent memory i = _committed(Tier.MEDIUM);

        // The diverted-invoice attack at the escrow: the committed amount, another beneficiary.
        i.beneficiary = anyone;
        _expectDepositRevert(i, PaymentEscrow.CommitmentMismatch.selector);

        _assertNothingHeld();
    }

    function test_RevertWhen_DepositChangesAnyOtherFieldOfTheCommittedIntent() public {
        for (uint256 field = 0; field < 8; ++field) {
            PaymentIntent memory i = _committed(Tier.MEDIUM);
            if (field == 0) i.corridorId = keccak256("NG-GH");
            if (field == 1) i.token = makeAddr("another token");
            if (field == 2) i.offchainHash = ~i.offchainHash;
            if (field == 3) i.decisionHash = ~i.decisionHash;
            if (field == 4) i.approvalHash = ~i.approvalHash;
            if (field == 5) i.tier = uint8(Tier.LOW);
            if (field == 6) i.validUntil += 1;
            if (field == 7) i.nonce += 1;

            _expectDepositRevert(i, PaymentEscrow.CommitmentMismatch.selector);
        }
        _assertNothingHeld();
    }

    function test_RevertWhen_DepositOfALowIntent() public {
        PaymentIntent memory i = _committed(Tier.LOW);

        _expectDepositRevert(i, PaymentEscrow.TierNotEscrowable.selector);

        _assertNothingHeld();
    }

    function test_RevertWhen_DepositOfAHighOrCriticalIntent() public {
        _expectDepositRevert(_committed(Tier.HIGH), PaymentEscrow.TierNotEscrowable.selector);
        _expectDepositRevert(_committed(Tier.CRITICAL), PaymentEscrow.TierNotEscrowable.selector);

        _assertNothingHeld();
    }

    function test_RevertWhen_DepositForAPaymentThatIsNotCommitted() public {
        Status[5] memory from = [Status.NONE, Status.CONFIRMED, Status.DENIED, Status.REVOKED, Status.EXECUTED];
        for (uint256 k = 0; k < from.length; ++k) {
            PaymentIntent memory i = _reach(from[k]);

            _expectDepositRevert(i, PaymentEscrow.InvalidTransition.selector);
        }
        _assertNothingHeld();
    }

    function test_RevertWhen_DepositTwice() public {
        PaymentIntent memory i = _held();

        _expectDepositRevert(i, PaymentEscrow.AlreadyDeposited.selector);

        _assertOpenHolds(AMOUNT);
    }

    function test_RevertWhen_DepositAgainAfterTheHoldWasSettled() public {
        // The hold expires and is refunded while the payment is still COMMITTED: one deposit per payment, ever.
        PaymentIntent memory i = _held();
        skip(HOLD_SECONDS + 1);
        escrow.refund(i.paymentId);
        _assertStatus(i.paymentId, Status.COMMITTED);

        _expectDepositRevert(i, PaymentEscrow.AlreadyDeposited.selector);

        _assertNothingHeld();
    }

    function test_RevertWhen_DepositByAnyoneButTheRouter() public {
        PaymentIntent memory i = _committed(Tier.MEDIUM);
        bytes32 routerRole = escrow.ROUTER_ROLE();
        address[4] memory callers = [anyone, admin, analystSigner, payer];

        for (uint256 k = 0; k < callers.length; ++k) {
            vm.expectRevert(
                abi.encodeWithSelector(IAccessControl.AccessControlUnauthorizedAccount.selector, callers[k], routerRole)
            );
            vm.prank(callers[k]);
            escrow.deposit(i, payer);
        }
        _assertNothingHeld();
    }

    function test_RevertWhen_PayerDidNotApproveTheEscrow() public {
        address stranger = makeAddr("payer without approval");
        vm.prank(admin);
        eurc.mint(stranger, AMOUNT);
        PaymentIntent memory i = _committed(Tier.MEDIUM);

        // The token's own error comes back unchanged through SafeERC20.
        vm.expectRevert(
            abi.encodeWithSelector(IERC20Errors.ERC20InsufficientAllowance.selector, address(escrow), 0, AMOUNT)
        );
        vm.prank(relayer);
        escrow.deposit(i, stranger);

        _assertNothingHeld();
        assertEq(uint256(escrow.holdOf(i.paymentId).state), uint256(PaymentEscrow.HoldState.NONE));
    }

    function test_RevertWhen_PayerCannotCoverTheAmount() public {
        address poor = makeAddr("payer without funds");
        vm.prank(poor);
        eurc.approve(address(escrow), type(uint256).max);
        PaymentIntent memory i = _committed(Tier.MEDIUM);

        vm.expectRevert(abi.encodeWithSelector(IERC20Errors.ERC20InsufficientBalance.selector, poor, 0, AMOUNT));
        vm.prank(relayer);
        escrow.deposit(i, poor);

        _assertNothingHeld();
    }

    function test_CheckOrder_Deposit() public {
        // 1. registry status, before the intent comparison
        PaymentIntent memory revoked = _reach(Status.REVOKED);
        revoked.amount += 1;
        _expectDepositRevert(revoked, PaymentEscrow.InvalidTransition.selector);

        // 2. intent comparison, before the tier
        PaymentIntent memory low = _committed(Tier.LOW);
        low.amount += 1;
        _expectDepositRevert(low, PaymentEscrow.CommitmentMismatch.selector);

        // 3. tier (a LOW intent can never have a hold, so the last check cannot hide it)
        low.amount -= 1;
        _expectDepositRevert(low, PaymentEscrow.TierNotEscrowable.selector);

        // 4. existing hold
        PaymentIntent memory held = _held();
        _expectDepositRevert(held, PaymentEscrow.AlreadyDeposited.selector);
    }

    // =================================================================== release

    function test_Release_PaysTheBeneficiaryAndMarksThePaymentExecuted() public {
        PaymentIntent memory i = _held();
        _verify(i, VerificationResult.CONFIRMED);
        bytes32 executionRef = escrow.RELEASE_EXECUTION_REF();

        vm.expectEmit(address(escrow));
        emit PaymentEscrow.Released(i.paymentId);
        vm.expectEmit(address(registry));
        emit PaymentRegistry.PaymentExecuted(i.paymentId, executionRef);
        vm.prank(anyone); // anyone may trigger a release: it can only pay the signed beneficiary
        escrow.release(i.paymentId);

        assertEq(eurc.balanceOf(beneficiary), AMOUNT);
        assertEq(eurc.balanceOf(anyone), 0);
        assertEq(eurc.balanceOf(payer), TREASURY - AMOUNT);
        _assertNothingHeld();
        _assertStatus(i.paymentId, Status.EXECUTED);
        assertEq(uint256(escrow.holdOf(i.paymentId).state), uint256(PaymentEscrow.HoldState.RELEASED));
    }

    function test_Release_IsStillPossibleAtExpiresAt() public {
        PaymentIntent memory i = _held();
        _verify(i, VerificationResult.CONFIRMED);

        vm.warp(escrow.holdOf(i.paymentId).expiresAt);
        escrow.release(i.paymentId);

        _assertStatus(i.paymentId, Status.EXECUTED);
    }

    function test_RevertWhen_ReleaseOfAnUnknownPayment() public {
        vm.expectRevert(PaymentEscrow.PaymentNotReleasable.selector);
        escrow.release(keccak256("never deposited"));
    }

    function test_RevertWhen_ReleaseOfACommittedPaymentWithoutHold() public {
        PaymentIntent memory i = _reach(Status.CONFIRMED); // confirmed, but nothing was deposited

        vm.expectRevert(PaymentEscrow.PaymentNotReleasable.selector);
        escrow.release(i.paymentId);
    }

    function test_RevertWhen_ReleaseBeforeTheSupplierConfirmed() public {
        PaymentIntent memory i = _held();

        _expectReleaseRevert(i);
        _assertOpenHolds(AMOUNT);
    }

    function test_RevertWhen_ReleaseAfterTheSupplierDenied() public {
        PaymentIntent memory i = _held();
        _verify(i, VerificationResult.DENIED);

        _expectReleaseRevert(i);
        _assertOpenHolds(AMOUNT);
    }

    function test_RevertWhen_ReleaseOfARevokedPayment() public {
        // Scene 2b of the demo: denied, revoked, then an attacker calls release().
        PaymentIntent memory i = _held();
        _verify(i, VerificationResult.DENIED);
        _revoke(i);

        vm.expectRevert(PaymentEscrow.PaymentNotReleasable.selector);
        vm.prank(anyone);
        escrow.release(i.paymentId);

        assertEq(eurc.balanceOf(beneficiary), 0);
        _assertOpenHolds(AMOUNT);
    }

    function test_RevertWhen_ReleaseOfAPaymentRevokedAfterConfirmation() public {
        PaymentIntent memory i = _held();
        _verify(i, VerificationResult.CONFIRMED);
        _revoke(i);

        _expectReleaseRevert(i);
        _assertOpenHolds(AMOUNT);
    }

    function test_RevertWhen_ReleaseOfAFrozenHold() public {
        PaymentIntent memory i = _held();
        _verify(i, VerificationResult.CONFIRMED);
        vm.prank(guardian);
        escrow.freeze(i.paymentId);

        _expectReleaseRevert(i);
        _assertOpenHolds(AMOUNT);
        _assertStatus(i.paymentId, Status.CONFIRMED);
    }

    function test_RevertWhen_ReleaseAfterExpiry() public {
        PaymentIntent memory i = _held();
        _verify(i, VerificationResult.CONFIRMED);

        vm.warp(uint256(escrow.holdOf(i.paymentId).expiresAt) + 1);

        _expectReleaseRevert(i);
        _assertOpenHolds(AMOUNT);
    }

    function test_RevertWhen_ReleaseWhileTheCorridorIsPaused() public {
        PaymentIntent memory i = _held();
        _verify(i, VerificationResult.CONFIRMED);

        vm.prank(guardian);
        escrow.pauseCorridor(CORRIDOR);
        _expectReleaseRevert(i);
        _assertOpenHolds(AMOUNT);

        // Once the admin unpauses the corridor, the same release goes through.
        vm.prank(admin);
        escrow.unpauseCorridor(CORRIDOR);
        escrow.release(i.paymentId);
        _assertStatus(i.paymentId, Status.EXECUTED);
    }

    function test_Release_IsNotBlockedByAnotherCorridorsPause() public {
        PaymentIntent memory i = _held();
        _verify(i, VerificationResult.CONFIRMED);
        vm.prank(guardian);
        escrow.pauseCorridor(keccak256("NG-GH"));

        escrow.release(i.paymentId);

        _assertStatus(i.paymentId, Status.EXECUTED);
    }

    function test_RevertWhen_ReleaseTwice() public {
        PaymentIntent memory i = _held();
        _verify(i, VerificationResult.CONFIRMED);
        escrow.release(i.paymentId);

        _expectReleaseRevert(i);
        assertEq(eurc.balanceOf(beneficiary), AMOUNT, "paid once");
    }

    function test_RevertWhen_ReleaseAfterRefund() public {
        PaymentIntent memory i = _held();
        _verify(i, VerificationResult.CONFIRMED);
        vm.prank(analystSigner);
        escrow.refund(i.paymentId);

        // The registry still says CONFIRMED, but the hold is settled.
        _assertStatus(i.paymentId, Status.CONFIRMED);
        _expectReleaseRevert(i);
        assertEq(eurc.balanceOf(beneficiary), 0);
    }

    function test_RevertWhen_ReleaseAfterTheRelayerMarkedThePaymentExecuted() public {
        // An executor closes the payment in the registry without going through the escrow: the money can then
        // only go back to the payer.
        PaymentIntent memory i = _held();
        _verify(i, VerificationResult.CONFIRMED);
        vm.prank(relayer);
        registry.markExecuted(i.paymentId, EXECUTION_REF);

        _expectReleaseRevert(i);

        skip(HOLD_SECONDS + 1);
        escrow.refund(i.paymentId);
        assertEq(eurc.balanceOf(payer), TREASURY);
    }

    function test_RevertWhen_ReleaseButTheEscrowIsNotAnExecutor() public {
        PaymentIntent memory i = _held();
        _verify(i, VerificationResult.CONFIRMED);
        bytes32 executorRole = registry.EXECUTOR_ROLE();
        vm.prank(admin);
        registry.revokeRole(executorRole, address(escrow));

        // The whole release reverts, payout included: the money stays in the hold.
        vm.expectRevert(
            abi.encodeWithSelector(
                IAccessControl.AccessControlUnauthorizedAccount.selector, address(escrow), executorRole
            )
        );
        escrow.release(i.paymentId);

        assertEq(eurc.balanceOf(beneficiary), 0);
        _assertOpenHolds(AMOUNT);
    }

    // =================================================================== refund

    function test_Refund_ByAnyoneOnceThePaymentIsRevoked() public {
        PaymentIntent memory i = _held();
        _verify(i, VerificationResult.DENIED);
        _revoke(i);

        vm.expectEmit(address(escrow));
        emit PaymentEscrow.Refunded(i.paymentId, false);
        vm.prank(anyone);
        escrow.refund(i.paymentId);

        assertEq(eurc.balanceOf(payer), TREASURY, "the payer has everything back");
        assertEq(eurc.balanceOf(anyone), 0);
        assertEq(eurc.balanceOf(beneficiary), 0);
        _assertNothingHeld();
        _assertStatus(i.paymentId, Status.REVOKED);
        assertEq(uint256(escrow.holdOf(i.paymentId).state), uint256(PaymentEscrow.HoldState.REFUNDED));
    }

    function test_Refund_ByAnyoneOnceTheHoldHasExpired() public {
        PaymentIntent memory i = _held();
        uint256 expiresAt = escrow.holdOf(i.paymentId).expiresAt;

        // At `expiresAt` the hold is not expired yet.
        vm.warp(expiresAt);
        vm.expectRevert(PaymentEscrow.NotRefundable.selector);
        vm.prank(anyone);
        escrow.refund(i.paymentId);

        vm.warp(expiresAt + 1);
        vm.expectEmit(address(escrow));
        emit PaymentEscrow.Refunded(i.paymentId, true);
        vm.prank(anyone);
        escrow.refund(i.paymentId);

        assertEq(eurc.balanceOf(payer), TREASURY);
        _assertNothingHeld();
        _assertStatus(i.paymentId, Status.COMMITTED);
    }

    function test_Refund_AfterExpiryEvenIfTheSupplierConfirmed() public {
        PaymentIntent memory i = _held();
        _verify(i, VerificationResult.CONFIRMED);
        skip(HOLD_SECONDS + 1);

        vm.prank(anyone);
        escrow.refund(i.paymentId);

        assertEq(eurc.balanceOf(payer), TREASURY);
        assertEq(eurc.balanceOf(beneficiary), 0);
    }

    function test_Refund_ByAnAnalystAtAnyTime() public {
        Status[3] memory during = [Status.COMMITTED, Status.CONFIRMED, Status.DENIED];
        for (uint256 k = 0; k < during.length; ++k) {
            PaymentIntent memory i = _held();
            if (during[k] == Status.CONFIRMED) _verify(i, VerificationResult.CONFIRMED);
            if (during[k] == Status.DENIED) _verify(i, VerificationResult.DENIED);

            vm.expectEmit(address(escrow));
            emit PaymentEscrow.Refunded(i.paymentId, false);
            vm.prank(analystSigner);
            escrow.refund(i.paymentId);

            _assertStatus(i.paymentId, during[k]);
        }
        assertEq(eurc.balanceOf(payer), TREASURY);
        _assertNothingHeld();
    }

    function test_RevertWhen_RefundByTheWrongCallerWhileThePaymentIsOpen() public {
        Status[3] memory during = [Status.COMMITTED, Status.CONFIRMED, Status.DENIED];
        address[5] memory callers = [anyone, payer, relayer, guardian, admin];
        for (uint256 k = 0; k < during.length; ++k) {
            PaymentIntent memory i = _held();
            if (during[k] == Status.CONFIRMED) _verify(i, VerificationResult.CONFIRMED);
            if (during[k] == Status.DENIED) _verify(i, VerificationResult.DENIED);

            for (uint256 c = 0; c < callers.length; ++c) {
                vm.expectRevert(PaymentEscrow.NotRefundable.selector);
                vm.prank(callers[c]);
                escrow.refund(i.paymentId);
            }
        }
        _assertOpenHolds(3 * AMOUNT);
    }

    function test_RevertWhen_RefundOfAnUnknownPayment() public {
        vm.expectRevert(PaymentEscrow.UnknownPayment.selector);
        escrow.refund(keccak256("never deposited"));

        // Committed, even revoked, but never deposited: there is nothing to refund.
        PaymentIntent memory i = _reach(Status.REVOKED);
        vm.expectRevert(PaymentEscrow.UnknownPayment.selector);
        vm.prank(analystSigner);
        escrow.refund(i.paymentId);
    }

    function test_RevertWhen_RefundTwice() public {
        PaymentIntent memory i = _held();
        _revoke(i);
        escrow.refund(i.paymentId);

        vm.expectRevert(PaymentEscrow.AlreadySettled.selector);
        escrow.refund(i.paymentId);

        // Not for an analyst either, and not after expiry.
        skip(HOLD_SECONDS + 1);
        vm.expectRevert(PaymentEscrow.AlreadySettled.selector);
        vm.prank(analystSigner);
        escrow.refund(i.paymentId);

        assertEq(eurc.balanceOf(payer), TREASURY, "refunded once");
    }

    function test_RevertWhen_RefundAfterRelease() public {
        PaymentIntent memory i = _held();
        _verify(i, VerificationResult.CONFIRMED);
        escrow.release(i.paymentId);

        vm.expectRevert(PaymentEscrow.AlreadySettled.selector);
        vm.prank(analystSigner);
        escrow.refund(i.paymentId);

        skip(HOLD_SECONDS + 1);
        vm.expectRevert(PaymentEscrow.AlreadySettled.selector);
        escrow.refund(i.paymentId);

        assertEq(eurc.balanceOf(beneficiary), AMOUNT);
        assertEq(eurc.balanceOf(payer), TREASURY - AMOUNT);
    }

    function test_Refund_OfAFrozenHoldFollowsTheNormalRules() public {
        PaymentIntent memory i = _held();
        vm.prank(guardian);
        escrow.freeze(i.paymentId);

        // Frozen is not refundable by itself...
        vm.expectRevert(PaymentEscrow.NotRefundable.selector);
        vm.prank(anyone);
        escrow.refund(i.paymentId);

        // ...but a frozen hold is never stuck: revocation (or expiry, or an analyst) sends it back.
        _revoke(i);
        vm.prank(anyone);
        escrow.refund(i.paymentId);
        assertEq(eurc.balanceOf(payer), TREASURY);
    }

    function test_Refund_IsNotBlockedByACorridorPause() public {
        PaymentIntent memory i = _held();
        vm.prank(guardian);
        escrow.pauseCorridor(CORRIDOR);
        _revoke(i);

        vm.prank(anyone);
        escrow.refund(i.paymentId);

        assertEq(eurc.balanceOf(payer), TREASURY);
    }

    // =================================================================== freeze, pause, settings

    function test_Freeze_ByAnAnalystOrTheGuardian() public {
        address[2] memory callers = [analystSigner, guardian];
        for (uint256 k = 0; k < callers.length; ++k) {
            PaymentIntent memory i = _held();

            vm.expectEmit(address(escrow));
            emit PaymentEscrow.Frozen(i.paymentId, callers[k]);
            vm.prank(callers[k]);
            escrow.freeze(i.paymentId);

            assertTrue(escrow.holdOf(i.paymentId).frozen);
            assertEq(uint256(escrow.holdOf(i.paymentId).state), uint256(PaymentEscrow.HoldState.HELD));
        }
        _assertOpenHolds(2 * AMOUNT);
    }

    function test_Freeze_CanBeRepeated() public {
        PaymentIntent memory i = _held();
        vm.prank(guardian);
        escrow.freeze(i.paymentId);

        vm.prank(analystSigner);
        escrow.freeze(i.paymentId);

        assertTrue(escrow.holdOf(i.paymentId).frozen);
    }

    function test_RevertWhen_FreezeByAnyoneElse() public {
        PaymentIntent memory i = _held();
        bytes32 guardianRole = escrow.GUARDIAN_ROLE();
        address[4] memory callers = [anyone, admin, relayer, payer];

        for (uint256 k = 0; k < callers.length; ++k) {
            vm.expectRevert(
                abi.encodeWithSelector(
                    IAccessControl.AccessControlUnauthorizedAccount.selector, callers[k], guardianRole
                )
            );
            vm.prank(callers[k]);
            escrow.freeze(i.paymentId);
        }
        assertFalse(escrow.holdOf(i.paymentId).frozen);
    }

    function test_RevertWhen_FreezeOfAnUnknownPayment() public {
        vm.expectRevert(PaymentEscrow.UnknownPayment.selector);
        vm.prank(guardian);
        escrow.freeze(keccak256("never deposited"));
    }

    function test_RevertWhen_FreezeOfASettledHold() public {
        PaymentIntent memory released = _held();
        _verify(released, VerificationResult.CONFIRMED);
        escrow.release(released.paymentId);

        PaymentIntent memory refunded = _held();
        vm.prank(analystSigner);
        escrow.refund(refunded.paymentId);

        vm.expectRevert(PaymentEscrow.AlreadySettled.selector);
        vm.prank(guardian);
        escrow.freeze(released.paymentId);

        vm.expectRevert(PaymentEscrow.AlreadySettled.selector);
        vm.prank(analystSigner);
        escrow.freeze(refunded.paymentId);
    }

    function test_PauseCorridor_OnlyTheGuardian() public {
        bytes32 guardianRole = escrow.GUARDIAN_ROLE();
        address[3] memory callers = [anyone, admin, analystSigner];
        for (uint256 k = 0; k < callers.length; ++k) {
            vm.expectRevert(
                abi.encodeWithSelector(
                    IAccessControl.AccessControlUnauthorizedAccount.selector, callers[k], guardianRole
                )
            );
            vm.prank(callers[k]);
            escrow.pauseCorridor(CORRIDOR);
        }
        assertFalse(escrow.corridorPaused(CORRIDOR));

        vm.expectEmit(address(escrow));
        emit PaymentEscrow.CorridorPaused(CORRIDOR, guardian);
        vm.prank(guardian);
        escrow.pauseCorridor(CORRIDOR);

        assertTrue(escrow.corridorPaused(CORRIDOR));
    }

    function test_UnpauseCorridor_OnlyTheAdmin() public {
        vm.prank(guardian);
        escrow.pauseCorridor(CORRIDOR);
        bytes32 adminRole = escrow.DEFAULT_ADMIN_ROLE();

        // The guardian can stop a corridor but cannot restart it.
        address[2] memory callers = [guardian, anyone];
        for (uint256 k = 0; k < callers.length; ++k) {
            vm.expectRevert(
                abi.encodeWithSelector(IAccessControl.AccessControlUnauthorizedAccount.selector, callers[k], adminRole)
            );
            vm.prank(callers[k]);
            escrow.unpauseCorridor(CORRIDOR);
        }
        assertTrue(escrow.corridorPaused(CORRIDOR));

        vm.expectEmit(address(escrow));
        emit PaymentEscrow.CorridorUnpaused(CORRIDOR, admin);
        vm.prank(admin);
        escrow.unpauseCorridor(CORRIDOR);

        assertFalse(escrow.corridorPaused(CORRIDOR));
    }

    function test_SetHoldSeconds_OnlyTheAdminAndOnlyForNewHolds() public {
        PaymentIntent memory before = _held();
        uint64 expiryBefore = escrow.holdOf(before.paymentId).expiresAt;
        bytes32 adminRole = escrow.DEFAULT_ADMIN_ROLE();

        vm.expectRevert(
            abi.encodeWithSelector(IAccessControl.AccessControlUnauthorizedAccount.selector, guardian, adminRole)
        );
        vm.prank(guardian);
        escrow.setHoldSeconds(1 hours);

        vm.expectEmit(address(escrow));
        emit PaymentEscrow.HoldSecondsSet(HOLD_SECONDS, 1 hours);
        vm.prank(admin);
        escrow.setHoldSeconds(1 hours);
        assertEq(escrow.holdSeconds(), 1 hours);

        PaymentIntent memory afterChange = _held();
        assertEq(escrow.holdOf(afterChange.paymentId).expiresAt, _now() + 1 hours, "new holds use the new lifetime");
        assertEq(escrow.holdOf(before.paymentId).expiresAt, expiryBefore, "existing holds keep their expiry");
    }

    // =================================================================== funds

    function test_EscrowBalance_EqualsTheSumOfOpenHolds() public {
        uint256[5] memory amounts = [uint256(85_000e6), 12_500e6, 1, 999_999e6, 40_000e6];
        PaymentIntent[5] memory p;
        uint256 open;

        for (uint256 k = 0; k < amounts.length; ++k) {
            p[k] = _intent(_freshRef(), Tier.MEDIUM);
            p[k].amount = amounts[k];
            _commit(p[k]);
            _deposit(p[k]);
            open += amounts[k];
            _assertOpenHolds(open);
        }

        // 0: confirmed and released to the beneficiary
        _verify(p[0], VerificationResult.CONFIRMED);
        escrow.release(p[0].paymentId);
        open -= amounts[0];
        _assertOpenHolds(open);

        // 1: denied, revoked and refunded by anyone
        _verify(p[1], VerificationResult.DENIED);
        _revoke(p[1]);
        vm.prank(anyone);
        escrow.refund(p[1].paymentId);
        open -= amounts[1];
        _assertOpenHolds(open);

        // 2: refunded early by an analyst
        vm.prank(analystSigner);
        escrow.refund(p[2].paymentId);
        open -= amounts[2];
        _assertOpenHolds(open);

        // 3: frozen. A frozen hold is still held.
        vm.prank(guardian);
        escrow.freeze(p[3].paymentId);
        _assertOpenHolds(open);

        // 3 and 4: nobody confirms, the holds expire and anyone sends the money back
        skip(HOLD_SECONDS + 1);
        vm.startPrank(anyone);
        escrow.refund(p[3].paymentId);
        open -= amounts[3];
        _assertOpenHolds(open);
        escrow.refund(p[4].paymentId);
        vm.stopPrank();
        open -= amounts[4];

        assertEq(open, 0);
        _assertNothingHeld();
        // Every unit went to the beneficiary fixed by an intent or back to the payer.
        assertEq(eurc.balanceOf(beneficiary), amounts[0]);
        assertEq(eurc.balanceOf(payer), TREASURY - amounts[0]);
        assertEq(eurc.balanceOf(anyone), 0);
    }

    function testFuzz_EscrowBalance_EqualsTheSumOfOpenHolds(uint96[4] memory amounts, uint8 fates) public {
        PaymentIntent[4] memory p;
        uint256 open;
        uint256 paid;

        for (uint256 k = 0; k < 4; ++k) {
            uint256 amount = bound(amounts[k], 0, TREASURY / 4);
            p[k] = _intent(_freshRef(), Tier.MEDIUM);
            p[k].amount = amount;
            _commit(p[k]);
            _deposit(p[k]);
            open += amount;
        }
        _assertOpenHolds(open);

        // Two bits per payment decide its fate: 0 stays held, 1 released, 2 revoked and refunded, 3 refunded early.
        for (uint256 k = 0; k < 4; ++k) {
            uint256 fate = (fates >> (2 * k)) & 3;
            if (fate == 1) {
                _verify(p[k], VerificationResult.CONFIRMED);
                escrow.release(p[k].paymentId);
                paid += p[k].amount;
            } else if (fate == 2) {
                _revoke(p[k]);
                escrow.refund(p[k].paymentId);
            } else if (fate == 3) {
                vm.prank(analystSigner);
                escrow.refund(p[k].paymentId);
            }
            if (fate != 0) open -= p[k].amount;
            _assertOpenHolds(open);
        }

        assertEq(eurc.balanceOf(beneficiary), paid);
        assertEq(eurc.balanceOf(payer), TREASURY - paid - open);
    }

    // =================================================================== reentrancy

    function test_RevertWhen_TheTokenReentersTheEscrowDuringAPayout() public {
        (ReentrantTokenMock hostile, PaymentIntent memory i) = _heldWithHostileToken();
        _verify(i, VerificationResult.CONFIRMED);

        bytes[2] memory attacks =
            [abi.encodeCall(PaymentEscrow.release, (i.paymentId)), abi.encodeCall(PaymentEscrow.refund, (i.paymentId))];
        for (uint256 k = 0; k < attacks.length; ++k) {
            hostile.arm(address(escrow), attacks[k], false);

            vm.expectRevert(ReentrancyGuard.ReentrancyGuardReentrantCall.selector);
            escrow.release(i.paymentId);

            assertEq(uint256(escrow.holdOf(i.paymentId).state), uint256(PaymentEscrow.HoldState.HELD));
            _assertStatus(i.paymentId, Status.CONFIRMED);
        }
    }

    function test_Reentrancy_CannotPayAHoldTwice() public {
        (ReentrantTokenMock hostile, PaymentIntent memory i) = _heldWithHostileToken();
        _verify(i, VerificationResult.CONFIRMED);
        // The token hides the failure of its inner call, so the outer release completes.
        hostile.arm(address(escrow), abi.encodeCall(PaymentEscrow.release, (i.paymentId)), true);

        escrow.release(i.paymentId);

        assertFalse(hostile.lastAttackSucceeded(), "the reentrant call was refused");
        assertEq(hostile.payouts(), 1, "one payout only");
        assertEq(uint256(escrow.holdOf(i.paymentId).state), uint256(PaymentEscrow.HoldState.RELEASED));
        _assertStatus(i.paymentId, Status.EXECUTED);
    }

    // =================================================================== helpers

    function _deposit(PaymentIntent memory i) internal {
        vm.prank(relayer);
        escrow.deposit(i, payer);
    }

    /// @dev A committed MEDIUM payment of EUR 85,000 whose amount sits in the escrow.
    function _held() internal returns (PaymentIntent memory i) {
        i = _committed(Tier.MEDIUM);
        _deposit(i);
    }

    function _heldWithHostileToken() internal returns (ReentrantTokenMock hostile, PaymentIntent memory i) {
        hostile = new ReentrantTokenMock();
        i = _intent(_freshRef(), Tier.MEDIUM);
        i.token = address(hostile);
        _commit(i);
        _deposit(i);
    }

    function _expectDepositRevert(PaymentIntent memory i, bytes4 errorSelector) internal {
        vm.expectRevert(errorSelector);
        vm.prank(relayer);
        escrow.deposit(i, payer);
    }

    function _expectReleaseRevert(PaymentIntent memory i) internal {
        vm.expectRevert(PaymentEscrow.PaymentNotReleasable.selector);
        escrow.release(i.paymentId);
    }

    /// @dev PRD invariant 1: the escrow's token balance equals the sum of the open holds.
    function _assertOpenHolds(uint256 expected) internal view {
        assertEq(eurc.balanceOf(address(escrow)), expected, "escrow balance");
        assertEq(escrow.totalHeld(address(eurc)), expected, "totalHeld");
    }

    function _assertNothingHeld() internal view {
        _assertOpenHolds(0);
    }
}

/// @notice The system exactly as `script/Deploy.s.sol` deploys it, with the public dev keys (the Anvil
/// mnemonic: local and mock use only). It checks the role wiring of the script, then replays the seven steps of
/// the chain conformance suite (`sylo_spec/conformance/chain.py`, build spec section 4.7) that the Python
/// MockChain passes in v0 and FujiChain must pass in v1.
contract DeployedSystemTest is SyloFixture {
    string internal constant DEV_MNEMONIC = "test test test test test test test test test test test junk";

    // Index of each role in the dev mnemonic (build spec section 4.7).
    uint32 internal constant DEPLOYER = 0;
    uint32 internal constant RELAYER = 1;
    uint32 internal constant ROUTER_SIGNER = 2;
    uint32 internal constant VERIFIER_SIGNER = 3;
    uint32 internal constant ANALYST_SIGNER = 4;
    uint32 internal constant GUARDIAN = 5;
    uint32 internal constant EU_CASP = 6;
    uint32 internal constant GH_VASP = 7;
    uint32 internal constant ATTACKER = 8;

    Deploy internal script;
    MockEURC internal eurc;
    PaymentEscrow internal escrow;

    address internal guardian;
    address internal euCasp;
    address internal attacker;
    uint256 internal attackerPk;

    function setUp() public {
        vm.warp(START);

        routerPk = vm.deriveKey(DEV_MNEMONIC, ROUTER_SIGNER);
        verifierPk = vm.deriveKey(DEV_MNEMONIC, VERIFIER_SIGNER);
        analystPk = vm.deriveKey(DEV_MNEMONIC, ANALYST_SIGNER);
        attackerPk = vm.deriveKey(DEV_MNEMONIC, ATTACKER);

        admin = _devAddress(DEPLOYER);
        relayer = _devAddress(RELAYER);
        routerSigner = vm.addr(routerPk);
        verifierSigner = vm.addr(verifierPk);
        analystSigner = vm.addr(analystPk);
        guardian = _devAddress(GUARDIAN);
        euCasp = _devAddress(EU_CASP);
        beneficiary = _devAddress(GH_VASP);
        attacker = vm.addr(attackerPk);
        outsider = attacker;

        script = new Deploy();
        Deploy.Deployment memory d = script.deploy(
            Deploy.Config({
                deployerPk: vm.deriveKey(DEV_MNEMONIC, DEPLOYER),
                relayer: relayer,
                routerSigner: routerSigner,
                verifierSigner: verifierSigner,
                analystSigner: analystSigner,
                guardian: guardian,
                euCasp: euCasp
            })
        );
        registry = d.registry;
        escrow = d.escrow;
        eurc = d.token;
        token = address(eurc);
        assertEq(d.deployer, admin);

        // The EU CASP approves the escrow with its own key (a separate script in v1).
        vm.prank(euCasp);
        eurc.approve(address(escrow), type(uint256).max);
    }

    // ------------------------------------------------------------------ what the script must set up

    function test_Deploy_UsesTheWellKnownDevAccounts() public view {
        assertEq(admin, 0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266, "account 0 of the dev mnemonic");
        assertEq(beneficiary, 0x14dC79964da2C08b23698B3D3cc7Ca32193d9955, "account 7 of the dev mnemonic");
    }

    function test_Deploy_WiresTheThreeContracts() public view {
        assertEq(address(escrow.registry()), address(registry));
        assertEq(escrow.holdSeconds(), 86_400);
        assertEq(script.HOLD_SECONDS(), 86_400);

        assertEq(eurc.name(), "Sylo Test Euro");
        assertEq(eurc.symbol(), "tEURC");
        assertEq(eurc.decimals(), 6);
        assertEq(eurc.owner(), admin);
        assertEq(eurc.balanceOf(euCasp), 10_000_000e6, "10,000,000 tEURC for the EU CASP");
        assertEq(eurc.totalSupply(), 10_000_000e6);
        assertEq(script.TREASURY_MINT(), 10_000_000e6);
    }

    function test_Deploy_GrantsTheRegistryRoles() public view {
        assertTrue(registry.hasRole(registry.DEFAULT_ADMIN_ROLE(), admin));
        assertTrue(registry.hasRole(registry.ROUTER_SIGNER_ROLE(), routerSigner));
        assertTrue(registry.hasRole(registry.VERIFIER_SIGNER_ROLE(), verifierSigner));
        assertTrue(registry.hasRole(registry.ANALYST_SIGNER_ROLE(), analystSigner));
        assertTrue(registry.hasRole(registry.EXECUTOR_ROLE(), address(escrow)));
        assertTrue(registry.hasRole(registry.EXECUTOR_ROLE(), relayer));
    }

    function test_Deploy_GrantsTheEscrowRoles() public view {
        assertTrue(escrow.hasRole(escrow.DEFAULT_ADMIN_ROLE(), admin));
        assertTrue(escrow.hasRole(escrow.ROUTER_ROLE(), relayer));
        assertTrue(escrow.hasRole(escrow.ANALYST_ROLE(), analystSigner));
        assertTrue(escrow.hasRole(escrow.GUARDIAN_ROLE(), guardian));
    }

    function test_Deploy_GrantsNothingElse() public view {
        // The script contract itself keeps no power.
        assertFalse(registry.hasRole(registry.DEFAULT_ADMIN_ROLE(), address(script)));
        assertFalse(escrow.hasRole(escrow.DEFAULT_ADMIN_ROLE(), address(script)));

        // Signing roles are separate, and the relayer signs nothing.
        assertFalse(registry.hasRole(registry.ROUTER_SIGNER_ROLE(), relayer));
        assertFalse(registry.hasRole(registry.VERIFIER_SIGNER_ROLE(), routerSigner));
        assertFalse(registry.hasRole(registry.ANALYST_SIGNER_ROLE(), verifierSigner));
        assertFalse(registry.hasRole(registry.ROUTER_SIGNER_ROLE(), analystSigner));
        assertFalse(registry.hasRole(registry.EXECUTOR_ROLE(), admin));

        assertFalse(escrow.hasRole(escrow.ROUTER_ROLE(), admin));
        assertFalse(escrow.hasRole(escrow.ANALYST_ROLE(), relayer));
        assertFalse(escrow.hasRole(escrow.GUARDIAN_ROLE(), analystSigner));

        address[2] memory strangers = [attacker, euCasp];
        for (uint256 k = 0; k < strangers.length; ++k) {
            assertFalse(registry.hasRole(registry.ROUTER_SIGNER_ROLE(), strangers[k]));
            assertFalse(registry.hasRole(registry.VERIFIER_SIGNER_ROLE(), strangers[k]));
            assertFalse(registry.hasRole(registry.ANALYST_SIGNER_ROLE(), strangers[k]));
            assertFalse(registry.hasRole(registry.EXECUTOR_ROLE(), strangers[k]));
            assertFalse(escrow.hasRole(escrow.ROUTER_ROLE(), strangers[k]));
            assertFalse(escrow.hasRole(escrow.ANALYST_ROLE(), strangers[k]));
            assertFalse(escrow.hasRole(escrow.GUARDIAN_ROLE(), strangers[k]));
        }
    }

    // ------------------------------------------------------------------ the seven chain conformance steps

    /// Step 1. Commit signed by the router key -> COMMITTED. Committing the same payment again -> InvalidTransition.
    function test_Conformance_1_Commit() public {
        PaymentIntent memory i = _intent("CONF-s1", Tier.MEDIUM);
        bytes memory sig = _signIntent(routerPk, i);
        _assertStatus(i.paymentId, Status.NONE);

        registry.commit(i, sig);

        _assertStatus(i.paymentId, Status.COMMITTED);
        assertEq(registry.intentOf(i.paymentId), registry.digestOf(i), "intent hash is the EIP-712 digest");

        vm.expectRevert(PaymentRegistry.InvalidTransition.selector);
        registry.commit(i, sig);
    }

    /// Step 2. Commit signed by a non-router key -> UnauthorizedSigner.
    function test_Conformance_2_UnauthorizedSigner() public {
        PaymentIntent memory i = _intent("CONF-s2", Tier.LOW);
        bytes memory sig = _signIntent(attackerPk, i);

        vm.expectRevert(PaymentRegistry.UnauthorizedSigner.selector);
        registry.commit(i, sig);

        _assertStatus(i.paymentId, Status.NONE);
    }

    /// Step 3. Reusing a nonce for the same signer -> NonceUsed.
    function test_Conformance_3_NonceReuse() public {
        PaymentIntent memory first = _intent("CONF-s3a", Tier.LOW);
        _commit(first);

        PaymentIntent memory second = _intent("CONF-s3b", Tier.LOW);
        second.nonce = first.nonce;
        bytes memory sig = _signIntent(routerPk, second);

        vm.expectRevert(PaymentRegistry.NonceUsed.selector);
        registry.commit(second, sig);

        _assertStatus(second.paymentId, Status.NONE);
    }

    /// Step 4. Deposit with another amount -> CommitmentMismatch. Deposit of a committed LOW intent -> TierNotEscrowable.
    function test_Conformance_4_DepositGuards() public {
        PaymentIntent memory medium = _intent("CONF-s4a", Tier.MEDIUM);
        _commit(medium);
        medium.amount += 1;
        vm.expectRevert(PaymentEscrow.CommitmentMismatch.selector);
        vm.prank(relayer);
        escrow.deposit(medium, euCasp);

        PaymentIntent memory low = _intent("CONF-s4b", Tier.LOW);
        _commit(low);
        vm.expectRevert(PaymentEscrow.TierNotEscrowable.selector);
        vm.prank(relayer);
        escrow.deposit(low, euCasp);
    }

    /// Step 5. MEDIUM: commit, deposit, DENIED, revoke -> release reverts, refund works once.
    function test_Conformance_5_DenyRevokeRefund() public {
        PaymentIntent memory i = _intent("CONF-s5", Tier.MEDIUM);
        _commit(i);
        vm.prank(relayer);
        escrow.deposit(i, euCasp);
        assertEq(eurc.balanceOf(address(escrow)), AMOUNT);

        _verify(i, VerificationResult.DENIED);
        _assertStatus(i.paymentId, Status.DENIED);
        _revoke(i);
        _assertStatus(i.paymentId, Status.REVOKED);

        vm.expectRevert(PaymentEscrow.PaymentNotReleasable.selector);
        vm.prank(attacker);
        escrow.release(i.paymentId);

        vm.prank(relayer);
        escrow.refund(i.paymentId);
        assertEq(eurc.balanceOf(euCasp), 10_000_000e6, "the treasury has everything back");

        vm.expectRevert(PaymentEscrow.AlreadySettled.selector);
        vm.prank(relayer);
        escrow.refund(i.paymentId);

        _assertStatus(i.paymentId, Status.REVOKED);
    }

    /// Step 6. MEDIUM: commit, deposit, CONFIRMED -> release succeeds -> EXECUTED.
    function test_Conformance_6_ConfirmRelease() public {
        PaymentIntent memory i = _intent("CONF-s6", Tier.MEDIUM);
        _commit(i);
        vm.prank(relayer);
        escrow.deposit(i, euCasp);
        _verify(i, VerificationResult.CONFIRMED);
        _assertStatus(i.paymentId, Status.CONFIRMED);

        vm.prank(relayer);
        escrow.release(i.paymentId);

        _assertStatus(i.paymentId, Status.EXECUTED);
        assertEq(eurc.balanceOf(beneficiary), AMOUNT, "the GH VASP was paid");
        assertEq(eurc.balanceOf(address(escrow)), 0);
    }

    /// Step 7. LOW: commit -> markExecuted -> EXECUTED.
    function test_Conformance_7_LowExecuted() public {
        PaymentIntent memory i = _intent("CONF-s7", Tier.LOW);
        _commit(i);

        vm.prank(relayer);
        registry.markExecuted(i.paymentId, keccak256("execution s7"));

        _assertStatus(i.paymentId, Status.EXECUTED);
    }

    function _devAddress(uint32 index) internal pure returns (address) {
        return vm.addr(vm.deriveKey(DEV_MNEMONIC, index));
    }
}
