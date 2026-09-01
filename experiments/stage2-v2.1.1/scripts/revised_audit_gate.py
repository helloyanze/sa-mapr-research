from __future__ import annotations

import argparse,json,subprocess
from pathlib import Path

from common import load_json,read_csv,save_json
from revised_common import GROUPS,initialize_run

ROOT=Path(__file__).resolve().parents[1]

def truth(value): return str(value).lower()=='true'

def git_text(*args):
    try: return subprocess.check_output(['git',*args],cwd=ROOT,text=True,errors='replace').strip()
    except Exception: return ''

def build_leakage_report(out: Path):
    findings=[]; counts={'prompt':0,'contract':0,'shared_context':0}
    for path in sorted((out/'prompts').glob('*.json')):
        counts['prompt']+=1; audit=load_json(path).get('leakage_audit',{})
        for finding in audit.get('findings',[]): findings.append({'kind':'prompt','file':str(path.relative_to(out)),'finding':finding})
    for path in sorted((out/'contracts').glob('*_leakage_audit.json')):
        counts['contract']+=1
        for finding in load_json(path).get('findings',[]): findings.append({'kind':'contract','file':str(path.relative_to(out)),'finding':finding})
    for path in sorted((out/'shared_contexts').glob('*/shared_context_leakage_audit.json')):
        counts['shared_context']+=1
        for finding in load_json(path).get('findings',[]): findings.append({'kind':'shared_context','file':str(path.relative_to(out)),'finding':finding})
    report={'pass':not findings,'forbidden_findings':len(findings),'counts':counts,'findings':findings}
    save_json(out/'revised_preflight_leakage_audit.json',report)
    lines=['# Revised Pre-flight Leakage Audit','',f"- Status: {'PASS' if report['pass'] else 'FAIL'}",
           f"- Prompt records: {counts['prompt']}",f"- Contract audits: {counts['contract']}",
           f"- Shared Context audits: {counts['shared_context']}",f"- Forbidden findings: {len(findings)}",'']
    lines += [f"- `{x['kind']}` `{x['file']}`: {x['finding']}" for x in findings]
    (out/'revised_preflight_leakage_audit.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    return report

def build_fairness_report(out: Path):
    rows=read_csv(out/'revised_preflight_manifest.csv'); by_bug={}; findings=[]
    for row in rows: by_bug.setdefault(row['bug_key'],{})[row['experiment_group']]=row
    audit_rows=[]
    fairness_fields=('model','model_version','temperature','top_p','max_output_tokens','maximum_attempts','token_budget',
                     'timeout_compile','timeout_trigger_test','timeout_all_tests','timeout_spotbugs','patch_quantity_limit')
    for bug,groups in sorted(by_bug.items()):
        missing=set(GROUPS)-set(groups); hashes={g:groups.get(g,{}).get('shared_context_sha256','') for g in GROUPS}
        hash_equal=not missing and len(set(hashes.values()))==1 and bool(hashes['A'])
        parameters_equal=not missing and all(len({groups[g].get(field,'') for g in GROUPS})==1 for field in fairness_fields)
        shared=out/'shared_contexts'/bug/'shared_context.json'; full_files=shared.exists() and not load_json(shared).get('source_context_truncated',True)
        if not hash_equal: findings.append(f'{bug}: shared context hash mismatch')
        if not parameters_equal: findings.append(f'{bug}: fairness parameter mismatch')
        if not full_files: findings.append(f'{bug}: shared source context is missing or truncated')
        audit_rows.append({'bug_key':bug,'shared_context_hash_equal':hash_equal,'fairness_parameters_equal':parameters_equal,
                           'full_allowed_file_context':full_files,'hashes':hashes})
    report={'pass':not findings,'bugs':audit_rows,'findings':findings}; save_json(out/'revised_preflight_group_fairness_audit.json',report)
    lines=['# Revised Pre-flight Group Fairness Audit','',f"- Status: {'PASS' if report['pass'] else 'FAIL'}",'',
           '| Bug | Shared hash A=R=C | Parameters equal | Full allowed-file context |','|---|---:|---:|---:|']
    for row in audit_rows: lines.append(f"| {row['bug_key']} | {row['shared_context_hash_equal']} | {row['fairness_parameters_equal']} | {row['full_allowed_file_context']} |")
    if findings: lines += ['',*['- '+x for x in findings]]
    (out/'revised_preflight_group_fairness_audit.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    return report

def build_gate(out: Path,leakage: dict,fairness: dict):
    manifest=read_csv(out/'revised_preflight_manifest.csv'); bugs=read_csv(out/'revised_preflight_bug_results.csv'); attempts=read_csv(out/'revised_preflight_attempt_results.csv')
    expected={(bug,group) for bug in ('Chart-1','Codec-1','Chart-22') for group in GROUPS}
    manifest_pairs={(x['bug_key'],x['experiment_group']) for x in manifest}; result_pairs={(x['bug_key'],x['experiment_group']) for x in bugs}
    evaluated=[x for x in attempts if x['candidate_status']=='evaluated']; keys=[(x['bug_key'],x['experiment_group'],x['attempt']) for x in attempts]
    contracts=[load_json(path) for path in sorted((out/'contracts').glob('*.json')) if not path.name.endswith('_leakage_audit.json')]
    severity={o['severity'] for contract in contracts for o in contract['repair_obligations']+contract['verification_obligations']}
    chart22=[x for x in evaluated if x['bug_key']=='Chart-22']
    base_hash_equal=all(len({x['base_prompt_sha256'] for x in evaluated if x['bug_key']==bug})==1 for bug in ('Chart-1','Codec-1','Chart-22'))
    checks={
        'immutable_run_id':bool(load_json(out/'run_metadata.json').get('run_id')),
        'nine_primary_runs_completed':manifest_pairs==expected and result_pairs==expected and all(x['status']=='completed' for x in manifest),
        'raw_responses_complete':all(any((out/'responses').glob(f'{bug}_{group}_attempt*.json')) for bug,group in expected),
        'patches_complete':all(any((out/'patches').glob(f'{bug}_{group}_attempt*.diff')) for bug,group in expected),
        'token_runtime_cost_complete':all(x['input_tokens']!='' and x['output_tokens']!='' and x['runtime_seconds']!='' and x['estimated_cost']!='' for x in bugs),
        'attempts_not_overwritten':len(keys)==len(set(keys)) and bool(attempts),
        'base_prompt_hash_equal':bool(evaluated) and base_hash_equal,
        'treatment_appendix_hash_recorded':bool(evaluated) and all(x['treatment_appendix_sha256'] for x in evaluated),
        'shared_context_hash_equal':bool(fairness.get('pass')),
        'forbidden_findings_zero':bool(leakage.get('pass')) and leakage.get('forbidden_findings')==0,
        'file_level_hard_scope':len(contracts)==3 and all(x['hard_repair_scope']['file_level'] for x in contracts),
        'warning_method_not_mandatory':all('allowed_source_files' in x['hard_repair_scope'] for x in contracts),
        'contract_supports_three_classes':{'blocking','advisory','metric_only'}.issubset(severity),
        'attempt_level_three_verifiers':bool(evaluated) and all(x['would_accept_test_only']!='' and x['would_accept_generic']!='' and x['would_accept_hybrid']!='' for x in evaluated),
        'mapping_complete_for_C':all(x['claimed_mapping_valid'] not in ('','not_applicable') and x['realized_mapping_success'] not in ('','not_applicable') and x['mapping_consistent'] not in ('','not_applicable') for x in evaluated if x['experiment_group']=='C'),
        'chart22_functional_veto':bool(chart22) and all(not(truth(x['target_warning_removed']) and not truth(x['full_test']) and truth(x['would_accept_hybrid'])) for x in chart22),
        'no_effectiveness_gate':True,
    }
    blockers=[key for key,value in checks.items() if not value]
    report={'protocol_version':'2.1','pass':not blockers,'decision':'GO_FOR_20_BUG_MVE' if not blockers else 'HOLD_AND_FIX',
            'checks':checks,'blocking_issues':blockers,'primary_runs':len(bugs),'attempt_rows':len(attempts)}
    save_json(out/'revised_preflight_gate.json',report); return report

def build_execution_report(out: Path,gate: dict):
    bugs=read_csv(out/'revised_preflight_bug_results.csv'); attempts=read_csv(out/'revised_preflight_attempt_results.csv')
    totals={'input':sum(int(float(x['input_tokens'] or 0)) for x in bugs),'output':sum(int(float(x['output_tokens'] or 0)) for x in bugs),
            'cost':sum(float(x['estimated_cost'] or 0) for x in bugs),'runtime':sum(float(x['runtime_seconds'] or 0) for x in bugs)}
    lines=['# SA-MAPR v2.1 Revised Pre-flight Execution Report','',f"- Run ID: `{load_json(out/'run_metadata.json')['run_id']}`",
           f"- Gate: **{gate['decision']}**",f"- Primary runs: {len(bugs)}",f"- Attempt rows: {len(attempts)}",
           f"- Input tokens: {totals['input']}",f"- Output tokens: {totals['output']}",f"- Estimated cost: {totals['cost']:.6f} USD",
           f"- Runtime sum: {totals['runtime']:.3f} seconds",f"- Implementation commit: `{git_text('rev-parse','HEAD')}`",'',
           '## Primary Results','',
           '| Bug | Group | Attempts | V0 Test-only | V1 Generic | V2 Hybrid | Full test | Mapping consistent |','|---|---|---:|---:|---:|---:|---:|---:|']
    for row in sorted(bugs,key=lambda x:(x['bug_key'],x['experiment_group'])):
        lines.append(f"| {row['bug_key']} | {row['experiment_group']} | {row['attempts_used']} | {row['would_accept_test_only']} | {row['would_accept_generic']} | {row['would_accept_hybrid']} | {row['full_test']} | {row['mapping_consistent']} |")
    lines += ['', '## Gate Checks','']+[f"- [{'x' if value else ' '}] {key}" for key,value in gate['checks'].items()]
    diff=git_text('show','--stat','--oneline','--summary','HEAD')
    lines += ['', '## Implementation Commit Diff Summary','', '```text', diff or 'git commit summary unavailable', '```','']
    (out/'revised_preflight_execution_report.md').write_text('\n'.join(lines),encoding='utf-8')

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--config',default='config/stage2_v2_1_config.json'); ap.add_argument('--run-id',required=True)
    args=ap.parse_args(); cfg=load_json(ROOT/args.config); out=initialize_run(ROOT,cfg,args.run_id,True)
    leakage=build_leakage_report(out); fairness=build_fairness_report(out); gate=build_gate(out,leakage,fairness); build_execution_report(out,gate)
    print(json.dumps(gate,ensure_ascii=False,indent=2)); return 0 if gate['pass'] else 2

if __name__=='__main__': raise SystemExit(main())
