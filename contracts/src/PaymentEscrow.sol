// SPDX-License-Identifier: MIT
pragma solidity ^0.8.28;

import {AccessControl} from "@openzeppelin/contracts/access/AccessControl.sol";
import {IERC20} from "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import {SafeERC20} from "@openzeppelin/contracts/token/ERC20/utils/SafeERC20.sol";
import {ReentrancyGuard} from "@openzeppelin/contracts/utils/ReentrancyGuard.sol";
import {SafeCast} from "@openzeppelin/contracts/utils/math/SafeCast.sol";

import {PaymentRegistry} from "./PaymentRegistry.sol";
import {PaymentIntent, Status, Tier} from "./SyloTypes.sol";

/// @title PaymentEscrow
/// @notice Holds a MEDIUM payment on its chain hop until the supplier's known contact confirms it.
/// Money leaves only to the beneficiary fixed by the committed intent (`release`) or back to the payer
/// (`refund`); no other function moves funds.
contract PaymentEscrow is AccessControl, ReentrancyGuard {
    using SafeERC20 for IERC20;

    bytes32 public constant ROUTER_ROLE = keccak256("ROUTER_ROLE");
    bytes32 public constant ANALYST_ROLE = keccak256("ANALYST_ROLE");
    bytes32 public constant GUARDIAN_ROLE = keccak256("GUARDIAN_ROLE");
    uint64 public constant DEFAULT_HOLD_SECONDS = 86_400;

    struct Hold {
        address payer;
        address beneficiary;
        address token;
        uint256 amount;
        bytes32 corridorId;
        uint64 expiresAt;
        bool frozen;
        bool settled;
    }

    PaymentRegistry public immutable REGISTRY;
    uint64 public holdSeconds;

    mapping(bytes32 paymentId => Hold) private _holds;
    mapping(bytes32 corridorId => bool) public corridorPaused;
    /// @notice Sum of the open (unsettled) holds per token; always equal to this contract's balance.
    mapping(address token => uint256) public totalHeld;

    event Deposited(
        bytes32 indexed paymentId, address payer, address beneficiary, uint256 amount, uint64 expiresAt, bytes32 intentHash
    );
    event Released(bytes32 indexed paymentId);
    event Refunded(bytes32 indexed paymentId, bool expired);
    event Frozen(bytes32 indexed paymentId, address by);
    event CorridorPaused(bytes32 indexed corridorId, address by);
    event CorridorUnpaused(bytes32 indexed corridorId, address by);
    event HoldSecondsSet(uint64 holdSeconds);

    error CommitmentMismatch();
    error InvalidTransition();
    error TierNotEscrowable();
    error AlreadyDeposited();
    error PaymentNotReleasable();
    error NoHold();
    error AlreadySettled();
    error RefundNotAllowed();
    error InvalidHoldSeconds();

    constructor(PaymentRegistry registry, address admin, uint64 holdSeconds_) {
        REGISTRY = registry;
        _grantRole(DEFAULT_ADMIN_ROLE, admin);
        _setHoldSeconds(holdSeconds_);
    }

    /// @notice Pulls a committed MEDIUM payment from the payer (who approved this contract) into a hold.
    /// Any field that differs from the committed intent changes the digest and reverts.
    function deposit(PaymentIntent calldata i, address payer) external nonReentrant onlyRole(ROUTER_ROLE) {
        bytes32 intentHash = REGISTRY.intentOf(i.paymentId);
        if (intentHash == bytes32(0) || REGISTRY.digestOf(i) != intentHash) revert CommitmentMismatch();
        if (REGISTRY.statusOf(i.paymentId) != Status.COMMITTED) revert InvalidTransition();
        if (i.tier != uint8(Tier.MEDIUM)) revert TierNotEscrowable();
        Hold storage h = _holds[i.paymentId];
        if (h.expiresAt != 0) revert AlreadyDeposited();

        uint64 expiresAt = SafeCast.toUint64(block.timestamp) + holdSeconds;
        h.payer = payer;
        h.beneficiary = i.beneficiary;
        h.token = i.token;
        h.amount = i.amount;
        h.corridorId = i.corridorId;
        h.expiresAt = expiresAt;
        totalHeld[i.token] += i.amount;
        emit Deposited(i.paymentId, payer, i.beneficiary, i.amount, expiresAt, intentHash);

        // The payer treasury approved this contract; only the router may pull, and only for a committed intent.
        // forge-lint: disable-next-line(arbitrary-send-erc20)
        IERC20(i.token).safeTransferFrom(payer, address(this), i.amount);
    }

    /// @notice Pays the beneficiary of the intent. Anyone may call it; it only succeeds once the registry
    /// says CONFIRMED and the hold is not frozen, expired or on a paused corridor.
    function release(bytes32 paymentId) external nonReentrant {
        Hold storage h = _holds[paymentId];
        bool releasable = h.expiresAt != 0 && !h.settled && !h.frozen && block.timestamp <= h.expiresAt
            && !corridorPaused[h.corridorId] && REGISTRY.statusOf(paymentId) == Status.CONFIRMED;
        if (!releasable) revert PaymentNotReleasable();

        h.settled = true;
        totalHeld[h.token] -= h.amount;
        emit Released(paymentId);

        REGISTRY.markExecuted(paymentId, bytes32(uint256(uint160(address(this)))));
        IERC20(h.token).safeTransfer(h.beneficiary, h.amount);
    }

    /// @notice Returns the money to the payer: the analyst may do it at any time, anyone once the
    /// payment is revoked or the hold has expired.
    function refund(bytes32 paymentId) external nonReentrant {
        Hold storage h = _holds[paymentId];
        if (h.expiresAt == 0) revert NoHold();
        if (h.settled) revert AlreadySettled();
        bool expired = block.timestamp > h.expiresAt;
        if (!expired && REGISTRY.statusOf(paymentId) != Status.REVOKED && !hasRole(ANALYST_ROLE, msg.sender)) {
            revert RefundNotAllowed();
        }

        h.settled = true;
        totalHeld[h.token] -= h.amount;
        emit Refunded(paymentId, expired);

        IERC20(h.token).safeTransfer(h.payer, h.amount);
    }

    function freeze(bytes32 paymentId) external {
        if (!hasRole(ANALYST_ROLE, msg.sender) && !hasRole(GUARDIAN_ROLE, msg.sender)) {
            revert AccessControlUnauthorizedAccount(msg.sender, GUARDIAN_ROLE);
        }
        Hold storage h = _holds[paymentId];
        if (h.expiresAt == 0) revert NoHold();
        h.frozen = true;
        emit Frozen(paymentId, msg.sender);
    }

    function pauseCorridor(bytes32 corridorId) external onlyRole(GUARDIAN_ROLE) {
        corridorPaused[corridorId] = true;
        emit CorridorPaused(corridorId, msg.sender);
    }

    function unpauseCorridor(bytes32 corridorId) external onlyRole(DEFAULT_ADMIN_ROLE) {
        corridorPaused[corridorId] = false;
        emit CorridorUnpaused(corridorId, msg.sender);
    }

    function setHoldSeconds(uint64 holdSeconds_) external onlyRole(DEFAULT_ADMIN_ROLE) {
        _setHoldSeconds(holdSeconds_);
    }

    function holdOf(bytes32 paymentId) external view returns (Hold memory) {
        return _holds[paymentId];
    }

    function _setHoldSeconds(uint64 holdSeconds_) private {
        if (holdSeconds_ == 0) revert InvalidHoldSeconds();
        holdSeconds = holdSeconds_;
        emit HoldSecondsSet(holdSeconds_);
    }
}
