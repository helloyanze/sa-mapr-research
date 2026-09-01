from __future__ import annotations

import csv
import hashlib
import json
import re
import shutil
import subprocess
from collections import defaultdict
from pathlib import Path


AUDIT_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = AUDIT_ROOT.parents[1]
RUN_ID = "stage2_mve_formal_20260825T210517"
RUN_ROOT = PROJECT_ROOT / f"outputs_revised_mve/{RUN_ID}"
SHARED_ROOT = PROJECT_ROOT / f"work/_revised_shared/{RUN_ID}"
ATTEMPT_ROOT = PROJECT_ROOT / f"work/_revised_attempts/{RUN_ID}"


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def git(checkout: Path, *args: str, binary: bool = False):
    result = subprocess.run(
        ["git", "-C", str(checkout), *args],
        capture_output=True,
        text=not binary,
        check=True,
    )
    return result.stdout


def resolve_project(path_text: str) -> Path:
    path = Path(path_text)
    return path if path.is_absolute() else PROJECT_ROOT / path


def generated_paths(diff_text: str) -> list[str]:
    paths = []
    for line in diff_text.splitlines():
        if line.startswith("+++ b/"):
            paths.append(line[6:].strip())
    return sorted(set(paths))


def safe_copy(source: Path, destination: Path) -> bool:
    if not source.is_file():
        return False
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    return True


def verify_generation_manifest() -> dict:
    manifest_path = RUN_ROOT / "PACKAGE_MANIFEST.csv"
    rows = read_csv(manifest_path)
    missing = []
    mismatched = []
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


