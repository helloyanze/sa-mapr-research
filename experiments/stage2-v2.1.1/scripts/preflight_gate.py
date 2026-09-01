from __future__ import annotations

import csv
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'outputs'
PRE = {'Chart-1', 'Codec-1', 'Chart-22'}
EXPECTED_PAIRS = {(bug_key, group) for bug_key in PRE for group in ('A', 'B')}


def load_report(path: Path) -> dict:
    if not path.exists():
        return {'pass': False}
    return json.loads(path.read_text(encoding='utf-8'))


def api_response_recorded(out: Path, bug_key: str, group: str) -> bool:
    response_dir = out / 'responses'
    return any(response_dir.glob(f'{bug_key}_{group}_attempt*.json'))


def build_preflight_report(out: Path = OUT) -> dict:
    env = load_report(out / 'preflight_environment_report.json')
    leak = load_report(out / 'stage2_prompt_leakage_audit.json')
    dry = load_report(out / 'dry_run_report.json')

    results_path = out / 'stage2_bug_results.csv'
    if results_path.exists():
        with results_path.open('r', encoding='utf-8-sig', newline='') as handle:
            rows = list(csv.DictReader(handle))
    else:
        rows = []

    preflight_rows = [row for row in rows if row.get('bug_key') in PRE]
    rows_by_pair = {
        (row.get('bug_key', ''), row.get('experiment_group', '')): row
        for row in preflight_rows
    }

    def every_pair(predicate) -> bool:
        return all(pair in rows_by_pair and predicate(rows_by_pair[pair])
                   for pair in EXPECTED_PAIRS)

    checks = {
        'dry_run': bool(dry.get('pass')),
        'environment_preflight': bool(env.get('pass')),
        'prompt_leakage_audit': bool(leak.get('pass')),
        'six_paired_runs': (
            len(preflight_rows) == len(EXPECTED_PAIRS)
            and set(rows_by_pair) == EXPECTED_PAIRS
        ),
        'all_api_responses_recorded': all(
            api_response_recorded(out, bug_key, group)
            for bug_key, group in EXPECTED_PAIRS
        ),
        'all_patch_parse_apply_pipeline_reached': every_pair(
            lambda row: row.get('patch_apply_status') not in ('', 'not_generated')
        ),
        'token_usage_recorded': every_pair(
            lambda row: row.get('input_tokens') != '' and row.get('output_tokens') != ''
        ),
        'mapping_recorded_for_B': all(
            (bug_key, 'B') in rows_by_pair
            and rows_by_pair[(bug_key, 'B')].get('claimed_mapping_validity') not in ('', 'not_run')
            and rows_by_pair[(bug_key, 'B')].get('realized_mapping_success') not in ('', 'not_run')
            for bug_key in PRE
        ),
        'logs_recorded': every_pair(lambda row: bool(row.get('log_path'))),
        'patch_applied_all_six': every_pair(
            lambda row: row.get('patch_apply_status') == 'applied'
        ),
    }
    return {
        'pass': all(checks.values()),
        'checks': checks,
        'preflight_rows': len(preflight_rows),
    }


def main() -> int:
    report = build_preflight_report()
    (OUT / 'preflight_gate.json').write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding='utf-8',
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report['pass'] else 2


if __name__ == '__main__':
    raise SystemExit(main())
