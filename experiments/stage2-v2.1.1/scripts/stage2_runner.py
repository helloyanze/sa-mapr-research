from __future__ import annotations

import argparse, hashlib, os, shutil, sys, time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))

from common import *
from contract_builder import allowed_source_files, build_contract, load_registry, validate_contract
from llm_client import chat_completion
from manifest_loader import load_runtime_dataset
from patching import apply_patch, patch_size
from prompting import audit_prompt_text, live_code_contexts, load_template, parse_model_output, render_user_prompt
from spotbugs_utils import parse_alerts, run_spotbugs, warning_delta
from verifier import build_evidence_report, run_javaparser_files, validate_claimed_mapping

ROOT=Path(__file__).resolve().parents[1]


def update_manifest(out, cfg, item, group, phase, status, started='', finished=''):
    rows=read_csv(out/'stage2_run_manifest.csv'); key=(item['bug_key'],group)
    for r in rows:
        if (r['bug_key'],r['experiment_group'])==key:
            finished_value='' if status=='running' else (finished or r.get('finished_at',''))
            r.update({'phase':phase,'model':cfg['llm']['model'],'model_version':cfg['llm']['model_version'],
                'temperature':cfg['llm']['temperature'],'top_p':cfg['llm']['top_p'],'max_output_tokens':cfg['llm']['max_output_tokens'],
                'maximum_attempts':cfg['llm']['maximum_attempts'],'token_budget':cfg['llm']['total_token_budget_per_bug_group'],
                'timeout_compile':cfg['timeouts']['compile'],'timeout_trigger_test':cfg['timeouts']['trigger_test'],
                'timeout_all_tests':cfg['timeouts']['all_tests'],'timeout_spotbugs':cfg['timeouts']['spotbugs'],
                'patch_quantity_limit':cfg['patch_quantity_limit_per_attempt'],'status':status,
                'started_at':started or r.get('started_at',''),'finished_at':finished_value})
    write_csv(out/'stage2_run_manifest.csv',rows,RUN_MANIFEST_FIELDS)


def checkout(cfg,item,wd,log):
    if wd.exists(): safe_rmtree(wd)
    wd.parent.mkdir(parents=True,exist_ok=True)
    return run_cmd([cfg['defects4j_bin'],'checkout','-p',item['project_id'],'-v',f"{item['bug_id']}b",'-w',str(wd)],ROOT,log,int(cfg['timeouts']['checkout']))


def project_files(cfg,wd,source_files,out,tag):
    src=defects4j_export(cfg['defects4j_bin'],wd,'dir.src.classes',out/f'stage2_logs/{tag}_export_src.log',120)
    if not src: raise RuntimeError('Cannot export dir.src.classes')
    project={f:(Path(src)/f).as_posix() for f in source_files}
    absolute={f:wd/src/f for f in source_files}
    return project,absolute


def test_status(code,text):
    n=parse_failing_count(text); return code==0 and n in (0,None)


def generic_feedback(apply_info,compile_ok,trigger_ok,all_ok,compile_text,trigger_text,all_text):
    if apply_info['status']!='applied': return 'The patch could not be applied: '+apply_info.get('output','')[-1500:]
    if not compile_ok: return 'The patch does not compile. Compiler output:\n'+compile_text[-3000:]
    if not trigger_ok: return 'The original trigger test still fails:\n'+trigger_text[-3000:]
    if not all_ok: return 'Regression tests still fail:\n'+all_text[-3000:]
    return ''


def finalize_run_metrics(row,cfg,attempts_used,total_in,total_out,elapsed):
    """Keep the best patch outcome while recording usage across every attempt."""
    row=dict(row)
    row.update({
        'attempts_used':attempts_used,
        'input_tokens':total_in,
        'output_tokens':total_out,
        'total_cost':total_in/1_000_000*float(cfg['llm']['input_price_per_million'])
                     +total_out/1_000_000*float(cfg['llm']['output_price_per_million']),
        'execution_time':round(elapsed,3),
    })
    return row


def failure(out,item,group,attempt,stage,code,message,log=''):
    append_failure(out/'stage2_failures.csv',{'project_id':item['project_id'],'bug_id':item['bug_id'],'bug_key':item['bug_key'],
        'experiment_group':group,'attempt':attempt,'stage':stage,'returncode':code,'message':str(message)[-2000:],'log_path':str(log)})


