from __future__ import annotations

import argparse,tempfile,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))

from common import load_json,save_json
from manifest_loader import load_runtime_dataset
from revised_common import canonical_json,initialize_run,sha256_text
from revised_contract import build_contract_v2_1,load_registry,raw_static_evidence,validate_contract_v2_1
from revised_prompting import audit_generation_prompt,audit_structured_payload,build_prompt_record
from revised_verifier import build_attempt_evidence,validate_claimed_mapping

ROOT=Path(__file__).resolve().parents[1]

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--config',default='config/stage2_v2_1_config.json'); ap.add_argument('--run-id',required=True)
    args=ap.parse_args(); cfg=load_json(ROOT/args.config); out=initialize_run(ROOT,cfg,args.run_id,True)
    data=load_runtime_dataset(ROOT); registry=load_registry(ROOT); rows=[]
    baseline=(ROOT/'prompts/revised_baseline_system.md').read_text(encoding='utf-8')
    contract_system=(ROOT/'prompts/revised_contract_system.md').read_text(encoding='utf-8')
    for bug in cfg['revised_preflight_bug_keys']:
        item=data[bug]; contract=build_contract_v2_1(item,registry)
        validate_contract_v2_1(contract,ROOT/'schemas/executable_evidence_contract_v2_1.schema.json')
        contract_audit=audit_structured_payload(contract,'contract')
        shared={'schema_version':'2.1','run_id':args.run_id,'bug_key':bug,'project_id':item['project_id'],'bug_id':str(item['bug_id']),
                'buggy_version':str(item['bug_id'])+'b','trigger_tests':item['trigger_tests'],'failure_summary':'Failing tests: 1',
                'trigger_failure_outputs':['Failing tests: 1'],'allowed_source_files':contract['hard_repair_scope']['allowed_source_files'],
                'source_root':'source','source_policy':'full_allowed_files','source_context_truncated':False,
                'source_files':[{'file':x,'project_path':'source/'+x,'sha256':'fixture','line_count':1,'content':'1: class Fixture {}'} for x in contract['hard_repair_scope']['allowed_source_files']],
                'fairness_parameters':{'model':cfg['llm']['model'],'model_version':cfg['llm']['model_version'],'temperature':cfg['llm']['temperature'],
                                       'top_p':cfg['llm']['top_p'],'max_output_tokens':cfg['llm']['max_output_tokens'],'token_budget':cfg['llm']['total_token_budget_per_bug_group'],
                                       'maximum_attempts':cfg['llm']['maximum_attempts'],'timeouts':cfg['timeouts'],'patch_quantity_limit':cfg['patch_quantity_limit_per_attempt']}}
        shared_hash=sha256_text(canonical_json(shared)); prompt_pass=True; prompt_findings=[]
        for group in ('A','R','C'):
            record=build_prompt_record(group,contract_system if group=='C' else baseline,shared,shared_hash,
                                       raw_static_evidence(item) if group in ('R','C') else None,contract if group=='C' else None)
            prompt_pass=prompt_pass and record['leakage_audit']['pass']; prompt_findings.extend(record['leakage_audit']['findings'])
        source=contract['hard_repair_scope']['allowed_source_files'][0]
        ast={x:{'status':'ok','unchanged':True,'changed_methods':[{'key':'differentMethod()','name':'differentMethod','status':'modified','ast_nodes':['IfStmt'],'after_source':'void differentMethod() {}'}],
                'imports_changed':False,'fields_changed':False,'added_private_methods':[]} for x in contract['hard_repair_scope']['allowed_source_files']}
        anchors={x['id']:x for x in contract['evidence_anchor']}
        claimed=[{'obligation_id':o['id'],'patch_location':anchors[o['evidence_anchor_id']]['file']+'::differentMethod()','justification':'fixture'} for o in contract['repair_obligations']]
        claimed_ok,problems=validate_claimed_mapping(contract,claimed)
        delta={'target_warning_removed':True,'new_same_warning_count':0,'targets':[{'pattern':a['pattern'],'file':a['file'],'method':a['method'],'removed':True} for a in contract['evidence_anchor']]}
        with tempfile.TemporaryDirectory() as temp:
            evidence=build_attempt_evidence('C',contract,claimed,claimed_ok,problems,{'status':'applied','scope_ok':True,'files':contract['hard_repair_scope']['allowed_source_files']},True,True,True,delta,ast,Path(temp)/'evidence.json')
        classes={o['severity'] for o in contract['repair_obligations']+contract['verification_obligations']}
        passed=contract_audit['pass'] and prompt_pass and classes=={'blocking','advisory','metric_only'} and evidence['hard_repair_scope']['pass'] and evidence['verifier_decisions']['would_accept_hybrid'] and evidence['mapping']['mapping_consistent']
        rows.append({'bug_key':bug,'pass':passed,'shared_context_sha256':shared_hash,'prompt_findings':prompt_findings,
                     'file_level_different_method_allowed':evidence['hard_repair_scope']['pass'],'severity_classes':sorted(classes),
                     'mapping_consistent':evidence['mapping']['mapping_consistent']})
    report={'pass':len(rows)==3 and all(x['pass'] for x in rows),'api_calls':0,'runs':rows}
    save_json(out/'revised_protocol_dry_run.json',report); print(report); return 0 if report['pass'] else 2

if __name__=='__main__': raise SystemExit(main())
