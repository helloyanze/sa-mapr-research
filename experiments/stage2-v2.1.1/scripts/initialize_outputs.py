from pathlib import Path
from common import read_csv, write_csv, RESULT_FIELDS, RUN_MANIFEST_FIELDS, FAILURE_FIELDS
import json
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'outputs'; OUT.mkdir(exist_ok=True)
manifest=read_csv(ROOT/'frozen_inputs/stage2_20bug_input_manifest.csv')
rows=[]
seq=1
for item in manifest:
    for group in ['A','B']:
        rows.append({
            'sequence_id':seq,'project_id':item['project_id'],'bug_id':item['bug_id'],'bug_key':item['bug_key'],
            'experiment_group':group,'phase':'preflight' if item['preflight'].lower()=='true' else 'full',
            'model':'','model_version':'','temperature':'','top_p':'','max_output_tokens':'','maximum_attempts':'',
            'token_budget':'','timeout_compile':'','timeout_trigger_test':'','timeout_all_tests':'','timeout_spotbugs':'',
            'patch_quantity_limit':'','status':'pending','started_at':'','finished_at':''
        }); seq+=1
write_csv(OUT/'stage2_run_manifest.csv',rows,RUN_MANIFEST_FIELDS)
for path,fields in [(OUT/'stage2_bug_results.csv',RESULT_FIELDS),(OUT/'stage2_failures.csv',FAILURE_FIELDS)]:
    if not path.exists(): write_csv(path,[],fields)
for d in ['stage2_logs','stage2_patch_inventory','evidence_reports','spotbugs_reports','prompts','responses','api_diff','runtime_contracts','dry_run']:
    (OUT/d).mkdir(parents=True,exist_ok=True)
print('Initialized outputs')
