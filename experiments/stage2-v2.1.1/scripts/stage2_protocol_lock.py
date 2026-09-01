from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import load_json, now, save_json
from revised_common import canonical_json, sha256_text


ROOT = Path(__file__).resolve().parents[1]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def git_head() -> str:
    result = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True, capture_output=True, check=True)
    return result.stdout.strip()


def lock_payload(config_path: Path) -> dict:
    cfg = load_json(config_path)
    baseline = ROOT / "prompts/revised_baseline_system.md"
    contract_prompt = ROOT / "prompts/revised_contract_system.md"
    prompt_hashes = {
        "A_R_system": sha256_file(baseline),
        "C_system": sha256_file(contract_prompt),
    }
    return {
        "protocol_version": cfg["protocol_version"],
        "mapping_implementation_version": cfg["mapping_implementation_version"],
        "code_commit": git_head(),
        "config_path": str(config_path.relative_to(ROOT)).replace("\\", "/"),
        "config_hash": sha256_file(config_path),
        "prompt_hash": sha256_text(canonical_json(prompt_hashes)),
        "prompt_hashes": prompt_hashes,
        "contract_schema_hash": sha256_file(ROOT / "schemas/executable_evidence_contract_v2_1.schema.json"),
        "obligation_registry_hash": sha256_file(ROOT / "config/obligation_registry.json"),
        "model": cfg["llm"]["model"],
        "model_version": cfg["llm"]["model_version"],
        "thinking": cfg["llm"].get("thinking"),
        "temperature": cfg["llm"]["temperature"],
        "top_p": cfg["llm"]["top_p"],
        "token_budget": cfg["llm"]["total_token_budget_per_bug_group"],
        "max_output_tokens": cfg["llm"]["max_output_tokens"],
        "attempt_limit": cfg["llm"]["maximum_attempts"],
        "timeout": {"api": cfg["llm"]["timeout_seconds"], **cfg["timeouts"]},
        "patch_quantity_limit": cfg["patch_quantity_limit_per_attempt"],
        "groups": cfg["revised_groups"],
        "bug_count": len(cfg["stage2_mve_bug_keys"]),
        "primary_run_count": len(cfg["stage2_mve_bug_keys"]) * len(cfg["revised_groups"]),
        "bug_keys": cfg["stage2_mve_bug_keys"],
        "20_bug_manifest_hash": sha256_file(ROOT / "frozen_inputs/stage2_20bug_input_manifest.csv"),
    }


def add_lock_id(payload: dict) -> dict:
    lock_id = "stage2-v2.1.1-" + sha256_text(canonical_json(payload))[:16]
    return {"protocol_lock_id": lock_id, "created_at": now(), **payload}


def verify_lock(lock: dict, config_path: Path) -> list[str]:
    problems = []
    expected_payload = lock_payload(config_path)
    actual_payload = {key: value for key, value in lock.items() if key not in {"protocol_lock_id", "created_at"}}
    expected_id = "stage2-v2.1.1-" + sha256_text(canonical_json(actual_payload))[:16]
    if lock.get("protocol_lock_id") != expected_id:
        problems.append("protocol_lock_id digest mismatch")
    for key, value in expected_payload.items():
        if actual_payload.get(key) != value:
            problems.append(f"locked field changed: {key}")
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description="Create or verify the frozen Stage 2 20-Bug protocol lock")
    parser.add_argument("--config", default="config/stage2_v2_1_20bug_config.json")
    parser.add_argument("--output", default="protocol_locks/stage2_protocol_lock.json")
    parser.add_argument("--hotfix-gate", default="outputs/mapping_hotfix_v2_1_1/mapping_hotfix_gate.json")
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    config_path = (ROOT / args.config).resolve()
    output = (ROOT / args.output).resolve()
    if args.verify:
        if not output.is_file():
            raise SystemExit(f"protocol lock not found: {output}")
        problems = verify_lock(load_json(output), config_path)
        print(json.dumps({"pass": not problems, "problems": problems}, ensure_ascii=False, indent=2))
        return 1 if problems else 0
    gate_path = (ROOT / args.hotfix_gate).resolve()
    if not gate_path.is_file() or not load_json(gate_path).get("pass"):
        raise SystemExit("MAPPING_HOTFIX_PASS gate is required before protocol lock creation")
    if output.exists():
        raise SystemExit(f"immutable protocol lock already exists: {output}")
    payload = add_lock_id(lock_payload(config_path))
    save_json(output, payload)
    print(json.dumps({"output": str(output), "protocol_lock_id": payload["protocol_lock_id"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
