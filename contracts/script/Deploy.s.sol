// SPDX-License-Identifier: MIT
pragma solidity ^0.8.28;

import {Script} from "forge-std/Script.sol";

import {MockEURC} from "../src/MockEURC.sol";
import {PaymentEscrow} from "../src/PaymentEscrow.sol";
import {PaymentRegistry} from "../src/PaymentRegistry.sol";

/// @notice Deploys MockEURC, PaymentRegistry and PaymentEscrow, grants the roles, funds the EU CASP
/// treasury and writes deployments/<chainId>.json. v0 runs it on a local Anvil node only (make anvil-deploy).
/// The EU CASP's approval of the escrow is a separate transaction signed with its own key (Lane C, v1).
contract Deploy is Script {
    uint256 internal constant EU_CASP_MINT = 10_000_000e6;

    struct Roles {
        address relayer;
        address routerSigner;
        address verifierSigner;
        address analystSigner;
        address guardian;
        address euCasp;
    }

    function run() external returns (MockEURC token, PaymentRegistry registry, PaymentEscrow escrow) {
        uint256 deployerKey = vm.envUint("DEPLOYER_PK");
        address deployer = vm.addr(deployerKey);
        Roles memory roles = Roles({
            relayer: vm.envAddress("RELAYER_ADDRESS"),
            routerSigner: vm.envAddress("ROUTER_SIGNER_ADDRESS"),
            verifierSigner: vm.envAddress("VERIFIER_SIGNER_ADDRESS"),
            analystSigner: vm.envAddress("ANALYST_SIGNER_ADDRESS"),
            guardian: vm.envAddress("GUARDIAN_ADDRESS"),
            euCasp: vm.envAddress("EU_CASP_ADDRESS")
        });
        uint256 startBlock = block.number;

        vm.startBroadcast(deployerKey);
        token = new MockEURC(deployer);
        registry = new PaymentRegistry(deployer);
        escrow = new PaymentEscrow(registry, deployer, 86_400);

        registry.grantRole(registry.ROUTER_SIGNER_ROLE(), roles.routerSigner);
        registry.grantRole(registry.VERIFIER_SIGNER_ROLE(), roles.verifierSigner);
        registry.grantRole(registry.ANALYST_SIGNER_ROLE(), roles.analystSigner);
        registry.grantRole(registry.EXECUTOR_ROLE(), address(escrow));
        registry.grantRole(registry.EXECUTOR_ROLE(), roles.relayer);
        escrow.grantRole(escrow.ROUTER_ROLE(), roles.relayer);
        escrow.grantRole(escrow.ANALYST_ROLE(), roles.analystSigner);
        escrow.grantRole(escrow.GUARDIAN_ROLE(), roles.guardian);

        token.mint(roles.euCasp, EU_CASP_MINT);
        vm.stopBroadcast();

        _write(token, registry, escrow, startBlock);
    }

    /// `startBlock` is the chain height before the first deployment: scan events from there.
    function _write(MockEURC token, PaymentRegistry registry, PaymentEscrow escrow, uint256 startBlock) private {
        string memory key = "deployment";
        vm.serializeUint(key, "chainId", block.chainid);
        vm.serializeUint(key, "startBlock", startBlock);
        vm.serializeAddress(key, "token", address(token));
        vm.serializeAddress(key, "registry", address(registry));
        string memory json = vm.serializeAddress(key, "escrow", address(escrow));
        vm.writeJson(json, string.concat(vm.projectRoot(), "/deployments/", vm.toString(block.chainid), ".json"));
    }
}
