// CLI (Fuji, real transactions; each run is appended to deployments/demo-runs-43113.json unless --no-record):
//   node src/cli.mjs float [targetEur] [minEur]   wrap the EU CASP float (top-up only below minEur)
//   node src/cli.mjs transfer <paymentId> <eur>   confidential transfer from the float
//   node src/cli.mjs settle <eur>                 GH VASP unwraps a netted amount
//   node src/cli.mjs status                       decrypted float / unsettled balances
import { appendDemoRun, shutdownProver } from "./lib.mjs";
import { demoRecord, runFloat, runSettle, runStatus, runTransfer, shortJson } from "./transfer.mjs";

const record = !process.argv.includes("--no-record");
const [cmd, a, b] = process.argv.slice(2).filter((x) => x !== "--no-record");
const log = (m) => console.log(m);
const USAGE = "usage: node src/cli.mjs float [targetEur] [minEur] | transfer <paymentId> <eur> | settle <eur> | status";

try {
	let r;
	if (cmd === "float") {
		r = await runFloat({ ...(a && { targetEur: Number(a) }), ...(b && { minEur: Number(b) }) }, log);
		if (record && r.wrapped) appendDemoRun(demoRecord("float", r, "cli"));
	} else if (cmd === "transfer") {
		if (!a || !b) throw new Error(USAGE);
		r = await runTransfer({ paymentId: a, amountEur: Number(b) }, log);
		if (record) appendDemoRun(demoRecord("transfer", r, "cli"));
	} else if (cmd === "settle") {
		if (!a) throw new Error(USAGE);
		r = await runSettle({ amountEur: Number(a) }, log);
		if (record) appendDemoRun(demoRecord("settle", r, "cli"));
	} else if (cmd === "status") {
		r = await runStatus();
	} else {
		throw new Error(USAGE);
	}
	console.log(shortJson(r));
	if (r.auditor?.decryptedAmountEur !== undefined)
		console.log(`\nAuditor decrypted: EUR ${r.auditor.decryptedAmountEur.toLocaleString("en-US")}`);
} catch (e) {
	console.error(e.shortMessage ?? e.message);
	process.exitCode = 1;
} finally {
	await shutdownProver();
}
