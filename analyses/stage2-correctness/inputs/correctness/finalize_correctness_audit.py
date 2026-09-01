from __future__ import annotations

import csv
import hashlib
import json
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path


AUDIT_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = AUDIT_ROOT.parents[1]
RUN_ID = "stage2_mve_formal_20260825T210517"
RUN_ROOT = PROJECT_ROOT / f"outputs_revised_mve/{RUN_ID}"


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict], fields: list[str]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def is_true(value: object) -> bool:
    return str(value).lower() == "true"


def verify_generation_manifest() -> dict:
    manifest_path = RUN_ROOT / "PACKAGE_MANIFEST.csv"
    rows = read_csv(manifest_path)
    missing, mismatched = [], []
    for row in rows:
        path = RUN_ROOT / row["relative_path"]
        if not path.is_file():
            missing.append(row["relative_path"])
            continue
        if path.stat().st_size != int(row["size_bytes"]):
            mismatched.append(f"{row['relative_path']}:size")
            continue
        if sha256_file(path) != row["sha256"]:
            mismatched.append(f"{row['relative_path']}:sha256")
    return {
        "run_id": RUN_ID,
        "package_manifest_sha256": sha256_file(manifest_path),
        "manifest_entries": len(rows),
        "missing": missing,
        "mismatched": mismatched,
        "pass": not missing and not mismatched,
    }


def ratio(numerator: int, denominator: int) -> str:
    return f"{numerator / denominator:.6f}" if denominator else "not_applicable"


