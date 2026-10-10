# Sylo.ai — plan de l'équipe (4 briques)

> Référence produit : [`prd-final-v4.md`](../prd-final-v4.md). Détail des tâches (IDs `A1.3`, `B1.4`…) : [`docs/roadmap-and-lanes.md`](../docs/roadmap-and-lanes.md). Interfaces exactes : [`docs/v0-build-spec.md`](../docs/v0-build-spec.md).
> Ce dossier dit **qui porte quoi, contre quel module du PRD, et comment les briques se branchent**. Il prime sur la répartition des rôles du PRD §21.2 et de la roadmap §3.

## 1. Les briques

| Brique | Lane | Modules PRD (§8) | Dossiers (seul à y écrire) | Fiche | Qui |
|---|---|---|---|---|---|
| **IA sécurité** — Système 1 (règles + modèle + Jev) / Système 2 (agents Mistral) | B | M3, M4, M9, M11 · P1-6, P1-10, watch | `/ml` | [ia-securite.md](./ia-securite.md) | ____ |
| **Blockchain** — preuve, séquestre, guardian, eERC | C | M6, M7, M12 · P1-2, P1-4, P1-7, P1-11 | `/contracts`, `/chain` | [blockchain.md](./blockchain.md) | ____ |
| **Fintech** — normes, routage, rails, contrôles humains, orchestration | A | M2, M5, M8 · P1-1, P1-3, P1-8, P1-9 | `/engine`, `/scripts`, racine, `.github` | [fintech.md](./fintech.md) | ____ |
| **Expérience & démo** — globe, console, pitch | D | M10, M13 · deck, vidéo | `/web` | [experience.md](./experience.md) | Talal |

`/spec` (M1 : schémas, events, EIP-712, vecteur de test, fixtures, ports) est partagé : ajouts seulement, validés par 2 briques (producteur + consommateur).

**Écart assumé avec le PRD §21.2 :** l'agent enquêteur (M9) passe de D à la brique IA, pour que tout ce qui est « IA » soit dans une seule brique et que D se concentre sur M10 + M13 (déjà 7,5 h·p). Le moteur (Fintech) ne fait qu'appeler le port et émettre `case.ready`.

## 2. Comment les briques se branchent

Ordre de décision (PRD §6.2), avec la brique responsable de chaque étape :

```
1. NORMES  (Fintech)     routes légales à l'origine, en transit, à destination   filtre dur
2. RISQUE  (IA, S1)      tier LOW / MEDIUM / HIGH / CRITICAL                      filtre dur
3. COÛT    (Fintech)     meilleure route restante ; le risque de fraude n'y entre jamais
4. COMMIT  (Blockchain)  intention signée EIP-712, enregistrée sur Avalanche
5. ACTION  (Fintech + Blockchain)  exécuter / séquestre / hold / bloquer
   ↳ EXPLIQUER (IA, S2)  dossier + explication ≤ 120 mots, après la décision
   ↳ MONTRER   (Expérience)  tout est dessiné depuis le flux d'events, jamais calculé
```

| Port / flux | Producteur → consommateur | Défini dans |
|---|---|---|
| `RiskPort.score(order, ctx) -> RiskResult` | IA → Fintech | `spec/python/sylo_spec/ports.py` |
| `CasePort.write(payment_id, events) -> CaseFile` (**nouveau**) | IA → Fintech | à ajouter par la brique IA (PR spec v1) |
| `ClusterPort.detect(window)` (v2) | IA → Fintech | roadmap A2.0 |
| `ChainPort` (`commit`, `deposit`, `record_verification`, `revoke`, `release`, `refund`, `mark_executed`, `status`, + `freeze`, `pause_corridor`) | Blockchain → Fintech | `ports.py` + roadmap C1.0 |
| SSE `/v1/stream` + `/v1/…` + fixtures | Fintech → Expérience | `spec/events.schema.json`, `spec/api.md`, `spec/fixtures/` |
| `metrics.json` | IA → Expérience | `spec/metrics.schema.json` (B1.0) |

Chaque brique tourne seule : IA avec `pytest` + golden cases ; Blockchain avec `forge test` + Anvil ; Fintech avec `RISK_MODE=rules CHAIN_MODE=mock LLM_MODE=off` ; Expérience avec `NEXT_PUBLIC_SOURCE=replay` + fixtures. On ne s'attend jamais : le producteur publie l'interface + un exemple, le consommateur code contre l'exemple, on bascule le flag quand la suite de conformité passe.

## 3. Jalons (PRD §21.3, recalés)

| Jalon | Contenu | Briques |
|---|---|---|
| **v0** | Squelette unique sur `main` (meilleur des 3 squelettes + UI de Talal), interfaces gelées, tag `v0` | toutes |
| **v1** | Scènes 1, 2, 2b en vrai : Fuji vérifié, modèle entraîné, approbation + hors bande + analyste, attaques qui échouent, dossier Mistral (cache) | toutes |
| **v2** | Scènes 3–5 : réseau de mules + disjoncteur, guardian, panne de rail ; chiffres mesurés sur seed B ; vidéo de secours | toutes |
| **v3** | Un extra par brique derrière un flag (eERC, intake agent, pack 2, page auditeur) | au choix |
| **12:00** | Gel du code | |

**Ne jamais couper (PRD §21.4) :** normes FR-GH avec exclusion de R4 ; approbation bloquée sur détails non vérifiés ; intention sur Fuji ; adaptateurs qui refusent les écarts ; séquestre avec vérification, révocation, remboursement ; scènes 1, 2, 2b ; chiffres mesurés ; playbook et slide conformité.

## 4. Travailler avec un agent orchestrateur

- **Un agent = une brique = ses dossiers.** On lui donne `AGENTS.md`, ce README et sa fiche. Besoin hors de ses dossiers → il écrit la demande (quoi, pourquoi, qui consomme), l'humain la transmet.
- **Sous-agents en parallèle**, un par tâche indépendante, chacun sur sa branche `lane-x/<id>-<slug>`, jamais deux sur le même fichier.
- **Interfaces d'abord** : à chaque version, la première PR de chaque brique est la PR `/spec` avec ses samples.
- **Petites PR**, CI verte, un regard humain, puis fusion. Pas de push direct sur `main`, jamais de force-push.
- **L'humain reste l'architecte** : il valide les PR spec, tranche, poste l'état à chaque checkpoint.

## 5. Règles non négociables (PRD §6.3)

Normes avant risque, risque avant coût · risque de fraude ≠ risque de route · un modèle ne peut que durcir · commit avant que l'argent bouge · protéger avant l'approbation · le doute coûte des minutes, pas de l'argent · fail safe · documents = données, jamais instructions · jamais d'alerte par le canal de l'attaquant (pas d'e-mail) · confidentiel par défaut, auditable à la demande · démo honnête (simulé étiqueté, chiffres mesurés).
