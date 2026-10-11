// eERC confidential-leg service (Fuji). Binds 127.0.0.1:EERC_PORT (default 8010).
//   POST /transfer {paymentId, amountEur}  confidential transfer from the EU CASP float (auto top-up if short)
//   POST /settle   {amountEur}             GH VASP unwraps a netted amount
//   POST /float    {targetEur?, minEur?}   wrap / top up the float (idempotent above minEur)
//   GET  /status                           decrypted float / unsettled balances
//   GET  /health
// EERC_RECORD=1 appends each successful float / transfer / settle to deployments/demo-runs-43113.json.
// Fail closed: every error is a non-2xx JSON {error}; 4xx = bad request / insufficient balance,
// 503 = misconfigured (e.g. auditor key mismatch), 502 = chain / RPC failure.
import http from "node:http";
import { appendDemoRun, loadDeployments } from "./lib.mjs";
import { demoRecord, runFloat, runSettle, runStatus, runTransfer, shortJson } from "./transfer.mjs";

const PORT = Number(process.env.EERC_PORT ?? 8010);
const HOST = process.env.EERC_HOST ?? "127.0.0.1";

function send(res, status, body) {
	res.writeHead(status, { "content-type": "application/json", "access-control-allow-origin": "*" });
	res.end(shortJson(body));
}

async function readJson(req) {
	let raw = "";
	for await (const chunk of req) {
		raw += chunk;
		if (raw.length > 4096) throw Object.assign(new Error("body too large"), { status: 413 });
	}
	try {
		return JSON.parse(raw || "{}");
	} catch {
		throw Object.assign(new Error("invalid JSON"), { status: 400 });
	}
}

const num = (v) => (v === undefined ? undefined : Number(v));

const RECORD = process.env.EERC_RECORD === "1";
const recorded = (step, via) => (r) => {
	if (RECORD && (step !== "float" || r.wrapped)) appendDemoRun(demoRecord(step, r, via));
	return r;
};

const ROUTES = {
	"POST /transfer": (b, log) =>
		runTransfer({ paymentId: b.paymentId, amountEur: num(b.amountEur) }, log).then(recorded("transfer", "POST /transfer")),
	"POST /settle": (b, log) => runSettle({ amountEur: num(b.amountEur) }, log).then(recorded("settle", "POST /settle")),
	"POST /float": (b, log) =>
		runFloat(
			{ ...(b.targetEur !== undefined && { targetEur: num(b.targetEur) }), ...(b.minEur !== undefined && { minEur: num(b.minEur) }) },
			log,
		).then(recorded("float", "POST /float")),
	"GET /status": () => runStatus(),
};

const server = http.createServer(async (req, res) => {
	if (req.method === "OPTIONS") {
		res.writeHead(204, {
			"access-control-allow-origin": "*",
			"access-control-allow-methods": "POST, GET",
			"access-control-allow-headers": "content-type",
		});
		return res.end();
	}
	if (req.method === "GET" && req.url === "/health") {
		const d = loadDeployments();
		return send(res, d ? 200 : 503, {
			ok: !!d,
			chainId: 43113,
			mode: "float+netting",
			encryptedErc: d?.contracts.EncryptedERC ?? null,
			owner: d?.owner ?? null,
			auditor: d?.auditor?.address ?? null,
			endpoints: Object.keys(ROUTES),
		});
	}
	const route = ROUTES[`${req.method} ${req.url}`];
	if (!route) return send(res, 404, { error: "not found" });
	let body = {};
	let tag = req.url;
	try {
		if (req.method === "POST") body = await readJson(req);
		tag = body.paymentId ?? req.url;
		send(res, 200, await route(body, (m) => console.log(`[${tag}] ${m}`)));
	} catch (e) {
		const msg = e.shortMessage ?? e.message;
		console.error(`[${tag}] failed: ${msg}`);
		send(res, e.status ?? 502, { error: msg, ...(body.paymentId && { paymentId: body.paymentId }) });
	}
});

server.listen(PORT, HOST, () => console.log(`eERC confidential-leg service on http://${HOST}:${PORT}`));
