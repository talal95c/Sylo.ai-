// The confidential leg, run the way institutions would: a pre-funded float and netted unwraps.
//   float    EU CASP wraps a standing MockEURC float into eEURC once (top-up only below a threshold).
//   transfer EU CASP -> GH VASP confidential transfer from the float, encrypted metadata {paymentId};
//            the auditor decrypts the amount, GH VASP decrypts the metadata. No wrap/unwrap per payment.
//   settle   GH VASP unwraps a netted total later, which matches no single payment.
//
// Honest limits: addresses, the float wrap amount and the settle unwrap amount are public; only the
// eEURC transfer amounts, balances and metadata are hidden. A contract cannot hold or release eEURC
// (no BabyJubJub key, no proofs), so MEDIUM payments keep the public escrow (Mode A).
import {
	MOCK_EURC,
	contracts,
	decryptMetadata,
	decryptPCT,
	decryptedBalance,
	deriveIdentity,
	egctFlat,
	encryptMetadata,
	eercUnitsToEur,
	eurToEercUnits,
	pctOf,
	poseidonEncryptFor,
	prove,
	provider,
	transferInput,
	txLink,
	wallet,
	withdrawInput,
} from "./lib.mjs";

export const FLOAT_TARGET_EUR = Number(process.env.EERC_FLOAT_EUR ?? 1_000_000);
export const FLOAT_MIN_EUR = Number(process.env.EERC_FLOAT_MIN_EUR ?? 250_000);
const MAX_EUR = 10_000_000;

const SIG = {
	deposit: "deposit(uint256,address,uint256[7])",
	transfer:
		"transfer(address,uint256,((uint256[2],uint256[2][2],uint256[2]),uint256[32]),uint256[7],bytes)",
	withdraw: "withdraw(uint256,((uint256[2],uint256[2][2],uint256[2]),uint256[16]),uint256[7])",
};

/** Request errors carry an HTTP status; anything else is an upstream (chain/RPC) failure -> 502. */
export class LegError extends Error {
	constructor(message, status = 400) {
		super(message);
		this.status = status;
	}
}

let ctx;
async function context() {
	if (!ctx) {
		const p = provider();
		const w = { auditor: wallet("auditor", p), euCasp: wallet("euCasp", p), ghVasp: wallet("ghVasp", p) };
		const id = {};
		for (const [k, v] of Object.entries(w)) id[k] = await deriveIdentity(v);
		ctx = { p, w, id, ...contracts(p) };
	}
	// Re-read every time: a rotation must not leave us proving against a stale auditor key.
	const [onChain, pub] = await Promise.all([ctx.eerc.auditor(), ctx.eerc.auditorPublicKey()]);
	const auditorPub = pub.map(BigInt);
	const mine = ctx.id.auditor;
	if (onChain !== mine.address || auditorPub[0] !== mine.publicKey[0] || auditorPub[1] !== mine.publicKey[1])
		throw new LegError(`auditor key mismatch: on-chain auditor ${onChain}, AUDITOR_PK is ${mine.address}`, 503);
	ctx.tokenId ??= await ctx.eerc.tokenIds(MOCK_EURC);
	return { ...ctx, auditorPub };
}

function findEvent(eerc, rcpt, name) {
	for (const log of rcpt.logs) {
		try {
			const ev = eerc.interface.parseLog(log);
			if (ev?.name === name) return ev;
		} catch {}
	}
	throw new Error(`${name} event not found in ${rcpt.hash}`);
}

/** Current encrypted balance + its local decryption (balancePCT + pending amountPCTs, checked vs ElGamal). */
async function encBalance(c, role) {
	const bal = await c.eerc.balanceOf(c.id[role].address, c.tokenId);
	return { bal, units: decryptedBalance(c.id[role].privateKey, bal) };
}

function checkEur(name, v) {
	if (!(Number.isFinite(v) && v > 0 && v <= MAX_EUR && Math.round(v * 100) === v * 100))
		throw new LegError(`${name} must be a number in (0, ${MAX_EUR.toLocaleString("en-US")}] with at most 2 decimals`);
}

const links = (txs) => Object.fromEntries(Object.entries(txs).map(([k, h]) => [k, txLink(h)]));

let queue = Promise.resolve();
/** Serialised: one operation at a time (nonces + encrypted balance state). */
function serial(fn) {
	const run = queue.then(fn);
	queue = run.catch(() => {});
	return run;
}

// ---------------------------------------------------------------- float

