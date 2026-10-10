// SPDX-License-Identifier: MIT
pragma solidity ^0.8.28;

import {Script, console2} from "forge-std/Script.sol";
import {VmSafe} from "forge-std/Vm.sol";

import {MockEURC} from "../src/MockEURC.sol";
import {PaymentEscrow} from "../src/PaymentEscrow.sol";
import {PaymentRegistry} from "../src/PaymentRegistry.sol";

/// @title Deploy
/// @notice Deploys MockEURC, PaymentRegistry and PaymentEscrow, grants the roles, mints the demo treasury and
/// writes `deployments/<chainId>.json`.
///
/// Local Anvil node (`make anvil-deploy`):
///   forge script script/Deploy.s.sol --rpc-url http://127.0.0.1:8545 --broadcast
/// Fuji (v1, Lane C; not run in v0):
///   forge script script/Deploy.s.sol --rpc-url fuji --broadcast --verify
///
/// Environment: DEPLOYER_PK (0x-prefixed), RELAYER_ADDRESS, ROUTER_SIGNER_ADDRESS, VERIFIER_SIGNER_ADDRESS,
/// ANALYST_SIGNER_ADDRESS, GUARDIAN_ADDRESS, EU_CASP_ADDRESS.
///
/// The deployer becomes the admin of the registry and of the escrow, and the owner of MockEURC.
/// The EU CASP must still approve the escrow with its own key (separate script, Lane C, v1).
///
/// The file is written only when the script broadcasts: a dry run (no `--broadcast`) deploys nothing, so it
/// prints the addresses it would use and leaves `deployments/` alone.
contract Deploy is Script {
    /// @notice Lifetime of an escrow hold: 24 hours.
    uint64 public constant HOLD_SECONDS = 86_400;
    /// @notice 10,000,000 tEURC (6 decimals) minted to the EU CASP treasury.
    uint256 public constant TREASURY_MINT = 10_000_000 * 10 ** 6;

    struct Config {
        uint256 deployerPk;
        address relayer;
        address routerSigner;
        address verifierSigner;
        address analystSigner;
        address guardian;
        address euCasp;
    }

    struct Deployment {
        address deployer;
        MockEURC token;
        PaymentRegistry registry;
        PaymentEscrow escrow;
        // The chain's block number when the script ran. A script cannot know in which block its transactions
        // will be mined; they are mined after this block, so reading logs from `fromBlock` misses nothing.
        uint256 fromBlock;
    }

    function run() external returns (Deployment memory d) {
        Config memory c = Config({
            deployerPk: vm.envUint("DEPLOYER_PK"),
            relayer: vm.envAddress("RELAYER_ADDRESS"),
            routerSigner: vm.envAddress("ROUTER_SIGNER_ADDRESS"),
            verifierSigner: vm.envAddress("VERIFIER_SIGNER_ADDRESS"),
            analystSigner: vm.envAddress("ANALYST_SIGNER_ADDRESS"),
            guardian: vm.envAddress("GUARDIAN_ADDRESS"),
            euCasp: vm.envAddress("EU_CASP_ADDRESS")
        });

        d = deploy(c);

        console2.log("chain id        ", block.chainid);
        console2.log("deployer (admin)", d.deployer);
        console2.log("MockEURC        ", address(d.token));
        console2.log("PaymentRegistry ", address(d.registry));
        console2.log("PaymentEscrow   ", address(d.escrow));

        string memory path = string.concat("./deployments/", vm.toString(block.chainid), ".json");
        if (vm.isContext(VmSafe.ForgeContext.ScriptBroadcast) || vm.isContext(VmSafe.ForgeContext.ScriptResume)) {
            vm.writeJson(_deploymentJson(c, d), path);
            console2.log("wrote", path);
        } else {
            console2.log("dry run: nothing was deployed and nothing was written. Add --broadcast to deploy.");
        }
    }

    /// @notice Deploys and wires the three contracts. Uses no environment variable and writes no file, so the
    /// tests can run exactly what a deployment runs.
    function deploy(Config memory c) public returns (Deployment memory d) {
        d.deployer = vm.addr(c.deployerPk);
        d.fromBlock = block.number;

        vm.startBroadcast(c.deployerPk);

        d.token = new MockEURC(d.deployer);
        d.registry = new PaymentRegistry(d.deployer);
        d.escrow = new PaymentEscrow(d.registry, d.deployer, HOLD_SECONDS);

        // Registry: who may sign what, and who may mark a payment executed.
        d.registry.grantRole(d.registry.ROUTER_SIGNER_ROLE(), c.routerSigner);
        d.registry.grantRole(d.registry.VERIFIER_SIGNER_ROLE(), c.verifierSigner);
        d.registry.grantRole(d.registry.ANALYST_SIGNER_ROLE(), c.analystSigner);
        d.registry.grantRole(d.registry.EXECUTOR_ROLE(), address(d.escrow));
        d.registry.grantRole(d.registry.EXECUTOR_ROLE(), c.relayer);

        // Escrow: who may deposit, refund early, freeze and pause.
        d.escrow.grantRole(d.escrow.ROUTER_ROLE(), c.relayer);
        d.escrow.grantRole(d.escrow.ANALYST_ROLE(), c.analystSigner);
        d.escrow.grantRole(d.escrow.GUARDIAN_ROLE(), c.guardian);

        // Demo treasury of the payer side.
        d.token.mint(c.euCasp, TREASURY_MINT);

        vm.stopBroadcast();
    }

    /// @dev Content of `deployments/<chainId>.json`: the three addresses with the block to read their logs from,
    /// and who holds which role.
    function _deploymentJson(Config memory c, Deployment memory d) internal returns (string memory) {
        string memory contractsKey = "contracts";
        vm.serializeString(contractsKey, "MockEURC", _contractJson("MockEURC", address(d.token), d.fromBlock));
        vm.serializeString(
            contractsKey, "PaymentRegistry", _contractJson("PaymentRegistry", address(d.registry), d.fromBlock)
        );
        string memory contractsJson = vm.serializeString(
            contractsKey, "PaymentEscrow", _contractJson("PaymentEscrow", address(d.escrow), d.fromBlock)
        );

        string memory rolesKey = "roles";
        vm.serializeAddress(rolesKey, "admin", d.deployer);
        vm.serializeAddress(rolesKey, "relayer", c.relayer);
        vm.serializeAddress(rolesKey, "routerSigner", c.routerSigner);
        vm.serializeAddress(rolesKey, "verifierSigner", c.verifierSigner);
        vm.serializeAddress(rolesKey, "analystSigner", c.analystSigner);
        vm.serializeAddress(rolesKey, "guardian", c.guardian);
        string memory rolesJson = vm.serializeAddress(rolesKey, "euCasp", c.euCasp);

        // `serializeString` embeds a value that is itself a JSON object as an object, not as a string.
        string memory rootKey = "deployment";
        vm.serializeUint(rootKey, "chainId", block.chainid);
        vm.serializeUint(rootKey, "holdSeconds", HOLD_SECONDS);
        vm.serializeString(rootKey, "contracts", contractsJson);
        return vm.serializeString(rootKey, "roles", rolesJson);
    }

    function _contractJson(string memory name, address deployedAt, uint256 fromBlock) internal returns (string memory) {
        vm.serializeAddress(name, "address", deployedAt);
        return vm.serializeUint(name, "fromBlock", fromBlock);
    }
}
