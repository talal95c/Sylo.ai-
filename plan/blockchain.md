# Blockchain — preuve, séquestre, guardian · Lane C · `/contracts`, `/chain`

**Mission (PRD §13)** : rendre la décision **infalsifiable et vérifiable par des tiers** (rails, banque du fournisseur, auditeurs). Chaque paiement, quel que soit le rail, est engagé on-chain sous forme d'intention EIP-712 **avant** que l'argent bouge ; le séquestre ne libère que si le fournisseur a confirmé ; toute tentative de triche échoue de façon visible sur l'explorer.

## Ce qui va on-chain (§13.1)

| On-chain | Off-chain |
|---|---|
| Intentions et attestations signées (hash, signataire, statut) pour **tous** les paiements ; état et fonds du séquestre pour R3 ; transferts confidentiels eERC (P1) ; racines Merkle du journal (P1) | Noms, numéros de compte, factures, features, scores, dossiers — n'entrent que comme **hash salés** |

## Livrables

**Contrats (M6, §13.3)**
- `PaymentRegistry` : `commit`, `recordVerification`, `revoke`, `markExecuted`, `intentOf`, `statusOf` ; machine d'états `NONE → COMMITTED → CONFIRMED | DENIED`, `→ REVOKED` (final), `CONFIRMED → EXECUTED` (MEDIUM), `COMMITTED → EXECUTED` (LOW) ; toute autre transition revert.
- `PaymentEscrow` (mode A, EURC public) : `deposit` (revert `CommitmentMismatch`), `release` (revert `PaymentNotReleasable` sauf `CONFIRMED`), `refund` (permissionless si révoqué ou expiré), `freeze`, `pauseCorridor`.
- `MockEURC` (`tEURC`, 6 décimales) pour les montants de démo, étiqueté.
- **Invariants** (unit + fuzz + invariant Foundry) : solde du séquestre = somme des fonds tenus ; fonds seulement vers le payeur ou le bénéficiaire de l'intention ; dépôt différent de l'intention → revert ; `release` seulement si `CONFIRMED` et non gelé/expiré/en pause ; remboursement permissionless ; un dépôt par `paymentId`, un nonce une fois ; reentrancy guard, CEI, `SafeERC20`.

**EIP-712 et chaîne d'autorité (§13.4)** — domaine `SyloPaymentRegistry` v1 lié à `chainId` + contrat :

| Attestation | Signataire | Sens |
|---|---|---|
| `PaymentIntent` | service routeur de la banque émettrice | « le payeur a approuvé ce bénéficiaire et ce montant, cette décision, valable jusqu'à… » |
| `VerificationAttestation` | service vérificateur | « le contact connu du fournisseur a confirmé / refusé, après vérification SIM-swap » — référence le hash exact de l'intention |
| `Revocation` | analyste (ou kill switch) | « ce paiement ne doit pas continuer », avec la raison |

Le vecteur de test `spec/eip712.json` doit donner le même hash en Python et en Solidity (M1).

**Client chaîne (M7, §13.8)** : `sylo_chain.FujiChain` implémente `ChainPort` ; une clé par rôle ; ≥ 2 RPC avec repli ; refuse de démarrer si le chain ID ≠ 43113 ; attend les reçus ; un gestionnaire de nonce par émetteur ; erreurs custom décodées → `ChainReverted(reason)` ; `TxRef` avec lien explorer.

**Attaques de la scène 2b (M12)** : libérer un paiement révoqué, changer le bénéficiaire en transit, rejouer une intention → chacune revert on-chain, **minée et visible sur Snowtrace** (gas fixe, pas d'estimation), en < 10 s ; scripts `cast` de secours utilisables sans le moteur.

**P1** : guardian (§13.7 : surveille registre + séquestre via 2 RPC, gèle / met en pause si `CONFIRMED` sans trace hors bande, règlement sans intention, appel privilégié inconnu ; brouillon d'incident DORA) ; eERC (§13.6, time-box 3 h : wrap EURC → eEURC, transfert confidentiel lisible par le destinataire et l'auditeur ; limite honnête : un contrat ne peut pas détenir et libérer de l'eEURC, donc le séquestre MEDIUM reste en mode A) ; `DecisionAnchor` (racine Merkle du journal toutes les 60 s, preuve d'inclusion) ; lectures à 2 fournisseurs (P1-11).

**P2 (slide)** : L1 consortium (proposition du mentor) avec AllowLists, racines ancrées sur la C-Chain publique.

## Ordre de travail

| Version | Tâches |
|---|---|
| v1 | PR spec C1.0 (`freeze`, `pause_corridor`, URL explorer, format `deployments/<chainId>.json`) → durcissement + invariants (C1.1) → **déploiement Fuji + vérification Snowtrace, adresses postées** (C1.2, attendu par tous) → `FujiChain` conforme sur Anvil puis Fuji (C1.3) → transactions d'attaque visibles (C1.4) → scripts `cast` (C1.5) |
| v2 | Guardian + scène « clé de vérificateur volée » (C2.1) → eERC en time-box (C2.2) → vérif des liens explorer (C2.3) |
| v3 | `DecisionAnchor` ou L1 consortium |

**Couper en premier → en dernier** : eERC (slide) → scripts `cast` → guardian (slide). **Jamais** : déploiement Fuji vérifié, `FujiChain`, attaques qui échouent on-chain avec lien explorer.

**Pitch** : slide conformité (§18.1 : FATF R.16, DORA, MiCA, règle de voyage, RGPD) et slide preuve on-chain ; démonstration « comment un auditeur vérifie une décision » (§18.2).

## Prompt de démarrage (agent orchestrateur)

```
Tu travailles sur Sylo.ai, brique « Blockchain » (Lane C). Lis AGENTS.md, plan/README.md, plan/blockchain.md,
puis PRD §13, §18.2, §19, docs/setup.md §4–7 et les sections Lane C de docs/roadmap-and-lanes.md.
Tu n'écris que sous /contracts et /chain (et /spec par PR additive validée par 2 briques).
Commence par la PR spec C1.0. Sous-agents en parallèle : (a) tests fuzz/invariants, (b) déploiement + vérification Fuji,
(c) FujiChain + conformance, (d) attaques visibles ; une branche lane-c/<id>-<slug> et une petite PR chacun.
Règles : rien de personnel on-chain (hash salés) ; wallets de test uniquement ; aucune clé dans le dépôt.
Avant de finir : cd contracts && forge test vert, run_chain_conformance vert sur Anvil.
```
