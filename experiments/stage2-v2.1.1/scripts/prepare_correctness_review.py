from pathlib import Path
import csv
from common import read_csv, write_csv
ROOT=Path(__file__).resolve().parents[1]; OUT=ROOT/'outputs'; rows=read_csv(OUT/'stage2_bug_results.csv')
if len(rows)!=40: raise SystemExit(f'Need 40 result rows before correctness review; found {len(rows)}')
fields=['project_id','bug_id','bug_key','experiment_group','plausible_status','patch_path','final_correctness','correctness_notes','reviewer']
out=[]
for r in rows: out.append({k:r.get(k,'') for k in fields}|{'final_correctness':'pending_human','correctness_notes':'','reviewer':''})
write_csv(OUT/'stage2_correctness_review_template.csv',out,fields)
print('Created outputs/stage2_correctness_review_template.csv')
