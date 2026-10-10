// SPDX-License-Identifier: MIT
pragma solidity ^0.8.28;

import {Test} from "forge-std/Test.sol";

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

/// @dev Contracts wired like script/Deploy.s.sol, with throwaway test keys for the three signers.
abstract contract SyloTestBase is Test {
    uint256 internal constant AMOUNT = 85_000e6;
    uint256 internal constant TREASURY = 10_000_000e6;
    uint64 internal constant HOLD = 1 days;
    bytes32 internal constant CORRIDOR = keccak256("FR-GH");

    address internal admin = makeAddr("admin");
    address internal relayer = makeAddr("relayer");
    address internal guardian = makeAddr("guardian");
    address internal payer = makeAddr("euCasp");
    address internal beneficiary = makeAddr("ghVasp");
    address internal attacker = makeAddr("attacker");

    address internal routerSigner;
    uint256 internal routerKey;
    address internal verifierSigner;
    uint256 internal verifierKey;
    address internal analystSigner;
    uint256 internal analystKey;
    uint256 internal outsiderKey;

    MockEURC internal token;
    PaymentRegistry internal registry;
    PaymentEscrow internal escrow;

    uint256 private _sequence;

    function setUp() public virtual {
        (routerSigner, routerKey) = makeAddrAndKey("routerSigner");
        (verifierSigner, verifierKey) = makeAddrAndKey("verifierSigner");
        (analystSigner, analystKey) = makeAddrAndKey("analystSigner");
        (, outsiderKey) = makeAddrAndKey("outsider");

        token = new MockEURC(admin);
        registry = new PaymentRegistry(admin);
        escrow = new PaymentEscrow(registry, admin, HOLD);

        vm.startPrank(admin);
        registry.grantRole(registry.ROUTER_SIGNER_ROLE(), routerSigner);
        registry.grantRole(registry.VERIFIER_SIGNER_ROLE(), verifierSigner);
        registry.grantRole(registry.ANALYST_SIGNER_ROLE(), analystSigner);
        registry.grantRole(registry.EXECUTOR_ROLE(), address(escrow));
        registry.grantRole(registry.EXECUTOR_ROLE(), relayer);
        escrow.grantRole(escrow.ROUTER_ROLE(), relayer);
        escrow.grantRole(escrow.ANALYST_ROLE(), analystSigner);
        escrow.grantRole(escrow.GUARDIAN_ROLE(), guardian);
        token.mint(payer, TREASURY);
        vm.stopPrank();

        vm.prank(payer);
        token.approve(address(escrow), type(uint256).max);
    }

    function _next() internal returns (uint256) {
        return ++_sequence;
    }

    function _intent(Tier tier) internal returns (PaymentIntent memory i) {
        uint256 n = _next();
        i.paymentId = keccak256(abi.encodePacked("PAY-TEST-", n));
        i.corridorId = CORRIDOR;
        i.beneficiary = beneficiary;
        i.token = address(token);
        i.amount = AMOUNT;
        i.offchainHash = keccak256(abi.encodePacked("offchain", n));
        i.decisionHash = keccak256(abi.encodePacked("decision", n));
        i.approvalHash = keccak256(abi.encodePacked("approval", n));
        i.tier = uint8(tier);
        i.validUntil = uint64(block.timestamp + 10 minutes);
        i.nonce = n;
    }

    function _attestation(PaymentIntent memory i, VerificationResult result)
        internal
        returns (VerificationAttestation memory v)
    {
        uint256 n = _next();
        v.paymentId = i.paymentId;
        v.intentHash = registry.digestOf(i);
        v.method = uint8(VerificationMethod.OOB_KNOWN_CONTACT);
        v.result = uint8(result);
        v.simSwapChecked = true;
        v.evidenceHash = keccak256(abi.encodePacked("evidence", n));
        v.verifiedAt = uint64(block.timestamp);
        v.nonce = n;
    }

    function _revocation(bytes32 paymentId) internal returns (Revocation memory r) {
        uint256 n = _next();
        r.paymentId = paymentId;
        r.reasonCode = uint8(RevocationReason.SUPPLIER_DENIED);
        r.caseHash = keccak256(abi.encodePacked("case", n));
        r.nonce = n;
    }

    function _sign(uint256 key, bytes32 digest) internal pure returns (bytes memory) {
        (uint8 v, bytes32 r, bytes32 s) = vm.sign(key, digest);
        return abi.encodePacked(r, s, v);
    }

    function _typedDigest(bytes32 structHash) internal view returns (bytes32) {
        return keccak256(abi.encodePacked("\x19\x01", registry.domainSeparator(), structHash));
    }

    function _signVerification(uint256 key, VerificationAttestation memory v) internal view returns (bytes memory) {
        return _sign(key, _typedDigest(registry.hashVerification(v)));
    }

    function _signRevocation(uint256 key, Revocation memory r) internal view returns (bytes memory) {
        return _sign(key, _typedDigest(registry.hashRevocation(r)));
    }

    function _commit(PaymentIntent memory i) internal returns (bytes32 intentHash) {
        intentHash = registry.digestOf(i);
        registry.commit(i, _sign(routerKey, intentHash));
    }

    function _verify(PaymentIntent memory i, VerificationResult result) internal {
        VerificationAttestation memory v = _attestation(i, result);
        registry.recordVerification(v, _signVerification(verifierKey, v));
    }

    function _revoke(bytes32 paymentId) internal {
        Revocation memory r = _revocation(paymentId);
        registry.revoke(r, _signRevocation(analystKey, r));
    }

    function _deposit(PaymentIntent memory i) internal {
        vm.prank(relayer);
        escrow.deposit(i, payer);
    }

    /// A committed MEDIUM payment whose money sits in the escrow.
    function _held() internal returns (PaymentIntent memory i) {
        i = _intent(Tier.MEDIUM);
        _commit(i);
        _deposit(i);
    }

    function _assertStatus(bytes32 paymentId, Status expected) internal view {
        assertEq(uint8(registry.statusOf(paymentId)), uint8(expected), "registry status");
    }
}
