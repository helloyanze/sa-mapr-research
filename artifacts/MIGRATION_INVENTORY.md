# Migration inventory

## Copied into Git

- Stage 2 Python/Java/Shell implementation and 35 regression tests;
- five runtime configs, 20 Evidence Contracts, two schemas and five prompts;
- frozen 20 Bug manifest and runtime-safe JSONL;
- correctness CSV/JSON/report files and 20 developer patches;
- mechanical result tables, formal protocol snapshots and legacy lock;
- Docker, repository guard and project-template files.

## Kept locally but excluded from Git

- four dependency ZIP files in `artifacts/cache/`;
- validator output under `analysis_output/`;
- JavaParser Maven target and Python bytecode caches.

## Not copied

- `.env` and every credential;
- `work/` Defects4J checkouts;
- `outputs/`, `outputs_archive/`, `outputs_revised/` and `outputs_revised_mve/`;
- raw responses, per-attempt prompts/logs, SpotBugs XML and duplicate audit source trees;
- historical unpacked deliverables and document-generation products.

The source thesis workspace remains the authoritative archive for omitted historical evidence.
