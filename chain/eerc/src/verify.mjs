// Verify the deployed contracts on Snowtrace (Routescan etherscan-compatible API, no key needed).
import fs from "node:fs";
import path from "node:path";
import { ethers } from "ethers";
import { ART, EERC_DECIMALS, VENDOR, artifact, loadDeployments } from "./lib.mjs";

const API = "https://api.routescan.io/v2/network/testnet/evm/43113/etherscan/api";
const d = loadDeployments();
const biDir = path.join(VENDOR, "artifacts/build-info");
const bi = JSON.parse(fs.readFileSync(path.join(biDir, fs.readdirSync(biDir)[0]), "utf8"));

const SOURCE = {
	RegistrationVerifier: "contracts/prod/RegistrationVerifier.sol",
	MintVerifier: "contracts/prod/MintVerifier.sol",
	WithdrawVerifier: "contracts/prod/WithdrawVerifier.sol",
	TransferVerifier: "contracts/prod/TransferVerifier.sol",
	BurnVerifier: "contracts/prod/BurnVerifier.sol",
	BabyJubJub: "contracts/libraries/BabyJubJub.sol",
	Registrar: "contracts/Registrar.sol",
	EncryptedERC: "contracts/EncryptedERC.sol",
};

function ctorArgs(name) {
	const iface = new ethers.Interface(artifact(ART[name]).abi);
	const c = d.contracts;
	if (name === "Registrar") return iface.encodeDeploy([c.RegistrationVerifier]).slice(2);
	if (name === "EncryptedERC")
		return iface
			.encodeDeploy([
				{
					registrar: c.Registrar,
					isConverter: true,
					name: "",
					symbol: "",
					decimals: EERC_DECIMALS,
					mintVerifier: c.MintVerifier,
					withdrawVerifier: c.WithdrawVerifier,
					transferVerifier: c.TransferVerifier,
					burnVerifier: c.BurnVerifier,
				},
			])
			.slice(2);
	return "";
}

async function post(params) {
	const r = await fetch(API, { method: "POST", body: new URLSearchParams(params) });
	return r.json();
}

for (const name of process.argv.slice(2).length ? process.argv.slice(2) : Object.keys(SOURCE)) {
	const input = structuredClone(bi.input);
	if (name === "EncryptedERC")
		input.settings.libraries = { "contracts/libraries/BabyJubJub.sol": { BabyJubJub: d.contracts.BabyJubJub } };
	const res = await post({
		module: "contract",
		action: "verifysourcecode",
		contractaddress: d.contracts[name],
		sourceCode: JSON.stringify(input),
		codeformat: "solidity-standard-json-input",
		contractname: `${SOURCE[name]}:${name}`,
		compilerversion: `v${bi.solcLongVersion}`,
		constructorArguements: ctorArgs(name),
	});
	let status = res;
	if (res.status === "1") {
		for (let i = 0; i < 10; i++) {
			await new Promise((r) => setTimeout(r, 3000));
			status = await post({ module: "contract", action: "checkverifystatus", guid: res.result });
			if (!/pending/i.test(status.result)) break;
		}
	}
	console.log(`${name.padEnd(20)} ${status.result}`);
}
