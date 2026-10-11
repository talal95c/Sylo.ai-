// Shared helpers for the Sylo.ai eERC (EncryptedERC, converter mode) PoC on Fuji.
// Crypto mirrors ava-labs/EncryptedERC@8dc98cd test/helpers.ts and test/user.ts, but proofs
// are generated with snarkjs from the vendored production circuits (circom/build), so no
// circuit compilation / trusted-setup download is needed.
//
// TEST-ONLY KEYS: BabyJubJub keys are derived from the institution's EVM key. Synthetic demo.

import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import dotenv from "dotenv";
import { ethers } from "ethers";
import * as snarkjs from "snarkjs";
import * as BJJ from "@zk-kit/baby-jubjub";
import { Base8, mulPointEscalar, subOrder } from "@zk-kit/baby-jubjub";
import {
	formatPrivKeyForBabyJub,
	genRandomBabyJubValue,
	poseidonDecrypt,
	poseidonEncrypt,
} from "maci-crypto";
import { poseidon3 } from "poseidon-lite";
import { randomBytes } from "node:crypto";
import { execFileSync } from "node:child_process";

const HERE = path.dirname(fileURLToPath(import.meta.url));
export const EERC_DIR = path.resolve(HERE, "..");
export const REPO_ROOT = path.resolve(EERC_DIR, "../..");
export const VENDOR = path.join(EERC_DIR, "vendor/EncryptedERC");
export const DEPLOYMENTS_FILE = path.join(EERC_DIR, "deployments/43113.json");
export const DEMO_RUNS_FILE = path.join(EERC_DIR, "deployments/demo-runs-43113.json");
export const CHAIN_ID = 43113n;
export const EXPLORER = "https://testnet.snowtrace.io";
export const MOCK_EURC = "0xd1A86C8Fc2a693E9C81E6ddC2924179e82A407bD";
export const EERC_DECIMALS = 2;
export const TOKEN_DECIMALS = 6;

/** Repo-root .env; SYLO_ENV_FILE overrides, and a git worktree falls back to the main checkout's .env. */
export function envFile() {
	if (process.env.SYLO_ENV_FILE) return process.env.SYLO_ENV_FILE;
	const local = path.join(REPO_ROOT, ".env");
	if (fs.existsSync(local)) return local;
	try {
		const common = execFileSync("git", ["rev-parse", "--path-format=absolute", "--git-common-dir"], {
			cwd: REPO_ROOT,
			encoding: "utf8",
		}).trim();
		const main = path.join(path.dirname(common), ".env");
		if (fs.existsSync(main)) return main;
	} catch {}
	return local;
}

dotenv.config({ path: envFile(), quiet: true });

export const txLink = (hash) => `${EXPLORER}/tx/${hash}`;
export const addrLink = (a) => `${EXPLORER}/address/${a}`;

export function provider() {
	const url = process.env.FUJI_RPC_URL || process.env.FUJI_RPC_URL_2;
	if (!url) throw new Error("FUJI_RPC_URL missing in repo-root .env");
	return new ethers.JsonRpcProvider(url, Number(CHAIN_ID), { staticNetwork: true });
}

// deployer only deploys; admin owns EncryptedERC; auditor holds the audit decryption key.
export const ROLE_ENV = {
	deployer: "DEPLOYER_PK",
	admin: "EERC_ADMIN_PK",
	auditor: "AUDITOR_PK",
	euCasp: "EU_CASP_PK",
	ghVasp: "GH_VASP_PK",
};

export function wallet(role, p = provider()) {
	const pk = process.env[ROLE_ENV[role]];
	if (!pk) throw new Error(`${ROLE_ENV[role]} missing in repo-root .env`);
	return new ethers.NonceManager(new ethers.Wallet(pk, p));
}

// ---------------------------------------------------------------- keys

const KEY_MESSAGE = "Sylo.ai eERC BabyJubJub key v1 | Avalanche Fuji 43113";

/** Deterministic BabyJubJub identity: keccak256(EIP-191 sig of a fixed message) -> 253-bit key. */
export async function deriveIdentity(w) {
	const signer = w.signer ?? w;
	const sig = await signer.signMessage(KEY_MESSAGE);
	const privateKey = BigInt(ethers.keccak256(sig)) >> 3n;
	const formattedPrivateKey = formatPrivKeyForBabyJub(privateKey) % subOrder;
	const publicKey = mulPointEscalar(Base8, formattedPrivateKey).map(BigInt);
	return { address: await signer.getAddress(), privateKey, formattedPrivateKey, publicKey };
}

