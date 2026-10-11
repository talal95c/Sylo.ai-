// SPDX-License-Identifier: MIT
pragma solidity ^0.8.28;

import {ERC20} from "@openzeppelin/contracts/token/ERC20/ERC20.sol";
import {ReentrancyGuard} from "@openzeppelin/contracts/utils/ReentrancyGuard.sol";

import {PaymentEscrow} from "../src/PaymentEscrow.sol";
import {PaymentIntent, Tier, VerificationResult} from "../src/SyloTypes.sol";
import {SyloTestBase} from "./SyloTestBase.sol";

/// @dev A token that calls back into the escrow during every transfer to or from it, and records how
/// the re-entrant call ended.
contract ReentrantToken is ERC20 {
    PaymentEscrow public immutable ESCROW;
    bytes32 public target;
    bool public armed;
    bytes4 public releaseError;
    bytes4 public refundError;
    uint256 public reentryAttempts;

    constructor(PaymentEscrow escrow) ERC20("Reentrant", "RE") {
        ESCROW = escrow;
    }

    function mint(address to, uint256 amount) external {
        _mint(to, amount);
    }

    function arm(bytes32 paymentId) external {
        target = paymentId;
        armed = true;
    }

    function _update(address from, address to, uint256 value) internal override {
        super._update(from, to, value);
        if (!armed || (from != address(ESCROW) && to != address(ESCROW))) return;
        armed = false;
        reentryAttempts++;
        try ESCROW.release(target) {}
        catch (bytes memory err) {
            releaseError = bytes4(err);
        }
        try ESCROW.refund(target) {}
        catch (bytes memory err) {
            refundError = bytes4(err);
        }
    }
}

/// @dev Invariant 7: release, refund and deposit cannot be re-entered, so a hostile token gets paid once.
contract ReentrancyTest is SyloTestBase {
    ReentrantToken internal evil;

    function setUp() public override {
        super.setUp();
        evil = new ReentrantToken(escrow);
        evil.mint(payer, TREASURY);
        vm.prank(payer);
        evil.approve(address(escrow), type(uint256).max);
    }

    function _evilIntent() internal returns (PaymentIntent memory i) {
        i = _intent(Tier.MEDIUM);
        i.token = address(evil);
        _commit(i);
    }

    function _assertBlocked() internal view {
        bytes4 blocked = ReentrancyGuard.ReentrancyGuardReentrantCall.selector;
        assertEq(evil.reentryAttempts(), 1, "the token did not try to re-enter");
        assertEq(evil.releaseError(), blocked, "re-entrant release not blocked by the guard");
        assertEq(evil.refundError(), blocked, "re-entrant refund not blocked by the guard");
    }

    function test_ReleaseCannotBeReentered() public {
        PaymentIntent memory i = _evilIntent();
        _deposit(i);
        _verify(i, VerificationResult.CONFIRMED);
        evil.arm(i.paymentId);

        escrow.release(i.paymentId);

        _assertBlocked();
        assertEq(evil.balanceOf(beneficiary), AMOUNT, "beneficiary paid more or less than once");
        assertEq(evil.balanceOf(address(escrow)), 0);
        assertEq(escrow.totalHeld(address(evil)), 0);
    }

    function test_RefundCannotBeReentered() public {
        PaymentIntent memory i = _evilIntent();
        _deposit(i);
        _revoke(i.paymentId);
        evil.arm(i.paymentId);

        escrow.refund(i.paymentId);

        _assertBlocked();
        assertEq(evil.balanceOf(payer), TREASURY, "payer refunded more or less than once");
        assertEq(escrow.totalHeld(address(evil)), 0);
    }

    function test_DepositCannotBeReentered() public {
        PaymentIntent memory i = _evilIntent();
        evil.arm(i.paymentId);

        _deposit(i);

        _assertBlocked();
        assertEq(evil.balanceOf(address(escrow)), AMOUNT);
        assertEq(escrow.totalHeld(address(evil)), AMOUNT);
    }
}
