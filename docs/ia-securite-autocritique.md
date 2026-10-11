# Autocritique — IA & sécurité (Lane B)

Ce document recense ce que nos chiffres ne prouvent pas, ce qui manque, et ce qu'un jury ou une banque pourrait attaquer. Chaque point suit le même plan : le constat, la preuve, l'impact, puis la parade (faite ou à faire). Les chiffres viennent de `ml/reports/metrics.json` (modèle `gbm-20261011`, seed d'entraînement A, éval B, hors distribution C).

## 1. Données et validité des chiffres

**1.1 Évaluation circulaire.** Nous avons écrit le simulateur, les typologies et le modèle. La seed C est décalée, mais elle sort du même générateur. Une AUC de 0,998 mesure surtout notre capacité à apprendre nos propres règles de génération. *Impact :* aucun chiffre n'est transposable à une vraie banque. *Parade :* le dire sur la slide. L'étape suivante serait un jeu public (Feedzai BAF, IBM AML-Data) ou un pilote sur des données réelles pseudonymisées.

**1.2 La prévalence irréaliste gonfle la précision.** Pour seed B, la précision et les retenues légitimes par fraude attrapée varient ainsi selon la prévalence :

| Prévalence | Précision MEDIUM+ | Retenues légitimes / fraude attrapée MEDIUM+ | Précision HIGH+ | Retenues légitimes / fraude attrapée HIGH+ |
|---:|---:|---:|---:|---:|
| 1 % | 12,85 % | 6,78 | 89,86 % | 0,11 |
| 0,1 % | 1,44 % | 68,44 | 46,76 % | 1,14 |
| 0,01 % | 0,15 % | 684,97 | 8,07 % | 11,39 |

MEDIUM+ utilise un TPR de 98,13 % et un FPR de 6,72 %. HIGH+ utilise un TPR de 73,87 % et un FPR légitime de 0,0842 %, recalculé en rejouant seed B dans `_score_engine` avec le modèle gelé, sans ré-entraînement (125 HIGH+ légitimes sur 148 500). Ces extrapolations partent de données synthétiques et ne prédisent pas les performances d'une banque. *Impact :* à faible prévalence, la charge analyste dépasse largement le nombre de fraudes attrapées. *Parade :* présenter le « coût par fraude attrapée » à plusieurs prévalences, et non une précision brute.
<!-- MEDIUM+: ml/reports/evasion.json#/prevalence_table/medium_plus/rows; TPR/FPR: ml/reports/metrics.json#/metrics/recallAll, #/metrics/fprMediumPlus. HIGH+: ml/reports/evasion.json#/prevalence_table/high_plus/tpr, #/prevalence_table/high_plus/fpr, #/prevalence_table/high_plus/rows; method: #/prevalence_table/high_plus/method. -->

**1.3 Pas de boucle de labels.** En réalité, une fraude est confirmée des jours ou des semaines plus tard, et le modèle dérive. Nous n'avons ni labels retardés, ni suivi de dérive, ni procédure de ré-entraînement ou de rollback. *Parade (à faire) :* suivi de la population par feature (PSI), score mesuré sur une fenêtre glissante, seuils re-gelés après validation humaine.

**1.4 Rappel T1 à 100 % : circulaire.** La baseline `rules_only` attrape 100 % des T1, ce qui montre d'abord que R-PV-01 est câblée, pas que le modèle reconnaît le faux fournisseur. J'ai donc échantillonné avec remise 2 000 lignes par niveau à partir des 450 T1 synthétiques de seed B; les historiques sont définis par les agrégats observés, pas simulés comme des événements.

| Niveau | Signaux retirés / modifiés | Rappel MEDIUM+ | Rappel HIGH+ | Séquestre HIGH + OOB | Action bloquante | Modèle seul MEDIUM+ |
|---|---|---:|---:|---:|---:|---:|
| E0 | T1 courant | 100,00 % | 76,45 % | 19,85 % | 56,60 % | 92,95 % |
| E1 | Provenance `verified_registry` | 92,95 % | 76,45 % | 19,85 % | 56,60 % | 92,95 % |
| E2 | Compte ≥90 jours, ≥3 paiements réussis agrégés, non détenu par le fournisseur; compte précédent conservé, `history_count` ≥1 | 92,65 % | 75,30 % | 19,85 % | 55,45 % | 92,65 % |
| E3 | Le fournisseur détient le compte et l'historique agrégé indique ce même compte | 75,50 % | 51,50 % | 13,75 % | 37,75 % | 67,35 % |

E3 n'est pas proche de zéro : le moteur attrape encore 75,50 % à MEDIUM+ et 51,50 % à HIGH+ dans cet échantillon synthétique, mais le rappel baisse nettement par rapport à E0. Le rappel MEDIUM+ d'E0 à 100 % ne survit donc pas à une provenance fiable; la combinaison E3 contourne aussi les signaux d'ancienneté, de détention et de changement de compte. Ces chiffres mesurent uniquement le simulateur seed B, pas une efficacité réelle. <!-- metrics.json#/baselines/2/recallT1; evasion.json#/levels/0, #/levels/1, #/levels/2, #/levels/3, #/sampling/source_t1_count -->

## 2. Cibles du PRD manquées

| Mesure | Résultat | Cible |
|---|---|---|
| Faux positifs MEDIUM+, B | 6,72 % | ≤ 2 % |
| Précision HIGH+, B | 89,86 % (IC 88,1–91,4) | ≥ 90 % |
| Rappel T4 (fractionnement), B | 93,3 % (IC 90,3–96,0) | non fixée, mais plus faible typologie |
| Négatifs difficiles retenus | 47,6 % | — |

80,5 % des retenues légitimes sont voulues : il s'agit de la garantie hors bande sur un nouveau bénéficiaire. Il reste un coût réel de friction. Près d'un vrai changement de banque fournisseur sur deux est retenu. Les fournisseurs ghanéens dont le nom commercial diffère du nom légal sont aussi pénalisés, avec un risque de biais lié aux conventions de nommage et de translittération.

## 3. Garantie hors bande (OOB) : le cœur, et ses angles morts

- **Elle vaut ce que vaut le registre des contacts.** Si l'attaquant modifie le contact enregistré avant le changement de RIB (prise de contrôle de l'ERP ou du fichier fournisseurs du payeur, ou complicité interne), la confirmation part chez lui. Nous ne modélisons ni la provenance ni l'ancienneté des modifications du registre.
- **Le téléphone du fournisseur lui-même** (SIM swap, ingénierie sociale par appel) : le contrôle SIM swap existe côté démo (scénario `diverted_simswap`), mais il dépend d'une API opérateur que nous simulons.
- **Un compte mule déjà nominé ou déjà payé** échappe aux règles « nouveau compte ». Seuls le modèle et les clusters le voient. C'est précisément la population où le modèle rate des T1 évasifs (RESEARCH R2).
- **Fournisseur injoignable :** le séquestre a une expiration (`expiresAt`, puis remboursement), mais nous n'avons pas mesuré l'impact commercial des délais.
- **Le séquestre détient des fonds.** Le README dit que Sylo « ne détient jamais l'argent », alors que `PaymentEscrow` détient des EURC. Il faut expliquer qui est le dépositaire en droit (partenaire PSP ou EMI) au regard de la DSP2 et de MiCA, sinon un juriste attaquera ce point.