// ---------------------------------------------------------------- encryption

const BASE_POINT_ORDER = subOrder;

function randomNonce() {
	return BigInt(`0x${randomBytes(16).toString("hex")}`) + 1n;
}

function randomScalar() {
	let r = genRandomBabyJubValue();
	if (r >= BASE_POINT_ORDER) r = genRandomBabyJubValue() / 100n;
	return r;
}

/** Poseidon-ECDH "PCT" encryption (src/poseidon/poseidon.ts). */
export function poseidonEncryptFor(inputs, publicKey) {
	const nonce = randomNonce();
	const encRandom = randomScalar();
	const key = mulPointEscalar(publicKey, encRandom);
	const authKey = mulPointEscalar(Base8, encRandom);
	const ciphertext = poseidonEncrypt(inputs, key, nonce);
	return { ciphertext, nonce, encRandom, authKey };
}

export function pctOf(enc) {
	return [...enc.ciphertext, ...enc.authKey, enc.nonce];
}

/** Decrypt a 7-element PCT ([ciphertext(4), authKey(2), nonce]) with the raw private key. */
export function decryptPCT(privateKey, pct, length = 1) {
	const p = pct.map(BigInt);
	const shared = mulPointEscalar(p.slice(4, 6), formatPrivKeyForBabyJub(privateKey));
	return poseidonDecrypt(p.slice(0, 4), shared, p[6], length).slice(0, length);
}

/** ElGamal encryption of a scalar on BabyJubJub (src/jub/jub.ts). */
export function elgamalEncrypt(publicKey, message) {
	const random = randomScalar();
	const c1 = mulPointEscalar(Base8, random);
	const m = mulPointEscalar(Base8, message);
	const pky = mulPointEscalar(publicKey, random);
	return { cipher: [c1, BJJ.addPoint(m, pky)], random };
}

// ---------------------------------------------------------------- metadata (src/metadata.ts)

function str2int(s) {
	const hex = Buffer.from(s, "utf8").toString("hex");
	let rem = hex === "" ? 0n : BigInt(`0x${hex}`);
	const chunk = 2n ** 250n;
	if (rem === 0n) return [[0n], 1n];
	const out = [];
	while (rem > 0n) {
		out.push(rem % chunk);
		rem /= chunk;
	}
	return [out, BigInt(out.length)];
}

function int2str(chunks) {
	const chunk = 2n ** 250n;
	let v = 0n;
	for (let i = chunks.length - 1; i >= 0; i--) v = v * chunk + BigInt(chunks[i]);
	if (v === 0n) return "";
	let hex = v.toString(16);
	if (hex.length % 2) hex = `0${hex}`;
	return Buffer.from(hex, "hex").toString("utf8").replace(/\u0000/g, "");
}

export function encryptMetadata(publicKey, message) {
	const [fields, length] = str2int(message);
	const enc = poseidonEncryptFor(fields, publicKey);
	const word = (x) => ethers.zeroPadValue(ethers.toBeHex(x), 32);
	return ethers.concat([
		word(length),
		word(enc.nonce),
		word(enc.authKey[0]),
		word(enc.authKey[1]),
		...enc.ciphertext.map(word),
	]);
}

export function decryptMetadata(privateKey, bytes) {
	const h = bytes.startsWith("0x") ? bytes.slice(2) : bytes;
	const w = (i) => BigInt(`0x${h.slice(i * 64, i * 64 + 64)}`);
	const length = Number(w(0));
	const nonce = w(1);
	const authKey = [w(2), w(3)];
	const ct = [];
	for (let i = 256; i < h.length; i += 64) ct.push(BigInt(`0x${h.slice(i, i + 64)}`));
	const shared = mulPointEscalar(authKey, formatPrivKeyForBabyJub(privateKey));
	return int2str(poseidonDecrypt(ct, shared, nonce, length).slice(0, length));
}

// ---------------------------------------------------------------- proofs

const CIRCUITS = {
	registration: "circom/build/registration/circuit_final.zkey",
	transfer: "circom/build/transfer/transfer.zkey",
	withdraw: "circom/build/withdraw/circuit_final.zkey",
};

const stringify = (v) =>
	Array.isArray(v) ? v.map(stringify) : typeof v === "bigint" ? v.toString() : String(v);