def run_one(cfg,item,group,phase,out,force=False):
    existing=read_csv(out/'stage2_bug_results.csv')
    if not force and any(r['bug_key']==item['bug_key'] and r['experiment_group']==group for r in existing):
        print('SKIP existing',item['bug_key'],group); return
    contract=build_contract(item,load_registry(ROOT)); validate_contract(contract,ROOT/'schemas/executable_evidence_contract.schema.json')
    source_files=allowed_source_files(contract); save_json(out/'runtime_contracts'/f"{item['bug_key']}.json",contract)
    started=now(); update_manifest(out,cfg,item,group,phase,'running',started=started)
    total_in=total_out=0; attempts_executed=0; start_clock=time.time(); best=None; feedback=''
    system=load_template(ROOT/('prompts/samapr_system.md' if group=='B' else 'prompts/baseline_system.md'))
    for attempt in range(1,int(cfg['llm']['maximum_attempts'])+1):
        attempts_executed=attempt
        tag=f"{item['bug_key']}_{group}_attempt{attempt}"; wd=(ROOT/cfg['work_root']).resolve()/item['bug_key']/group/f'attempt_{attempt}'; logdir=out/'stage2_logs'
        code,text=checkout(cfg,item,wd,logdir/f'{tag}_checkout.log')
        if code!=0: failure(out,item,group,attempt,'checkout',code,text,logdir/f'{tag}_checkout.log'); break
        try: project,absolute=project_files(cfg,wd,source_files,out,tag)
        except Exception as exc: failure(out,item,group,attempt,'source_path',125,exc); break
        missing=[str(p) for p in absolute.values() if not p.exists()]
        if missing: failure(out,item,group,attempt,'target_file',2,missing); break
        before_files={}
        for index,(source,path) in enumerate(absolute.items(),1):
            snap=out/'api_diff'/f'{tag}_before_{index}.java'; snap.parent.mkdir(parents=True,exist_ok=True); shutil.copy2(path,snap); before_files[source]=snap
        code,buggy_compile=run_cmd([cfg['defects4j_bin'],'compile'],wd,logdir/f'{tag}_buggy_compile.log',int(cfg['timeouts']['compile']))
        if code!=0: failure(out,item,group,attempt,'buggy_compile',code,buggy_compile,logdir/f'{tag}_buggy_compile.log'); break
        before_report=out/'spotbugs_reports'/f'{tag}_before.xml'
        before_ok,_=run_spotbugs(cfg,wd,before_report,logdir/f'{tag}_spotbugs_before.log','buggy')
        if not before_ok: failure(out,item,group,attempt,'spotbugs_before',2,'buggy SpotBugs report missing',logdir/f'{tag}_spotbugs_before.log'); break
        contexts=live_code_contexts(item,absolute,int(cfg.get('context',{}).get('window_lines',120)))
        user=render_user_prompt(group,item,project[item['target_file']],contract if group=='B' else None,feedback,contexts)
        audit=audit_prompt_text(system+'\n'+user)
        prompt_record={'messages':[{'role':'system','content':system},{'role':'user','content':user}],
                       'sha256':hashlib.sha256((system+'\n'+user).encode()).hexdigest(),'leakage_audit':audit}
        prompt_path=out/'prompts'/f'{tag}.json'; save_json(prompt_path,prompt_record)
        if not audit['pass']: failure(out,item,group,attempt,'prompt_leakage',2,audit['findings'],prompt_path); break
        try:
            llm=chat_completion(cfg['llm'],prompt_record['messages']); total_in+=llm['input_tokens']; total_out+=llm['output_tokens']; save_json(out/'responses'/f'{tag}.json',llm['raw'])
        except Exception as exc: failure(out,item,group,attempt,'llm_api',125,exc); feedback='API error: '+str(exc); continue
        if total_in+total_out>int(cfg['llm']['total_token_budget_per_bug_group']): feedback='Token budget exhausted'; break
        try: parsed=parse_model_output(llm['content'],group)
        except Exception as exc: failure(out,item,group,attempt,'response_parse',2,exc,out/'responses'/f'{tag}.json'); feedback='Return valid JSON containing a unified diff.'; continue
        patch_path=out/'stage2_patch_inventory'/f'{tag}.diff'
        apply_info=apply_patch(cfg,wd,parsed['patch'],patch_path,list(project.values()),logdir/f'{tag}_patch_apply.log'); add,delete=patch_size(parsed['patch'])
        compile_ok=trigger_ok=all_ok=False; compile_text=trigger_text=all_text=''
        if apply_info['status']=='applied':
            code,compile_text=run_cmd([cfg['defects4j_bin'],'compile'],wd,logdir/f'{tag}_compile.log',int(cfg['timeouts']['compile'])); compile_ok=code==0
            if compile_ok:
                trigger_ok=True; outs=[]
                for index,trig in enumerate(item['trigger_tests'],1):
                    code,t=run_cmd([cfg['defects4j_bin'],'test','-t',trig],wd,logdir/f'{tag}_trigger_{index}.log',int(cfg['timeouts']['trigger_test'])); outs.append(t); trigger_ok=trigger_ok and test_status(code,t)
                trigger_text='\n'.join(outs); code,all_text=run_cmd([cfg['defects4j_bin'],'test'],wd,logdir/f'{tag}_all_tests.log',int(cfg['timeouts']['all_tests'])); all_ok=test_status(code,all_text)
        ast_results=run_javaparser_files(cfg,before_files,absolute,out/'api_diff',logdir,tag)
        delta={'target_warning_removed':False,'new_same_warning_count':None,'targets':[],'all_targets_present_before':False}
        spotbugs_ok=False
        if compile_ok:
            after_report=out/'spotbugs_reports'/f'{tag}_after.xml'; spotbugs_ok,_=run_spotbugs(cfg,wd,after_report,logdir/f'{tag}_spotbugs_after.log','patched')
            if spotbugs_ok: delta=warning_delta(parse_alerts(before_report),parse_alerts(after_report),contract['static_evidence'])
        claimed=parsed.get('claimed_mapping',[]); claimed_ok,claimed_problems=validate_claimed_mapping(contract,claimed) if group=='B' else (True,[])
        evidence=build_evidence_report(group,contract,claimed,claimed_ok,claimed_problems,apply_info,compile_ok,trigger_ok,all_ok,delta,ast_results,out/'evidence_reports'/f'{tag}.json')
        plausible=compile_ok and trigger_ok and all_ok; score=(int(apply_info['status']=='applied'),int(compile_ok),int(trigger_ok),int(all_ok),int(evidence['verifier_decision']=='accept'))
        row={'project_id':item['project_id'],'bug_id':item['bug_id'],'bug_key':item['bug_key'],'experiment_group':group,'final_human_label':'',
            'spotbugs_pattern':'|'.join(dict.fromkeys(w['spotbugs_pattern'] for w in item['buggy_spotbugs_warnings'])),'model':cfg['llm']['model'],'model_version':cfg['llm']['model_version'],
            'temperature':cfg['llm']['temperature'],'maximum_attempts':cfg['llm']['maximum_attempts'],'attempts_used':attempt,'input_tokens':total_in,'output_tokens':total_out,
            'total_cost':total_in/1_000_000*float(cfg['llm']['input_price_per_million'])+total_out/1_000_000*float(cfg['llm']['output_price_per_million']),
            'execution_time':round(time.time()-start_clock,3),'patch_apply_status':apply_info['status'],'compile_status':'pass' if compile_ok else 'fail',
            'trigger_test_status':'pass' if trigger_ok else 'fail','all_test_status':'pass' if all_ok else 'fail',
            'target_warning_removed':str(delta.get('target_warning_removed',False)).lower() if spotbugs_ok else 'tool_failed',
            'new_same_warning_count':delta.get('new_same_warning_count') if spotbugs_ok else 'tool_failed','public_api_unchanged':str(bool(evidence['api_unchanged'])).lower(),
            'scope_result':'pass' if evidence['scope']['valid'] else 'fail','patch_size_added':add,'patch_size_deleted':delete,
            'claimed_mapping_validity':('pass' if claimed_ok else 'fail') if group=='B' else 'not_applicable',
            'realized_mapping_success':str(bool(evidence['realized_mapping_success'])).lower() if group=='B' else 'not_applicable',
            'verifier_decision':evidence['verifier_decision'],'interception_reason':'|'.join(evidence['blocking_failures']),
            'plausible_status':str(plausible).lower(),'result_label':'Plausible' if plausible else ('Compile-failed' if not compile_ok else 'Test-failed'),
            'final_correctness':'pending_human','failure_reason':'|'.join(evidence['blocking_failures']),'patch_path':str(patch_path.relative_to(ROOT)),'log_path':str(logdir.relative_to(ROOT))}
        if best is None or score>best[0]: best=(score,row)
        if (group=='A' and plausible) or (group=='B' and evidence['verifier_decision']=='accept'): break
        generic=generic_feedback(apply_info,compile_ok,trigger_ok,all_ok,compile_text,trigger_text,all_text)
        feedback=(generic+'\nContract verification failures: '+', '.join(evidence['blocking_failures'])+'\nClaimed mapping problems: '+', '.join(claimed_problems)).strip() if group=='B' else generic
    if best is None:
        row={k:'' for k in RESULT_FIELDS}; row.update({'project_id':item['project_id'],'bug_id':item['bug_id'],'bug_key':item['bug_key'],'experiment_group':group,'model':cfg['llm']['model'],'model_version':cfg['llm']['model_version'],'temperature':cfg['llm']['temperature'],'maximum_attempts':cfg['llm']['maximum_attempts'],'attempts_used':0,'input_tokens':total_in,'output_tokens':total_out,'total_cost':0,'execution_time':round(time.time()-start_clock,3),'patch_apply_status':'not_generated','compile_status':'not_run','trigger_test_status':'not_run','all_test_status':'not_run','target_warning_removed':'not_run','new_same_warning_count':'not_run','public_api_unchanged':'not_run','scope_result':'not_run','claimed_mapping_validity':'not_run' if group=='B' else 'not_applicable','realized_mapping_success':'not_run' if group=='B' else 'not_applicable','verifier_decision':'reject','plausible_status':'false','result_label':'Framework-failed','final_correctness':'pending_human','failure_reason':'no usable patch','log_path':str((out/'stage2_logs').relative_to(ROOT))}); best=((),row)
    final_row=finalize_run_metrics(best[1],cfg,attempts_executed,total_in,total_out,time.time()-start_clock)
    upsert_csv(out/'stage2_bug_results.csv',final_row,RESULT_FIELDS,['bug_key','experiment_group']); update_manifest(out,cfg,item,group,phase,'completed',finished=now())


