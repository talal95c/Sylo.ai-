// Deploys the eERC converter stack on Fuji (prod verifiers + BabyJubJub + Registrar +
// EncryptedERC{isConverter:true, decimals:2}), registers auditor / EU CASP / GH VASP and sets
// the auditor key. Idempotent: reruns reuse deployments/43113.json and skip done steps.
// Then run src/roles.mjs to hand EncryptedERC ownership from the deployer to the admin wallet.
import fs from "node:fs";
import { ethers } from "ethers";
import {
	ART,
	CHAIN_ID,
	DEPLOYMENTS_FILE,
	EERC_DECIMALS,
	MOCK_EURC,
	addrLink,
	artifact,
	contracts,
	deriveIdentity,
	linkBytecode,
	loadDeployments,
	prove,
	provider,
	registrationInput,
	shutdownProver,
	txLink,
	wallet,
} from "./lib.mjs";

const p = provider();
const deployer = wallet("deployer", p);
const deployerAddr = await deployer.getAddress();

async function deploy(name, args = [], libs = {}) {
	const art = artifact(ART[name]);
	const f = new ethers.ContractFactory(art.abi, linkBytecode(art, libs), deployer);
	const c = await f.deploy(...args);
	const rcpt = await c.deploymentTransaction().wait();
	const address = await c.getAddress();
	console.log(`  ${name.padEnd(20)} ${address}  ${txLink(rcpt.hash)}`);
	return { address, tx: rcpt.hash, block: rcpt.blockNumber };
}

let d = loadDeployments();
if (!d) {
	console.log("Deploying eERC converter stack (deployer = owner)...");
	const out = {};
	for (const v of ["RegistrationVerifier", "MintVerifier", "WithdrawVerifier", "TransferVerifier", "BurnVerifier"])
		out[v] = await deploy(v);
	out.BabyJubJub = await deploy("BabyJubJub");
	out.Registrar = await deploy("Registrar", [out.RegistrationVerifier.address]);
	out.EncryptedERC = await deploy(
		"EncryptedERC",
		[
			{
				registrar: out.Registrar.address,
				isConverter: true,
				name: "",
				symbol: "",
				decimals: EERC_DECIMALS,
				mintVerifier: out.MintVerifier.address,
				withdrawVerifier: out.WithdrawVerifier.address,
				transferVerifier: out.TransferVerifier.address,
				burnVerifier: out.BurnVerifier.address,
			},
		],
		{ "contracts/libraries/BabyJubJub.sol:BabyJubJub": out.BabyJubJub.address },
	);
	d = {
		chainId: Number(CHAIN_ID),
		source: "ava-labs/EncryptedERC@8dc98cd (contracts/prod verifiers, circom/build circuits)",
		mode: "converter",
		eercDecimals: EERC_DECIMALS,
		underlying: MOCK_EURC,
		owner: deployerAddr,
		startBlock: out.RegistrationVerifier.block,
		contracts: Object.fromEntries(Object.entries(out).map(([k, v]) => [k, v.address])),
		deployTxs: Object.fromEntries(Object.entries(out).map(([k, v]) => [k, v.tx])),
		registered: {},
	};
	fs.writeFileSync(DEPLOYMENTS_FILE, `${JSON.stringify(d, null, 2)}\n`);
}

const { registrar, eerc } = contracts(deployer);
const roles = { auditor: wallet("auditor", p), euCasp: wallet("euCasp", p), ghVasp: wallet("ghVasp", p) };

for (const [role, w] of Object.entries(roles)) {
	const id = await deriveIdentity(w);
	if (await registrar.isUserRegistered(id.address)) {
		const pk = (await registrar.getUserPublicKey(id.address)).map(BigInt);
		if (pk[0] !== id.publicKey[0] || pk[1] !== id.publicKey[1])
			throw new Error(`${role} registered with a different key`);
		console.log(`  ${role.padEnd(8)} already registered (${id.address})`);
		continue;
	}
	const proof = await prove("registration", registrationInput(id), { verify: true });
	const tx = await registrar.connect(w).register(proof);
	await tx.wait();
	d.registered[role] = { address: id.address, publicKey: id.publicKey.map(String), tx: tx.hash };
	console.log(`  ${role.padEnd(8)} registered ${id.address}  ${txLink(tx.hash)}`);
}

if (!(await eerc.isAuditorKeySet())) {
	const auditorAddr = await roles.auditor.getAddress();
	const tx = await eerc.setAuditorPublicKey(auditorAddr);
	await tx.wait();
	d.auditor = { address: auditorAddr, setTx: tx.hash, note: "dedicated auditor wallet (compliance function in production)" };
	console.log(`  auditor key set -> ${auditorAddr}  ${txLink(tx.hash)}`);
}

fs.writeFileSync(DEPLOYMENTS_FILE, `${JSON.stringify(d, null, 2)}\n`);
console.log(`EncryptedERC: ${addrLink(d.contracts.EncryptedERC)}`);
await shutdownProver();
