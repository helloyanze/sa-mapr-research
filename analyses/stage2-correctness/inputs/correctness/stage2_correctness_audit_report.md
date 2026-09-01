# SA-MAPR v2.1.1 Stage 2 Developer-Patch Correctness Audit

- Run ID: `stage2_mve_formal_20260825T210517`
- Audit mode: offline, developer-patch-grounded semantic review
- Original generation artifacts: `UNCHANGED` (6,862/6,862 manifest entries verified before and after)
- Final gate: `STAGE2_CORRECTNESS_AUDIT_COMPLETE`

## 1. Audit coverage

- Plausible selected patches audited: `32/32`
- Unique plausible patches: `25`
- Duplicate instances beyond unique patches: `7`
- Duplicate hash groups: `6`
- Non-plausible primary runs labeled mechanical failure: `28/28`
- Pending correctness labels: `0`

## 2. Correctness results

| Group | Plausible | Correct | Plausible-but-incorrect | Correct / Plausible |
|---|---:|---:|---:|---:|
| A | 9 | 7 | 2 | 77.8% |
| R | 12 | 10 | 2 | 83.3% |
| C | 11 | 9 | 2 | 81.8% |

The six plausible-but-incorrect instances are the A/R/C selected patches for JacksonDatabind-3 and Jsoup-89. JacksonDatabind-3 fixes only the default deserializer path and omits the developer's custom-null-value repair. Jsoup-89 fixes the orphan NPE but omits the parent-backed Map.Entry old-value semantics.

## 3. Pairwise bug-level comparison

- A→R gains / harms: `3 / 0`
- R→C gains / harms: `0 / 1`
- A→C gains / harms: `3 / 1`

Pattern counts:

- `A0 R0 C0`: 10
- `A0 R1 C0`: 0
- `A0 R0 C1`: 0
- `A1 R1 C1`: 6
- `A1 R0 C0`: 0
- `A1 R1 C0`: 1
- `A1 R0 C1`: 0
- `A0 R1 C1`: 3

A→R gains occur on Collections-1, Collections-26, and Math-91. R→C has no gain and one harm (JacksonDatabind-29), where R produced a correct patch but C did not produce a plausible selected patch.

## 4. Verifier × correctness (60 selected primary patches)

| Verifier | Accept | False accept | False reject | Precision among accepted |
|---|---:|---:|---:|---:|
| V0_test_only | 32 | 6 | 0 | 81.2% |
| V1_generic | 30 | 6 | 2 | 80.0% |
| V2_hybrid | 30 | 6 | 2 | 80.0% |

- Hybrid-only interception: `0`
- Harmful extra rejection: `2`

V1/V2 reject the two correct Collections-26 patches because the developer-equivalent private→protected readResolve repair does not remove the target warning and changes non-public API visibility. They do not intercept the six audited incorrect plausible patches. Thus, on this selected-patch sample, the added verifier rules reduce acceptance but do not improve correctness precision.

## 5. Mapping × correctness (Group C)

- mapping consistent & correct: `9`
- mapping consistent & incorrect: `10`
- mapping inconsistent & correct: `0`
- mapping inconsistent & incorrect: `1`

Mapping consistency is a traceability property, not a correctness oracle: 10 of 19 mapping-consistent C runs are incorrect, including mechanical failures and plausible-but-incorrect patches.

## 6. Direct vs Supporting evidence strata

| Stratum | Group | Bugs | Plausible | Correct | Precision among plausible |
|---|---|---:|---:|---:|---:|
| direct | A | 14 | 7 | 5 | 71.4% |
| direct | R | 14 | 10 | 8 | 80.0% |
| direct | C | 14 | 10 | 8 | 80.0% |
| supporting | A | 6 | 2 | 2 | 100.0% |
| supporting | R | 6 | 2 | 2 | 100.0% |
| supporting | C | 6 | 1 | 1 | 100.0% |

Supporting precision is 100% only because the plausible supporting subset is very small (A=2, R=2, C=1); it must not be interpreted as evidence that Supporting cases are easier or superior.

## 7. Second-review cases

- `Jsoup-45 / UP-02` → `correct` (`alternative_correct`): Reviewed the full resetInsertionMode control flow, the last flag's fragment-context role, and testReinsertionModeForThCelss. The generated precedence differs from the developer text but implements the same root repair with coherent alternative semantics.
- `JacksonDatabind-3 / UP-08` → `incorrect` (`plausible_but_incorrect`): Confirmed against the complete developer diff, the _deserializeCustom implementation, JsonDeserializer.getNullValue(), and the analogous StringCollectionDeserializer behavior. The omitted branch has a concrete semantic obligation independent of textual patch equality.
- `Jsoup-89 / UP-09` → `incorrect` (`plausible_but_incorrect`): Confirmed from Attributes.iterator(), which creates parent-backed Attribute views, and the Map.Entry-style setValue contract. The missing parent.get(key) branch has an observable counterexample and is not a cosmetic difference.
- `Jsoup-89 / UP-14` → `incorrect` (`plausible_but_incorrect`): Confirmed from Attributes.iterator(), which creates parent-backed Attribute views, and the Map.Entry-style setValue contract. The missing parent.get(key) branch has an observable counterexample and is not a cosmetic difference.
- `JacksonDatabind-3 / UP-15` → `incorrect` (`plausible_but_incorrect`): Confirmed against the complete developer diff, the _deserializeCustom implementation, JsonDeserializer.getNullValue(), and the analogous StringCollectionDeserializer behavior. The omitted branch has a concrete semantic obligation independent of textual patch equality.
- `Jsoup-89 / UP-25` → `incorrect` (`plausible_but_incorrect`): Confirmed from Attributes.iterator(), which creates parent-backed Attribute views, and the Map.Entry-style setValue contract. The missing parent.get(key) branch has an observable counterexample and is not a cosmetic difference.

All identified semantic-difference cases received a second evidence pass; no unresolved `needs_second_review` case remains.

## 8. Audit conclusion

`STAGE2_CORRECTNESS_AUDIT_COMPLETE`

Raw SpotBugs evidence improves correct repairs from 7/20 (A) to 10/20 (R), with three paired gains and no paired harm. The Contract group yields 9/20 correct repairs: one fewer than R, with no R→C gain and one R→C harm. On this 20-Bug MVE, the Evidence Contract adds warning-removal and traceability structure but does not provide an incremental correctness gain over raw evidence. These are small-sample paired results and should be reported with effect sizes and uncertainty rather than inflated significance claims.