def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--config',default='config/stage2_config.json'); ap.add_argument('--phase',choices=['preflight','full','all'],required=True); ap.add_argument('--groups',nargs='+',choices=['A','B'],default=['A','B']); ap.add_argument('--bug',action='append'); ap.add_argument('--force',action='store_true')
    args=ap.parse_args(); cfg=load_json(ROOT/args.config); apply_java_home(cfg); out=(ROOT/cfg['output_root']).resolve(); out.mkdir(parents=True,exist_ok=True)
    if not (out/'stage2_run_manifest.csv').exists(): import initialize_outputs  # noqa
    if args.phase in ('full','all'):
        gate=load_json(out/'preflight_gate.json') if (out/'preflight_gate.json').exists() else {'pass':False}
        if not gate.get('pass'): raise SystemExit('Full phase blocked: outputs/preflight_gate.json does not pass')
    safe=load_runtime_dataset(ROOT); requested=set(args.bug or []); unknown=requested-set(safe)
    if unknown: raise SystemExit('Unknown --bug: '+', '.join(sorted(unknown)))
    selected=[]
    for item in safe.values():
        is_pre=item['bug_key'] in cfg['preflight_bug_keys']
        if args.phase=='preflight' and not is_pre: continue
        if args.phase=='full' and is_pre: continue
        if requested and item['bug_key'] not in requested: continue
        selected.append(item)
    selected.sort(key=lambda x:int(x['sequence_id']))
    for item in selected:
        for group in args.groups: run_one(cfg,item,group,args.phase,out,args.force)
    print(f'Completed phase={args.phase}, bugs={len(selected)}, groups={args.groups}')
if __name__=='__main__': main()
