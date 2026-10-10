// SPDX-License-Identifier: MIT
pragma solidity ^0.8.28;

import {Ownable} from "@openzeppelin/contracts/access/Ownable.sol";
import {ERC20} from "@openzeppelin/contracts/token/ERC20/ERC20.sol";

/// @title MockEURC
/// @notice Simulated euro stablecoin for local and test networks. Not Circle's EURC.
contract MockEURC is ERC20, Ownable {
    constructor(address owner_) ERC20("Sylo Test Euro", "tEURC") Ownable(owner_) {}

    function decimals() public pure override returns (uint8) {
        return 6;
    }

    function mint(address to, uint256 amount) external onlyOwner {
        _mint(to, amount);
    }
}
