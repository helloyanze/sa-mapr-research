from __future__ import annotations

import json
from pathlib import Path

from common import read_csv, safe_rel_path


def _split_trigger_tests(value: str) -> list[str]:
    return [x.strip() for x in str(value or '').replace('|', '\n').splitlines() if x.strip()]


def load_runtime_dataset(root: Path) -> dict[str, dict]:
    """Load only frozen manifest + runtime-safe buggy inputs and validate their join."""
    manifest_path = root / 'frozen_inputs/stage2_20bug_input_manifest.csv'
    safe_path = root / 'runtime_safe/stage2_safe_bug_inputs.jsonl'
    manifest = {r['bug_key']: r for r in read_csv(manifest_path)}
    safe: dict[str, dict] = {}
    for line_no, line in enumerate(safe_path.read_text(encoding='utf-8').splitlines(), 1):
        if not line.strip():
            continue
        item = json.loads(line)
        key = str(item.get('bug_key', ''))
        if not key or key in safe:
            raise ValueError(f'invalid or duplicate bug_key at runtime-safe line {line_no}: {key!r}')
        safe[key] = item
    if set(manifest) != set(safe):
        raise ValueError(f'manifest/runtime-safe key mismatch: manifest_only={sorted(set(manifest)-set(safe))}, safe_only={sorted(set(safe)-set(manifest))}')
    for key, item in safe.items():
        row = manifest[key]
        checks = {
            'project_id': str(item['project_id']) == str(row['project_id']),
            'bug_id': str(item['bug_id']) == str(row['bug_id']),
            'target_file': safe_rel_path(item['target_file']) == safe_rel_path(row['target_file']),
            'target_method': str(item['target_method']) == str(row['target_method']),
            'preflight': bool(item['preflight']) == (str(row['preflight']).lower() == 'true'),
            'trigger_tests': set(item['trigger_tests']) == set(_split_trigger_tests(row['trigger_tests'])),
        }
        failed = [name for name, ok in checks.items() if not ok]
        if failed:
            raise ValueError(f'{key} manifest/runtime-safe mismatch: {failed}')
        item['_manifest'] = {k: v for k, v in row.items() if k != 'final_human_label'}
    return safe


def code_contexts(item: dict) -> list[dict]:
    """Return deduplicated buggy contexts shared by both experimental groups."""
    contexts: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for warning in item.get('buggy_spotbugs_warnings', []):
        key = (safe_rel_path(warning['target_file']), str(warning.get('target_method', '')))
        if key in seen:
            continue
        seen.add(key)
        contexts.append({
            'file': key[0],
            'method': key[1],
            'code': str(warning.get('buggy_context', '')).strip(),
        })
    primary = (safe_rel_path(item['target_file']), str(item.get('target_method', '')))
    if primary not in seen:
        contexts.insert(0, {'file': primary[0], 'method': primary[1], 'code': str(item.get('buggy_code_seed_context', '')).strip()})
    return contexts
