// SPDX-License-Identifier: MIT
pragma solidity ^0.8.28;

import {Ownable} from "@openzeppelin/contracts/access/Ownable.sol";
import {ERC20} from "@openzeppelin/contracts/token/ERC20/ERC20.sol";

/// @title MockEURC
/// @notice Test euro for the demo ("Sylo Test Euro", tEURC, 6 decimals like Circle's EURC). It has no value.
/// Only the owner can mint.
contract MockEURC is ERC20, Ownable {
    constructor(address initialOwner) ERC20("Sylo Test Euro", "tEURC") Ownable(initialOwner) {}

    function decimals() public pure override returns (uint8) {
        return 6;
    }

    /// @notice Mints `amount` units (6 decimals) to `to`.
    function mint(address to, uint256 amount) external onlyOwner {
        _mint(to, amount);
    }
}
