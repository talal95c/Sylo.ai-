// SPDX-License-Identifier: MIT
pragma solidity ^0.8.28;

import {PaymentEscrow} from "../src/PaymentEscrow.sol";
import {PaymentIntent, Status, Tier} from "../src/SyloTypes.sol";
import {EscrowHandler} from "./EscrowHandler.sol";
import {SyloTestBase} from "./SyloTestBase.sol";

/// @dev Handler-based invariant tests for PRD §13.3 invariants 1–6 (7, reentrancy, is in Reentrancy.t.sol).
/// The handler predicts every call's outcome from the rules; `mismatches` counts disagreements.
contract EscrowInvariantsTest is SyloTestBase {
    EscrowHandler internal handler;
    address internal beneficiaryB = makeAddr("beneficiaryB");

    function setUp() public override {
        super.setUp();
        handler = new EscrowHandler(
            registry,
            escrow,
            token,
            EscrowHandler.Actors({
                admin: admin,
                relayer: relayer,
                guardian: guardian,
                analyst: analystSigner,
                payer: payer,
                attacker: attacker,
                beneficiaryA: beneficiary,
                beneficiaryB: beneficiaryB,
                routerKey: routerKey,
                verifierKey: verifierKey,
                analystKey: analystKey
            })
        );

        bytes4[] memory selectors = new bytes4[](14);
        selectors[13] = EscrowHandler.commitDepositVerify.selector;
        selectors[0] = EscrowHandler.commit.selector;
        selectors[1] = EscrowHandler.replayRouterNonce.selector;
        selectors[2] = EscrowHandler.deposit.selector;
        selectors[3] = EscrowHandler.depositTampered.selector;
        selectors[4] = EscrowHandler.verify.selector;
        selectors[5] = EscrowHandler.revoke.selector;
        selectors[6] = EscrowHandler.markExecuted.selector;
        selectors[7] = EscrowHandler.release.selector;
        selectors[8] = EscrowHandler.refund.selector;
        selectors[9] = EscrowHandler.freeze.selector;
        selectors[10] = EscrowHandler.pauseCorridor.selector;
        selectors[11] = EscrowHandler.unpauseCorridor.selector;
        selectors[12] = EscrowHandler.warp.selector;
        targetSelector(FuzzSelector({addr: address(handler), selectors: selectors}));
        targetContract(address(handler));
    }

    /// 1. The escrow's token balance always equals the sum of its open holds.
    function invariant_1_escrowBalanceEqualsOpenHolds() public view {
        assertEq(token.balanceOf(address(escrow)), escrow.totalHeld(address(token)), "balance != totalHeld");
        assertEq(escrow.totalHeld(address(token)), handler.ghostOpenHeld(), "totalHeld != open holds");
    }

    /// 2. Money only ever moves between the payer, the escrow and intent beneficiaries.
    function invariant_2_fundsOnlyGoToPayerOrBeneficiary() public view {
        uint256 accounted = token.balanceOf(payer) + token.balanceOf(address(escrow)) + token.balanceOf(beneficiary)
            + token.balanceOf(beneficiaryB);
        assertEq(accounted, token.totalSupply(), "tokens left the payer/escrow/beneficiary set");
        assertEq(token.balanceOf(attacker), 0, "the attacker received tokens");
    }

    /// 3–6. Every call behaved as the rules predict: tampered deposits revert CommitmentMismatch; release only
    /// when CONFIRMED and not frozen, expired or paused; anyone may refund after revoke or expiry; one deposit
    /// per payment; a nonce is used once.
    function invariant_3to6_contractsFollowTheRules() public view {
        assertEq(handler.mismatches(), 0, handler.lastMismatch());
    }

    /// Every hold mirrors its committed intent, and only MEDIUM payments are held.
    function invariant_holdsMirrorTheCommittedIntent() public view {
        for (uint256 k = 0; k < handler.count(); k++) {
            PaymentIntent memory i = handler.intentAt(k);
            PaymentEscrow.Hold memory h = escrow.holdOf(i.paymentId);
            if (h.expiresAt == 0) continue;
            assertEq(i.tier, uint8(Tier.MEDIUM), "a non-MEDIUM payment is held");
            assertEq(h.beneficiary, i.beneficiary, "hold beneficiary");
            assertEq(h.amount, i.amount, "hold amount");
            assertEq(h.token, i.token, "hold token");
            assertEq(h.payer, payer, "hold payer");
        }
    }

    /// REVOKED and EXECUTED are final.
    function invariant_finalStatusesNeverChange() public view {
        for (uint256 k = 0; k < handler.count(); k++) {
            bytes32 id = handler.intentAt(k).paymentId;
            Status recorded = handler.finalStatus(id);
            if (recorded != Status.NONE) {
                assertEq(uint8(registry.statusOf(id)), uint8(recorded), "final status changed");
            }
        }
    }
}
