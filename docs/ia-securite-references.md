# IA sécurité — références et valeur ajoutée

Chaque décision du plan ([`plan/ia-securite.md`](../plan/ia-securite.md)) s'appuie sur une architecture ou une publication éprouvée. « Vérifié » = page source ouverte pendant la rédaction (titre/identifiant confirmés) ; « mémoire » = référence connue mais non rouverte, à vérifier avant de la citer sur une slide.

## Sources par décision

| Décision | Source | Ce qu'on reprend | Vérifié |
|---|---|---|---|
| D1 — garantie OOB indépendante du score | Règlement (UE) 2024/886 (paiements instantanés, *Verification of Payee*) — https://eur-lex.europa.eu/eli/reg/2024/886/oj | Vérifier le nom du bénéficiaire avant l'envoi ; on l'étend au corridor FR–GH, hors zone VoP | vérifié (URL) |
| D1 — fraude au virement autorisé (APP / BEC) | UK Payment Systems Regulator, APP scams — https://www.psr.org.uk/our-work/app-scams/ ; FBI IC3 Annual Report 2023 — https://www.ic3.gov/AnnualReport/Reports/2023_IC3Report.pdf | Le faux fournisseur est la typologie à plus forte perte ; remboursement obligatoire au UK ⇒ la banque paie l'erreur | vérifié (URL) |
| D3 — CRITICAL réservé aux règles / humains | Règlement (UE) 2024/1689 (AI Act), contrôle humain (art. 14) ; annexe III 5(b) exclut la détection de fraude financière du haut risque — https://eur-lex.europa.eu/eli/reg/2024/1689/oj | Le modèle ne déclenche aucune action sur un tiers ; humain dans la boucle | vérifié (URL), articles : mémoire |
| D4 — GBM calibré + règles plancher | Ke et al., *LightGBM*, NeurIPS 2017 | Modèle tabulaire rapide, contraintes monotones | mémoire |
| D4 — calibration isotone | Niculescu-Mizil & Caruana, *Predicting Good Probabilities with Supervised Learning*, ICML 2005 | Isotone sur un jeu de calibration séparé | mémoire |
| D4/D7 — éval temporelle, précision sur budget d'alertes | Dal Pozzolo et al., *Credit Card Fraud Detection: A Realistic Modeling and a Novel Learning Strategy*, IEEE TNNLS 2018 | Split temporel, précision@k (capacité analystes), dérive | mémoire |
| D6 — raisons par modèle | Lundberg et al., *Explainable AI for Trees* (TreeSHAP) — arXiv:1905.04610 | Contributions exactes par feature ⇒ raisons en langage clair | vérifié |
| D6 — quarantaine de l'agent Mistral | Greshake et al., *Indirect Prompt Injection* — arXiv:2302.12173 ; Hines et al., *Spotlighting* — arXiv:2403.14720 | Texte de facture balisé comme donnée, jamais instruction | vérifié |
| D6 — séparation plan/données de l'agent | Debenedetti et al., *CaMeL: Defeating Prompt Injections by Design* — arXiv:2503.18813 ; Beurer-Kellner et al., *Design Patterns for Securing LLM Agents against Prompt Injections* — arXiv:2506.08837 | Motif « LLM sans outils dont la sortie ne contrôle aucun flux » + validateur de citations | vérifié |
| D7 — éval anti-circulaire sur synthétique | Jesus et al., *Turning the Tables* (Bank Account Fraud, Feedzai), NeurIPS 2022 — arXiv:2211.13358 ; Altman et al., *Realistic Synthetic Financial Transactions for AML* (IBM AMLworld), NeurIPS 2023 — arXiv:2306.16424 | Données biaisées/dynamiques, seed hors distribution, typologies explicites | vérifié |
| D9 — mules en graphe | Weber et al., *AML in Bitcoin with GCNs* (Elliptic) — arXiv:1908.02591 ; IBM AMLworld (motifs fan-in/fan-out) | v2 : composantes connexes simples avant tout GNN | vérifié |
| Piste v2 — incertitude | Angelopoulos & Bates, *A Gentle Introduction to Conformal Prediction* — arXiv:2107.07511 | « Je ne sais pas » ⇒ revue humaine plutôt que score sûr de lui | vérifié |

## Valeur ajoutée face à l'existant

Les briques sont prouvées ; l'assemblage est nouveau.

1. **Vérification du bénéficiaire transfrontière.** VoP (UE) et CoP (UK) s'arrêtent à leur zone ; un paiement France → Ghana en sort. Sylo prolonge la garantie jusqu'au bout du corridor.
2. **Le score déclenche un séquestre réversible, pas un bloquer/laisser passer.** Si le doute porte sur l'identité du bénéficiaire (`oobResolvable`), les fonds vont en séquestre on-chain lié à l'intention signée, libérés après confirmation hors bande ou remboursés. Un faux positif coûte un délai, pas un client ; un faux négatif est rattrapé par la vérification.
3. **IA auditable par construction.** Règles, score, raisons SHAP et dossier de l'agent sont des événements horodatés rattachés à l'intention scellée : un régulateur peut rejouer la décision.
4. **Agent LLM en quarantaine.** Il fait gagner du temps à l'analyste sans pouvoir agir ni rassurer à tort ; chaque phrase cite un signal réel, sinon repli sur gabarit.

## Mesures qui doivent soutenir ces points

| Point | Mesure | Où |
|---|---|---|
| 1, 2 | Valeur stoppée vs taux de friction (STP) ; rappel T1 évasif | `ml/reports/metrics.json` |
| 2 | Part des HIGH levables qui finissent en séquestre et non en rejet | éval moteur |
| 3 | 100 % des décisions ont un événement `risk.scored` rejouable | tests moteur |
| 4 | Red team : 0 injection qui change l'action ou passe le validateur | tests System 2 |
