from __future__ import annotations

import argparse, re
from datetime import datetime
from pathlib import Path

from common import RESULT_FIELDS, load_json, read_csv, write_csv
from stage2_runner import finalize_run_metrics

ROOT=Path(__file__).resolve().parents[1]


def elapsed_seconds(started,finished,fallback):
    try:
        return (datetime.strptime(finished,'%Y-%m-%dT%H:%M:%S%z')
                -datetime.strptime(started,'%Y-%m-%dT%H:%M:%S%z')).total_seconds()
    except (TypeError,ValueError):
        return float(fallback or 0)


def main():
    ap=argparse.ArgumentParser(description='Reconcile result usage from saved prompt/response artifacts.')
    ap.add_argument('--config',default='config/stage2_config.json')
    args=ap.parse_args()
    cfg=load_json(ROOT/args.config); out=(ROOT/cfg['output_root']).resolve()
    results=read_csv(out/'stage2_bug_results.csv'); manifests=read_csv(out/'stage2_run_manifest.csv')
    manifest_index={(r['bug_key'],r['experiment_group']):r for r in manifests}
    reconciled=[]
    for row in results:
        bug=row['bug_key']; group=row['experiment_group']; prefix=f'{bug}_{group}_attempt'
        prompt_paths=list((out/'prompts').glob(f'{prefix}*.json'))
        response_paths=list((out/'responses').glob(f'{prefix}*.json'))
        if not response_paths:
            reconciled.append(row); continue
        attempt_numbers=[]
        for path in prompt_paths:
            match=re.search(r'_attempt(\d+)\.json$',path.name)
            if match: attempt_numbers.append(int(match.group(1)))
        total_in=total_out=0
        for path in response_paths:
            usage=load_json(path).get('usage',{})
            total_in+=int(usage.get('prompt_tokens',usage.get('input_tokens',0)) or 0)
            total_out+=int(usage.get('completion_tokens',usage.get('output_tokens',0)) or 0)
        attempts=max(attempt_numbers or [int(row.get('attempts_used') or 0)])
        manifest=manifest_index.get((bug,group),{})
        elapsed=elapsed_seconds(manifest.get('started_at'),manifest.get('finished_at'),row.get('execution_time'))
        reconciled.append(finalize_run_metrics(row,cfg,attempts,total_in,total_out,elapsed))
    write_csv(out/'stage2_bug_results.csv',reconciled,RESULT_FIELDS)
    print(f'Reconciled {len(reconciled)} result rows from saved artifacts')


if __name__=='__main__': main()
