# Expérience & démo — globe, console, pitch · Lane D · `/web`

**Mission (PRD §7, M10, M13, §22)** : ce que le jury voit et retient. Les scènes 1, 2 et 2b doivent être **lisibles sans narration**, et tout ce qui s'affiche vient du flux d'events du moteur ou des fixtures : **le web dessine, il ne décide jamais**. Base : l'UI claire et minimaliste déjà sur `main` (globe pointillé, carte de paiement, étapes de décision, fil d'events, alerte, contrôles).

## Livrables

**Globe, vue principale (M13)** : institutions en nœuds, rails en arcs ; la route choisie se dessine hop par hop depuis `route.selected`, `leg.sent`, `leg.settled` ; la trace s'arrête et change de couleur sur séquestre, hold ou blocage ; alertes et pannes sur le globe. < 1 s entre un event et son dessin ; ≤ 200 arcs animés ; assets servis en local ; le fil texte montre les mêmes events et marche sans WebGL.

**Console (M10)**
- **Vue payeur** (Claire, Marc) : routes avec la décomposition du score, routes exclues avec la règle et sa référence légale, notice fiscale, prix de la sécurité, approbation et co-approbation.
- **Téléphones** : Claire (in-app / SMS, **jamais e-mail**) et Kwame (demande hors bande, Confirmer / Refuser), statut de la vérification SIM-swap.
- **Panneau preuve** : chaque event chaîne avec fonction, statut avant → après, hash court avec lien explorer, ou badge « simulé » ; transactions refusées en rouge avec la raison.
- **Analyste** : file et dossier, raisons avec références, dossier du Système 2 avec citations cliquables, actions Confirmer la révocation / Libérer / Geler, compte à rebours d'expiration 24 h.
- **Console d'attaque** (scène 2b) : libérer un paiement révoqué, changer le bénéficiaire, rejouer ; croix rouge là où c'est refusé.
- **Bandeau de mode** : ce qui est réel, simulé, dégradé (`system.mode`).
- **Page métriques** : chiffres de `metrics.json` (seed B), modèle vs baselines, ablations ; « sample » en gros tant que c'est l'exemple.

**P1** : cluster de mules en hexagones près d'Aflao + disjoncteur (scène 3), incident guardian (scène 4), panne + reroutage (scène 5), vue auditeur eERC, page auditeur qui recalcule le hash d'intention dans le navigateur.

**Pitch (§22)** : deck (≈ 4 min : problème chiffré, démo live, comment ça marche, preuve, chiffres, conformité, modèle économique, équipe), **vidéo de secours** enregistrée depuis le dernier tag vert, fiche de défense consolidée avec les 3 autres briques.

## Ordre de travail

| Version | Tâches |
|---|---|
| v0 | Garder l'UI actuelle et la brancher sur `spec/fixtures` + le flux SSE live du squelette fusionné ; vérifier le replay des scènes |
| v1 | Polish globe + caméra par scène (D1.1) → vue payeur (D1.2) → téléphones (D1.3) → panneau preuve + bandeau (D1.4) → analyste (D1.5) → console d'attaque (D1.6) — tout contre `samples-v1.jsonl` avant que les endpoints existent |
| v2 | Cluster + disjoncteur (D2.1) → panne (D2.2) → page métriques (D2.3) → incidents (D2.4) → **vidéo de secours** (D2.7) |
| v3 | Page auditeur ou vue banque destinataire |

**Couper en premier → en dernier** : trafic de fond → vue auditeur eERC → extras du globe. **Jamais** : alerte, vues payeur / téléphone / preuve, console d'attaque, repli replay.

## Prompt de démarrage (agent orchestrateur)

```
Tu travailles sur Sylo.ai, brique « Expérience & démo » (Lane D). Lis AGENTS.md, plan/README.md, plan/experience.md,
puis PRD §7, M10, M13, §15.3, docs/v0-build-spec.md §4.2 et §8 et les sections Lane D de docs/roadmap-and-lanes.md.
Tu n'écris que sous /web. Style : clair, minimaliste, micro-animations, pas d'« IA slop » ; garder la DA existante.
Sous-agents en parallèle, un par panneau (payeur, téléphones, preuve, analyste, console d'attaque, métriques),
une branche lane-d/<id>-<slug> et une petite PR chacun. Code contre les fixtures et samples de /spec ;
aucune logique de décision dans le front. Avant de finir : pnpm -C web test, typecheck et build verts.
```
