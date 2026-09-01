from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import load_json, save_json, write_csv
from mapping_normalization import replay_mapping
from revised_prompting import audit_structured_payload


ROOT = Path(__file__).resolve().parents[1]
BUGS = ("Chart-1", "Codec-1", "Chart-22")
METRICS = (
    "claimed_mapping_valid",
    "realized_mapping_success",
    "mapping_consistent",
    "mapping_exact",
    "mapping_precision",
    "mapping_coverage",
)
FUNCTIONAL_FIELDS = (
    "patch_apply",
    "compile",
    "trigger_test",
    "full_test",
    "plausible",
    "target_warning_removed",
    "public_api_unchanged",
    "hard_scope_pass",
    "would_accept_test_only",
    "would_accept_generic",
    "would_accept_hybrid",
)
SUMMARY_FIELDS = [
    "bug_key", "experiment_group", "selected_attempt", "evidence_path",
    *[f"before_{field}" for field in METRICS],
    *[f"after_{field}" for field in METRICS],
    *FUNCTIONAL_FIELDS,
    "functional_result_unchanged", "semantic_mismatch_reasons",
]


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def protected_hashes(source_run: Path) -> dict[str, str]:
    paths = []
    for folder in ("prompts", "responses", "patches", "contracts", "evidence_reports", "api_diff", "spotbugs_reports"):
        paths.extend(path for path in (source_run / folder).rglob("*") if path.is_file())
    paths.extend(source_run / name for name in (
        "revised_preflight_attempt_results.csv", "revised_preflight_bug_results.csv", "revised_preflight_manifest.csv",
    ))
    return {str(path.relative_to(source_run)).replace("\\", "/"): file_hash(path) for path in sorted(paths) if path.is_file()}


def read_rows(path: Path) -> list[dict]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def bool_from_json(value) -> bool:
    return value is True or str(value).lower() == "true"


def replay_one(source_run: Path, output: Path, bug_row: dict) -> tuple[dict, dict]:
    bug = bug_row["bug_key"]
    attempt = str(bug_row["best_attempt"])
    evidence_path = ROOT / bug_row["best_evidence_path"]
    evidence = load_json(evidence_path)
    contract = load_json(source_run / "contracts" / f"{bug}.json")
    original_claimed = evidence.get("claimed_mapping", [])
    original_realized = evidence.get("realized_mapping", [])
    claimed_valid = bool_from_json(evidence.get("mapping", {}).get("claimed_mapping_valid"))
    replay = replay_mapping(contract, original_claimed, original_realized, claimed_valid)

    target = output / f"{bug}-C"
    target.mkdir(parents=True, exist_ok=False)
    save_json(target / "claimed_original.json", original_claimed)
    save_json(target / "claimed_normalized.json", replay["claimed_normalized"])
    save_json(target / "realized_original.json", original_realized)
    save_json(target / "realized_normalized.json", replay["realized_normalized"])
    save_json(target / "mapping_normalized.json", {
        "claimed": replay["claimed_normalized"], "realized": replay["realized_normalized"]
    })
    save_json(target / "mapping_compare.json", replay["comparison"])
    save_json(target / "mapping_metrics.json", replay["metrics"])

    before = evidence.get("mapping", {})
    reasons = [
        f"{entry['obligation_id']}: {', '.join(entry['mismatch_reasons'])}"
        for entry in replay["comparison"]["entries"] if not entry["confirmed"]
    ]
    row = {
        "bug_key": bug,
        "experiment_group": "C",
        "selected_attempt": attempt,
        "evidence_path": str(evidence_path.relative_to(ROOT)).replace("\\", "/"),
        **{f"before_{field}": before.get(field) for field in METRICS},
        **{f"after_{field}": replay["metrics"].get(field) for field in METRICS},
        **{field: bug_row.get(field, "") for field in FUNCTIONAL_FIELDS},
        "functional_result_unchanged": True,
        "semantic_mismatch_reasons": "; ".join(reasons),
    }
    return row, {
        "bug_key": bug,
        "attempt": attempt,
        "functional_results": {field: bug_row.get(field, "") for field in FUNCTIONAL_FIELDS},
        "functional_correctness_from_evidence": evidence.get("functional_correctness", {}),
        "verifier_decisions_from_evidence": evidence.get("verifier_decisions", {}),
    }


