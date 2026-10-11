# Autocritique — IA & sécurité (Lane B)

Ce document recense ce que nos chiffres ne prouvent pas, ce qui manque, et ce qu'un jury ou une banque pourrait attaquer. Chaque point suit le même plan : le constat, la preuve, l'impact, puis la parade (faite ou à faire). Les chiffres viennent de `ml/reports/metrics.json` (modèle `gbm-20261011`, seed d'entraînement A, éval B, hors distribution C).

## 1. Données et validité des chiffres

**1.1 Évaluation circulaire.** Nous avons écrit le simulateur, les typologies et le modèle. La seed C est décalée, mais elle sort du même générateur. Une AUC de 0,998 mesure surtout notre capacité à apprendre nos propres règles de génération. *Impact :* aucun chiffre n'est transposable à une vraie banque. *Parade :* le dire sur la slide. L'étape suivante serait un jeu public (Feedzai BAF, IBM AML-Data) ou un pilote sur des données réelles pseudonymisées.

**1.2 La prévalence irréaliste gonfle la précision.** Il y a 1 500 fraudes pour 150 000 paiements, soit 1 %. La précision dépend de la prévalence. À taux de détection et de faux positifs égaux, nos 89,9 % de précision en HIGH tomberaient à environ 47 % pour une prévalence de 0,1 %, et à environ 8 % pour 0,01 %. Le même calcul vaut pour les retenues MEDIUM+ (98 % de rappel, 6,72 % de faux positifs). À 1 %, environ 13 % des retenues sont des fraudes ; à 0,1 %, environ 1,4 %, soit à peu près 68 paiements légitimes retenus par fraude. *Impact :* la charge analyste réelle serait bien plus lourde que ce que suggère le pitch. *Parade :* présenter le résultat comme « coût par fraude stoppée » à plusieurs prévalences, et non comme une précision brute.

**1.3 Pas de boucle de labels.** En réalité, une fraude est confirmée des jours ou des semaines plus tard, et le modèle dérive. Nous n'avons ni labels retardés, ni suivi de dérive, ni procédure de ré-entraînement ou de rollback. *Parade (à faire) :* suivi de la population par feature (PSI), score mesuré sur une fenêtre glissante, seuils re-gelés après validation humaine.

**1.4 Rappel T1 à 100 % : circulaire.** Le simulateur donne à chaque T1, même « évasif », une provenance non fiable et un nouveau compte : la règle de garantie R-PV-01 les attrape par construction (la baseline rules_only fait aussi 100 % sur T1). Ce chiffre prouve que la garantie est câblée, pas que le modèle détecte le faux fournisseur. *Parade :* générer des T1 vers un compte déjà payé ou avec une provenance fiable (mule « vieillie », registre fournisseur compromis) et mesurer. <!-- metrics.json: /byTypology/0/recall, /baselines/2/recallT1 -->

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
- Le détecteur du moteur (`WindowClusterDetector`) ne connaît pas le payeur : 3 paiements d'un même payeur vers 3 comptes jeunes d'une banque frontalière déclenchent aussi un cluster ; sa précision n'est mesurée que par le test de la scène 3, pas par le benchmark hors ligne.
- La fenêtre du moteur couvre 1 h et fixe `day = 0`, alors que le benchmark travaille par jours : la scène 3 et le benchmark ne testent pas exactement la même fenêtre.
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
