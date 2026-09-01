from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import load_json, now, save_json, write_csv
from manifest_loader import load_runtime_dataset
from revised_common import (ATTEMPT_FIELDS, BUG_RESULT_FIELDS, GROUPS, HASH_AUDIT_FIELDS, MANIFEST_FIELDS,
                            canonical_json, sha256_text, validate_run_id)
from revised_context import build_shared_context
from revised_contract import build_contract_v2_1, load_registry, validate_contract_v2_1
from revised_preflight_runner import rel, run_group, update_manifest
from revised_prompting import audit_structured_payload
from stage2_protocol_lock import verify_lock


ROOT = Path(__file__).resolve().parents[1]
PREFIX = "stage2_mve"


def frozen_parameter_problems(cfg: dict) -> list[str]:
    preflight = load_json(ROOT / "config/stage2_v2_1_config.json")
    checks = {
        "llm": (cfg.get("llm"), preflight.get("llm")),
        "timeouts": (cfg.get("timeouts"), preflight.get("timeouts")),
        "patch_quantity_limit_per_attempt": (
            cfg.get("patch_quantity_limit_per_attempt"), preflight.get("patch_quantity_limit_per_attempt")
        ),
        "shared_context": (cfg.get("shared_context"), preflight.get("shared_context")),
        "revised_groups": (cfg.get("revised_groups"), preflight.get("revised_groups")),
    }
    return [f"formal config changed frozen field: {key}" for key, (current, old) in checks.items() if current != old]


def initialize_mve_run(cfg: dict, lock: dict, run_id: str, resume: bool) -> Path:
    out = (ROOT / cfg["mve_output_root"] / validate_run_id(run_id)).resolve()
    if out.exists() and not resume:
        raise FileExistsError(f"immutable formal run directory already exists: {out}")
    out.mkdir(parents=True, exist_ok=True)
    for name in ("shared_contexts", "prompts", "responses", "patches", "contracts", "evidence_reports",
                 "attempt_reports", "api_diff", "spotbugs_reports", "logs"):
        (out / name).mkdir(exist_ok=True)
    metadata_path = out / "run_metadata.json"
    if not metadata_path.exists():
        save_json(metadata_path, {
            "run_id": run_id,
            "phase": "formal_20bug_mve",
            "protocol_version": cfg["protocol_version"],
            "mapping_implementation_version": cfg["mapping_implementation_version"],
            "protocol_lock_id": lock["protocol_lock_id"],
            "created_at": now(),
            "groups": list(GROUPS),
            "bug_keys": cfg["stage2_mve_bug_keys"],
            "primary_run_count": len(cfg["stage2_mve_bug_keys"]) * len(GROUPS),
        })
        save_json(out / "stage2_protocol_lock.snapshot.json", lock)
        save_json(out / "stage2_v2_1_20bug_config.snapshot.json", cfg)
    manifest_path = out / f"{PREFIX}_manifest.csv"
    if not manifest_path.exists():
        data = load_runtime_dataset(ROOT)
        rows, sequence = [], 1
        for bug in cfg["stage2_mve_bug_keys"]:
            item = data[bug]
            for group in GROUPS:
                rows.append({
                    "run_id": run_id, "sequence_id": sequence, "project_id": item["project_id"],
                    "bug_id": item["bug_id"], "bug_key": bug, "experiment_group": group,
                    "phase": "formal_20bug_mve", "protocol_version": cfg["protocol_version"],
                    "protocol_lock_id": lock["protocol_lock_id"], "model": cfg["llm"]["model"],
                    "model_version": cfg["llm"]["model_version"], "temperature": cfg["llm"]["temperature"],
                    "top_p": cfg["llm"]["top_p"], "max_output_tokens": cfg["llm"]["max_output_tokens"],
                    "maximum_attempts": cfg["llm"]["maximum_attempts"],
                    "token_budget": cfg["llm"]["total_token_budget_per_bug_group"],
                    "timeout_compile": cfg["timeouts"]["compile"],
                    "timeout_trigger_test": cfg["timeouts"]["trigger_test"],
                    "timeout_all_tests": cfg["timeouts"]["all_tests"],
                    "timeout_spotbugs": cfg["timeouts"]["spotbugs"],
                    "patch_quantity_limit": cfg["patch_quantity_limit_per_attempt"],
                    "status": "pending", "started_at": "", "finished_at": "",
                    "shared_context_path": "", "shared_context_sha256": "",
                })
                sequence += 1
        write_csv(manifest_path, rows, MANIFEST_FIELDS)
    for filename, fields in ((f"{PREFIX}_attempt_results.csv", ATTEMPT_FIELDS),
                             (f"{PREFIX}_bug_results.csv", BUG_RESULT_FIELDS),
                             ("shared_context_hash_audit.csv", HASH_AUDIT_FIELDS)):
        path = out / filename
        if not path.exists():
            write_csv(path, [], fields)
    return out


