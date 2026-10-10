# Événements partagés

Chaque événement utilise l'enveloppe `EventEnvelope`; pour les événements on-chain, l'URL d'exploration est portée par `explorerUrl` dans l'enveloppe (exemple : `https://testnet.snowtrace.io/tx/<hash>`).

| Type | Sens | Exemple de `data` |
|---|---|---|
| `norms.checked` | Résultats des contrôles de conformité et notices fiscales. | `{"decision":{"normChecks":[{"routeId":"R4","ruleId":"GH_FX_EXPORT_PROCEEDS_NOMINATED_BANK","result":"FAIL","legalRef":"GH FX export proceeds"}],"taxNotices":[{"text":"No Ghanaian withholding on this goods payment","reference":"FR-GH treaty 1993","source":"GH tax profile"}]}}` |
| `risk.scored` | Score, niveau et motifs du paiement. | `{"decision":{"risk":{"score":18,"tier":"LOW","rulesFired":[],"topReasons":[],"modelVersion":"rules-v1"}}}` |
| `route.selected` | Route classée et routes candidates ou exclues. | `{"decision":{"route":{"chosen":"R3","candidates":[{"routeId":"R1","S":216},{"routeId":"R2","S":935},{"routeId":"R3","S":179},{"routeId":"R4","excludedBy":"GH_FX_EXPORT_PROCEEDS_NOMINATED_BANK"}],"settlement":"DIRECT","quoteValidUntil":"2026-10-11T00:20:00Z"}}}` |
| `approval.required` | Approbateurs requis et éventuel blocage de la validation. | `{"decision":{"approval":{"by":["claire","marc"],"method":"DUAL_CONTROL","hash":"approval-required"},"blocked":"verification_required"}}` |
| `approval.granted` | Approbation enregistrée pour le paiement. | `{"decision":{"approval":{"by":["claire"],"method":"DUAL_CONTROL","hash":"0xapproval"}}}` |
| `intent.committed` | Intention immuable enregistrée sur Fuji. | `{"txHash":"0x1111111111111111111111111111111111111111111111111111111111111111","contract":"PaymentRegistry","status":"COMMITTED","intentHash":"0xintent"}` — `explorerUrl`: `https://testnet.snowtrace.io/tx/<hash>` |
| `escrow.deposited` | Fonds placés sous séquestre conditionnel. | `{"txHash":"0x2222222222222222222222222222222222222222222222222222222222222222","contract":"PaymentEscrow","status":"DEPOSITED","amount":"85000 EUR","expiresAt":"2026-10-12T00:00:00Z"}` — `explorerUrl`: `https://testnet.snowtrace.io/tx/<hash>` |
| `simswap.checked` | Contrôle SIM swap du contact connu terminé. | `{"msisdn":"+233240000000","lookbackDays":7,"swapped":false,"simulated":true}` |
| `oob.requested` | Vérification sortante demandée au contact enregistré. | `{"contact":"Kwame","msisdn":"+233240000000","channel":"simulated_phone","prompt":"Have you changed your account?"}` |
| `verification.recorded` | Réponse hors bande inscrite au registre on-chain. | `{"txHash":"0x7777777777777777777777777777777777777777777777777777777777777777","contract":"PaymentRegistry","status":"VERIFICATION_DENIED","result":"DENIED","by":"Kwame","method":"OOB_KNOWN_CONTACT","simulated":true}` — `explorerUrl`: `https://testnet.snowtrace.io/tx/<hash>` |
| `intent.revoked` | Intention révoquée avant règlement. | `{"txHash":"0x3333333333333333333333333333333333333333333333333333333333333333","contract":"PaymentRegistry","status":"REVOKED","reason":"Supplier denied account change"}` — `explorerUrl`: `https://testnet.snowtrace.io/tx/<hash>` |
| `escrow.refunded` | Fonds séquestrés retournés au payeur. | `{"txHash":"0x4444444444444444444444444444444444444444444444444444444444444444","contract":"PaymentEscrow","status":"REFUNDED","reason":"Verification denied"}` — `explorerUrl`: `https://testnet.snowtrace.io/tx/<hash>` |
| `escrow.released` | Fonds libérés après confirmation vérifiée. | `{"txHash":"0x5555555555555555555555555555555555555555555555555555555555555555","contract":"PaymentEscrow","status":"RELEASED","verification":"CONFIRMED"}` — `explorerUrl`: `https://testnet.snowtrace.io/tx/<hash>` |
| `leg.sent` | Jambe de paiement transmise au rail. | `{"leg":{"rail":"R3","rank":1,"status":"pending"},"intentHash":"0xintent"}` |
| `leg.settled` | Jambe de paiement réglée par le rail. | `{"leg":{"rail":"R3","rank":1,"status":"settled"},"amount":"85000 EUR","simulated":true}` |
| `leg.rejected` | Rail a refusé la jambe de paiement. | `{"rail":"R3","reason":"intent hash mismatch","attack":"B"}` |
| `alert.raised` | Alerte fraude transmise à l'équipe ou à la banque concernée. | `{"alertId":"alert_scene2","tier":"MEDIUM","uetr":"uetr-scene2","recipient":"Ama's bank","freezeRequested":true}` |
| `case.ready` | Dossier analyste cité prêt à examiner. | `{"caseId":"case_scene2","tier":"MEDIUM","summary":"Supplier account change denied by known contact.","explanation":"Three independent signals raised the payment to MEDIUM.","citations":["R-FL-01","R-FL-03","R-NM-01"],"reportDraft":"TRACFIN draft: suspected supplier impersonation.","cached":false}` |
| `killswitch.on` | Connecteur de rail désactivé après un échec d'intégrité. | `{"rail":"R3","reason":"CommitmentMismatch","scope":"adapter","simulated":true}` |
| `breaker.on` | P1, non émis en P0 : circuit breaker activé pour un corridor ou une région. | `{"scope":"GH","reason":"fraud_wave","durationHours":24}` |
| `breaker.off` | P1, non émis en P0 : circuit breaker levé par un analyste. | `{"scope":"GH","by":"analyst"}` |
| `rail.down` | P1, non émis en P0 : route marquée indisponible après une panne. | `{"rail":"R3","reason":"provider_unavailable"}` |
| `rail.up` | P1, non émis en P0 : route remise en service. | `{"rail":"R3"}` |
| `tx.reverted` | Transaction Fuji refusée par le contrat. | `{"txHash":"0x6666666666666666666666666666666666666666666666666666666666666666","contract":"PaymentEscrow","status":"REVERTED","attack":"A","function":"release","revertReason":"PaymentNotReleasable"}` — `explorerUrl`: `https://testnet.snowtrace.io/tx/<hash>` |
| `log.tampered` | Vérification d'intégrité du journal hash-chaîné a échoué. | `{"seq":42,"expectedHash":"0xexpected","actualHash":"0xactual","reason":"decision payload rewritten"}` |
| `mode.degraded` | Dépendance indisponible: décision plus stricte, aucun déblocage automatique. | `{"dependency":"rpc","status":"unavailable","policy":"rules_and_humans_only","releaseDisabled":true}` |
