from __future__ import annotations

import argparse, shutil, sys, time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))

from common import apply_java_home,load_json,now,read_csv,save_json,write_csv,upsert_csv,run_cmd,parse_failing_count
from llm_client import chat_completion
from manifest_loader import load_runtime_dataset
from patching import apply_patch,patch_size
from revised_common import (ATTEMPT_FIELDS,BUG_RESULT_FIELDS,GROUPS,HASH_AUDIT_FIELDS,MANIFEST_FIELDS,
                            canonical_json,initialize_run,sha256_text)
from revised_context import build_shared_context,checkout_buggy,resolve_source_files,verify_attempt_sources
from revised_contract import (allowed_source_files,build_contract_v2_1,load_registry,raw_static_evidence,
                              validate_contract_v2_1)
from revised_prompting import (audit_structured_payload,build_prompt_record,parse_revised_output)
from revised_verifier import build_attempt_evidence,validate_claimed_mapping
from spotbugs_utils import parse_alerts,run_spotbugs,warning_delta
from verifier import run_javaparser_files

ROOT=Path(__file__).resolve().parents[1]

def test_status(code,text):
    count=parse_failing_count(text)
    return code==0 and count in (0,None)

def update_manifest(out: Path,bug: str,group: str,artifact_prefix='revised_preflight',**values):
    path=out/f'{artifact_prefix}_manifest.csv'; rows=read_csv(path)
    for row in rows:
        if row['bug_key']==bug and row['experiment_group']==group: row.update(values)
    write_csv(path,rows,MANIFEST_FIELDS)

def append_attempt(out: Path,row: dict,artifact_prefix='revised_preflight'):
    path=out/f'{artifact_prefix}_attempt_results.csv'; rows=read_csv(path)
    key=(row['bug_key'],row['experiment_group'],str(row['attempt']))
    if any((x['bug_key'],x['experiment_group'],str(x['attempt']))==key for x in rows):
        raise RuntimeError(f'attempt overwrite forbidden: {key}')
    rows.append({field:row.get(field,'') for field in ATTEMPT_FIELDS}); write_csv(path,rows,ATTEMPT_FIELDS)

def rel(path: Path): return str(path.relative_to(ROOT)).replace('\\','/')

def cost(cfg,total_in,total_out):
    return total_in/1_000_000*float(cfg['llm']['input_price_per_million'])+total_out/1_000_000*float(cfg['llm']['output_price_per_million'])

def generic_feedback(apply_info,compile_ok,trigger_ok,full_ok,compile_text,trigger_text,full_text):
    if apply_info.get('status')!='applied': return 'The patch could not be applied: '+apply_info.get('output','')[-1500:]
    if not compile_ok: return 'The patch does not compile. Compiler output:\n'+compile_text[-3000:]
    if not trigger_ok: return 'The original trigger test still fails:\n'+trigger_text[-3000:]
    if not full_ok: return 'Regression tests still fail:\n'+full_text[-3000:]
    return ''

def failed_attempt_row(run_id,bug,group,attempt,shared_hash,prompt_path='',response_path='',reason='',usage=None,runtime=0,
                       protocol_lock_id=''):
    usage=usage or {'input':0,'output':0}
    return {
        'run_id':run_id,'protocol_lock_id':protocol_lock_id,'bug_key':bug,'experiment_group':group,'attempt':attempt,'candidate_status':'framework_failed',
        'shared_context_sha256':shared_hash,'input_tokens':usage['input'],'output_tokens':usage['output'],
        'estimated_cost':0,'runtime_seconds':round(runtime,3),'patch_apply':'not_run','compile':'not_run',
        'trigger_test':'not_run','full_test':'not_run','plausible':'false','tests_unchanged':'not_run',
        'target_warning_removed':'not_run','new_same_warning_count':'not_run','public_api_unchanged':'not_run',
        'hard_scope_pass':'not_run','would_accept_test_only':'false','would_accept_generic':'false',
        'would_accept_hybrid':'false','prompt_path':prompt_path,'response_path':response_path,'failure_reason':reason,
    }

