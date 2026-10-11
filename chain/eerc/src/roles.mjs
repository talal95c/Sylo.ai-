// Separate wallets per role (idempotent):
//   1. create AUDITOR_PK / EERC_ADMIN_PK in the repo-root .env if absent (only addresses are printed),
//   2. fund them with a little Fuji AVAX from the deployer,
//   3. register the auditor in the Registrar and point EncryptedERC's auditor key at it,
//   4. hand EncryptedERC ownership (Ownable2Step) from the deployer to the admin, admin accepts.
// The Registrar has no owner. Transfers made before the rotation stay decryptable only with the
// previous auditor key (the deployer's).
import fs from "node:fs";
import { ethers } from "ethers";
import {
	addrLink,
	contracts,
	deriveIdentity,
	envFile,
	loadDeployments,
	prove,
	provider,
	registrationInput,
	saveDeployments,
	shutdownProver,
	txLink,
	wallet,
} from "./lib.mjs";

const FUND_AVAX = ethers.parseEther(process.env.EERC_ROLE_FUND_AVAX ?? "0.02");
const DEPLOYER_FLOOR = ethers.parseEther("0.1");

function ensureKey(pkVar, addrVar) {
	if (process.env[pkVar]) return;
	const w = ethers.Wallet.createRandom();
	const file = envFile();
	const cur = fs.readFileSync(file, "utf8");
	const sep = cur.endsWith("\n") ? "" : "\n";
	fs.appendFileSync(file, `${sep}${pkVar}=${w.privateKey}\n${addrVar}=${w.address}\n`);
	process.env[pkVar] = w.privateKey;
	process.env[addrVar] = w.address;
	console.log(`  created ${addrVar}=${w.address} (key appended to .env)`);
}

ensureKey("AUDITOR_PK", "AUDITOR_ADDRESS");
ensureKey("EERC_ADMIN_PK", "EERC_ADMIN_ADDRESS");

const p = provider();
const deployer = wallet("deployer", p);
const admin = wallet("admin", p);
const auditor = wallet("auditor", p);
const deployerAddr = await deployer.getAddress();
const adminAddr = await admin.getAddress();
const auditorAddr = await auditor.getAddress();
const d = loadDeployments();
const { registrar, eerc } = contracts(p);
const fmt = (wei) => `${ethers.formatEther(wei)} AVAX`;

for (const [role, addr] of [
	["auditor", auditorAddr],
	["admin", adminAddr],
]) {
	const bal = await p.getBalance(addr);
	if (bal >= FUND_AVAX / 2n) {
		console.log(`  ${role.padEnd(8)} ${addr} has ${fmt(bal)}`);
		continue;
	}
	const depBal = await p.getBalance(deployerAddr);
	if (depBal - FUND_AVAX < DEPLOYER_FLOOR)
		throw new Error(`deployer has ${fmt(depBal)}; refusing to go below ${fmt(DEPLOYER_FLOOR)}`);
	const tx = await deployer.sendTransaction({ to: addr, value: FUND_AVAX });
	await tx.wait();
	console.log(`  funded ${role} ${addr} with ${fmt(FUND_AVAX)}  ${txLink(tx.hash)}`);
}

const prevAuditor = { ...d.auditor };
d.roles = {
	deployer: { address: deployerAddr, does: "deployed the contracts; no standing rights after the handover" },
	admin: { address: adminAddr, does: "owner of EncryptedERC (setAuditorPublicKey, setTokenBlacklist)" },
	auditor: { address: auditorAddr, does: "holds the audit decryption key; decrypts amounts only" },
	euCasp: { address: d.registered.euCasp.address, does: "payer-side institution; holds the eEURC float" },
	ghVasp: { address: d.registered.ghVasp.address, does: "payee-side institution; settles netted amounts" },
};
if (d.registered.auditor?.address === deployerAddr) {
	d.registered.legacyAuditorDeployer = d.registered.auditor;
	delete d.registered.auditor;
}

const id = await deriveIdentity(auditor);
if (await registrar.isUserRegistered(auditorAddr)) {
	const pk = (await registrar.getUserPublicKey(auditorAddr)).map(BigInt);
	if (pk[0] !== id.publicKey[0] || pk[1] !== id.publicKey[1]) throw new Error("auditor registered with a different key");
	console.log(`  auditor  already registered (${auditorAddr})`);
} else {
	const proof = await prove("registration", registrationInput(id), { verify: true });
	const tx = await registrar.connect(auditor).register(proof);
	await tx.wait();
	d.registered.auditor = { address: auditorAddr, publicKey: id.publicKey.map(String), tx: tx.hash };
	console.log(`  auditor  registered ${auditorAddr}  ${txLink(tx.hash)}`);
}

if ((await eerc.auditor()) !== auditorAddr) {
	const owner = await eerc.owner();
	if (owner !== deployerAddr) throw new Error(`EncryptedERC owner is ${owner}; run the auditor rotation as that owner`);
	const tx = await eerc.connect(deployer).setAuditorPublicKey(auditorAddr);
	await tx.wait();
	d.auditor = {
		address: auditorAddr,
		setTx: tx.hash,
		note: "dedicated auditor wallet (compliance function in production); rotatable by the admin",
		previous: [
			{
				address: prevAuditor.address,
				setTx: prevAuditor.setTx,
				note: "deployer key: transfers made before this rotation are decryptable only with it",
			},
		],
	};
	console.log(`  auditor key rotated -> ${auditorAddr}  ${txLink(tx.hash)}`);
}

let owner = await eerc.owner();
if (owner === deployerAddr) {
	if ((await eerc.pendingOwner()) !== adminAddr) {
		const tx = await eerc.connect(deployer).transferOwnership(adminAddr);
		await tx.wait();
		d.ownership = { ...d.ownership, transferTx: tx.hash };
		console.log(`  transferOwnership -> ${adminAddr}  ${txLink(tx.hash)}`);
	}
	const tx = await eerc.connect(admin).acceptOwnership();
	await tx.wait();
	d.ownership = { ...d.ownership, acceptTx: tx.hash, model: "Ownable2Step (admin accepted)" };
	console.log(`  acceptOwnership by admin  ${txLink(tx.hash)}`);
	owner = await eerc.owner();
}
if (owner !== adminAddr) throw new Error(`EncryptedERC owner is ${owner}, expected admin ${adminAddr}`);
d.owner = adminAddr;
d.ownership = { ...d.ownership, owner: adminAddr, registrar: "not ownable (no admin functions)" };

saveDeployments(d);
for (const [role, addr] of [
	["deployer", deployerAddr],
	["admin", adminAddr],
	["auditor", auditorAddr],
])
	console.log(`  ${role.padEnd(8)} ${addrLink(addr)}  ${fmt(await p.getBalance(addr))}`);
await shutdownProver();
