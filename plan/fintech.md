# Fintech — normes, routage, rails, contrôles humains · Lane A · `/engine`, `/scripts`, racine

**Mission (PRD §9, §11, §12, §13.5, §16)** : le métier du paiement transfrontalier B2B FR → GH. Dire quelles routes sont **légales**, choisir **la moins chère parmi les sûres**, faire passer les **contrôles humains** (approbation, double contrôle, vérification hors bande), exécuter sur les **rails** sans écart possible avec l'intention, et appliquer le **playbook de réponse**. C'est aussi le moteur qui orchestre le pipeline et branche les ports des autres briques.

## Livrables

**Normes (M2, §9)**
- Profils FR et GH + pack `FR-GH.yaml` (rails R1–R4, convention fiscale, règles avec référence légale). Chaque règle renvoie `PASS | FAIL | NEEDS_DOCUMENT` par route ; un `FAIL` exclut la route et l'enregistre ; en conflit, le plus strict gagne ; inconnu = `FAIL`.
- Règles P0 : `GH_FX_EXPORT_PROCEEDS_NOMINATED_BANK` (exclut R4 pour des marchandises, signal R1 si le compte n'est pas la banque désignée), `GH_VASP_LICENSED`, `GH_WALLET_DAILY_CAP`, `EU_MICA_EMT_CASP`, `EU_TRAVEL_RULE`, `EU_HIGH_RISK_EDD`, `EU_VOP_SCOPE`, `SANCTIONS_SCREEN`.
- Notices fiscales (§9.4) : information seulement, ne changent jamais montant, route ni éligibilité.

**Routage (M5, §11)**
- Deux risques séparés : le **risque de fraude** fixe le tier qui restreint les routes ; le **risque de route** (panne, taux d'échec, intermédiaire peu fiable, connecteur sous kill switch) entre dans le score. Rerouter ne répond jamais à la fraude.
- `eligible(r)` = rail UP ∧ normes PASS ∧ plafonds OK ∧ pas de kill switch ∧ (LOW, ou MEDIUM avec règlement conditionnel) ∧ tier ∉ {HIGH, CRITICAL}.
- `S(r) = cost + λ·A·T + μ·A·pFail + ν·A·pUnusable + σ·routeRisk` — **le risque de fraude n'est pas dans S** (test unitaire obligatoire). Exemple scène 1 (85 000 €) : R1 ≈ 216 €, R3 ≈ 179 €, R2 ≈ 935 € → R3. Afficher le « prix de la sécurité ».

**Orchestration et réponse (M8, §12)**
- Registre des bénéficiaires + provenance des champs ; règle R-PV-01 : détails nouveaux ou modifiés venant d'une source non fiable → **approbation bloquée** jusqu'à la vérification hors bande.
- Approbation payeur avec double contrôle (≥ 20 k€, ou nouveau bénéficiaire ≥ 5 k€ ; l'auteur ne peut pas être le second approbateur) ; time-lock sur premier paiement à un nouveau compte.
- Commit de l'intention (via `ChainPort`) **avant** tout mouvement ; séquestre (R3) ou hold fiat (R1) pour MEDIUM ; vérification SIM-swap puis demande hors bande au contact connu (enregistré ≥ 30 j, sortant) ; R-OOB-01 si SIM-swap récent → analyste ; révocation + remboursement sur refus ; remboursement auto à 24 h.
- 4 tiers du playbook (§12.1) ; overlays (§12.2) : disjoncteur régional, kill switch, panne de rail, incident du guardian, tentative de falsification, mode dégradé. **Jamais d'alerte payeur par e-mail.**
- Journal chaîné par hash (`seq, prevHash, type, payload, hash`), rejouable par un auditeur.

**Rails (§13.5)** : un adaptateur par rail R1–R4 avec la même interface (`quote`, `initiate`, `status`, `onWebhook`, `reconcile`). Avant `initiate` : recalcul du hash d'intention depuis les champs + sel, fenêtre de validité, nonce inutilisé, statut du registre (`COMMITTED` LOW / `CONFIRMED` MEDIUM), clé d'idempotence. Toute différence → `leg.rejected` ; répétitions → kill switch. Message de jambe au format `pacs.008` avec UETR, `intentHash`, nonce. Adaptateurs simulés et étiquetés.

**API (§16.2)** : `/v1/quotes`, `/payments`, `/payments/{id}/approve`, `/payments/{id}/proof`, `/payees/{id}/verify`, `/cases`, `/cases/{id}/actions`, `/sim/events`, `/stream` (SSE), `/metrics`. Intégration banque (§16.3) : hook de pré-exécution, entrée `pacs.008`/`pain.001`, adoption en shadow mode.

**Intégration** : bascule des flags `RISK_MODE`, `CHAIN_MODE`, `LLM_MODE` quand la conformité passe, sinon repli + bandeau `degraded` ; fixtures ré-enregistrées ; `make demo-check`.

## Ordre de travail

| Version | Tâches |
|---|---|
| v1 | PR spec A1.0 (events + endpoints + `samples-v1.jsonl`) et validation de `CasePort` → approbation + double contrôle (A1.3) → hors bande + SIM-swap (A1.4) → actions analyste (A1.8) → adaptateurs R1–R4 + attaques (A1.5) → branchement Fuji (A1.1) et modèle (A1.2) et appel `CasePort` → fixtures + `demo-check` (A1.9) → journal + `/proof` (A1.6) |
| v2 | Disjoncteur régional (A2.1) → panne + reroutage (A2.2) → kill switch + mode dégradé (A2.3) → incidents du guardian + brouillon DORA (A2.4) |
| v3 | Pack 2 Lagos → Accra en un seul fichier (P1-8) ou horloge de démo (P1-9) |

**Couper en premier → en dernier** : journal chaîné → incidents guardian → panne/reroutage. **Jamais** : exclusion de R4 par les normes, approbation bloquée sur détails non vérifiés, adaptateurs qui refusent les écarts, actions analyste, intégration Fuji, fixtures + `demo-check`.

**Pitch** : pilote de la démo (run sheet, boutons, replis), **playbook de réponse** (livrable du sujet, §12), slide adoption (pilote banque 4 semaines en shadow mode).

## Prompt de démarrage (agent orchestrateur)

```
Tu travailles sur Sylo.ai, brique « Fintech » (Lane A, moteur). Lis AGENTS.md, plan/README.md, plan/fintech.md,
puis PRD §6, §9, §11, §12, §13.5, §16, docs/v0-build-spec.md §4–5 et les sections Lane A de docs/roadmap-and-lanes.md.
Tu n'écris que sous /engine, /scripts, les fichiers racine et .github (et /spec par PR additive validée par 2 briques).
L'agent Mistral appartient à la brique IA : tu appelles seulement CasePort et émets case.ready.
Commence par la PR spec A1.0. Sous-agents en parallèle : (a) approbation + hors bande + actions analyste,
(b) adaptateurs de rails + attaques, (c) branchement des ports + fixtures + demo-check ; une branche lane-a/<id>-<slug> chacun.
Règles : le risque de fraude n'entre jamais dans le score de route ; commit avant tout mouvement ; jamais d'alerte
payeur par e-mail ; fail safe. Avant de finir : cd engine && uv run pytest et make fixtures-check verts.
```
