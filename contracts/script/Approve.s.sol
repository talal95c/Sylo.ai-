// SPDX-License-Identifier: MIT
pragma solidity ^0.8.28;

import {Script, console} from "forge-std/Script.sol";
import {IERC20} from "@openzeppelin/contracts/token/ERC20/IERC20.sol";

/// @notice The EU CASP treasury approves the escrow to pull tEURC for MEDIUM deposits. Signed with the
/// treasury's own key (EU_CASP_PK), never the deployer's. Reads the addresses that Deploy.s.sol wrote
/// to deployments/<chainId>.json. The allowance is the treasury's balance at the time of the call.
contract Approve is Script {
    function run() external {
        uint256 casp = vm.envUint("EU_CASP_PK");
        string memory json =
            vm.readFile(string.concat(vm.projectRoot(), "/deployments/", vm.toString(block.chainid), ".json"));
        IERC20 token = IERC20(vm.parseJsonAddress(json, ".token"));
        address escrow = vm.parseJsonAddress(json, ".escrow");
        uint256 amount = token.balanceOf(vm.addr(casp));
        require(amount > 0, "EU CASP holds no tEURC: run Deploy.s.sol first");

        vm.startBroadcast(casp);
        require(token.approve(escrow, amount), "approve failed");
        vm.stopBroadcast();

        console.log("EU CASP allowance to escrow:", token.allowance(vm.addr(casp), escrow));
    }
}
