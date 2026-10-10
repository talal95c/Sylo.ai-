# Tâches — Oscar (données, risque, évaluation)

> **Ta mission** : un moteur de risque qui classe la scène 2 en **MEDIUM avec ≥ 3 raisons citées**, et des **chiffres reproductibles** (seed B jamais vue) qui prouvent que nos signaux (géographie, normes, réseau) détectent mieux qu'une institution isolée.
> **Pourquoi c'est critique** : la détection pèse **30 %** de la note ; un juge demandera « vos données sont synthétiques ? » → la réponse est ton protocole (générateur publié, bruit honnête, seed B, baselines, ablations).
> **À lire dans le PRD v4** : §10 (signaux, règles, modèle, seuils), §17 (données, baselines, métriques), §12.4.
> **Dossier** : `/ml` (Python 3.12, scikit-learn, LightGBM, NetworkX). Tu ne touches pas aux autres dossiers.

## 1. Ce qu'il faut comprendre (5 min)

- **Niveau = max(plancher des règles, niveau du modèle)**. Les règles (R-HB, R-PV, R-FL, R-NM, R-OOB du §10.2) donnent un plancher ; le modèle ne peut que **monter** le niveau. Règle bloquante → CRITICAL.
- **Le back t'appelle comme une fonction Python**, pas comme un service : `from ml.score import score`. Il te passe l'ordre et un **contexte** déjà calculé (registre, télécom, géo, réseau, signaux de normes). Tu n'as pas à reconstruire le graphe en ligne pour la démo.
- **Chaque raison doit être citable** : `ref` = un `ruleId` (`R-FL-03`) ou un `signalId` (`B.name_match`). L'agent Mistral de Devin n'a le droit de citer que ces `ref`.
- **Calibration** (isotonic sur la validation) : le score 0–100 affiché doit être une vraie probabilité × 100.

## 2. Interface à livrer (figée à 22:00 avec Devin)

```python
# ml/score.py
def score(order: dict, ctx: dict) -> dict:
    """Retourne {score: int 0-100, tier: "LOW"|"MEDIUM"|"HIGH"|"CRITICAL",
                 rulesFired: [str], topReasons: [{"ref": str, "text": str}], modelVersion: str}"""
```

Seuils retenus : LOW 0–39, MEDIUM 40–79, HIGH 80–94, CRITICAL 95–100, pour que le score 74 de la scène 2 reste MEDIUM.

`ctx` (`RiskContext`, point de départ à ajuster ensemble à 21:30 — une clé par signal du §10.1) :