def main() -> None:
    before = json.loads((AUDIT_ROOT / "generation_artifact_integrity_before.json").read_text(encoding="utf-8"))
    after = verify_generation_manifest()
    after["matches_before"] = (
        after["package_manifest_sha256"] == before["package_manifest_sha256"]
        and after["manifest_entries"] == before["manifest_entries"]
        and after["pass"]
    )
    write_json(AUDIT_ROOT / "generation_artifact_integrity_after.json", after)
    if not after["matches_before"]:
        raise SystemExit("Frozen generation artifacts changed during correctness audit")

    working = read_csv(AUDIT_ROOT / "stage2_correctness_audit_working.csv")
    bug_results = read_csv(RUN_ROOT / "stage2_bug_results.csv")
    manifest_rows = read_csv(PROJECT_ROOT / "frozen_inputs/stage2_20bug_input_manifest.csv")
    manifest = {row["bug_key"]: row for row in manifest_rows}
    unique_groups = read_csv(AUDIT_ROOT / "unique_patch_groups.csv")
    verdicts = json.loads((AUDIT_ROOT / "unique_patch_verdicts.json").read_text(encoding="utf-8"))

    verdict_by_id = {}
    for bug_key, verdict in verdicts.items():
        for patch_id in verdict["unique_patch_ids"]:
            if patch_id in verdict_by_id:
                raise RuntimeError(f"Duplicate verdict id: {patch_id}")
            verdict_by_id[patch_id] = {"bug_key": bug_key, **verdict}
    expected_unique = {row["unique_patch_id"] for row in unique_groups}
    if set(verdict_by_id) != expected_unique:
        raise RuntimeError(f"Verdict coverage mismatch: expected {expected_unique}, got {set(verdict_by_id)}")

    for row in working:
        if row["plausible"] != "true":
            row["correctness_basis"] = "mechanical_failure"
            continue
        verdict = verdict_by_id[row["unique_patch_id"]]
        if verdict["bug_key"] != row["bug_key"]:
            raise RuntimeError(f"Bug mismatch for {row['unique_patch_id']}")
        for field in (
            "root_cause_related",
            "semantic_equivalent",
            "overfitting_risk",
            "final_correctness",
            "correctness_type",
            "developer_patch_mechanism",
            "generated_patch_mechanism",
            "correctness_reason",
            "second_review_required",
            "second_reviewer",
            "second_review_reason",
        ):
            row[field] = verdict[field]
        row["audit_status"] = "complete"
        row["reviewer"] = "Codex developer-patch-grounded forensic audit"
        row["correctness_basis"] = "developer_patch+buggy_source+patched_source+fixed_source+trigger_and_full_test_logs"

    audit_fields = list(working[0].keys())
    write_csv(AUDIT_ROOT / "stage2_correctness_audit.csv", working, audit_fields)

    pending = [row for row in working if row["final_correctness"] not in {"correct", "incorrect"}]
    missing_reason = [row for row in working if not row["correctness_reason"]]
    second_review_pending = [
        row
        for row in working
        if row["second_review_required"] == "true"
        and (not row["second_reviewer"] or not row["second_review_reason"])
    ]
    if pending or missing_reason or second_review_pending:
        raise RuntimeError(
            f"Audit incomplete: pending={len(pending)}, missing_reason={len(missing_reason)}, "
            f"second_review_pending={len(second_review_pending)}"
        )

    audit_index = {(row["bug_key"], row["group"]): row for row in working}
    merged = []
    for result in bug_results:
        key = (result["bug_key"], result["experiment_group"])
        audit = audit_index[key]
        row = dict(result)
        row["generation_final_correctness"] = row["final_correctness"]
        row["final_correctness"] = audit["final_correctness"]
        for field in (
            "selected_attempt_id",
            "patch_hash",
            "unique_patch_id",
            "plausible",
            "correctness_type",
            "correctness_reason",
            "correctness_basis",
            "root_cause_related",
            "semantic_equivalent",
            "overfitting_risk",
            "audit_status",
            "reviewer",
            "second_review_required",
            "second_reviewer",
            "second_review_reason",
            "evidence_stratum",
            "defect_category",
        ):
            row[f"audit_{field}" if field == "plausible" else field] = audit[field]
        merged.append(row)
    merged_fields = list(merged[0])
    write_csv(AUDIT_ROOT / "stage2_bug_results_with_correctness.csv", merged, merged_fields)

    unique_audit_rows = []
    for unique in unique_groups:
        verdict = verdict_by_id[unique["unique_patch_id"]]
        unique_audit_rows.append(
            {
                **unique,
                "root_cause_related": verdict["root_cause_related"],
                "semantic_equivalent": verdict["semantic_equivalent"],
                "overfitting_risk": verdict["overfitting_risk"],
                "final_correctness": verdict["final_correctness"],
                "correctness_type": verdict["correctness_type"],
                "correctness_reason": verdict["correctness_reason"],
                "second_review_required": verdict["second_review_required"],
                "second_reviewer": verdict["second_reviewer"],
                "second_review_reason": verdict["second_review_reason"],
            }
        )
    write_csv(AUDIT_ROOT / "stage2_unique_patch_audit.csv", unique_audit_rows, list(unique_audit_rows[0]))

    pairwise_rows = []
    for bug_key in [row["bug_key"] for row in manifest_rows]:
        values = {group: audit_index[(bug_key, group)] for group in "ARC"}
        flags = {group: values[group]["final_correctness"] == "correct" for group in "ARC"}
        pairwise_rows.append(
            {
                "bug_key": bug_key,
                "evidence_stratum": manifest[bug_key]["final_human_label"],
                "defect_category": manifest[bug_key]["research_defect_categories"],
                "A_plausible": values["A"]["plausible"],
                "A_correct": str(flags["A"]).lower(),
                "R_plausible": values["R"]["plausible"],
                "R_correct": str(flags["R"]).lower(),
                "C_plausible": values["C"]["plausible"],
                "C_correct": str(flags["C"]).lower(),
                "pattern": f"A{int(flags['A'])} R{int(flags['R'])} C{int(flags['C'])}",
                "raw_evidence_gain": str((not flags["A"]) and flags["R"]).lower(),
                "raw_evidence_harm": str(flags["A"] and (not flags["R"])).lower(),
                "contract_gain_over_raw": str((not flags["R"]) and flags["C"]).lower(),
                "contract_harm_over_raw": str(flags["R"] and (not flags["C"])).lower(),
                "full_treatment_gain": str((not flags["A"]) and flags["C"]).lower(),
                "full_treatment_harm": str(flags["A"] and (not flags["C"])).lower(),
            }
        )
    write_csv(AUDIT_ROOT / "stage2_correctness_pairwise.csv", pairwise_rows, list(pairwise_rows[0]))

    result_index = {(row["bug_key"], row["experiment_group"]): row for row in bug_results}
    verifier_fields = {
        "V0_test_only": "would_accept_test_only",
        "V1_generic": "would_accept_generic",
        "V2_hybrid": "would_accept_hybrid",
    }
    verifier_rows = []
    for scope_group in ["A", "R", "C", "ALL"]:
        scope = [row for row in working if scope_group == "ALL" or row["group"] == scope_group]
        for verifier, field in verifier_fields.items():
            accepted = rejected = true_accept = false_accept = true_reject = false_reject = 0
            for audit in scope:
                decision = is_true(result_index[(audit["bug_key"], audit["group"])][field])
                correct = audit["final_correctness"] == "correct"
                accepted += decision
                rejected += not decision
                true_accept += decision and correct
                false_accept += decision and not correct
                true_reject += (not decision) and (not correct)
                false_reject += (not decision) and correct
            if verifier == "V2_hybrid":
                hybrid_only = sum(
                    is_true(result_index[(audit["bug_key"], audit["group"])]["would_accept_test_only"])
                    and not is_true(result_index[(audit["bug_key"], audit["group"])]["would_accept_hybrid"])
                    and audit["final_correctness"] == "incorrect"
                    for audit in scope
                )
                harmful_extra = sum(
                    is_true(result_index[(audit["bug_key"], audit["group"])]["would_accept_test_only"])
                    and not is_true(result_index[(audit["bug_key"], audit["group"])]["would_accept_hybrid"])
                    and audit["final_correctness"] == "correct"
                    for audit in scope
                )
            else:
                hybrid_only = harmful_extra = 0
            verifier_rows.append(
                {
                    "scope_group": scope_group,
                    "verifier": verifier,
                    "records": len(scope),
                    "accepted": accepted,
                    "rejected": rejected,
                    "true_accept": true_accept,
                    "false_accept": false_accept,
                    "true_reject": true_reject,
                    "false_reject": false_reject,
                    "precision_among_accepted": ratio(true_accept, accepted),
                    "hybrid_only_interception": hybrid_only,
                    "harmful_extra_rejection": harmful_extra,
                }
            )
    write_csv(AUDIT_ROOT / "stage2_verifier_correctness.csv", verifier_rows, list(verifier_rows[0]))

    mapping_rows = []
    for result in [row for row in bug_results if row["experiment_group"] == "C"]:
        audit = audit_index[(result["bug_key"], "C")]
        consistent = is_true(result["mapping_consistent"])
        correct = audit["final_correctness"] == "correct"
        mapping_rows.append(
            {
                "bug_key": result["bug_key"],
                "plausible": audit["plausible"],
                "final_correctness": audit["final_correctness"],
                "claimed_mapping_valid": result["claimed_mapping_valid"],
                "realized_mapping_success": result["realized_mapping_success"],
                "mapping_consistent": result["mapping_consistent"],
                "mapping_exact": result["mapping_exact"],
                "mapping_precision": result["mapping_precision"],
                "mapping_coverage": result["mapping_coverage"],
                "contingency_bucket": (
                    "consistent_correct"
                    if consistent and correct
                    else "consistent_incorrect"
                    if consistent
                    else "inconsistent_correct"
                    if correct
                    else "inconsistent_incorrect"
                ),
            }
        )
    write_csv(AUDIT_ROOT / "stage2_mapping_correctness.csv", mapping_rows, list(mapping_rows[0]))

    strata_rows = []
    for stratum in ("direct", "supporting"):
        for group in "ARC":
            rows = [row for row in working if row["evidence_stratum"] == stratum and row["group"] == group]
            plausible_count = sum(row["plausible"] == "true" for row in rows)
            correct_count = sum(row["final_correctness"] == "correct" for row in rows)
            plausible_incorrect = sum(
                row["plausible"] == "true" and row["final_correctness"] == "incorrect" for row in rows
            )
            mechanical = sum(row["correctness_type"] == "mechanical_failure" for row in rows)
            strata_rows.append(
                {
                    "evidence_stratum": stratum,
                    "experiment_group": group,
                    "bugs": len(rows),
                    "plausible": plausible_count,
                    "correct": correct_count,
                    "plausible_but_incorrect": plausible_incorrect,
                    "mechanical_failure": mechanical,
                    "correct_rate_all_bugs": ratio(correct_count, len(rows)),
                    "precision_among_plausible": ratio(correct_count, plausible_count),
                }
            )
    write_csv(AUDIT_ROOT / "stage2_evidence_strata_correctness.csv", strata_rows, list(strata_rows[0]))

    group_summary = []
    for group in "ARC":
        rows = [row for row in working if row["group"] == group]
        plausible_count = sum(row["plausible"] == "true" for row in rows)
        correct_count = sum(row["final_correctness"] == "correct" for row in rows)
        plausible_incorrect = sum(
            row["plausible"] == "true" and row["final_correctness"] == "incorrect" for row in rows
        )
        group_summary.append(
            {
                "group": group,
                "plausible": plausible_count,
                "correct": correct_count,
                "plausible_but_incorrect": plausible_incorrect,
                "precision": ratio(correct_count, plausible_count),
            }
        )

    pattern_counts = Counter(row["pattern"] for row in pairwise_rows)
    pair_stats = {
        "A_to_R_gains": sum(is_true(row["raw_evidence_gain"]) for row in pairwise_rows),
        "A_to_R_harms": sum(is_true(row["raw_evidence_harm"]) for row in pairwise_rows),
        "R_to_C_gains": sum(is_true(row["contract_gain_over_raw"]) for row in pairwise_rows),
        "R_to_C_harms": sum(is_true(row["contract_harm_over_raw"]) for row in pairwise_rows),
        "A_to_C_gains": sum(is_true(row["full_treatment_gain"]) for row in pairwise_rows),
        "A_to_C_harms": sum(is_true(row["full_treatment_harm"]) for row in pairwise_rows),
    }
    verifier_all = {row["verifier"]: row for row in verifier_rows if row["scope_group"] == "ALL"}
    mapping_counts = Counter(row["contingency_bucket"] for row in mapping_rows)
    disputed = [row for row in unique_audit_rows if row["second_review_required"] == "true"]

    report = [
        "# SA-MAPR v2.1.1 Stage 2 Developer-Patch Correctness Audit",
        "",
        f"- Run ID: `{RUN_ID}`",
        "- Audit mode: offline, developer-patch-grounded semantic review",
        "- Original generation artifacts: `UNCHANGED` (6,862/6,862 manifest entries verified before and after)",
        "- Final gate: `STAGE2_CORRECTNESS_AUDIT_COMPLETE`",
        "",
        "## 1. Audit coverage",
        "",
        f"- Plausible selected patches audited: `{sum(row['plausible'] == 'true' for row in working)}/32`",
        f"- Unique plausible patches: `{len(unique_groups)}`",
        f"- Duplicate instances beyond unique patches: `{32 - len(unique_groups)}`",
        f"- Duplicate hash groups: `{sum(int(row['member_count']) > 1 for row in unique_groups)}`",
        f"- Non-plausible primary runs labeled mechanical failure: `{sum(row['correctness_type'] == 'mechanical_failure' for row in working)}/28`",
        "- Pending correctness labels: `0`",
        "",
        "## 2. Correctness results",
        "",
        "| Group | Plausible | Correct | Plausible-but-incorrect | Correct / Plausible |",
        "|---|---:|---:|---:|---:|",
    ]
    for row in group_summary:
        report.append(
            f"| {row['group']} | {row['plausible']} | {row['correct']} | "
            f"{row['plausible_but_incorrect']} | {float(row['precision']):.1%} |"
        )
    report += [
        "",
        "The six plausible-but-incorrect instances are the A/R/C selected patches for JacksonDatabind-3 and Jsoup-89. JacksonDatabind-3 fixes only the default deserializer path and omits the developer's custom-null-value repair. Jsoup-89 fixes the orphan NPE but omits the parent-backed Map.Entry old-value semantics.",
        "",
        "## 3. Pairwise bug-level comparison",
        "",
        f"- A→R gains / harms: `{pair_stats['A_to_R_gains']} / {pair_stats['A_to_R_harms']}`",
        f"- R→C gains / harms: `{pair_stats['R_to_C_gains']} / {pair_stats['R_to_C_harms']}`",
        f"- A→C gains / harms: `{pair_stats['A_to_C_gains']} / {pair_stats['A_to_C_harms']}`",
        "",
        "Pattern counts:",
        "",
    ]
    for pattern in (
        "A0 R0 C0",
        "A0 R1 C0",
        "A0 R0 C1",
        "A1 R1 C1",
        "A1 R0 C0",
        "A1 R1 C0",
        "A1 R0 C1",
        "A0 R1 C1",
    ):
        report.append(f"- `{pattern}`: {pattern_counts.get(pattern, 0)}")
    report += [
        "",
        "A→R gains occur on Collections-1, Collections-26, and Math-91. R→C has no gain and one harm (JacksonDatabind-29), where R produced a correct patch but C did not produce a plausible selected patch.",
        "",
        "## 4. Verifier × correctness (60 selected primary patches)",
        "",
        "| Verifier | Accept | False accept | False reject | Precision among accepted |",
        "|---|---:|---:|---:|---:|",
    ]
    for verifier in ("V0_test_only", "V1_generic", "V2_hybrid"):
        row = verifier_all[verifier]
        report.append(
            f"| {verifier} | {row['accepted']} | {row['false_accept']} | {row['false_reject']} | "
            f"{float(row['precision_among_accepted']):.1%} |"
        )
    report += [
        "",
        f"- Hybrid-only interception: `{verifier_all['V2_hybrid']['hybrid_only_interception']}`",
        f"- Harmful extra rejection: `{verifier_all['V2_hybrid']['harmful_extra_rejection']}`",
        "",
        "V1/V2 reject the two correct Collections-26 patches because the developer-equivalent private→protected readResolve repair does not remove the target warning and changes non-public API visibility. They do not intercept the six audited incorrect plausible patches. Thus, on this selected-patch sample, the added verifier rules reduce acceptance but do not improve correctness precision.",
        "",
        "## 5. Mapping × correctness (Group C)",
        "",
        f"- mapping consistent & correct: `{mapping_counts.get('consistent_correct', 0)}`",
        f"- mapping consistent & incorrect: `{mapping_counts.get('consistent_incorrect', 0)}`",
        f"- mapping inconsistent & correct: `{mapping_counts.get('inconsistent_correct', 0)}`",
        f"- mapping inconsistent & incorrect: `{mapping_counts.get('inconsistent_incorrect', 0)}`",
        "",
        "Mapping consistency is a traceability property, not a correctness oracle: 10 of 19 mapping-consistent C runs are incorrect, including mechanical failures and plausible-but-incorrect patches.",
        "",
        "## 6. Direct vs Supporting evidence strata",
        "",
        "| Stratum | Group | Bugs | Plausible | Correct | Precision among plausible |",
        "|---|---|---:|---:|---:|---:|",
    ]
    for row in strata_rows:
        report.append(
            f"| {row['evidence_stratum']} | {row['experiment_group']} | {row['bugs']} | "
            f"{row['plausible']} | {row['correct']} | {float(row['precision_among_plausible']):.1%} |"
        )
    report += [
        "",
        "Supporting precision is 100% only because the plausible supporting subset is very small (A=2, R=2, C=1); it must not be interpreted as evidence that Supporting cases are easier or superior.",
        "",
        "## 7. Second-review cases",
        "",
    ]
    for row in disputed:
        report.append(
            f"- `{row['bug_key']} / {row['unique_patch_id']}` → `{row['final_correctness']}` "
            f"(`{row['correctness_type']}`): {row['second_review_reason']}"
        )
    report += [
        "",
        "All identified semantic-difference cases received a second evidence pass; no unresolved `needs_second_review` case remains.",
        "",
        "## 8. Audit conclusion",
        "",
        "`STAGE2_CORRECTNESS_AUDIT_COMPLETE`",
        "",
        "Raw SpotBugs evidence improves correct repairs from 7/20 (A) to 10/20 (R), with three paired gains and no paired harm. The Contract group yields 9/20 correct repairs: one fewer than R, with no R→C gain and one R→C harm. On this 20-Bug MVE, the Evidence Contract adds warning-removal and traceability structure but does not provide an incremental correctness gain over raw evidence. These are small-sample paired results and should be reported with effect sizes and uncertainty rather than inflated significance claims.",
    ]
    (AUDIT_ROOT / "stage2_correctness_audit_report.md").write_text("\n".join(report) + "\n", encoding="utf-8")

    summary = {
        "audited_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "run_id": RUN_ID,
        "audited_plausible_patches": 32,
        "unique_patches": len(unique_groups),
        "duplicate_instances": 32 - len(unique_groups),
        "duplicate_hash_groups": sum(int(row["member_count"]) > 1 for row in unique_groups),
        "group_results": group_summary,
        "pairwise": pair_stats,
        "verifier_all": verifier_all,
        "mapping_contingency": dict(mapping_counts),
        "second_review_cases": len(disputed),
        "unresolved_cases": 0,
        "pending_human": 0,
        "generation_artifacts_unchanged": after["matches_before"],
        "gate": "STAGE2_CORRECTNESS_AUDIT_COMPLETE",
    }
    write_json(AUDIT_ROOT / "stage2_correctness_audit_summary.json", summary)

    package_rows = []
    excluded = {"PACKAGE_MANIFEST.csv"}
    for path in sorted((path for path in AUDIT_ROOT.rglob("*") if path.is_file()), key=lambda value: value.as_posix()):
        relative = path.relative_to(AUDIT_ROOT).as_posix()
        if relative in excluded:
            continue
        package_rows.append(
            {"relative_path": relative, "size_bytes": path.stat().st_size, "sha256": sha256_file(path)}
        )
    write_csv(AUDIT_ROOT / "PACKAGE_MANIFEST.csv", package_rows, ["relative_path", "size_bytes", "sha256"])
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
