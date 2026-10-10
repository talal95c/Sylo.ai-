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
/// @notice Holds the settlement token of MEDIUM payments until the registry says what must happen (Mode A, public
/// token).
///
/// The money of a hold can leave in two ways only:
///   - `release`: to the beneficiary fixed in the signed intent, and only while the registry status is CONFIRMED;
///   - `refund`: back to the payer it was pulled from.
/// No role, including the admin, can send it anywhere else.
///
/// A hold is expired when `block.timestamp > expiresAt`. Freezing a hold or pausing its corridor blocks `release`
/// only: a refund stays possible under its own rules, so held money can always go back to the payer.
///
/// Fee-on-transfer and rebasing tokens are not supported: a hold records the amount of the intent.
contract PaymentEscrow is AccessControl, ReentrancyGuard {
    using SafeERC20 for IERC20;

    enum HoldState {
        NONE, // no deposit was ever made for this payment
        HELD, // the escrow holds the money
        RELEASED, // settled: paid to the beneficiary
        REFUNDED // settled: returned to the payer
    }

    /// @notice One deposit. `payer`, `beneficiary`, `token` and `amount` never change after the deposit.
    struct Hold {
        address payer; // where a refund goes
        uint64 expiresAt; // deposit time + holdSeconds
        HoldState state;
        bool frozen;
        address beneficiary; // where a release goes: the beneficiary of the committed intent
        address token;
        uint256 amount;
        bytes32 corridorId;
    }

    /// @notice The relayer allowed to deposit.
    bytes32 public constant ROUTER_ROLE = keccak256("ROUTER_ROLE");
    /// @notice Analysts: may refund a hold at any time and freeze it.
    bytes32 public constant ANALYST_ROLE = keccak256("ANALYST_ROLE");
    /// @notice The on-chain guardian: may freeze a hold and pause a corridor.
    bytes32 public constant GUARDIAN_ROLE = keccak256("GUARDIAN_ROLE");

    /// @notice `executionRef` that the escrow passes to `PaymentRegistry.markExecuted` when it releases a hold.
    bytes32 public constant RELEASE_EXECUTION_REF = keccak256("SYLO_ESCROW_RELEASE");

    /// @notice The registry whose status decides what can happen to a hold.
    PaymentRegistry public immutable registry;

    /// @notice Lifetime of a new hold, in seconds. After it, anyone can refund the payer.
    uint64 public holdSeconds;

    /// @notice True while releases of a corridor are paused.
    mapping(bytes32 corridorId => bool paused) public corridorPaused;

    /// @notice Sum of the amounts of the open holds of a token. The escrow's balance of the token is never below it.
    mapping(address token => uint256 amount) public totalHeld;

    mapping(bytes32 paymentId => Hold) private _holds;

    event Deposited(
        bytes32 indexed paymentId,
        address payer,
        address beneficiary,
        uint256 amount,
        uint64 expiresAt,
        bytes32 intentHash
    );
    event Released(bytes32 indexed paymentId);
    event Refunded(bytes32 indexed paymentId, bool expired);
    event Frozen(bytes32 indexed paymentId, address by);
    event CorridorPaused(bytes32 indexed corridorId, address by);
    event CorridorUnpaused(bytes32 indexed corridorId, address by);
    event HoldSecondsSet(uint64 previousHoldSeconds, uint64 newHoldSeconds);

    /// @notice The registry status of the payment is not COMMITTED, so nothing can be deposited for it.
    error InvalidTransition();
    /// @notice The intent passed to `deposit` is not the one committed in the registry.
    error CommitmentMismatch();
    /// @notice Only MEDIUM intents use the escrow.
    error TierNotEscrowable();
    /// @notice One deposit per payment.
    error AlreadyDeposited();
    /// @notice `release` needs an open, unfrozen, unexpired hold on an unpaused corridor and a CONFIRMED payment.
    error PaymentNotReleasable();
    /// @notice The hold was already released or refunded.
    error AlreadySettled();
    /// @notice The caller is not an analyst, and the payment is neither REVOKED nor expired.
    error NotRefundable();
    /// @notice No deposit was ever made for this payment.
    error UnknownPayment();

    /// @param registry_ The PaymentRegistry. This escrow needs `EXECUTOR_ROLE` on it, otherwise `release` reverts.
    /// @param admin Receives `DEFAULT_ADMIN_ROLE`: grants roles, unpauses corridors, sets `holdSeconds`.
    /// @param holdSeconds_ Lifetime of a hold in seconds (86,400 in the PoC).
    constructor(PaymentRegistry registry_, address admin, uint64 holdSeconds_) {
        registry = registry_;
        holdSeconds = holdSeconds_;
        _grantRole(DEFAULT_ADMIN_ROLE, admin);
    }

    // -----------------------------------------------------------------------------------------
    // Money in
    // -----------------------------------------------------------------------------------------

    /// @notice Pulls the intent's amount from `payer` (who approved this escrow) and holds it.
    /// @dev Checks, in order: registry status COMMITTED, intent equals the committed one, tier MEDIUM, no hold yet.
    function deposit(PaymentIntent calldata i, address payer) external nonReentrant onlyRole(ROUTER_ROLE) {
        if (registry.statusOf(i.paymentId) != Status.COMMITTED) revert InvalidTransition();
        bytes32 intentHash = registry.intentOf(i.paymentId);
        if (registry.digestOf(i) != intentHash) revert CommitmentMismatch();
        if (i.tier != uint8(Tier.MEDIUM)) revert TierNotEscrowable();

        Hold storage h = _holds[i.paymentId];
        if (h.state != HoldState.NONE) revert AlreadyDeposited();

        uint64 expiresAt = SafeCast.toUint64(block.timestamp + holdSeconds);
        h.payer = payer;
        h.expiresAt = expiresAt;
        h.state = HoldState.HELD;
        h.beneficiary = i.beneficiary;
        h.token = i.token;
        h.amount = i.amount;
        h.corridorId = i.corridorId;
        totalHeld[i.token] += i.amount;

        emit Deposited(i.paymentId, payer, i.beneficiary, i.amount, expiresAt, intentHash);

        // `payer` is not the caller by design: the relayer (ROUTER_ROLE) moves what the payer approved for this
        // escrow, and only into a hold that can pay the signed beneficiary or refund this same payer.
        // forge-lint: disable-next-line(arbitrary-send-erc20)
        IERC20(i.token).safeTransferFrom(payer, address(this), i.amount);
    }

    // -----------------------------------------------------------------------------------------
    // Money out
    // -----------------------------------------------------------------------------------------

    /// @notice Pays the beneficiary of the committed intent. Anyone may call it.
    /// @dev Reverts with `PaymentNotReleasable` unless the hold is open, not frozen, not expired, its corridor is
    /// not paused and the registry status is CONFIRMED. Marks the payment EXECUTED in the registry.
    function release(bytes32 paymentId) external nonReentrant {
        Hold storage h = _holds[paymentId];
        if (
            h.state != HoldState.HELD || h.frozen || _isExpired(h) || corridorPaused[h.corridorId]
                || registry.statusOf(paymentId) != Status.CONFIRMED
        ) revert PaymentNotReleasable();

        h.state = HoldState.RELEASED;
        totalHeld[h.token] -= h.amount;

        emit Released(paymentId);

        IERC20(h.token).safeTransfer(h.beneficiary, h.amount);
        registry.markExecuted(paymentId, RELEASE_EXECUTION_REF);
    }

    /// @notice Returns the money to the payer. An analyst may do it at any time; anyone may do it once the payment
    /// is REVOKED in the registry or the hold has expired.
    /// @dev `expired` in the event says whether the hold had expired when it was refunded.
    function refund(bytes32 paymentId) external nonReentrant {
        Hold storage h = _holds[paymentId];
        if (h.state == HoldState.NONE) revert UnknownPayment();
        if (h.state != HoldState.HELD) revert AlreadySettled();

        bool expired = _isExpired(h);
        if (!expired && !hasRole(ANALYST_ROLE, _msgSender()) && registry.statusOf(paymentId) != Status.REVOKED) {
            revert NotRefundable();
        }

        h.state = HoldState.REFUNDED;
        totalHeld[h.token] -= h.amount;

        emit Refunded(paymentId, expired);

        IERC20(h.token).safeTransfer(h.payer, h.amount);
    }

    // -----------------------------------------------------------------------------------------
    // Controls
    // -----------------------------------------------------------------------------------------

    /// @notice Blocks the release of one hold for good. An analyst or the guardian may call it.
    /// @dev There is no unfreeze: a frozen hold can only be refunded.
    function freeze(bytes32 paymentId) external {
        if (!hasRole(ANALYST_ROLE, _msgSender())) _checkRole(GUARDIAN_ROLE);

        Hold storage h = _holds[paymentId];
        if (h.state == HoldState.NONE) revert UnknownPayment();
        if (h.state != HoldState.HELD) revert AlreadySettled();

        h.frozen = true;

        emit Frozen(paymentId, _msgSender());
    }

    /// @notice Blocks every release of a corridor until the admin unpauses it.
    function pauseCorridor(bytes32 corridorId) external onlyRole(GUARDIAN_ROLE) {
        corridorPaused[corridorId] = true;
        emit CorridorPaused(corridorId, _msgSender());
    }

    /// @notice Allows releases of a corridor again.
    function unpauseCorridor(bytes32 corridorId) external onlyRole(DEFAULT_ADMIN_ROLE) {
        corridorPaused[corridorId] = false;
        emit CorridorUnpaused(corridorId, _msgSender());
    }

    /// @notice Sets the lifetime of future holds. Existing holds keep their expiry.
    function setHoldSeconds(uint64 newHoldSeconds) external onlyRole(DEFAULT_ADMIN_ROLE) {
        emit HoldSecondsSet(holdSeconds, newHoldSeconds);
        holdSeconds = newHoldSeconds;
    }

    // -----------------------------------------------------------------------------------------
    // Views
    // -----------------------------------------------------------------------------------------

    /// @notice The hold of a payment (`state` is NONE if nothing was ever deposited).
    function holdOf(bytes32 paymentId) external view returns (Hold memory) {
        return _holds[paymentId];
    }

    // -----------------------------------------------------------------------------------------
    // Internals
    // -----------------------------------------------------------------------------------------

    /// @dev A hold is expired strictly after `expiresAt` (at `expiresAt` itself it can still be released).
    function _isExpired(Hold storage h) private view returns (bool) {
        // A hold lasts hours: the few seconds a validator can shift a timestamp do not matter.
        // forge-lint: disable-next-line(block-timestamp)
        return block.timestamp > h.expiresAt;
    }
}