/** groth16 proof with the vendored production circuit, formatted for the Solidity verifier. */
export async function prove(circuit, input, { verify = false } = {}) {
	const wasm = path.join(VENDOR, `circom/build/${circuit}/${circuit}.wasm`);
	const zkey = path.join(VENDOR, CIRCUITS[circuit]);
	const inputs = Object.fromEntries(Object.entries(input).map(([k, v]) => [k, stringify(v)]));
	const { proof, publicSignals } = await snarkjs.groth16.fullProve(inputs, wasm, zkey);
	if (verify) {
		const vk = JSON.parse(
			fs.readFileSync(
				path.join(VENDOR, `circom/build/${circuit}/${circuit}_verification_key.json`),
				"utf8",
			),
		);
		if (!(await snarkjs.groth16.verify(vk, publicSignals, proof)))
			throw new Error(`${circuit}: local proof verification failed`);
	}
	return {
		proofPoints: {
			a: [proof.pi_a[0], proof.pi_a[1]],
			b: [
				[proof.pi_b[0][1], proof.pi_b[0][0]],
				[proof.pi_b[1][1], proof.pi_b[1][0]],
			],
			c: [proof.pi_c[0], proof.pi_c[1]],
		},
		publicSignals,
	};
}

export async function shutdownProver() {
	if (globalThis.curve_bn128) await globalThis.curve_bn128.terminate();
}

export function registrationInput(id) {
	return {
		SenderPrivateKey: id.formattedPrivateKey,
		SenderPublicKey: id.publicKey,
		SenderAddress: BigInt(id.address),
		ChainID: CHAIN_ID,
		RegistrationHash: poseidon3([CHAIN_ID, id.formattedPrivateKey, BigInt(id.address)]),
	};
}

export function transferInput(sender, senderBalance, senderEGCT, receiverPub, auditorPub, amount) {
	const sVTT = elgamalEncrypt(sender.publicKey, amount);
	const rVTT = elgamalEncrypt(receiverPub, amount);
	const rPCT = poseidonEncryptFor([amount], receiverPub);
	const aPCT = poseidonEncryptFor([amount], auditorPub);
	const newBal = poseidonEncryptFor([senderBalance - amount], sender.publicKey);
	return {
		input: {
			ValueToTransfer: amount,
			SenderPrivateKey: sender.formattedPrivateKey,
			SenderPublicKey: sender.publicKey,
			SenderBalance: senderBalance,
			SenderBalanceC1: senderEGCT.slice(0, 2),
			SenderBalanceC2: senderEGCT.slice(2, 4),
			SenderVTTC1: sVTT.cipher[0],
			SenderVTTC2: sVTT.cipher[1],
			ReceiverPublicKey: receiverPub,
			ReceiverVTTC1: rVTT.cipher[0],
			ReceiverVTTC2: rVTT.cipher[1],
			ReceiverVTTRandom: rVTT.random,
			ReceiverPCT: rPCT.ciphertext,
			ReceiverPCTAuthKey: rPCT.authKey,
			ReceiverPCTNonce: rPCT.nonce,
			ReceiverPCTRandom: rPCT.encRandom,
			AuditorPublicKey: auditorPub,
			AuditorPCT: aPCT.ciphertext,
			AuditorPCTAuthKey: aPCT.authKey,
			AuditorPCTNonce: aPCT.nonce,
			AuditorPCTRandom: aPCT.encRandom,
		},
		senderBalancePCT: pctOf(newBal),
	};
}

export function withdrawInput(user, userBalance, userEGCT, auditorPub, amount) {
	const newBal = poseidonEncryptFor([userBalance - amount], user.publicKey);
	const aPCT = poseidonEncryptFor([amount], auditorPub);
	return {
		input: {
			ValueToWithdraw: amount,
			SenderPrivateKey: user.formattedPrivateKey,
			SenderPublicKey: user.publicKey,
			SenderBalance: userBalance,
			SenderBalanceC1: userEGCT.slice(0, 2),
			SenderBalanceC2: userEGCT.slice(2, 4),
			AuditorPublicKey: auditorPub,
			AuditorPCT: aPCT.ciphertext,
			AuditorPCTAuthKey: aPCT.authKey,
			AuditorPCTNonce: aPCT.nonce,
			AuditorPCTRandom: aPCT.encRandom,
		},
		userBalancePCT: pctOf(newBal),
	};
}

// ---------------------------------------------------------------- contracts

export function artifact(rel) {
	return JSON.parse(fs.readFileSync(path.join(VENDOR, "artifacts/contracts", rel), "utf8"));
}