| Famille | Clés |
|---|---|
| B Bénéficiaire | `payee_is_new`, `account_first_seen_days`, `account_age_days`, `successful_payments_to_account`, `name_match` (0–1), `personal_account_for_business`, `amount_vs_account_capacity` |
| V Provenance | `provenance` (`verified_registry` / `payment_history` / `invoice_pdf_email` / `inbound_call` / `user_input`), `lookalike_domain`, `urgency_cues` |
| P Session payeur | `payer_sim_swap_72h`, `payer_new_device_24h`, `session_country_unusual` |
| G Géographie | `account_region`, `supplier_region`, `region_mismatch`, `account_near_border`, `wallet_region_mismatch`, `impossible_travel`, `regional_fraud_wave` |
| H Comportement | `amount_eur`, `amount_vs_history_ratio`, `unusual_hour`, `velocity_24h` |
| N Réseau | `fanout_wallets`, `minutes_credit_to_forward`, `shared_cashout_agents`, `young_fast_cluster` |
| S Structuration | `just_below_cap_count`, `declared_split` |
| R Normes | `norm_r1` (recettes d'export hors banque nominée) |
| Bloquants / OOB | `sanctions_hit`, `linked_confirmed_fraud`, `supplier_contact_sim_swap_7d` |

Valeurs de la scène 2 (doivent donner MEDIUM, score ≈ 74, raisons R-FL-01, R-FL-03, R-NM-01) : nouveau bénéficiaire, `invoice_pdf_email`, compte de 9 jours, name match 0,21, domaine lookalike + urgence, `norm_r1`, compte à Aflao (frontière) vs fournisseur dans le Nord, transferts vers 6 wallets en quelques minutes. Scène 1 : bénéficiaire connu, `verified_registry`, 7 paiements réussis → LOW.

## 3. Tâches dans l'ordre

| # | Quand | Tâche | Fini quand |
|---|---|---|---|
| 1 | 21:00–22:00 | Lire §10 et §17 ; figer `RiskContext` avec Devin ; squelette `/ml` (`pyproject` ou `requirements.txt`, `Makefile` cibles `data`, `train`, `eval`) | Interface écrite dans `ml/README.md` |
| 2 | 22:00–23:00 | **`score()` règles seules** (§10.2, seuils §12.3 : 10 k€ / 5 k€ / name match 0,85) | Scène 1 → LOW, scène 2 → MEDIUM avec 3 règles, Devin peut l'importer |
| 3 | 23:00–01:00 | **Simulateur seedé** (§17.1, version nuit : ~20 000 paiements, 30 jours, 10 régions du Ghana) : T1 BEC 0,3 %, T3 mules 0,3 %, T2/T4 quelques centaines de cas, **bruit honnête ≈ 3 %** (vrai changement de banque vérifié, noms commerciaux 0,6–0,85, voyages, nouveaux fournisseurs…), **aucune fraude détectable sur un seul champ** ; 300 scénarios d'intégrité I1–I3 dans `ml/data/integrity_<seed>.jsonl` (format avec Devin, c'est lui qui les rejoue contre les adaptateurs). Seed A et seed B avec des campagnes et grappes de mules **différentes** | `make data SEED=A` et `SEED=B` sont déterministes (même seed → mêmes fichiers) |
| 4 | 01:00–03:30 | Features → LightGBM (jours 1–20 train, 21–25 validation sur A) → calibration isotonic → seuils réglés pour : légitimes à MEDIUM+ ≤ 2 % et précision HIGH ≥ 90 % → raisons via `model.predict(X, pred_contrib=True)` traduites en phrases | **CP2** : `score()` utilise le modèle ; p95 < 300 ms |
| 5 | 03:30–04:45 | **Éval sur seed B** (§17.2–17.3) : baselines (règles seules, **institution isolée**, régression logistique) ; ablations (règles → + provenance/bénéficiaire → + session → **+ géographie** → + réseau → **+ normes**) à taux de faux positifs égal ; métriques du §17.3 → `ml/metrics.json` | `make eval SEED=B` régénère le fichier à l'identique |
| 6 | 04:45–05:00 | **Model card** courte `docs/model-card.md` (usage, données, limites, AI Act Annex III 5(b)) ; envoyer les chiffres clés à Omama pour la slide | Omama a les chiffres |
| 7 | 05:00–06:00 | Préparer la réponse à « Vos données sont synthétiques » et « Si votre modèle se trompe, qui est responsable ? » (PRD §22.3, §12.4) | 20 s chacune |

**Format de `ml/metrics.json`** (lu par la console et le deck) :
```json
{ "seed": "B", "modelVersion": "…", "n_payments": 20000,
  "recall_T1": 0.0, "recall_all": 0.0, "precision_high": 0.0, "fpr_medium_plus": 0.0,
  "pct_detected_before_execution": 0.0, "decision_p95_ms": 0,
  "baselines": [{"name": "rules_only", "recall_all": 0.0, "fpr_medium_plus": 0.0}],
  "ablations": [{"step": "+geography", "recall_all": 0.0, "fpr_medium_plus": 0.0}] }
```

## 4. Pièges

- **Le modèle apprend un raccourci du simulateur** (ex. tous les mules ont exactement 9 jours) → chiffres trop beaux et un juge le verra. Mettre de la variance partout et du bruit honnête.
- Les grappes de mules de B ne doivent **jamais** apparaître dans A.
- Ne jamais ajuster un seuil de **règle** pour améliorer les chiffres : seules les zones grises du modèle se règlent (budget d'alertes, §10.3).
- Si le modèle n'est pas prêt à 03:30 → règles + régression logistique (cut list), et tu passes à l'éval.

## 5. Ce que tu attends des autres / ce que tu livres

- **Reçois** : validation du `RiskContext` et format des scénarios d'intégrité (Devin, 21:30–22:00).
- **Livres** : `score()` règles seules (23:00), `score()` modèle (03:30), `ml/metrics.json` + model card (05:00).