def prepare_contracts(cfg: dict, out: Path) -> tuple[dict, list[str]]:
    data = load_runtime_dataset(ROOT)
    registry = load_registry(ROOT)
    problems = []
    for bug in cfg["stage2_mve_bug_keys"]:
        contract = build_contract_v2_1(data[bug], registry)
        try:
            validate_contract_v2_1(contract, ROOT / "schemas/executable_evidence_contract_v2_1.schema.json")
        except Exception as exc:
            problems.append(f"{bug}: contract schema failed: {exc}")
        audit = audit_structured_payload(contract, "contract")
        if not audit["pass"]:
            problems.append(f"{bug}: contract leakage: {audit['findings']}")
        contract_path = out / "contracts" / f"{bug}.json"
        audit_path = out / "contracts" / f"{bug}_leakage_audit.json"
        if contract_path.exists() and load_json(contract_path) != contract:
            problems.append(f"{bug}: immutable contract snapshot changed")
        elif not contract_path.exists():
            save_json(contract_path, contract)
        if audit_path.exists() and load_json(audit_path) != audit:
            problems.append(f"{bug}: immutable contract leakage audit changed")
        elif not audit_path.exists():
            save_json(audit_path, audit)
    return data, problems


def main() -> int:
    parser = argparse.ArgumentParser(description="Frozen 20 Bug x A/R/C Stage 2 MVE runner")
    parser.add_argument("--config", default="config/stage2_v2_1_20bug_config.json")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--prepare-only", action="store_true")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--bug", action="append")
    parser.add_argument("--group", action="append", choices=list(GROUPS))
    args = parser.parse_args()
    cfg_path = (ROOT / args.config).resolve()
    cfg = load_json(cfg_path)
    if not cfg.get("full_mve_enabled"):
        raise SystemExit("formal runner requires full_mve_enabled=true")
    lock_path = (ROOT / cfg["protocol_lock_path"]).resolve()
    if not lock_path.is_file():
        raise SystemExit(f"protocol lock not found: {lock_path}")
    lock = load_json(lock_path)
    problems = verify_lock(lock, cfg_path) + frozen_parameter_problems(cfg)
    cfg["protocol_lock_id"] = lock["protocol_lock_id"]
    out = initialize_mve_run(cfg, lock, args.run_id, args.resume)
    data, contract_problems = prepare_contracts(cfg, out)
    problems.extend(contract_problems)
    manifest_rows = sum(1 for _ in (out / f"{PREFIX}_manifest.csv").open(encoding="utf-8-sig")) - 1
    readiness = {
        "pass": not problems and manifest_rows == 60,
        "decision": "READY_FOR_20_BUG_MVE" if not problems and manifest_rows == 60 else "HOLD_AND_FIX",
        "protocol_lock_id": lock["protocol_lock_id"],
        "bug_count": len(cfg["stage2_mve_bug_keys"]),
        "group_count": len(GROUPS),
        "primary_run_count": manifest_rows,
        "new_llm_api_calls": 0 if args.prepare_only else "formal execution requested",
        "problems": problems,
    }
    save_json(out / "stage2_mve_readiness.json", readiness)
    if args.prepare_only or not readiness["pass"]:
        print(json.dumps({"output": str(out), **readiness}, ensure_ascii=False, indent=2))
        return 0 if readiness["pass"] else 1

    bugs = args.bug or cfg["stage2_mve_bug_keys"]
    groups = args.group or list(GROUPS)
    unknown = set(bugs) - set(cfg["stage2_mve_bug_keys"])
    if unknown:
        raise SystemExit(f"bugs outside frozen manifest: {sorted(unknown)}")
    hashes = {}
    for bug in bugs:
        contract = load_json(out / "contracts" / f"{bug}.json")
        shared, digest = build_shared_context(ROOT, cfg, data[bug], contract, out, args.run_id)
        hashes[bug] = digest
        for group in GROUPS:
            update_manifest(out, bug, group, PREFIX,
                            shared_context_path=rel(out / "shared_contexts" / bug / "shared_context.json"),
                            shared_context_sha256=digest)
        for group in groups:
            run_group(cfg, data[bug], group, contract, shared, digest, out, args.run_id, args.resume, PREFIX)
    write_csv(out / "shared_context_hash_audit.csv", [{
        "run_id": args.run_id, "bug_key": bug, "group_a_hash": digest, "group_r_hash": digest,
        "group_c_hash": digest, "all_equal": "true",
        "shared_context_path": rel(out / "shared_contexts" / bug / "shared_context.json"),
    } for bug, digest in hashes.items()], HASH_AUDIT_FIELDS)
    print(f"Completed formal Stage 2 MVE run_id={args.run_id}, bugs={bugs}, groups={groups}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
