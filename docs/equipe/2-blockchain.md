# Brique 2 — Blockchain · Lane C · `/contracts`, `/chain`

**Mission :** rendre la décision **infalsifiable** : l'intention signée (EIP-712) est enregistrée sur Avalanche avant que l'argent bouge, le séquestre ne libère que si le fournisseur a confirmé, et chaque attaque échoue de façon visible sur l'explorer.

## Livrables (par ordre de priorité)

**v1 (→ 03:30)**
1. **PR spec (20 min)** : `ChainPort.freeze`, `pause_corridor`, convention d'URL explorer, format `contracts/deployments/<chainId>.json` (C1.0). Validation : 2 + 3.
2. Durcissement des contrats : fuzz + invariants PRD §13.3 (C1.1).
3. **Déploiement Fuji + vérification Snowtrace** des 3 contrats, adresses postées (C1.2). C'est le premier livrable attendu par les autres.
4. `sylo_chain.FujiChain` qui passe `run_chain_conformance` sur Anvil (CI) et Fuji (à la main) (C1.3).
5. Transactions d'attaque minées et visibles avec leur raison de revert (C1.4) ; scripts `cast` de secours (C1.5).

**v2 (07:00 → 09:00)**
6. Guardian : surveille registre + séquestre, gèle avant le voleur de clé, poste l'incident au moteur (C2.1).
7. eERC (transfert confidentiel + vue auditeur), time-box 90 min, sinon une slide (C2.2).

**v3 (si temps)** : ancrage Merkle du journal de décisions (C3.1) ou L1 consortium (C3.2).

## Dépend de / attend

- Vecteur EIP-712 `spec/eip712.json` (v0). Wallets de test financés (setup.md §4–6). Rien d'autre : tout se teste avec `forge test` + Anvil.

## Ne jamais couper

Déploiement Fuji vérifié, `FujiChain`, attaques qui échouent on-chain avec lien explorer.

## Pitch

Slide conformité (PRD §18.1) et slide « preuve on-chain ».

## Prompt de démarrage (agent orchestrateur)

```
Tu travailles sur Sylo.ai, brique 2 « Blockchain » (Lane C). Lis AGENTS.md, docs/equipe/README.md,
docs/equipe/2-blockchain.md, les sections Lane C de docs/roadmap-and-lanes.md, PRD §13 et docs/setup.md §4–7.
Tu n'écris que sous /contracts et /chain (et /spec par PR additive validée par 2 briques).
Sous-agents en parallèle : (a) tests fuzz/invariants, (b) déploiement + vérification Fuji, (c) FujiChain + conformance,
une branche lane-c/<id>-<slug> et une petite PR chacun. Commence par la PR spec C1.0.
Règles : aucune donnée personnelle on-chain (hash salés seulement) ; wallets de test uniquement ; aucune clé
dans le dépôt. Avant de finir : cd contracts && forge test vert, et run_chain_conformance vert sur Anvil.
```
