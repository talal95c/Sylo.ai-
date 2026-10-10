# Brique 4 — Expérience & démo · Lane D · `/web` (+ deck, vidéo)

**Mission :** ce que le jury voit et retient : le globe, le parcours du paiement, l'alerte, les panneaux humains (payeur, téléphones, analyste), la preuve on-chain, la console d'attaque, puis le deck et la vidéo de secours. **Le web dessine, il ne décide jamais** : tout vient des events du moteur ou des fixtures.

## Livrables (par ordre de priorité)

**Étape 0** : choisir la base `/web` entre l'UI claire de `lane-d/web-v0` (déjà sur `main`) et celle de la v0 retenue, la brancher sur `spec/fixtures` (le script `sync-spec.mjs` lit déjà `/spec` s'il existe), vérifier le replay des 5 fixtures.

**v1 (→ 03:30)** — tout se code contre `samples-v1.jsonl` avant que les endpoints existent
1. Polish du globe + chorégraphie caméra par scène (D1.1).
2. Panneau payeur Claire/Marc : routes, routes exclues avec la règle, double validation (D1.2).
3. Téléphones : Claire (in-app/SMS, jamais e-mail) et Kwame (Confirmer / Refuser) (D1.3).
4. Panneau preuve + bandeau de mode (simulé / réel / dégradé) (D1.4).
5. Tiroir analyste avec le dossier de la brique 1 et ses citations cliquables (D1.5).
6. Console d'attaque : 3 boutons, croix rouge là où l'attaque est refusée (D1.6).

**v2 (03:30 → 04:30 puis 08:00 → 09:00)**
7. Cluster de mules + disjoncteur sur le globe (D2.1), panne + reroutage (D2.2), visuels d'incident (D2.4).
8. Page `/metrics` alimentée par `metrics.json` de la brique 1 (D2.3).
9. **Vidéo de secours** depuis le tag `v2` (D2.7).

**v3 (si temps)** : page auditeur qui recalcule le hash d'intention dans le navigateur (D3.1).

## Dépend de / attend

- Brique 3 : events + endpoints (samples d'abord). Brique 1 : `case-sample.json`, `metrics.sample.json`. Brique 2 : liens explorer.

## Ne jamais couper

Alerte, panneaux payeur / téléphone / preuve, console d'attaque, repli replay.

## Pitch

Deck assemblé et designé, vidéo, fiche de défense (consolidée avec les 3 autres).

## Prompt de démarrage (agent orchestrateur)

```
Tu travailles sur Sylo.ai, brique 4 « Expérience & démo » (Lane D). Lis AGENTS.md, docs/equipe/README.md,
docs/equipe/4-experience-demo.md, les sections Lane D de docs/roadmap-and-lanes.md et docs/v0-build-spec.md §4.2 et §8.
Tu n'écris que sous /web. Style : clair, minimaliste, micro-animations, pas d'« IA slop » ; garder la DA existante.
Sous-agents en parallèle, un par panneau (payeur, téléphones, preuve, analyste, console d'attaque),
une branche lane-d/<id>-<slug> et une petite PR chacun. Code contre les fixtures et samples de /spec ;
jamais de logique de décision dans le front. Avant de finir : pnpm -C web test, typecheck et build verts.
```
