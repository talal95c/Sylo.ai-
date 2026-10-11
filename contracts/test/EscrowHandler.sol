// SPDX-License-Identifier: MIT
pragma solidity ^0.8.28;

import {CommonBase} from "forge-std/Base.sol";
import {StdUtils} from "forge-std/StdUtils.sol";

import {MockEURC} from "../src/MockEURC.sol";
import {PaymentEscrow} from "../src/PaymentEscrow.sol";
import {PaymentRegistry} from "../src/PaymentRegistry.sol";
import {
    PaymentIntent,
    Revocation,
    RevocationReason,
    Status,
    Tier,
    VerificationAttestation,
    VerificationMethod,
    VerificationResult
} from "../src/SyloTypes.sol";

/// @dev Drives random sequences of registry and escrow calls for the invariant tests. Before each call it
/// predicts the outcome from the PRD rules; any call whose outcome differs is counted in `mismatches`.
contract EscrowHandler is CommonBase, StdUtils {
    struct Actors {
        address admin;
        address relayer;
        address guardian;
        address analyst;
        address payer;
        address attacker;
        address beneficiaryA;
        address beneficiaryB;
        uint256 routerKey;
        uint256 verifierKey;
        uint256 analystKey;
    }

    PaymentRegistry public immutable REGISTRY;
    PaymentEscrow public immutable ESCROW;
    MockEURC public immutable TOKEN;
    Actors internal a;
    bytes32[2] internal corridors = [keccak256("FR-GH"), keccak256("NG-GH")];

    PaymentIntent[] internal intents;
    uint256[] internal usedRouterNonces;
    mapping(bytes32 paymentId => Status) public finalStatus;
    mapping(string action => uint256) public calls;

    uint256 public ghostOpenHeld;
    uint256 public mismatches;
    string public lastMismatch;
    uint256 private _seq;

    constructor(PaymentRegistry registry, PaymentEscrow escrow, MockEURC token, Actors memory actors) {
        REGISTRY = registry;
        ESCROW = escrow;
        TOKEN = token;
        a = actors;
    }

    // --- actions -------------------------------------------------------------------------------

    function commit(uint256 tierSeed, uint256 amountSeed, uint256 beneficiarySeed, uint256 corridorSeed) external {
        // Rarer than the other actions, so each payment stays in _pick's window long enough to be settled.
        if (intents.length > 0 && corridorSeed % 3 != 0) return;
        PaymentIntent memory i = _newIntent(tierSeed, amountSeed, beneficiarySeed, corridorSeed);
        try REGISTRY.commit(i, _sign(a.routerKey, REGISTRY.digestOf(i))) {
            intents.push(i);
            usedRouterNonces.push(i.nonce);
            calls["commit"]++;
        } catch {
            _mismatch("commit of a fresh signed intent reverted");
        }
    }

    /// Commit, deposit and verify a MEDIUM payment in one step, so that releasable holds exist often
    /// enough for release, freeze, pause and expiry to be exercised against them.
    function commitDepositVerify(uint256 amountSeed, uint256 beneficiarySeed, uint256 corridorSeed, bool confirm)
        external
    {
        PaymentIntent memory i = _newIntent(0, amountSeed, beneficiarySeed, corridorSeed);
        try REGISTRY.commit(i, _sign(a.routerKey, REGISTRY.digestOf(i))) {
            intents.push(i);
            usedRouterNonces.push(i.nonce);
        } catch {
            return _mismatch("commit of a fresh signed intent reverted");
        }
        _deposit(i);
        _verify(i, confirm);
        calls["commitDepositVerify"]++;
    }

    function replayRouterNonce(uint256 nonceSeed) external {
        if (usedRouterNonces.length == 0) return;
        PaymentIntent memory i = _newIntent(1, 1, 0, 0);
        i.nonce = usedRouterNonces[nonceSeed % usedRouterNonces.length];
        try REGISTRY.commit(i, _sign(a.routerKey, REGISTRY.digestOf(i))) {
            _mismatch("a router nonce was used twice");
        } catch (bytes memory err) {
            _expectError(err, PaymentRegistry.NonceUsed.selector, "nonce reuse: wrong error");
        }
        calls["replayRouterNonce"]++;
    }

    function deposit(uint256 index) external {
        (PaymentIntent memory i, bool found) = _pick(index);
        if (found) _deposit(i);
    }

    function _deposit(PaymentIntent memory i) internal {
        bool expected = REGISTRY.statusOf(i.paymentId) == Status.COMMITTED && i.tier == uint8(Tier.MEDIUM)
            && ESCROW.holdOf(i.paymentId).expiresAt == 0 && TOKEN.balanceOf(a.payer) >= i.amount;
        uint256 before = TOKEN.balanceOf(address(ESCROW));
        vm.prank(a.relayer);
        try ESCROW.deposit(i, a.payer) {
            if (!expected) return _mismatch("deposit succeeded where the rules forbid it");
            if (TOKEN.balanceOf(address(ESCROW)) != before + i.amount) _mismatch("deposit moved a wrong amount");
            ghostOpenHeld += i.amount;
            calls["deposit"]++;
        } catch {
            if (expected) _mismatch("deposit reverted where the rules allow it");
        }
    }

    function depositTampered(uint256 index, uint256 field, uint256 salt) external {
        (PaymentIntent memory i, bool found) = _pick(index);
        if (!found) return;
        _tamper(i, field % 11, salt);
        vm.prank(a.relayer);
        try ESCROW.deposit(i, a.payer) {
            _mismatch("a deposit that differs from the committed intent succeeded");
        } catch (bytes memory err) {
            _expectError(err, PaymentEscrow.CommitmentMismatch.selector, "tampered deposit: wrong error");
        }
        calls["depositTampered"]++;
    }

    function verify(uint256 index, bool confirm) external {
        (PaymentIntent memory i, bool found) = _pick(index);
        if (found) _verify(i, confirm);
    }

    function _verify(PaymentIntent memory i, bool confirm) internal {
        bool expected = REGISTRY.statusOf(i.paymentId) == Status.COMMITTED;
        VerificationAttestation memory v = VerificationAttestation({
            paymentId: i.paymentId,
            intentHash: REGISTRY.intentOf(i.paymentId),
            method: uint8(VerificationMethod.OOB_KNOWN_CONTACT),
            result: uint8(confirm ? VerificationResult.CONFIRMED : VerificationResult.DENIED),
            simSwapChecked: true,
            evidenceHash: keccak256(abi.encode("evidence", ++_seq)),
            verifiedAt: uint64(block.timestamp),
            nonce: _seq
        });
        bytes memory sig = _sign(a.verifierKey, _typed(REGISTRY.hashVerification(v)));
        try REGISTRY.recordVerification(v, sig) {
            if (!expected) return _mismatch("verification recorded outside COMMITTED");
            calls["verify"]++;
        } catch {
            if (expected) _mismatch("verification of a COMMITTED payment reverted");
        }
        _recordFinal(i.paymentId);
    }

    function revoke(uint256 index) external {
        (PaymentIntent memory i, bool found) = _pick(index);
        if (!found) return;
        Status s = REGISTRY.statusOf(i.paymentId);
        bool expected = s == Status.COMMITTED || s == Status.CONFIRMED || s == Status.DENIED;
        Revocation memory r = Revocation({
            paymentId: i.paymentId,
            reasonCode: uint8(RevocationReason.SUPPLIER_DENIED),
            caseHash: keccak256(abi.encode("case", ++_seq)),
            nonce: _seq
        });
        try REGISTRY.revoke(r, _sign(a.analystKey, _typed(REGISTRY.hashRevocation(r)))) {
            if (!expected) return _mismatch("revoke succeeded on a final payment");
            calls["revoke"]++;
        } catch {
            if (expected) _mismatch("revoke of an open payment reverted");
        }
        _recordFinal(i.paymentId);
    }

    function markExecuted(uint256 index) external {
        (PaymentIntent memory i, bool found) = _pick(index);
        if (!found) return;
        Status s = REGISTRY.statusOf(i.paymentId);
        bool expected = (s == Status.COMMITTED && i.tier == uint8(Tier.LOW)) || s == Status.CONFIRMED;
        vm.prank(a.relayer);
        try REGISTRY.markExecuted(i.paymentId, keccak256("rail")) {
            if (!expected) return _mismatch("markExecuted succeeded where the rules forbid it");
            calls["markExecuted"]++;
        } catch {
            if (expected) _mismatch("markExecuted reverted where the rules allow it");
        }
        _recordFinal(i.paymentId);
    }

    function release(uint256 index, uint256 callerSeed) external {
        (PaymentIntent memory i, bool found) = _pick(index);
        if (!found) return;
        PaymentEscrow.Hold memory h = ESCROW.holdOf(i.paymentId);
        bool expected = h.expiresAt != 0 && !h.settled && !h.frozen && block.timestamp <= h.expiresAt
            && !ESCROW.corridorPaused(h.corridorId) && REGISTRY.statusOf(i.paymentId) == Status.CONFIRMED;
        uint256 before = TOKEN.balanceOf(h.beneficiary);
        vm.prank(_caller(callerSeed));
        try ESCROW.release(i.paymentId) {
            if (!expected) return _mismatch("release succeeded where the rules forbid it");
            if (TOKEN.balanceOf(h.beneficiary) != before + h.amount) _mismatch("release paid a wrong amount");
            if (h.beneficiary != i.beneficiary) _mismatch("release paid someone other than the intent beneficiary");
            ghostOpenHeld -= h.amount;
            calls["release"]++;
        } catch {
            if (expected) _mismatch("release reverted where the rules allow it");
        }
        _recordFinal(i.paymentId);
    }

    function refund(uint256 index, uint256 callerSeed) external {
        (PaymentIntent memory i, bool found) = _pick(index);
        if (!found) return;
        PaymentEscrow.Hold memory h = ESCROW.holdOf(i.paymentId);
        address caller = _caller(callerSeed);
        bool expected = h.expiresAt != 0 && !h.settled
            && (block.timestamp > h.expiresAt
                || REGISTRY.statusOf(i.paymentId) == Status.REVOKED
                || caller == a.analyst);
        uint256 before = TOKEN.balanceOf(a.payer);
        vm.prank(caller);
        try ESCROW.refund(i.paymentId) {
            if (!expected) return _mismatch("refund succeeded where the rules forbid it");
            if (TOKEN.balanceOf(a.payer) != before + h.amount) _mismatch("refund paid a wrong amount");
            ghostOpenHeld -= h.amount;
            calls["refund"]++;
        } catch {
            if (expected) _mismatch("refund reverted where anyone may refund");
        }
    }

    function freeze(uint256 index, uint256 callerSeed) external {
        (PaymentIntent memory i, bool found) = _pick(index);
        if (!found || callerSeed % 9 >= 3) return; // rarer than the other actions, or few holds stay releasable
        address caller = [a.analyst, a.guardian, a.attacker][callerSeed % 3];
        bool expected = caller != a.attacker && ESCROW.holdOf(i.paymentId).expiresAt != 0;
        vm.prank(caller);
        try ESCROW.freeze(i.paymentId) {
            if (!expected) return _mismatch("freeze succeeded for an outsider or without a hold");
            calls["freeze"]++;
        } catch {
            if (expected) _mismatch("freeze by the analyst or guardian reverted");
        }
    }

    function pauseCorridor(uint256 corridorSeed, bool byAttacker) external {
        if (corridorSeed % 3 != 0 && !byAttacker) return; // rarer than unpause, so corridors are mostly open
        bytes32 corridor = corridors[(corridorSeed / 3) % 2];
        vm.prank(byAttacker ? a.attacker : a.guardian);
        try ESCROW.pauseCorridor(corridor) {
            if (byAttacker) return _mismatch("the attacker paused a corridor");
            calls["pauseCorridor"]++;
        } catch {
            if (!byAttacker) _mismatch("the guardian could not pause a corridor");
        }
    }

    function unpauseCorridor(uint256 corridorSeed) external {
        vm.prank(a.admin);
        ESCROW.unpauseCorridor(corridors[corridorSeed % 2]);
        calls["unpauseCorridor"]++;
    }

    /// Mostly short steps; one in sixteen may pass the 1-day hold expiry.
    function warp(uint256 secondsSeed) external {
        vm.warp(block.timestamp + bound(secondsSeed >> 4, 0, secondsSeed % 16 == 0 ? 2 days : 30 minutes));
        calls["warp"]++;
    }

    // --- views for the invariants ---------------------------------------------------------------

    function count() external view returns (uint256) {
        return intents.length;
    }

    function intentAt(uint256 index) external view returns (PaymentIntent memory) {
        return intents[index];
    }

    // --- helpers -------------------------------------------------------------------------------

    function _newIntent(uint256 tierSeed, uint256 amountSeed, uint256 beneficiarySeed, uint256 corridorSeed)
        internal
        returns (PaymentIntent memory i)
    {
        uint256 n = ++_seq;
        i.paymentId = keccak256(abi.encode("INVARIANT", n));
        i.corridorId = corridors[(corridorSeed / 3) % 2];
        i.beneficiary = beneficiarySeed % 2 == 0 ? a.beneficiaryA : a.beneficiaryB;
        i.token = address(TOKEN);
        i.amount = bound(amountSeed, 1, 50_000e6);
        i.offchainHash = keccak256(abi.encode("offchain", n));
        i.decisionHash = keccak256(abi.encode("decision", n));
        i.approvalHash = keccak256(abi.encode("approval", n));
        i.tier = tierSeed % 2 == 0 ? uint8(Tier.MEDIUM) : uint8((tierSeed >> 1) % 4);
        i.validUntil = uint64(block.timestamp + 10 minutes);
        i.nonce = n;
    }

    /// Returns a fresh memory copy of a committed intent: usually one of the last two, so that full
    /// commit -> deposit -> verify -> release sequences happen; sometimes any of them.
    function _pick(uint256 index) internal view returns (PaymentIntent memory i, bool found) {
        uint256 n = intents.length;
        if (n == 0) return (i, false);
        if (index % 4 == 0) return (intents[(index >> 2) % n], true);
        uint256 window = n < 2 ? n : 2;
        return (intents[n - 1 - (index >> 2) % window], true);
    }

    function _tamper(PaymentIntent memory i, uint256 field, uint256 salt) internal view {
        bytes32 flip = keccak256(abi.encode(salt)) | bytes32(uint256(1));
        uint256 bump = 1 + salt % 1000;
        if (field == 0) i.paymentId ^= flip;
        else if (field == 1) i.corridorId ^= flip;
        else if (field == 2) i.beneficiary = i.beneficiary == a.attacker ? a.payer : a.attacker;
        else if (field == 3) i.token = address(uint160(i.token) ^ (uint160(salt) | 1));
        else if (field == 4) i.amount += bump;
        else if (field == 5) i.offchainHash ^= flip;
        else if (field == 6) i.decisionHash ^= flip;
        else if (field == 7) i.approvalHash ^= flip;
        else if (field == 8) i.tier = uint8((i.tier + 1 + salt % 3) % 4);
        else if (field == 9) i.validUntil += uint64(bump);
        else i.nonce += bump;
    }

    function _caller(uint256 seed) internal view returns (address) {
        return [a.relayer, a.attacker, a.payer, a.guardian, a.analyst, a.beneficiaryA][seed % 6];
    }

    function _recordFinal(bytes32 paymentId) internal {
        Status s = REGISTRY.statusOf(paymentId);
        if ((s == Status.REVOKED || s == Status.EXECUTED) && finalStatus[paymentId] == Status.NONE) {
            finalStatus[paymentId] = s;
        }
    }

    function _expectError(bytes memory err, bytes4 selector, string memory message) internal {
        if (err.length < 4 || bytes4(err) != selector) _mismatch(message);
    }

    function _mismatch(string memory message) internal {
        mismatches++;
        lastMismatch = message;
    }

    function _typed(bytes32 structHash) internal view returns (bytes32) {
        return keccak256(abi.encodePacked("\x19\x01", REGISTRY.domainSeparator(), structHash));
    }

    function _sign(uint256 key, bytes32 digest) internal pure returns (bytes memory) {
        (uint8 v, bytes32 r, bytes32 s) = vm.sign(key, digest);
        return abi.encodePacked(r, s, v);
    }
}
