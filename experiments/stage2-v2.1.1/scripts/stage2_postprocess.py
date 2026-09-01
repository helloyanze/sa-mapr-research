from __future__ import annotations
import argparse, csv, json
from collections import Counter, defaultdict
from pathlib import Path
from common import read_csv, write_csv
ROOT=Path(__file__).resolve().parents[1]
def b(v): return str(v).lower()=='true'
def main():
 ap=argparse.ArgumentParser(); ap.add_argument('--results',default='outputs/stage2_bug_results.csv'); ap.add_argument('--outdir',default='outputs'); args=ap.parse_args()
 rows=read_csv(ROOT/args.results); out=ROOT/args.outdir; by=defaultdict(dict)
 for r in rows: by[r['bug_key']][r['experiment_group']]=r
 comp=[]
 fields=['project_id','bug_id','bug_key','baseline_compile','samapr_compile','baseline_plausible','samapr_plausible','baseline_verifier_accept','samapr_verifier_accept','baseline_cost','samapr_cost','cost_delta','samapr_realized_mapping_success','final_correctness_A','final_correctness_B']
 for key,groups in sorted(by.items()):
  if 'A' not in groups or 'B' not in groups: continue
  a,c=groups['A'],groups['B']; comp.append({
   'project_id':a['project_id'],'bug_id':a['bug_id'],'bug_key':key,'baseline_compile':a['compile_status'],'samapr_compile':c['compile_status'],
   'baseline_plausible':a['plausible_status'],'samapr_plausible':c['plausible_status'],
   'baseline_verifier_accept':a['verifier_decision'],'samapr_verifier_accept':c['verifier_decision'],
   'baseline_cost':a['total_cost'],'samapr_cost':c['total_cost'],'cost_delta':float(c['total_cost'] or 0)-float(a['total_cost'] or 0),
   'samapr_realized_mapping_success':c['realized_mapping_success'],'final_correctness_A':a['final_correctness'],'final_correctness_B':c['final_correctness']})
 write_csv(out/'stage2_group_comparison.csv',comp,fields)
 groups=defaultdict(list)
 for r in rows: groups[r['experiment_group']].append(r)
 cost=[]; valid=[]
 for g,rs in sorted(groups.items()):
  cost.append({'experiment_group':g,'runs':len(rs),'input_tokens':sum(int(r['input_tokens'] or 0) for r in rs),'output_tokens':sum(int(r['output_tokens'] or 0) for r in rs),'total_cost':sum(float(r['total_cost'] or 0) for r in rs),'execution_time':sum(float(r['execution_time'] or 0) for r in rs)})
  valid.append({'experiment_group':g,'runs':len(rs),'compile_pass':sum(r['compile_status']=='pass' for r in rs),'trigger_pass':sum(r['trigger_test_status']=='pass' for r in rs),'all_tests_pass':sum(r['all_test_status']=='pass' for r in rs),'plausible':sum(b(r['plausible_status']) for r in rs),'verifier_accept':sum(r['verifier_decision']=='accept' for r in rs),'correct':sum(r['final_correctness']=='Correct' for r in rs),'incorrect':sum(r['final_correctness']=='Incorrect' for r in rs),'overfitting_suspected':sum(r['final_correctness']=='Overfitting-suspected' for r in rs),'pending_human':sum(r['final_correctness']=='pending_human' for r in rs)})
 write_csv(out/'stage2_cost_summary.csv',cost,['experiment_group','runs','input_tokens','output_tokens','total_cost','execution_time'])
 write_csv(out/'stage2_validation_summary.csv',valid,['experiment_group','runs','compile_pass','trigger_pass','all_tests_pass','plausible','verifier_accept','correct','incorrect','overfitting_suspected','pending_human'])
 complete=len(rows)==40; pending=any(r['final_correctness']=='pending_human' for r in rows)
 lines=['# SA-MAPR v2 Stage 2 execution report','',f'- Result rows: {len(rows)}/40',f'- Paired bugs: {len(comp)}/20',f'- Final correctness pending: {pending}','']
 for x in valid: lines += [f"## Group {x['experiment_group']}",f"- Compile pass: {x['compile_pass']}/{x['runs']}",f"- Plausible: {x['plausible']}/{x['runs']}",f"- Verifier accept: {x['verifier_accept']}/{x['runs']}",f"- Correct: {x['correct']}",f"- Pending human: {x['pending_human']}",'']
 if pending: lines += ['## Green-light decision','Final correctness is incomplete; no green-light claim is allowed.']
 (out/'stage2_execution_report.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
 print(json.dumps({'result_rows':len(rows),'paired_bugs':len(comp),'pending_human':pending},ensure_ascii=False,indent=2))
if __name__=='__main__': main()