def main() -> None:
    integrity = verify_generation_manifest()
    if not integrity["pass"]:
        raise SystemExit(f"Frozen generation artifacts failed integrity check: {integrity}")
    write_json(AUDIT_ROOT / "generation_artifact_integrity_before.json", integrity)

    bug_results = read_csv(RUN_ROOT / "stage2_bug_results.csv")
    manifest_rows = read_csv(PROJECT_ROOT / "frozen_inputs/stage2_20bug_input_manifest.csv")
    evidence_rows = read_csv(PROJECT_ROOT / "frozen_inputs/private_audit/audit_evidence_bug_level_consensus.csv")
    manifest = {row["bug_key"]: row for row in manifest_rows}
    evidence = {f"{row['project_id']}-{row['bug_id']}": row for row in evidence_rows}

    developer_metadata = {}
    for bug_key in sorted(manifest):
        checkout = SHARED_ROOT / bug_key
        tags = git(checkout, "tag", "--list").splitlines()
        buggy_tags = [tag for tag in tags if tag.endswith("_BUGGY_VERSION")]
        fixed_tags = [tag for tag in tags if tag.endswith("_FIXED_VERSION")]
        if len(buggy_tags) != 1 or len(fixed_tags) != 1:
            raise RuntimeError(f"Could not resolve fixed/buggy tags for {bug_key}: {tags}")
        buggy_tag, fixed_tag = buggy_tags[0], fixed_tags[0]
        diff = git(checkout, "diff", "--no-ext-diff", "--unified=80", buggy_tag, fixed_tag, "--")
        patch_path = AUDIT_ROOT / f"developer_patches/{bug_key}.diff"
        patch_path.parent.mkdir(parents=True, exist_ok=True)
        patch_path.write_text(diff, encoding="utf-8")
        changed_files = [line for line in git(checkout, "diff", "--name-only", buggy_tag, fixed_tag, "--").splitlines() if line]
        for relative in changed_files:
            for version, tag in (("buggy", buggy_tag), ("fixed", fixed_tag)):
                destination = AUDIT_ROOT / "developer_sources" / bug_key / version / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                try:
                    content = git(checkout, "show", f"{tag}:{relative}", binary=True)
                except subprocess.CalledProcessError:
                    continue
                destination.write_bytes(content)
        developer_metadata[bug_key] = {
            "buggy_tag": buggy_tag,
            "fixed_tag": fixed_tag,
            "developer_patch_path": patch_path.relative_to(AUDIT_ROOT).as_posix(),
            "developer_patch_sha256": sha256_file(patch_path),
            "developer_changed_files": changed_files,
        }
    write_json(AUDIT_ROOT / "developer_patch_inventory.json", developer_metadata)

    audit_fields = [
        "bug_id",
        "bug_key",
        "group",
        "run_id",
        "selected_attempt_id",
        "patch_hash",
        "unique_patch_id",
        "duplicate_group_size",
        "plausible",
        "developer_patch_available",
        "evidence_stratum",
        "defect_category",
        "root_cause_related",
        "semantic_equivalent",
        "overfitting_risk",
        "final_correctness",
        "correctness_type",
        "developer_patch_mechanism",
        "generated_patch_mechanism",
        "correctness_reason",
        "audit_status",
        "reviewer",
        "second_review_required",
        "second_reviewer",
        "second_review_reason",
    ]

    plausible_items = []
    all_items = []
    for row in bug_results:
        bug_key = row["bug_key"]
        patch_path = resolve_project(row["best_patch_path"])
        patch_hash = sha256_file(patch_path)
        stratum = manifest[bug_key]["final_human_label"]
        category = manifest[bug_key]["research_defect_categories"]
        plausible = row["plausible"] == "true"
        item = {
            "bug_id": f"{row['project_id']}-{row['bug_id']}",
            "bug_key": bug_key,
            "group": row["experiment_group"],
            "run_id": row["run_id"],
            "selected_attempt_id": row["best_attempt"],
            "patch_hash": patch_hash,
            "unique_patch_id": "",
            "duplicate_group_size": "",
            "plausible": str(plausible).lower(),
            "developer_patch_available": "true",
            "evidence_stratum": stratum,
            "defect_category": category,
            "root_cause_related": "pending" if plausible else "not_reviewed",
            "semantic_equivalent": "pending" if plausible else "no",
            "overfitting_risk": "pending" if plausible else "not_applicable",
            "final_correctness": "pending" if plausible else "incorrect",
            "correctness_type": "pending" if plausible else "mechanical_failure",
            "developer_patch_mechanism": "" if plausible else "not_reviewed_due_to_mechanical_failure",
            "generated_patch_mechanism": "" if plausible else "failed_frozen_functional_oracle",
            "correctness_reason": "" if plausible else "Selected primary patch failed the frozen full-test/plausibility oracle and therefore cannot count as a correct repair.",
            "audit_status": "pending_review" if plausible else "complete",
            "reviewer": "Codex offline semantic audit" if plausible else "mechanical oracle",
            "second_review_required": "pending" if plausible else "false",
            "second_reviewer": "",
            "second_review_reason": "",
        }
        all_items.append(item)
        if plausible:
            plausible_items.append((item, row, patch_path))

    groups_by_hash = defaultdict(list)
    for item, row, patch_path in plausible_items:
        groups_by_hash[item["patch_hash"]].append(item)
    unique_hashes = sorted(groups_by_hash)
    patch_ids = {patch_hash: f"UP-{index:02d}" for index, patch_hash in enumerate(unique_hashes, 1)}
    for item in all_items:
        if item["plausible"] == "true":
            item["unique_patch_id"] = patch_ids[item["patch_hash"]]
            item["duplicate_group_size"] = str(len(groups_by_hash[item["patch_hash"]]))
        else:
            item["unique_patch_id"] = "not_applicable"
            item["duplicate_group_size"] = "0"

    unique_rows = []
    for patch_hash in unique_hashes:
        members = groups_by_hash[patch_hash]
        unique_rows.append(
            {
                "unique_patch_id": patch_ids[patch_hash],
                "patch_hash": patch_hash,
                "member_count": len(members),
                "bug_key": members[0]["bug_key"],
                "members": "|".join(f"{item['bug_key']}:{item['group']}:attempt{item['selected_attempt_id']}" for item in members),
            }
        )
    write_csv(
        AUDIT_ROOT / "unique_patch_groups.csv",
        unique_rows,
        ["unique_patch_id", "patch_hash", "member_count", "bug_key", "members"],
    )
    write_csv(AUDIT_ROOT / "stage2_correctness_audit_working.csv", all_items, audit_fields)

    packet_index = []
    created_hashes = set()
    for item, result_row, patch_path in plausible_items:
        patch_hash = item["patch_hash"]
        packet_id = patch_ids[patch_hash]
        packet = AUDIT_ROOT / "audit_packets" / f"{item['bug_key']}_{packet_id}"
        if patch_hash not in created_hashes:
            packet.mkdir(parents=True, exist_ok=True)
            generated_patch = packet / "generated_patch.diff"
            shutil.copy2(patch_path, generated_patch)
            developer_patch = AUDIT_ROOT / developer_metadata[item["bug_key"]]["developer_patch_path"]
            shutil.copy2(developer_patch, packet / "developer_patch.diff")
            diff_text = generated_patch.read_text(encoding="utf-8", errors="replace")
            changed_paths = generated_paths(diff_text)
            shared_checkout = SHARED_ROOT / item["bug_key"]
            attempt_checkout = ATTEMPT_ROOT / item["bug_key"] / item["group"] / f"attempt_{item['selected_attempt_id']}"
            copied = {"buggy": [], "patched": [], "developer_fixed": []}
            for relative in sorted(set(changed_paths + developer_metadata[item["bug_key"]]["developer_changed_files"])):
                if safe_copy(shared_checkout / relative, packet / "sources/buggy" / relative):
                    copied["buggy"].append(relative)
                if safe_copy(attempt_checkout / relative, packet / "sources/patched" / relative):
                    copied["patched"].append(relative)
                fixed_source = AUDIT_ROOT / "developer_sources" / item["bug_key"] / "fixed" / relative
                if safe_copy(fixed_source, packet / "sources/developer_fixed" / relative):
                    copied["developer_fixed"].append(relative)
            metadata = {
                "unique_patch_id": packet_id,
                "patch_hash": patch_hash,
                "bug_key": item["bug_key"],
                "representative_group": item["group"],
                "representative_attempt": item["selected_attempt_id"],
                "duplicate_members": [
                    f"{member['bug_key']}:{member['group']}:attempt{member['selected_attempt_id']}"
                    for member in groups_by_hash[patch_hash]
                ],
                "trigger_tests": manifest[item["bug_key"]]["trigger_tests"],
                "target_file": manifest[item["bug_key"]]["target_file"],
                "target_method": manifest[item["bug_key"]]["target_method"],
                "evidence_stratum": item["evidence_stratum"],
                "defect_category": item["defect_category"],
                "bug_level_evidence": evidence.get(item["bug_key"], {}),
                "developer_metadata": developer_metadata[item["bug_key"]],
                "copied_sources": copied,
                "frozen_result": result_row,
            }
            write_json(packet / "metadata.json", metadata)
            created_hashes.add(patch_hash)
        packet_index.append(
            {
                "unique_patch_id": packet_id,
                "bug_key": item["bug_key"],
                "group": item["group"],
                "attempt": item["selected_attempt_id"],
                "packet_path": packet.relative_to(AUDIT_ROOT).as_posix(),
            }
        )
    write_csv(AUDIT_ROOT / "audit_packet_index.csv", packet_index, list(packet_index[0]))

    summary = {
        "run_id": RUN_ID,
        "primary_runs": len(bug_results),
        "plausible_selected_patches": len(plausible_items),
        "non_plausible_primary_runs": len(bug_results) - len(plausible_items),
        "unique_plausible_patches": len(unique_hashes),
        "duplicate_patch_instances": len(plausible_items) - len(unique_hashes),
        "duplicate_hash_groups": sum(len(members) > 1 for members in groups_by_hash.values()),
        "generation_integrity": integrity,
    }
    write_json(AUDIT_ROOT / "audit_preparation_summary.json", summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