## 4. Modèle

- **Évasion adaptative non mesurée.** Le tableau « coût d'évasion » de la to-do n'est pas fait. Les contraintes monotones et les features connues rendent le modèle prévisible : un attaquant qui vieillit un compte mule, l'utilise pour quelques petits paiements légitimes puis frappe, contourne la plupart des signaux B, H et N.
- **Plafond à 89 :** le modèle seul ne peut jamais déclencher CRITICAL. C'est voulu (contrôle humain), mais un modèle très sûr de lui reste au niveau HIGH.
- **Pas de signaux comportementaux, d'appareil ou de consortium réels.** Le signal « session » est simulé.
- **Latence :** 0,73 ms au p95, mesurée pour le scoring sur une VM et un seul thread. Il n'y a eu ni test de charge, ni mesure de la latence de bout en bout du moteur.
- **Calibration :** isotonic sur A. Elle est calibrée pour notre prévalence de 1 % et serait mal calibrée ailleurs (voir 1.2).

## 5. Mode dégradé

C'est sûr mais peu exploitable. Sans modèle, 43 % des paiements légitimes sont retenus. Sans historique, 100 % le sont et plus rien ne passe en traitement direct (STP 0 %). Le mode reste aussi légèrement plus laxiste que le mode normal sur une petite fraction des paiements : 0,11 % des actions sans modèle, 0,19 % sans historique (`neverLooser = false`). Une panne d'historique gèle donc toute l'activité. *Parade (à faire) :* un cache d'historique local de secours, et un SLA de retour au mode normal.

## 6. Clusters de mules

