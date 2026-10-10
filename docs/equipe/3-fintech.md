# Brique 3 — Fintech (moteur de paiement) · Lane A · `/engine`, `/scripts`, racine, `.github`

**Mission :** le métier du paiement transfrontalier : quelles routes sont **légales** (normes FR/GH), laquelle est **la moins chère et sûre** (le risque de fraude n'entre jamais dans ce score), les **contrôles humains** (double validation, vérification hors bande), l'**exécution** sur les rails et l'orchestration de tout le pipeline `normes → risque → coût → commit → action`. C'est aussi la brique qui branche les autres (ports) et garantit que la démo tourne.

## Livrables (par ordre de priorité)

**v1 (→ 03:30)**
1. **PR spec (20 min)** : events et endpoints v1 + `samples-v1.jsonl` (A1.0). Validation : 3 + 4. Valider aussi la PR `CasePort` de la brique 1.
2. Approbation payeur + double contrôle ≥ 20 k€ (A1.3) ; vérification hors bande + mock SIM-swap (A1.4) ; actions analyste (A1.8). → débloque les panneaux de la brique 4 : livrer les endpoints tôt.
3. **Adaptateurs de rails R1–R4** (interface unique `quote/initiate/status`, contrôle du hash d'intention avant chaque jambe) + attaques `swap_beneficiary` et `replay` (A1.5).
4. Branchements : `CHAIN_MODE=fuji` (A1.1, dès que la brique 2 livre), `RISK_MODE=model` (A1.2, dès que la brique 1 livre), `LLM_MODE` → appel de `CasePort` et émission de `case.ready` (le contenu est fait par la brique 1).
5. Fixtures ré-enregistrées + `make demo-check` (A1.9). Journal chaîné + endpoint `/proof` (A1.6) si temps.

**v2 (08:00 → 09:00, stubs dès 03:30)**
6. Disjoncteur régional sur cluster de mules (A2.1), panne de rail + reroutage (A2.2), kill switch + mode dégradé (A2.3), réception des incidents du guardian avec brouillon DORA (A2.4).

**v3 (si temps)** : corridor n°2 Lagos → Accra en un seul fichier (A3.1) — « un nouveau corridor = un fichier ».

## Dépend de / attend

- Brique 1 : `ModelRisk` (02:15) et `CaseWriter`. Brique 2 : adresses Fuji (01:00), `FujiChain` (02:15). Tant que ce n'est pas là : `rules`, `mock`, `cached` — on ne bloque jamais.

## Ne jamais couper

Approbation, adaptateurs + attaques, actions analyste, intégration Fuji, fixtures + `demo-check`.

## Pitch

Pilote de la démo (run sheet, boutons, replis), playbook de réponse, slide « adoption : pilote banque en shadow mode ».

## Prompt de démarrage (agent orchestrateur)

```
Tu travailles sur Sylo.ai, brique 3 « Fintech » (Lane A, moteur). Lis AGENTS.md, docs/equipe/README.md,
docs/equipe/3-fintech.md, les sections Lane A de docs/roadmap-and-lanes.md, et docs/v0-build-spec.md §4–5.
Tu n'écris que sous /engine, /scripts, les fichiers racine et .github (et /spec par PR additive validée par 2 briques).
L'agent Mistral appartient à la brique 1 : tu appelles seulement CasePort et émets case.ready.
Sous-agents en parallèle : (a) approbation + hors bande + actions analyste, (b) adaptateurs de rails + attaques,
(c) branchement des ports + fixtures + demo-check ; une branche lane-a/<id>-<slug> et une petite PR chacun.
Commence par la PR spec A1.0 avec samples-v1.jsonl.
Règles : le risque de fraude n'entre jamais dans le score de route ; intention engagée avant tout mouvement ;
jamais d'alerte payeur par e-mail ; fail safe. Avant de finir : cd engine && uv run pytest et make fixtures-check verts.
```
