// POST /transfer {paymentId, amountEur} -> confidential leg on Fuji (deposit, private transfer,
// auditor decrypt, withdraw). GET /health. Port: EERC_PORT (default 8010), binds 127.0.0.1.
import http from "node:http";
import { loadDeployments } from "./lib.mjs";
import { runTransfer, shortJson } from "./transfer.mjs";

const PORT = Number(process.env.EERC_PORT ?? 8010);
const HOST = process.env.EERC_HOST ?? "127.0.0.1";

function send(res, status, body) {
	res.writeHead(status, { "content-type": "application/json", "access-control-allow-origin": "*" });
	res.end(shortJson(body));
}

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
		return send(res, d ? 200 : 503, { ok: !!d, chainId: 43113, encryptedErc: d?.contracts.EncryptedERC ?? null });
	}
	if (req.method !== "POST" || req.url !== "/transfer") return send(res, 404, { error: "not found" });

	let raw = "";
	for await (const chunk of req) {
		raw += chunk;
		if (raw.length > 4096) return send(res, 413, { error: "body too large" });
	}
	let body;
	try {
		body = JSON.parse(raw || "{}");
	} catch {
		return send(res, 400, { error: "invalid JSON" });
	}
	const { paymentId, amountEur } = body;
	try {
		const result = await runTransfer({ paymentId, amountEur: Number(amountEur) }, (m) =>
			console.log(`[${paymentId}] ${m}`),
		);
		send(res, 200, result);
	} catch (e) {
		const msg = e.shortMessage ?? e.message;
		console.error(`[${paymentId}] failed: ${msg}`);
		send(res, /must/.test(msg) ? 400 : 502, { error: msg, paymentId });
	}
});

server.listen(PORT, HOST, () => console.log(`eERC confidential-leg service on http://${HOST}:${PORT}`));
