// CLI: node src/cli.mjs [paymentId] [amountEur]   (defaults: PAY-2026-0001 85000)
import { shutdownProver } from "./lib.mjs";
import { runTransfer, shortJson } from "./transfer.mjs";

const paymentId = process.argv[2] ?? "PAY-2026-0001";
const amountEur = Number(process.argv[3] ?? 85000);

try {
	const r = await runTransfer({ paymentId, amountEur }, (m) => console.log(m));
	console.log(shortJson(r));
	console.log(`\nAuditor decrypted: EUR ${r.auditor.decryptedAmountEur.toLocaleString("en-US")}`);
} catch (e) {
	console.error(e.shortMessage ?? e.message);
	process.exitCode = 1;
} finally {
	await shutdownProver();
}
