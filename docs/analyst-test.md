# Analyst case-file test protocol

**Indicative, not yet run (B3.2).**

## Protocol

- Two fraud analysts independently review the same five synthetic cases.
- For each case, record elapsed time from opening the case to a documented disposition.
- Run each review twice: once with the generated case file visible and once without it. Counterbalance the order between testers to reduce learning effects.
- Use the same event history and evidence in both conditions. Do not allow the case file to change the payment decision automatically.
- Record disposition, cited evidence, confidence, time, and any unsupported or misleading statement. Compare paired times and evidence coverage; treat this small exercise as usability feedback, not effectiveness evidence.

## Cases

| Case | Scenario to review |
|---|---|
| Legitimate supplier payment | Established supplier, known account, and ordinary payment history. |
| Supplier bank-detail change | Invoice or email requests payment to a new beneficiary account. |
| Social-engineering pressure | Document urges immediate payment or discourages independent verification. |
| Embedded instructions | Document contains text attempting to direct the investigator or model. |
| Mule-network fan-in | Multiple payers send to young accounts at a border institution. |

The protocol is synthetic and does not establish performance on real investigations.