- La campagne synthétique de « fan-in » est facile. On obtient 30/30 détections, mais aussi 30/30 faux clusters sur les comptes légitimes jeunes et populaires.
- Les agents de retrait (cash-out) ne sont pas modélisés (`agents = []`), alors que la roadmap les cite.
- La vue réseau suppose que plusieurs banques partagent des données. La faisabilité juridique (RGPD, secret bancaire, ghanaian Data Protection Act) n'est pas démontrée.
- Le moteur et le benchmark hors ligne utilisent le même détecteur (`NetworkXClusterDetector`), mais la scène 3 valide l'adaptation des paiements du moteur, pas la précision hors échantillon ni en production.
- La fenêtre du moteur couvre 1 h, tandis que le benchmark travaille par jours : la scène 3 et le benchmark ne testent pas exactement la même fenêtre.
- Les comptes inconnus, dont l'âge ou le nombre de paiements n'est pas connu, sont traités comme suspects. C'est le choix prudent, mais il peut générer des faux clusters sur les comptes absents du registre.

## 7. LLM (Jev, Mistral)

- **Jev, petits échantillons :** 30 messages tenus à part, écrits par nous. Une précision de 100 % sur 30 messages a un intervalle de confiance large.
- **Jev est lui-même manipulable.** La question « injection » n'attrape que 11 des 20 variantes du red team (14 sur 20 avec la question « pression »), et 6 sur 20 passent les trois questions. C'est une défense de profondeur, pas une garantie.
- **Côté moteur, le validateur accepte toujours les références `TX-*`,** même si aucun document n'a été analysé. Seul le validateur de Lane B (`_allowed_refs`) les limite au gabarit. La défense en profondeur est donc plus faible sur ce point.
- **Le validateur Mistral vérifie que les références citées existent, pas que la phrase dit vrai.** Une phrase correctement citée peut encore mal résumer le signal. C'est un risque d'excès de confiance de l'analyste.
- **En démo, les deux tournent en cache.** Ni la latence ni la disponibilité en live ne sont démontrées devant le jury.
- **Les deux sont des API tierces hébergées.** Des données (pseudonymisées) quittent notre périmètre, et il faut un DPA et une base de transfert hors UE.
- **Le gain de temps analyste n'est pas mesuré :** le protocole existe (5 cas, 2 testeurs), le test n'a pas été lancé.

## 8. Sécurité du système lui-même

- **Clés API collées en clair dans le chat** (Codiv, Mistral) : il faut les régénérer après le hackathon.
- **Je n'ai trouvé aucune authentification sur l'API du moteur** (`engine/sylo/main.py`), y compris sur les endpoints `/v1/sim/*`. C'est acceptable en démo locale, pas exposé tel quel.
- **Clé du vérificateur volée (scène 4) :** le gardien gèle avant la libération. La course entre les deux n'est fermée que par une fenêtre de contestation, qui est sur la roadmap.

## 9. Démo et honnêteté

Avant `devin/scene2-fixes`, plusieurs points ne montraient pas les nouvelles capacités IA :
- les fixtures du mode replay étaient enregistrées en mode règles (MEDIUM 64, dossier gabarit) ;
- la carte affichait le niveau d'action (MEDIUM) au lieu du niveau de risque (HIGH) ;
- le dossier ne recevait pas la facture, donc aucune phrase Jev n'apparaissait.

Ces trois points sont corrigés : les replays sont enregistrés en `model/cached` et le dossier cite `TX-CHANGE` et `TX-INJECTION`. Le SIM swap, l'historique, les rails et le fiat restent simulés et étiquetés comme tels.

**Reproductibilité :** un ré-entraînement sur la seed A redonne les mêmes seuils et des scores identiques sur 10 000 lignes de B. Pourtant, 88 des 4 562 lignes du texte des arbres LightGBM diffèrent. Le résultat est reproductible fonctionnellement, mais pas octet pour octet.

## 10. Priorités si on continue

1. Afficher le « coût par fraude stoppée » à plusieurs prévalences (1.2). C'est le chiffre le plus trompeur aujourd'hui.
2. Produire le tableau du coût d'évasion, et un test « mule vieillie » (4).
3. Protéger le registre des contacts : historique horodaté des modifications, et blocage de toute confirmation vers un contact modifié depuis moins de N jours (3).
4. Clusters : modéliser les agents de retrait et réduire les faux clusters sur les comptes jeunes et populaires (6).
5. Lancer le test de temps analyste, et rendre le validateur Mistral sémantique : chaque phrase doit être comparée à la valeur du signal cité (7).
6. Authentifier l'API, et régénérer les clés (8).