async function wrap(c, units, log) {
	const tokenUnits = units * 10n ** 4n;
	const euAddr = c.id.euCasp.address;
	const held = await c.token.balanceOf(euAddr);
	if (held < tokenUnits)
		throw new LegError(`EU CASP holds ${eercUnitsToEur(held / 10n ** 4n)} MockEURC, float top-up needs ${eercUnitsToEur(units)}`, 409);
	const txs = {};
	if ((await c.token.allowance(euAddr, c.eerc.target)) < tokenUnits) {
		const ap = await c.token.connect(c.w.euCasp).approve(c.eerc.target, tokenUnits);
		await ap.wait();
		txs.approve = ap.hash;
		log(`approve ${txLink(ap.hash)}`);
	}
	const dep = await c.eerc
		.connect(c.w.euCasp)
		[SIG.deposit](tokenUnits, MOCK_EURC, pctOf(poseidonEncryptFor([units], c.id.euCasp.publicKey)));
	await dep.wait();
	txs.deposit = dep.hash;
	log(`float deposit ${txLink(dep.hash)}`);
	return txs;
}

async function doFloat({ targetEur = FLOAT_TARGET_EUR, minEur = Math.min(FLOAT_MIN_EUR, targetEur) }, log) {
	checkEur("targetEur", targetEur);
	if (!(minEur >= 0 && minEur <= targetEur)) throw new LegError("minEur must be in [0, targetEur]");
	const c = await context();
	const before = (await encBalance(c, "euCasp")).units;
	const base = { simulated: false, network: "avalanche-fuji", chainId: 43113, encryptedErc: c.eerc.target, holder: c.id.euCasp.address };
	if (before >= eurToEercUnits(minEur)) {
		log(`float ok: EUR ${eercUnitsToEur(before)} >= threshold EUR ${minEur}, nothing wrapped`);
		return { ...base, wrapped: false, wrappedEur: 0, floatBeforeEur: eercUnitsToEur(before), floatAfterEur: eercUnitsToEur(before), txs: {}, links: {} };
	}
	const units = eurToEercUnits(targetEur) - before;
	const txs = await wrap(c, units, log);
	const after = (await encBalance(c, "euCasp")).units;
	return {
		...base,
		wrapped: true,
		wrappedEur: eercUnitsToEur(units),
		floatBeforeEur: eercUnitsToEur(before),
		floatAfterEur: eercUnitsToEur(after),
		txs,
		links: links(txs),
		visibility: { public: ["float wrap amount (deposit)"], hidden: ["eEURC float balance afterwards"] },
	};
}

// ---------------------------------------------------------------- transfer

async function doTransfer({ paymentId, amountEur }, log) {
	if (typeof paymentId !== "string" || !/^[A-Za-z0-9_-]{1,64}$/.test(paymentId))
		throw new LegError("paymentId must match ^[A-Za-z0-9_-]{1,64}$");
	checkEur("amountEur", amountEur);
	const c = await context();
	const units = eurToEercUnits(amountEur);
	const euAddr = c.id.euCasp.address;
	const ghAddr = c.id.ghVasp.address;
	const t0 = Date.now();

	// Auto top-up only when the float cannot cover the payment; it wraps up to the float target,
	// never the payment amount itself.
	let eu = await encBalance(c, "euCasp");
	let floatTopUp = null;
	if (eu.units < units) {
		const target = eurToEercUnits(Math.max(FLOAT_TARGET_EUR, amountEur + FLOAT_MIN_EUR));
		const txs = await wrap(c, target - eu.units, log);
		floatTopUp = { wrappedEur: eercUnitsToEur(target - eu.units), txs, links: links(txs) };
		eu = await encBalance(c, "euCasp");
	}

	const ghPub = (await c.registrar.getUserPublicKey(ghAddr)).map(BigInt);
	const tIn = transferInput(c.id.euCasp, eu.units, egctFlat(eu.bal), ghPub, c.auditorPub, units);
	const tProof = await prove("transfer", tIn.input);
	const metadata = encryptMetadata(ghPub, JSON.stringify({ paymentId }));
	const trTx = await c.eerc.connect(c.w.euCasp)[SIG.transfer](ghAddr, c.tokenId, tProof, tIn.senderBalancePCT, metadata);
	const trRcpt = await trTx.wait();
	log(`transfer ${txLink(trTx.hash)}`);

	const pt = findEvent(c.eerc, trRcpt, "PrivateTransfer");
	const auditorUnits = BigInt(decryptPCT(c.id.auditor.privateKey, [...pt.args.auditorPCT])[0]);
	const pm = findEvent(c.eerc, trRcpt, "PrivateMessage");
	const ghMeta = JSON.parse(decryptMetadata(c.id.ghVasp.privateKey, pm.args.metadata.encryptedMsg));
	const [euAfter, ghAfter] = await Promise.all([encBalance(c, "euCasp"), encBalance(c, "ghVasp")]);

	const txs = { transfer: trTx.hash };
	return {
		simulated: false,
		network: "avalanche-fuji",
		chainId: 43113,
		mode: "float+netting",
		paymentId,
		amountEur,
		encryptedErc: c.eerc.target,
		from: euAddr,
		to: ghAddr,
		txs,
		links: links(txs),
		blocks: { transfer: trRcpt.blockNumber },
		floatTopUp,
		auditor: {
			address: c.id.auditor.address,
			onChainAuditor: pt.args.auditorAddress,
			decryptedAmountEur: eercUnitsToEur(auditorUnits),
			matches: auditorUnits === units,
		},
		receiverMetadata: ghMeta,
		balances: {
			note: "decrypted locally by each holder; not visible on-chain",
			euCaspFloatEur: eercUnitsToEur(euAfter.units),
			ghVaspUnsettledEur: eercUnitsToEur(ghAfter.units),
		},
		visibility: {
			public: ["addresses", "that a transfer happened"],
			hidden: ["eEURC transfer amount", "eEURC balances", "metadata (paymentId)"],
		},
		elapsedMs: Date.now() - t0,
	};
}

