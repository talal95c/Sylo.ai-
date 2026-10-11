// Offline sanity check: prod verifier constants == circom/build verification keys, and
// snarkjs proofs from the vendored circuits verify locally. No transaction is sent.
import fs from "node:fs";
import path from "node:path";
import { ethers } from "ethers";
import {
	VENDOR,
	deriveIdentity,
	prove,
	registrationInput,
	shutdownProver,
	transferInput,
	elgamalEncrypt,
} from "./lib.mjs";

const pairs = [
	["Registration", "registration"],
	["Mint", "mint"],
	["Transfer", "transfer"],
	["Withdraw", "withdraw"],
	["Burn", "burn"],
];
for (const [name, dir] of pairs) {
	const vk = JSON.parse(
		fs.readFileSync(path.join(VENDOR, `circom/build/${dir}/${dir}_verification_key.json`), "utf8"),
	);
	const sol = fs.readFileSync(path.join(VENDOR, `contracts/prod/${name}Verifier.sol`), "utf8");
	const consts = new Set(sol.match(/\b\d{20,}\b/g));
	const want = [
		...vk.vk_alpha_1.slice(0, 2),
		...vk.vk_beta_2.slice(0, 2).flat(),
		...vk.vk_gamma_2.slice(0, 2).flat(),
		...vk.vk_delta_2.slice(0, 2).flat(),
		...vk.IC.flatMap((p) => p.slice(0, 2)),
	];
	const missing = want.filter((x) => !consts.has(x)).length;
	console.log(`${name}Verifier: ${want.length} vk constants, ${missing} missing`);
	if (missing) process.exit(1);
}

const a = await deriveIdentity(ethers.Wallet.createRandom());
const b = await deriveIdentity(ethers.Wallet.createRandom());
let t = Date.now();
await prove("registration", registrationInput(a), { verify: true });
console.log(`registration proof OK (${Date.now() - t} ms)`);

const bal = 1000n;
const enc = elgamalEncrypt(a.publicKey, bal).cipher;
t = Date.now();
const { input } = transferInput(a, bal, [...enc[0], ...enc[1]], b.publicKey, b.publicKey, 250n);
await prove("transfer", input, { verify: true });
console.log(`transfer proof OK (${Date.now() - t} ms)`);
await shutdownProver();
