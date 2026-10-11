// The confidential leg: EU CASP wraps MockEURC -> eEURC, sends it privately to GH VASP with
// encrypted metadata {paymentId}, the auditor decrypts the amount from the PrivateTransfer
// auditorPCT, GH VASP decrypts the metadata and unwraps back to MockEURC.
//
// Honest limits: wrap (deposit) and unwrap (withdraw) amounts are public, addresses are
// public, only the eEURC transfer amount/balances are hidden. A contract cannot hold or release
// eEURC (it has no BabyJubJub key and cannot produce proofs), so MEDIUM payments keep the
// public escrow (Mode A); this leg is for payments that need no escrow hold.
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
	eurToTokenUnits,
	pctOf,
	poseidonEncryptFor,
	prove,
	provider,
	transferInput,
	txLink,
	wallet,
	withdrawInput,
} from "./lib.mjs";

const SIG = {
	deposit: "deposit(uint256,address,uint256[7])",
	transfer:
		"transfer(address,uint256,((uint256[2],uint256[2][2],uint256[2]),uint256[32]),uint256[7],bytes)",
	withdraw: "withdraw(uint256,((uint256[2],uint256[2][2],uint256[2]),uint256[16]),uint256[7])",
};

let ctx;
async function context() {
	if (ctx) return ctx;
	const p = provider();
	const w = { auditor: wallet("auditor", p), euCasp: wallet("euCasp", p), ghVasp: wallet("ghVasp", p) };
	const id = {};
	for (const [k, v] of Object.entries(w)) id[k] = await deriveIdentity(v);
	const c = contracts(p);
	const auditorPub = (await c.eerc.auditorPublicKey()).map(BigInt);
	ctx = { p, w, id, ...c, auditorPub };
	return ctx;
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

let queue = Promise.resolve();

/** Serialised: one confidential leg at a time (nonces + encrypted balance state). */
export function runTransfer(args, log = () => {}) {
	const run = queue.then(() => doTransfer(args, log));
	queue = run.catch(() => {});
	return run;
}

async function doTransfer({ paymentId, amountEur }, log) {
	if (typeof paymentId !== "string" || !/^[A-Za-z0-9_-]{1,64}$/.test(paymentId))
		throw new Error("paymentId must match ^[A-Za-z0-9_-]{1,64}$");
	if (!(Number.isFinite(amountEur) && amountEur > 0 && amountEur <= 10_000_000))
		throw new Error("amountEur must be a number in (0, 10,000,000]");

	const { w, id, eerc, token, auditorPub } = await context();
	const tokenUnits = eurToTokenUnits(amountEur);
	const units = eurToEercUnits(amountEur);
	const euAddr = id.euCasp.address;
	const ghAddr = id.ghVasp.address;
	const t0 = Date.now();

	// 1. wrap: EU CASP deposits MockEURC, receives eEURC (amount is public here)
	const eu = eerc.connect(w.euCasp);
	if ((await token.allowance(euAddr, eerc.target)) < tokenUnits) {
		const ap = await token.connect(w.euCasp).approve(eerc.target, tokenUnits);
		await ap.wait();
		log(`approve ${txLink(ap.hash)}`);
	}
	const depTx = await eu[SIG.deposit](
		tokenUnits,
		MOCK_EURC,
		pctOf(poseidonEncryptFor([units], id.euCasp.publicKey)),
	);
	const depRcpt = await depTx.wait();
	log(`deposit  ${txLink(depTx.hash)}`);

	// 2. confidential transfer EU CASP -> GH VASP, metadata encrypted for GH VASP
	const tokenId = await eerc.tokenIds(MOCK_EURC);
	const euBal = await eerc.balanceOf(euAddr, tokenId);
	const euPlain = decryptedBalance(id.euCasp.privateKey, euBal);
	const ghPub = (await contracts(w.euCasp).registrar.getUserPublicKey(ghAddr)).map(BigInt);
	const tIn = transferInput(id.euCasp, euPlain, egctFlat(euBal), ghPub, auditorPub, units);
	const tProof = await prove("transfer", tIn.input);
	const metadata = encryptMetadata(ghPub, JSON.stringify({ paymentId }));
	const trTx = await eu[SIG.transfer](ghAddr, tokenId, tProof, tIn.senderBalancePCT, metadata);
	const trRcpt = await trTx.wait();
	log(`transfer ${txLink(trTx.hash)}`);

	// 3. auditor decrypts the amount from the on-chain auditorPCT
	const pt = findEvent(eerc, trRcpt, "PrivateTransfer");
	const auditorUnits = BigInt(decryptPCT(id.auditor.privateKey, [...pt.args.auditorPCT])[0]);
	const pm = findEvent(eerc, trRcpt, "PrivateMessage");
	const ghMeta = JSON.parse(decryptMetadata(id.ghVasp.privateKey, pm.args.metadata.encryptedMsg));

	// 4. unwrap: GH VASP withdraws the received eEURC back to MockEURC (amount is public here)
	const ghBal = await eerc.balanceOf(ghAddr, tokenId);
	const ghPlain = decryptedBalance(id.ghVasp.privateKey, ghBal);
	const wIn = withdrawInput(id.ghVasp, ghPlain, egctFlat(ghBal), auditorPub, units);
	const wProof = await prove("withdraw", wIn.input);
	const wdTx = await eerc.connect(w.ghVasp)[SIG.withdraw](tokenId, wProof, wIn.userBalancePCT);
	const wdRcpt = await wdTx.wait();
	log(`withdraw ${txLink(wdTx.hash)}`);

	const txs = { deposit: depTx.hash, transfer: trTx.hash, withdraw: wdTx.hash };
	return {
		simulated: false,
		network: "avalanche-fuji",
		chainId: 43113,
		paymentId,
		amountEur,
		encryptedErc: eerc.target,
		from: euAddr,
		to: ghAddr,
		txs,
		links: Object.fromEntries(Object.entries(txs).map(([k, h]) => [k, txLink(h)])),
		blocks: { deposit: depRcpt.blockNumber, transfer: trRcpt.blockNumber, withdraw: wdRcpt.blockNumber },
		auditor: {
			address: id.auditor.address,
			decryptedAmountEur: eercUnitsToEur(auditorUnits),
			matches: auditorUnits === units,
			note: "PoC auditor key holder = deployer; final holder to decide (PRD §13.6)",
		},
		receiverMetadata: ghMeta,
		visibility: {
			public: ["addresses", "deposit (wrap) amount", "withdraw (unwrap) amount"],
			hidden: ["eEURC transfer amount", "eEURC balances", "metadata (paymentId)"],
		},
		elapsedMs: Date.now() - t0,
	};
}

export function shortJson(o) {
	return JSON.stringify(o, (_, v) => (typeof v === "bigint" ? v.toString() : v), 2);
}
