# Sylo.ai

> Routeur de paiements transfrontaliers sûr : la route la moins chère quand tout va bien, une fenêtre pour arrêter l'argent quand quelque chose cloche.

Projet présenté au hackathon **Secure Horizons** (ESSEC, 10–11 octobre 2026) sur la **Track 1** (Fintech Security: Guardians of Value), avec une ouverture possible sur la **Track 3**. Le PRD l'appelle de son nom de travail, **L'Aiguilleur**.

📄 **Document de référence : [`prd-final.md`](./prd-final.md)** (PRD final v3.0, fusion des quatre PRD de l'équipe).

---

## Le problème

Un paiement transfrontalier traverse des systèmes qui ne se parlent pas : banques correspondantes, prestataires de paiement, mobile money, stablecoins. Chaque pays a ses propres règles (contrôle des changes, lutte anti-blanchiment, crypto, fiscalité). Chaque institution ne voit que son tronçon du paiement, et les fraudes (faux fournisseur, réseau de mules, prise de contrôle de compte) passent entre ces tronçons. En Europe, la vérification du nom du bénéficiaire s'arrête aux frontières de la zone SEPA : elle ne couvre pas un paiement vers Accra.

## La solution

Sylo.ai est une couche d'orchestration logicielle posée **au-dessus de rails agréés** : ce n'est pas une banque et elle ne détient pas les fonds. Avant que l'argent ne bouge, chaque paiement suit cet ordre de décision :

```
1. NORMES   routes légales au départ, en transit et à l'arrivée (la règle la plus stricte gagne)
2. RISQUE   le niveau de fraude restreint les routes autorisées ; il n'entre jamais dans le score de coût
3. COÛT     meilleure route restante (frais, change, délai, probabilité d'échec)
4. COMMIT   bénéficiaire, montant et décision signés (EIP-712) et engagés on-chain
5. ACTION   exécution, règlement conditionnel ou retenue
```

| Niveau de risque | Réponse |
| --- | --- |
| Faible | Meilleure route conforme |
| Moyen | Séquestre on-chain ou retenue fiat ; les fonds ne sont libérés qu'après une vérification hors bande sur le contact **déjà connu**, précédée d'un contrôle de SIM swap ; sinon remboursement automatique au bout de 24 h |
| Élevé | Signature bloquée ; le payeur et l'analyste sont alertés |
| Critique | Blocage, dossier d'enquête et déclaration de soupçon pré-remplie |

En plus : un **coupe-circuit** quand une vague de fraude frappe une région, et un **kill switch** quand un connecteur de rail est compromis.

**Garanties clés**
- **Pas de substitution** : chaque connecteur de rail vérifie l'empreinte de l'intention signée (`intent_hash`) avant d'exécuter. Un bénéficiaire ou un montant modifié est refusé, et la transaction on-chain échoue (revert).
- **L'IA ne décide pas** : Jev (Système 1) note la sémantique de la facture au moment de la signature ; Mistral (Système 2) rédige le dossier d'enquête et l'explication. Aucun modèle ne peut libérer de fonds.
- **Échec sûr** : si l'IA ou la chaîne tombe en panne, le système devient plus strict, jamais plus laxiste.
- **Preuve** : journal hash-chaîné, et `IntentRegistry` sur Avalanche avec des attestations EIP-712 (`PaymentCommitment`, `VerificationAttestation`, `Revocation`), vérifiables par un tiers sur l'explorer.

## La démo (3 min)

Corridor principal : **France → Ghana**. Claire, à Lyon, paie 85 000 € en EURC à son fournisseur de beurre de karité, Savanna Shea Exports.

1. **Paiement légitime** : le moteur de normes écarte une route et explique pourquoi ; la route conforme la moins chère est choisie et l'engagement apparaît sur l'explorer.
2. **Facture détournée** : un e-mail « nouvelles coordonnées bancaires » envoie le paiement vers un compte de mule. Résultat : niveau moyen, séquestre, vérification hors bande refusée, révocation et remboursement, chaque étape visible on-chain.
3. **Tentative de substitution ou de rejeu** : le rail refuse la jambe, la transaction échoue on-chain, et le connecteur est coupé.
4. **Réseau de mules** : la grappe est détectée et le coupe-circuit régional s'active.
5. **Bilan** : les indicateurs mesurés sur un jeu de données que le modèle n'a pas vu à l'entraînement.

Bonus (P1) : un second corridor **Lagos → Accra** (PAPSS, mobile money), chargé à partir d'un seul fichier, sans toucher au cœur. Paris → Abidjan reste décrit sur papier.

## Architecture

| Couche | Technologies prévues |
| --- | --- |
| Console analyste, globe en direct, signature | Next.js, TypeScript, Tailwind, react-globe.gl, viem |
| Normes, routage, risque, simulateur, évaluation | Python, FastAPI (flux SSE), networkx, CVXPY, scikit-learn |
| IA | Jev (Système 1), Mistral (Système 2) |
| Chaîne | Solidity + Foundry : `IntentRegistry`, séquestre ; L1 Avalanche dédiée ou Fuji C-Chain ; eERC pour les transferts confidentiels (P1) |
| Stockage | Supabase / Postgres |

## Statut et limites

- Hackathon, preuve de concept : **tous les rails, les flux et les comptes sont simulés**. Aucune donnée réelle, aucun vrai rail connecté.
- Les coûts et délais affichés sont illustratifs ; seuls les indicateurs de sécurité sont mesurés.
- Décisions encore ouvertes (voir §20 du PRD) : durée réelle du build, détenteurs de la clé auditeur et des clés d'attestation, cible chaîne finale (L1 dédiée ou Fuji).

## Contenu du dépôt

| Fichier | Rôle |
| --- | --- |
| [`prd-final.md`](./prd-final.md) | PRD final v3.0 : vision, exigences, démo, architecture, conformité, planning |