def run_group(cfg,item,group,contract,shared,shared_hash,out,run_id,resume=False,artifact_prefix='revised_preflight'):
    bug=item['bug_key']; existing=read_csv(out/f'{artifact_prefix}_bug_results.csv')
    if resume and any(x['bug_key']==bug and x['experiment_group']==group for x in existing): return
    update_manifest(out,bug,group,artifact_prefix,status='running',started_at=now(),finished_at='',
                    shared_context_path=rel(out/'shared_contexts'/bug/'shared_context.json'),shared_context_sha256=shared_hash)
    system_path=ROOT/('prompts/revised_contract_system.md' if group=='C' else 'prompts/revised_baseline_system.md')
    system=system_path.read_text(encoding='utf-8'); raw=raw_static_evidence(item); allowed=allowed_source_files(contract)
    total_in=total_out=0; attempts_used=0; best=None; feedback=''; group_start=time.time()
    max_attempts=int(cfg['llm']['maximum_attempts'])
    for attempt in range(1,max_attempts+1):
        attempts_used=attempt; attempt_start=time.time(); tag=f'{bug}_{group}_attempt{attempt}'
        wd=(ROOT/cfg['work_root']).resolve()/'_revised_attempts'/run_id/bug/group/f'attempt_{attempt}'
        code,text=checkout_buggy(ROOT,cfg,item,wd,out/'logs'/f'{tag}_checkout.log')
        if code!=0:
            append_attempt(out,failed_attempt_row(run_id,bug,group,attempt,shared_hash,reason='checkout failed: '+text[-1000:],runtime=time.time()-attempt_start,protocol_lock_id=cfg.get('protocol_lock_id','')),artifact_prefix); break
        try:
            _,project_paths,absolute=resolve_source_files(ROOT,cfg,wd,allowed,out/'logs'/f'{tag}_export_src.log')
            verify_attempt_sources(shared,absolute)
        except Exception as exc:
            append_attempt(out,failed_attempt_row(run_id,bug,group,attempt,shared_hash,reason=str(exc),runtime=time.time()-attempt_start,protocol_lock_id=cfg.get('protocol_lock_id','')),artifact_prefix); break
        prompt=build_prompt_record(group,system,shared,shared_hash,raw if group in ('R','C') else None,contract if group=='C' else None,feedback)
        prompt_path=out/'prompts'/f'{tag}.json'; save_json(prompt_path,prompt)
        if not prompt['leakage_audit']['pass']:
            append_attempt(out,failed_attempt_row(run_id,bug,group,attempt,shared_hash,rel(prompt_path),reason='prompt leakage: '+str(prompt['leakage_audit']['findings']),runtime=time.time()-attempt_start,protocol_lock_id=cfg.get('protocol_lock_id','')),artifact_prefix); break
        try:
            llm=chat_completion(cfg['llm'],prompt['messages']); total_in+=llm['input_tokens']; total_out+=llm['output_tokens']
            response_path=out/'responses'/f'{tag}.json'; save_json(response_path,llm['raw'])
        except Exception as exc:
            feedback='API error: '+str(exc)
            append_attempt(out,failed_attempt_row(run_id,bug,group,attempt,shared_hash,rel(prompt_path),reason=feedback,runtime=time.time()-attempt_start,protocol_lock_id=cfg.get('protocol_lock_id','')),artifact_prefix); continue
        try: parsed=parse_revised_output(llm['content'],group)
        except Exception as exc:
            feedback='Return valid JSON containing one unified diff.'
            row=failed_attempt_row(run_id,bug,group,attempt,shared_hash,rel(prompt_path),rel(response_path),'response parse failed: '+str(exc),
                                   {'input':llm['input_tokens'],'output':llm['output_tokens']},time.time()-attempt_start,
                                   cfg.get('protocol_lock_id',''))
            row['base_prompt_sha256']=prompt['base_prompt_sha256']; row['treatment_appendix_sha256']=prompt['treatment_appendix_sha256']
            row['prompt_sha256']=prompt['prompt_sha256']; row['estimated_cost']=cost(cfg,llm['input_tokens'],llm['output_tokens'])
            append_attempt(out,row,artifact_prefix); continue
        patch_path=out/'patches'/f'{tag}.diff'
        apply_info=apply_patch(cfg,wd,parsed['patch'],patch_path,list(project_paths.values()),out/'logs'/f'{tag}_patch_apply.log')
        added,deleted=patch_size(parsed['patch']); compile_ok=trigger_ok=full_ok=False; compile_text=trigger_text=full_text=''
        if apply_info['status']=='applied':
            code,compile_text=run_cmd([cfg['defects4j_bin'],'compile'],wd,out/'logs'/f'{tag}_compile.log',int(cfg['timeouts']['compile'])); compile_ok=code==0
            if compile_ok:
                trigger_ok=True; outputs=[]
                for index,test in enumerate(item['trigger_tests'],1):
                    code,result=run_cmd([cfg['defects4j_bin'],'test','-t',test],wd,out/'logs'/f'{tag}_trigger_{index}.log',int(cfg['timeouts']['trigger_test']))
                    outputs.append(result); trigger_ok=trigger_ok and test_status(code,result)
                trigger_text='\n'.join(outputs)
                code,full_text=run_cmd([cfg['defects4j_bin'],'test'],wd,out/'logs'/f'{tag}_all_tests.log',int(cfg['timeouts']['all_tests'])); full_ok=test_status(code,full_text)
        before_files={source:out/'shared_contexts'/bug/'source_snapshots'/source for source in allowed}
        ast=run_javaparser_files(cfg,before_files,absolute,out/'api_diff',out/'logs',tag)
        delta={'target_warning_removed':False,'new_same_warning_count':None,'targets':[],'all_targets_present_before':False}
        if compile_ok:
            after_report=out/'spotbugs_reports'/f'{tag}_patched.xml'
            ok,_=run_spotbugs(cfg,wd,after_report,out/'logs'/f'{tag}_spotbugs_after.log','patched')
            if ok:
                evidence=[{'pattern':x['pattern'],'location':{'file':x['file'],'method':x['method']}} for x in contract['evidence_anchor']]
                delta=warning_delta(parse_alerts(out/'spotbugs_reports'/f'{bug}_shared_buggy.xml'),parse_alerts(after_report),evidence)
        claimed=parsed.get('claimed_mapping',[]) if group=='C' else []
        claimed_ok,claimed_problems=validate_claimed_mapping(contract,claimed) if group=='C' else (True,[])
        evidence_path=out/'evidence_reports'/f'{tag}.json'
        evidence=build_attempt_evidence(group,contract,claimed,claimed_ok,claimed_problems,apply_info,compile_ok,trigger_ok,full_ok,delta,ast,evidence_path)
        compliance=evidence['obligation_compliance']; mapping=evidence['mapping']; decisions=evidence['verifier_decisions']
        attempt_runtime=time.time()-attempt_start
        row={
            'run_id':run_id,'protocol_lock_id':cfg.get('protocol_lock_id',''),'bug_key':bug,'experiment_group':group,'attempt':attempt,'candidate_status':'evaluated',
            'shared_context_sha256':shared_hash,'base_prompt_sha256':prompt['base_prompt_sha256'],
            'treatment_appendix_sha256':prompt['treatment_appendix_sha256'],'prompt_sha256':prompt['prompt_sha256'],
            'input_tokens':llm['input_tokens'],
            'output_tokens':llm['output_tokens'],'estimated_cost':cost(cfg,llm['input_tokens'],llm['output_tokens']),
            'runtime_seconds':round(attempt_runtime,3),'patch_apply':str(apply_info['status']=='applied').lower(),
            'compile':str(compile_ok).lower(),'trigger_test':str(trigger_ok).lower(),'full_test':str(full_ok).lower(),
            'plausible':str(decisions['would_accept_test_only']).lower(),'tests_unchanged':str(evidence['blocking_checks']['TESTS_UNCHANGED']).lower(),
            'target_warning_removed':str(bool(delta.get('target_warning_removed'))).lower(),
            'new_same_warning_count':delta.get('new_same_warning_count'),'public_api_unchanged':str(evidence['public_api_unchanged']).lower(),
            'hard_scope_pass':str(evidence['hard_repair_scope']['pass']).lower(),**compliance,
            'claimed_mapping_valid':str(mapping['claimed_mapping_valid']).lower() if group=='C' else 'not_applicable',
            'realized_mapping_success':str(mapping['realized_mapping_success']).lower() if group=='C' else 'not_applicable',
            'mapping_consistent':str(mapping['mapping_consistent']).lower() if group=='C' else 'not_applicable',
            'mapping_exact':str(mapping['mapping_exact']).lower() if group=='C' else 'not_applicable',
            'mapping_precision':mapping['mapping_precision'] if group=='C' else 'not_applicable',
            'mapping_coverage':mapping['mapping_coverage'] if group=='C' else 'not_applicable',
            **{key:str(value).lower() for key,value in decisions.items()},
            'evidence_relevance':'post_run_merge_pending','manual_correct':'pending','plausible_but_incorrect':'pending',
            'test_only_false_accept':'pending','generic_false_accept':'pending','hybrid_false_accept':'pending',
            'test_only_false_reject':'pending','generic_false_reject':'pending','hybrid_false_reject':'pending',
            'hybrid_only_interception':'pending','harmful_extra_rejection':'pending',
            'prompt_path':rel(prompt_path),'response_path':rel(response_path),'patch_path':rel(patch_path),
            'contract_path':rel(out/'contracts'/f'{bug}.json'),'evidence_path':rel(evidence_path),'failure_reason':'',
            '_added':added,'_deleted':deleted,
        }
        append_attempt(out,row,artifact_prefix); save_json(out/'attempt_reports'/f'{tag}.json',row)
        score=(int(decisions['would_accept_test_only']),int(trigger_ok),int(compile_ok),int(apply_info['status']=='applied'),-attempt)
        if best is None or score>best[0]: best=(score,row)
        feedback=generic_feedback(apply_info,compile_ok,trigger_ok,full_ok,compile_text,trigger_text,full_text)
        if group=='C':
            advisory_failed=[x['obligation_id'] for x in evidence['advisory_obligations'] if not x['pass']]
            extra=[]
            if advisory_failed: extra.append('Advisory contract checks not satisfied: '+', '.join(advisory_failed))
            if claimed_problems: extra.append('Claimed mapping problems: '+', '.join(claimed_problems))
            feedback='\n'.join(x for x in (feedback,*extra) if x)
        if decisions['would_accept_test_only']: break
    elapsed=time.time()-group_start
    if best:
        selected=best[1]
        result={field:'' for field in BUG_RESULT_FIELDS}
        for key in BUG_RESULT_FIELDS:
            if key in selected and key not in {'run_id','input_tokens','output_tokens','estimated_cost','runtime_seconds'}:
                result[key]=selected[key]
        result.update({
            'run_id':run_id,'protocol_lock_id':cfg.get('protocol_lock_id',''),'project_id':item['project_id'],'bug_id':item['bug_id'],'bug_key':bug,'experiment_group':group,
            'best_attempt':selected['attempt'],'attempts_used':attempts_used,'input_tokens':total_in,'output_tokens':total_out,
            'estimated_cost':cost(cfg,total_in,total_out),'runtime_seconds':round(elapsed,3),'final_correctness':'pending_human',
            'best_patch_path':selected['patch_path'],'best_evidence_path':selected['evidence_path'],
            'status':'completed','failure_reason':selected.get('failure_reason',''),
        })
    else:
        result={field:'' for field in BUG_RESULT_FIELDS}; result.update({
            'run_id':run_id,'protocol_lock_id':cfg.get('protocol_lock_id',''),'project_id':item['project_id'],'bug_id':item['bug_id'],'bug_key':bug,'experiment_group':group,
            'best_attempt':'','attempts_used':attempts_used,'input_tokens':total_in,'output_tokens':total_out,
            'estimated_cost':cost(cfg,total_in,total_out),'runtime_seconds':round(elapsed,3),'status':'framework_failed',
            'final_correctness':'pending_human','failure_reason':'no evaluated candidate',
        })
    upsert_csv(out/f'{artifact_prefix}_bug_results.csv',result,BUG_RESULT_FIELDS,['bug_key','experiment_group'])
    update_manifest(out,bug,group,artifact_prefix,status='completed' if best else 'failed',finished_at=now())

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--config',default='config/stage2_v2_1_config.json'); ap.add_argument('--run-id',required=True)
    ap.add_argument('--resume',action='store_true'); ap.add_argument('--group',action='append',choices=list(GROUPS)); ap.add_argument('--bug',action='append')
    args=ap.parse_args(); cfg=load_json(ROOT/args.config); apply_java_home(cfg)
    if cfg.get('full_mve_enabled'): raise SystemExit('Revised Pre-flight runner refuses full_mve_enabled=true')
    out=initialize_run(ROOT,cfg,args.run_id,args.resume); data=load_runtime_dataset(ROOT); registry=load_registry(ROOT)
    bugs=args.bug or list(cfg['revised_preflight_bug_keys']); groups=args.group or list(GROUPS)
    if set(bugs)-set(cfg['revised_preflight_bug_keys']): raise SystemExit('Only frozen Revised Pre-flight bugs are allowed')
    contexts={}; hashes={}
    for bug in bugs:
        item=data[bug]; contract=build_contract_v2_1(item,registry)
        validate_contract_v2_1(contract,ROOT/'schemas/executable_evidence_contract_v2_1.schema.json')
        contract_audit=audit_structured_payload(contract,'contract'); save_json(out/'contracts'/f'{bug}_leakage_audit.json',contract_audit)
        if not contract_audit['pass']: raise SystemExit(f'{bug}: contract leakage')
        save_json(out/'contracts'/f'{bug}.json',contract)
        shared,digest=build_shared_context(ROOT,cfg,item,contract,out,args.run_id); contexts[bug]=shared; hashes[bug]=digest
        for group in GROUPS:
            update_manifest(out,bug,group,shared_context_path=rel(out/'shared_contexts'/bug/'shared_context.json'),shared_context_sha256=digest)
    write_csv(out/'shared_context_hash_audit.csv',[
        {'run_id':args.run_id,'bug_key':bug,'group_a_hash':hashes[bug],'group_r_hash':hashes[bug],'group_c_hash':hashes[bug],
         'all_equal':'true','shared_context_path':rel(out/'shared_contexts'/bug/'shared_context.json')} for bug in bugs
    ],HASH_AUDIT_FIELDS)
    for bug in bugs:
        contract=load_json(out/'contracts'/f'{bug}.json')
        for group in groups: run_group(cfg,data[bug],group,contract,contexts[bug],hashes[bug],out,args.run_id,args.resume)
    print(f'Completed Revised Pre-flight run_id={args.run_id}, bugs={bugs}, groups={groups}')

if __name__=='__main__': raise SystemExit(main())