export const ART = {
	RegistrationVerifier: "prod/RegistrationVerifier.sol/RegistrationVerifier.json",
	MintVerifier: "prod/MintVerifier.sol/MintVerifier.json",
	WithdrawVerifier: "prod/WithdrawVerifier.sol/WithdrawVerifier.json",
	TransferVerifier: "prod/TransferVerifier.sol/TransferVerifier.json",
	BurnVerifier: "prod/BurnVerifier.sol/BurnVerifier.json",
	BabyJubJub: "libraries/BabyJubJub.sol/BabyJubJub.json",
	Registrar: "Registrar.sol/Registrar.json",
	EncryptedERC: "EncryptedERC.sol/EncryptedERC.json",
};

export function linkBytecode(art, libs) {
	let bc = art.bytecode;
	for (const [file, names] of Object.entries(art.linkReferences)) {
		for (const [name, refs] of Object.entries(names)) {
			const addr = libs[`${file}:${name}`];
			if (!addr) throw new Error(`missing library ${file}:${name}`);
			for (const { start, length } of refs) {
				const s = 2 + start * 2;
				bc = bc.slice(0, s) + addr.slice(2).toLowerCase() + bc.slice(s + length * 2);
			}
		}
	}
	return bc;
}

export function loadDeployments() {
	if (!fs.existsSync(DEPLOYMENTS_FILE)) return null;
	return JSON.parse(fs.readFileSync(DEPLOYMENTS_FILE, "utf8"));
}

export function saveDeployments(d) {
	fs.writeFileSync(DEPLOYMENTS_FILE, `${JSON.stringify(d, null, 2)}\n`);
}

/** Append one record to deployments/demo-runs-43113.json (older runs are kept). */
export function appendDemoRun(record) {
	const runs = fs.existsSync(DEMO_RUNS_FILE) ? JSON.parse(fs.readFileSync(DEMO_RUNS_FILE, "utf8")) : [];
	runs.push(record);
	fs.writeFileSync(DEMO_RUNS_FILE, `${JSON.stringify(runs, null, 2)}\n`);
}

export function contracts(runner) {
	const d = loadDeployments();
	if (!d) throw new Error("not deployed: run `node src/deploy.mjs` first");
	return {
		d,
		registrar: new ethers.Contract(d.contracts.Registrar, artifact(ART.Registrar).abi, runner),
		eerc: new ethers.Contract(d.contracts.EncryptedERC, artifact(ART.EncryptedERC).abi, runner),
		token: new ethers.Contract(
			MOCK_EURC,
			[
				"function approve(address,uint256) returns (bool)",
				"function allowance(address,address) view returns (uint256)",
				"function balanceOf(address) view returns (uint256)",
			],
			runner,
		),
	};
}

/** Decrypted eERC balance = balancePCT + all amountPCTs (test/helpers.ts getDecryptedBalance). */
export function decryptedBalance(privateKey, bal) {
	let total = 0n;
	const nz = (pct) => pct.some((e) => BigInt(e) !== 0n);
	if (nz(bal.balancePCT)) total += BigInt(decryptPCT(privateKey, bal.balancePCT)[0]);
	for (const entry of bal.amountPCTs) {
		const pct = entry.pct ?? entry[0];
		if (nz(pct)) total += BigInt(decryptPCT(privateKey, pct)[0]);
	}
	// cross-check against the on-chain ElGamal ciphertext: c2 - sk*c1 == total*G
	if (total === 0n) return total;
	const sk = formatPrivKeyForBabyJub(privateKey);
	const c1 = [BigInt(bal.eGCT.c1.x ?? bal.eGCT.c1[0]), BigInt(bal.eGCT.c1.y ?? bal.eGCT.c1[1])];
	const c2 = [BigInt(bal.eGCT.c2.x ?? bal.eGCT.c2[0]), BigInt(bal.eGCT.c2.y ?? bal.eGCT.c2[1])];
	const skc1 = mulPointEscalar(c1, sk);
	const plain = BJJ.addPoint(c2, [BJJ.Fr.e(skc1[0] * -1n), skc1[1]]);
	const expected = mulPointEscalar(Base8, total);
	if (plain[0] !== expected[0] || plain[1] !== expected[1])
		throw new Error("decrypted balance does not match on-chain ElGamal ciphertext");
	return total;
}

export function egctFlat(bal) {
	const g = (p) => [BigInt(p.x ?? p[0]), BigInt(p.y ?? p[1])];
	return [...g(bal.eGCT.c1), ...g(bal.eGCT.c2)];
}

export const eurToTokenUnits = (eur) => BigInt(Math.round(eur * 100)) * 10n ** BigInt(TOKEN_DECIMALS - EERC_DECIMALS);
export const eurToEercUnits = (eur) => BigInt(Math.round(eur * 100));
export const eercUnitsToEur = (u) => Number(u) / 10 ** EERC_DECIMALS;
