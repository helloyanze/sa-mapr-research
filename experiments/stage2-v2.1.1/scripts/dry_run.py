from __future__ import annotations

import argparse, hashlib, json, tempfile, sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))

from common import load_json, run_cmd, save_json
from contract_builder import allowed_source_files, build_contract, load_registry, validate_contract
from manifest_loader import load_runtime_dataset
from patching import apply_patch, patch_files
from prompting import audit_prompt_text, load_template, parse_model_output, render_user_prompt
from verifier import build_evidence_report, validate_claimed_mapping

ROOT=Path(__file__).resolve().parents[1]


def fixture_patch(files):
    chunks=[]
    for file in files:
        chunks += [f'--- a/{file}',f'+++ b/{file}','@@ -1 +1 @@','-class Fixture { int value = 1; }','+class Fixture { int value = 2; }']
    return '\n'.join(chunks)+'\n'


def fixture_ast(contract):
    results={}
    targets={}
    for obligation in contract['repair_obligations']:
        target=obligation.get('target',{}); file=target.get('file'); method=target.get('method')
        if file and method and obligation['type'] not in {'PUBLIC_API_UNCHANGED','SCOPE_LIMITATION'}:
            row=targets.setdefault(file,{}).setdefault(method,{'nodes':set(),'source':'void '+method+'() { if (value == null) return; value.toLowerCase(Locale.ROOT); }'})
            row['nodes'].update(obligation.get('expected_ast_nodes',[]))
    for file,methods in targets.items():
        results[file]={'status':'ok','unchanged':True,'imports_changed':False,'fields_changed':False,'added_private_methods':[],
            'changed_methods':[{'key':name+'()','name':name,'status':'modified','ast_nodes':sorted(data['nodes'] or {'MethodCallExpr'}),'before_source':'before','after_source':data['source']} for name,data in methods.items()]}
    for file in allowed_source_files(contract):
        results.setdefault(file,{'status':'ok','unchanged':True,'imports_changed':False,'fields_changed':False,'added_private_methods':[],'changed_methods':[]})
    return results


def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--bugs',nargs='+',default=['Chart-1','Codec-1','Chart-22']); ap.add_argument('--groups',nargs='+',choices=['A','B'],default=['A','B']); ap.add_argument('--config',default='config/stage2_config.json')
    args=ap.parse_args(); cfg=load_json(ROOT/args.config); data=load_runtime_dataset(ROOT); registry=load_registry(ROOT); out=ROOT/'outputs/dry_run'; rows=[]
    unknown=set(args.bugs)-set(data)
    if unknown: raise SystemExit('Unknown bugs: '+', '.join(sorted(unknown)))
    for bug in args.bugs:
        item=data[bug]; contract=build_contract(item,registry); validate_contract(contract,ROOT/'schemas/executable_evidence_contract.schema.json'); allowed=allowed_source_files(contract)
        for group in args.groups:
            run_dir=out/bug/group; run_dir.mkdir(parents=True,exist_ok=True); system=load_template(ROOT/('prompts/samapr_system.md' if group=='B' else 'prompts/baseline_system.md'))
            user=render_user_prompt(group,item,item['target_file'],contract if group=='B' else None); audit=audit_prompt_text(system+'\n'+user)
            save_json(run_dir/'prompt.json',{'messages':[{'role':'system','content':system},{'role':'user','content':user}],'sha256':hashlib.sha256((system+'\n'+user).encode()).hexdigest(),'leakage_audit':audit})
            claimed=[{'obligation_id':o['id'],'patch_location':o['target']['file']+'::'+o['target'].get('method',''),'justification':'fixture mapping'} for o in contract['repair_obligations']] if group=='B' else []
            raw=json.dumps({'patch':fixture_patch(allowed),'claimed_mapping':claimed,'summary':'fixture'},ensure_ascii=False); parsed=parse_model_output(raw,group)
            with tempfile.TemporaryDirectory(prefix='samapr-dry-') as temp:
                wd=Path(temp); run_cmd([cfg['git_bin'],'init','-q'],wd,run_dir/'git_init.log',60)
                for file in allowed:
                    path=wd/file; path.parent.mkdir(parents=True,exist_ok=True); path.write_text('class Fixture { int value = 1; }\n',encoding='utf-8')
                apply_info=apply_patch(cfg,wd,parsed['patch'],run_dir/'fixture.diff',allowed,run_dir/'patch_apply.log')
            delta={'target_warning_removed':True,'new_same_warning_count':0,'all_targets_present_before':True,'targets':[]}
            claimed_ok,problems=validate_claimed_mapping(contract,claimed) if group=='B' else (True,[])
            report=build_evidence_report(group,contract,claimed,claimed_ok,problems,apply_info,True,True,True,delta,fixture_ast(contract),run_dir/'validation_report.json')
            passed=audit['pass'] and set(patch_files(parsed['patch']))==set(allowed) and apply_info['status']=='applied' and report['verifier_decision']=='accept'
            rows.append({'bug_key':bug,'group':group,'pass':passed,'allowed_files':allowed,'realized_mapping_success':report['realized_mapping_success']})
            save_json(run_dir/'contract.json',contract); save_json(run_dir/'parsed_response.json',parsed)
    final={'pass':len(rows)==len(args.bugs)*len(args.groups) and all(x['pass'] for x in rows),'runs':rows}; save_json(ROOT/'outputs/dry_run_report.json',final); print(json.dumps(final,ensure_ascii=False,indent=2)); return 0 if final['pass'] else 2
if __name__=='__main__': raise SystemExit(main())
