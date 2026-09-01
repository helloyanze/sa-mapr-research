# SA-MAPR v2.1.1 Stage 2 formal generation report

- Generation gate: `STAGE2_GENERATION_COMPLETE`
- Formal Run ID: `stage2_mve_formal_20260825T210517`
- Protocol Lock ID: `stage2-v2.1.1-7a7d2bd44d0bc085`
- Implementation commit: `513548d7f3aa779072e6ab65c57ace7455391efa`
- Bugs / primary runs / attempts: `20 / 60 / 122`
- Prompt / raw response / patch counts: `122 / 122 / 122`
- Shared-context fairness: `PASS (20/20)`
- Protocol audit: `PASS`
- Leakage audit: `PASS (0 forbidden findings)`
- Framework failures: `0`

## Mechanical results

| Group | Runs | Attempts | Compile | Trigger | Full test / plausible | Warning removed | V0 | V1 | V2 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| A | 20 | 42 | 18 | 13 | 9 | 13 | 9 | 9 | 9 |
| R | 20 | 39 | 20 | 15 | 12 | 16 | 12 | 11 | 11 |
| C | 20 | 41 | 20 | 13 | 11 | 17 | 11 | 10 | 10 |

## Usage

- Input tokens: `1651100`
- Output tokens: `41527`
- Total tokens: `1692627`
- Estimated cost: `0.75435699`
- Aggregate run time: `60451.089 seconds`
- Wall-clock span: `69716 seconds` (2026-08-25T21:21:12+08:00 to 2026-08-26T16:43:08+08:00)

## Group C mapping

- Selected primary patches: claimed valid `20/20`, realized success `19/20`, consistent `19/20`, exact `2/20`.
- All C attempts: claimed valid `41/41`, realized success `37/41`, consistent `35/41`, exact `5/41`.

## Correctness boundary

Developer-patch correctness audit has not been performed. All final correctness labels remain `pending_human`; this report makes no Correct/Incorrect or treatment-superiority claim.