// ---------------------------------------------------------------- settle

async function doSettle({ amountEur }, log) {
	checkEur("amountEur", amountEur);
	const c = await context();
	const units = eurToEercUnits(amountEur);
	const t0 = Date.now();
	const gh = await encBalance(c, "ghVasp");
	if (gh.units < units)
		throw new LegError(`settle amount EUR ${amountEur} exceeds GH VASP unsettled eEURC EUR ${eercUnitsToEur(gh.units)}`, 409);
	const wIn = withdrawInput(c.id.ghVasp, gh.units, egctFlat(gh.bal), c.auditorPub, units);
	const wProof = await prove("withdraw", wIn.input);
	const wdTx = await c.eerc.connect(c.w.ghVasp)[SIG.withdraw](c.tokenId, wProof, wIn.userBalancePCT);
	const wdRcpt = await wdTx.wait();
	log(`settle withdraw ${txLink(wdTx.hash)}`);
	const ev = findEvent(c.eerc, wdRcpt, "Withdraw");
	const auditorUnits = BigInt(decryptPCT(c.id.auditor.privateKey, [...ev.args.auditorPCT])[0]);
	const after = await encBalance(c, "ghVasp");
	const txs = { withdraw: wdTx.hash };
	return {
		simulated: false,
		network: "avalanche-fuji",
		chainId: 43113,
		mode: "float+netting",
		amountEur,
		encryptedErc: c.eerc.target,
		holder: c.id.ghVasp.address,
		txs,
		links: links(txs),
		blocks: { withdraw: wdRcpt.blockNumber },
		auditor: { address: c.id.auditor.address, decryptedAmountEur: eercUnitsToEur(auditorUnits), matches: auditorUnits === units },
		balances: {
			note: "decrypted locally by GH VASP; not visible on-chain",
			ghVaspUnsettledBeforeEur: eercUnitsToEur(gh.units),
			ghVaspUnsettledAfterEur: eercUnitsToEur(after.units),
		},
		visibility: { public: ["netted unwrap amount (withdraw)"], hidden: ["which payments it nets", "remaining eEURC balance"] },
		elapsedMs: Date.now() - t0,
	};
}

async function doStatus() {
	const c = await context();
	const [eu, gh, owner] = await Promise.all([encBalance(c, "euCasp"), encBalance(c, "ghVasp"), c.eerc.owner()]);
	return {
		chainId: 43113,
		encryptedErc: c.eerc.target,
		owner,
		auditor: c.id.auditor.address,
		euCaspFloatEur: eercUnitsToEur(eu.units),
		ghVaspUnsettledEur: eercUnitsToEur(gh.units),
		floatTargetEur: FLOAT_TARGET_EUR,
		floatMinEur: FLOAT_MIN_EUR,
	};
}

export const runFloat = (args = {}, log = () => {}) => serial(() => doFloat(args, log));
export const runTransfer = (args, log = () => {}) => serial(() => doTransfer(args, log));
export const runSettle = (args, log = () => {}) => serial(() => doSettle(args, log));
export const runStatus = () => serial(doStatus);

/** Compact record of a float / transfer / settle result for deployments/demo-runs-43113.json. */
export function demoRecord(step, r, via) {
	const base = { step, at: new Date().toISOString(), via, txs: r.txs, links: r.links };
	if (step === "float") return { ...base, wrappedEur: r.wrappedEur, floatAfterEur: r.floatAfterEur };
	const audited = { auditor: r.auditor.address, auditorDecryptedAmountEur: r.auditor.decryptedAmountEur };
	if (step === "settle")
		return { ...base, amountEur: r.amountEur, ...audited, ghVaspUnsettledAfterEur: r.balances.ghVaspUnsettledAfterEur };
	return {
		...base,
		paymentId: r.paymentId,
		amountEur: r.amountEur,
		...(r.floatTopUp && { floatTopUp: r.floatTopUp }),
		...audited,
		receiverMetadata: r.receiverMetadata,
	};
}

export function shortJson(o) {
	return JSON.stringify(o, (_, v) => (typeof v === "bigint" ? v.toString() : v), 2);
}
