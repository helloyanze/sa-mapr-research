#!/usr/bin/env python3
from __future__ import annotations

import csv
import json
from collections import Counter, defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INPUT = ROOT / "inputs"
OUTPUT = ROOT / "analysis_output"
EXPECTED_RUN = "stage2_mve_formal_20260825T210517"
EXPECTED_LOCK = "stage2-v2.1.1-7a7d2bd44d0bc085"


def truth(value: str) -> bool:
    return str(value).strip().lower() == "true"


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def main() -> int:
    source = INPUT / "correctness/stage2_bug_results_with_correctness.csv"
    rows = read_csv(source)
    problems: list[str] = []

    if len(rows) != 60:
        problems.append(f"expected 60 primary rows, found {len(rows)}")

    group_counts = Counter(row["experiment_group"] for row in rows)
    if group_counts != Counter({"A": 20, "R": 20, "C": 20}):
        problems.append(f"unexpected group counts: {dict(group_counts)}")

    run_ids = {row["run_id"] for row in rows}
    lock_ids = {row["protocol_lock_id"] for row in rows}
    if run_ids != {EXPECTED_RUN}:
        problems.append(f"unexpected run ids: {sorted(run_ids)}")
    if lock_ids != {EXPECTED_LOCK}:
        problems.append(f"unexpected protocol locks: {sorted(lock_ids)}")

    by_bug: dict[str, dict[str, dict[str, str]]] = defaultdict(dict)
    for row in rows:
        by_bug[row["bug_key"]][row["experiment_group"]] = row
    malformed = sorted(bug for bug, groups in by_bug.items() if set(groups) != {"A", "R", "C"})
    if len(by_bug) != 20 or malformed:
        problems.append(f"paired layout invalid: bugs={len(by_bug)}, malformed={malformed}")

    correct = Counter()
    plausible = Counter()
    for row in rows:
        group = row["experiment_group"]
        if row["final_correctness"].strip().lower() == "correct":
            correct[group] += 1
        if truth(row["plausible"]):
            plausible[group] += 1
        if "pending" in row["final_correctness"].strip().lower():
            problems.append(f"pending correctness: {row['bug_key']} {group}")

    if correct != Counter({"R": 10, "C": 9, "A": 7}):
        problems.append(f"unexpected correct counts: {dict(correct)}")
    if plausible != Counter({"R": 12, "C": 11, "A": 9}):
        problems.append(f"unexpected plausible counts: {dict(plausible)}")

    pairwise = {}
    for first, second in (("A", "R"), ("R", "C"), ("A", "C")):
        gains = harms = 0
        for groups in by_bug.values():
            first_ok = groups[first]["final_correctness"].strip().lower() == "correct"
            second_ok = groups[second]["final_correctness"].strip().lower() == "correct"
            gains += int(not first_ok and second_ok)
            harms += int(first_ok and not second_ok)
        pairwise[f"{first}_to_{second}"] = {"gains": gains, "harms": harms}

    expected_pairwise = {
        "A_to_R": {"gains": 3, "harms": 0},
        "R_to_C": {"gains": 0, "harms": 1},
        "A_to_C": {"gains": 3, "harms": 1},
    }
    if pairwise != expected_pairwise:
        problems.append(f"unexpected pairwise transitions: {pairwise}")

    protocol_audit = json.loads((INPUT / "protocol/stage2_protocol_audit.json").read_text(encoding="utf-8"))
    audit_text = json.dumps(protocol_audit, ensure_ascii=False).lower()
    if '"pass": true' not in audit_text:
        problems.append("protocol audit does not contain pass=true")

    gate = "STAGE2_CORRECTNESS_INPUTS_READY" if not problems else "STAGE2_CORRECTNESS_ANALYSIS_HOLD"
    report = {
        "gate": gate,
        "source": str(source.relative_to(ROOT)),
        "rows": len(rows),
        "bugs": len(by_bug),
        "group_counts": dict(group_counts),
        "plausible": dict(plausible),
        "correct": dict(correct),
        "pairwise": pairwise,
        "problems": problems,
    }
    OUTPUT.mkdir(parents=True, exist_ok=True)
    (OUTPUT / "input_validation.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (OUTPUT / "ANALYSIS_GATE.txt").write_text(gate + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if not problems else 1


if __name__ == "__main__":
    raise SystemExit(main())