def replay_all_attempts(source_run: Path) -> list[dict]:
    rows = []
    for evidence_path in sorted((source_run / "evidence_reports").glob("*_C_attempt*.json")):
        evidence = load_json(evidence_path)
        bug, attempt_text = evidence_path.stem.rsplit("_C_attempt", 1)
        contract = load_json(source_run / "contracts" / f"{bug}.json")
        before = evidence.get("mapping", {})
        replay = replay_mapping(contract, evidence.get("claimed_mapping", []), evidence.get("realized_mapping", []),
                                bool_from_json(before.get("claimed_mapping_valid")))
        rows.append({
            "bug_key": bug,
            "attempt": attempt_text,
            **{f"before_{field}": before.get(field) for field in METRICS},
            **{f"after_{field}": replay["metrics"].get(field) for field in METRICS},
            "mismatch_reasons": "; ".join(
                f"{entry['obligation_id']}: {', '.join(entry['mismatch_reasons'])}"
                for entry in replay["comparison"]["entries"] if not entry["confirmed"]
            ),
        })
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description="Offline SA-MAPR v2.1.1 obligation-mapping replay")
    parser.add_argument("--source-run", required=True)
    parser.add_argument("--output", default="outputs/mapping_hotfix_v2_1_1")
    args = parser.parse_args()
    source_run = (ROOT / args.source_run).resolve()
    output = (ROOT / args.output).resolve()
    if not source_run.is_dir():
        raise SystemExit(f"source run not found: {source_run}")
    if output.exists():
        raise SystemExit(f"immutable hotfix output already exists: {output}")
    output.mkdir(parents=True)

    hashes_before = protected_hashes(source_run)
    bug_rows = [row for row in read_rows(source_run / "revised_preflight_bug_results.csv")
                if row.get("experiment_group") == "C" and row.get("bug_key") in BUGS]
    if {row["bug_key"] for row in bug_rows} != set(BUGS):
        raise SystemExit("source run does not contain all three selected C-group results")
    summaries, functional = [], []
    for bug in BUGS:
        row = next(item for item in bug_rows if item["bug_key"] == bug)
        summary, snapshot = replay_one(source_run, output, row)
        summaries.append(summary)
        functional.append(snapshot)
    write_csv(output / "mapping_replay_summary.csv", summaries, SUMMARY_FIELDS)

    attempts = replay_all_attempts(source_run)
    attempt_fields = list(attempts[0]) if attempts else []
    write_csv(output / "mapping_replay_all_attempts.csv", attempts, attempt_fields)
    save_json(output / "functional_results_snapshot.json", functional)
    hashes_after = protected_hashes(source_run)
    integrity = {
        "source_run": str(source_run.relative_to(ROOT)).replace("\\", "/"),
        "protected_artifact_count": len(hashes_before),
        "all_protected_artifacts_unchanged": hashes_before == hashes_after,
        "changed_paths": sorted(key for key in set(hashes_before) | set(hashes_after)
                                if hashes_before.get(key) != hashes_after.get(key)),
        "sha256": hashes_after,
    }
    save_json(output / "source_run_integrity.json", integrity)

    replay_payload = {
        "summaries": summaries,
        "all_attempts": attempts,
        "functional_results": functional,
    }
    leakage = audit_structured_payload(replay_payload, "mapping_replay")
    save_json(output / "mapping_hotfix_leakage_audit.json", leakage)
    checks = {
        "three_c_groups_replayed": len(summaries) == 3,
        "format_false_mismatches_removed": all(bool_from_json(row["after_mapping_consistent"]) for row in summaries),
        "precision_and_coverage_recomputed": all(
            row["after_mapping_precision"] is not None and row["after_mapping_coverage"] is not None for row in summaries
        ),
        "functional_results_unchanged": integrity["all_protected_artifacts_unchanged"],
        "no_new_data_leakage": leakage["pass"],
        "failed_codec_attempt_retains_real_mismatch": any(
            row["bug_key"] == "Codec-1" and row["attempt"] == "1" and not bool_from_json(row["after_mapping_consistent"])
            and "no realized mappable target" in row["mismatch_reasons"] for row in attempts
        ),
    }
    save_json(output / "mapping_replay_gate.json", {"pass": all(checks.values()), "checks": checks})
    print(json.dumps({"output": str(output), "checks": checks}, ensure_ascii=False, indent=2))
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
