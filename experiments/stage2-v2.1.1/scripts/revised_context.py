from __future__ import annotations

import hashlib, shutil
from pathlib import Path

from common import defects4j_export, run_cmd, safe_rmtree, save_json
from revised_common import canonical_json,sha256_text
from revised_contract import allowed_source_files
from revised_prompting import audit_structured_payload
from spotbugs_utils import run_spotbugs

def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()

def checkout_buggy(root: Path,cfg: dict,item: dict,wd: Path,log: Path):
    if wd.exists(): safe_rmtree(wd)
    wd.parent.mkdir(parents=True,exist_ok=True)
    return run_cmd([cfg['defects4j_bin'],'checkout','-p',item['project_id'],'-v',f"{item['bug_id']}b",'-w',str(wd)],root,log,int(cfg['timeouts']['checkout']))

def resolve_source_files(root: Path,cfg: dict,wd: Path,allowed: list[str],log: Path):
    source_root=defects4j_export(cfg['defects4j_bin'],wd,'dir.src.classes',log,120)
    if not source_root: raise RuntimeError('Cannot export dir.src.classes')
    project_paths={source:(Path(source_root)/source).as_posix() for source in allowed}
    absolute={source:wd/source_root/source for source in allowed}
    missing=[source for source,path in absolute.items() if not path.exists()]
    if missing: raise FileNotFoundError('Missing allowed source files: '+', '.join(missing))
    return source_root,project_paths,absolute

def build_shared_context(root: Path,cfg: dict,item: dict,contract: dict,out: Path,run_id: str):
    bug=item['bug_key']; shared_dir=out/'shared_contexts'/bug; context_path=shared_dir/'shared_context.json'
    if context_path.exists():
        import json
        shared=json.loads(context_path.read_text(encoding='utf-8'))
        return shared,sha256_text(canonical_json(shared))
    shared_dir.mkdir(parents=True,exist_ok=True); allowed=allowed_source_files(contract)
    wd=(root/cfg['work_root']).resolve()/'_revised_shared'/run_id/bug
    code,text=checkout_buggy(root,cfg,item,wd,out/'logs'/f'{bug}_shared_checkout.log')
    if code!=0: raise RuntimeError('Shared checkout failed: '+text[-1000:])
    source_root,project_paths,absolute=resolve_source_files(root,cfg,wd,allowed,out/'logs'/f'{bug}_shared_export_src.log')
    code,compile_text=run_cmd([cfg['defects4j_bin'],'compile'],wd,out/'logs'/f'{bug}_shared_compile.log',int(cfg['timeouts']['compile']))
    if code!=0: raise RuntimeError('Shared buggy checkout compile failed: '+compile_text[-1000:])
    trigger_outputs=[]
    for index,test in enumerate(item['trigger_tests'],1):
        _,result=run_cmd([cfg['defects4j_bin'],'test','-t',test],wd,out/'logs'/f'{bug}_shared_trigger_{index}.log',int(cfg['timeouts']['trigger_test']))
        trigger_outputs.append(result)
    _,all_test_output=run_cmd([cfg['defects4j_bin'],'test'],wd,out/'logs'/f'{bug}_shared_all_tests.log',int(cfg['timeouts']['all_tests']))
    before_report=out/'spotbugs_reports'/f'{bug}_shared_buggy.xml'
    spotbugs_ok,_=run_spotbugs(cfg,wd,before_report,out/'logs'/f'{bug}_shared_spotbugs.log','shared_buggy')
    if not spotbugs_ok: raise RuntimeError(f'{bug}: shared buggy SpotBugs failed')
    snapshots=[]; snapshot_root=shared_dir/'source_snapshots'
    for source,path in absolute.items():
        snapshot=snapshot_root/source; snapshot.parent.mkdir(parents=True,exist_ok=True); shutil.copy2(path,snapshot)
        lines=path.read_text(encoding='utf-8',errors='replace').splitlines()
        snapshots.append({'file':source,'project_path':project_paths[source],'sha256':file_sha256(path),
                          'line_count':len(lines),'content':'\n'.join(f'{i}: {line}' for i,line in enumerate(lines,1))})
    shared={
        'schema_version':'2.1','run_id':run_id,'bug_key':bug,'project_id':item['project_id'],'bug_id':str(item['bug_id']),
        'buggy_version':f"{item['bug_id']}b",'trigger_tests':list(item['trigger_tests']),
        'failure_summary':all_test_output,'trigger_failure_outputs':trigger_outputs,
        'allowed_source_files':allowed,'source_root':source_root,'source_policy':'full_allowed_files',
        'source_context_truncated':False,'source_files':snapshots,
        'fairness_parameters':{
            'model':cfg['llm']['model'],'model_version':cfg['llm']['model_version'],'temperature':cfg['llm']['temperature'],
            'top_p':cfg['llm']['top_p'],'max_output_tokens':cfg['llm']['max_output_tokens'],
            'token_budget':cfg['llm']['total_token_budget_per_bug_group'],'maximum_attempts':cfg['llm']['maximum_attempts'],
            'timeouts':cfg['timeouts'],'patch_quantity_limit':cfg['patch_quantity_limit_per_attempt'],
        },
    }
    audit=audit_structured_payload(shared,'shared_context')
    save_json(shared_dir/'shared_context_leakage_audit.json',audit)
    if not audit['pass']: raise RuntimeError(f'{bug}: shared context leakage: {audit["findings"]}')
    save_json(context_path,shared)
    return shared,sha256_text(canonical_json(shared))

def verify_attempt_sources(shared: dict,absolute: dict[str,Path]):
    expected={x['file']:x['sha256'] for x in shared['source_files']}
    mismatches=[source for source,digest in expected.items() if source not in absolute or file_sha256(absolute[source])!=digest]
    if mismatches: raise RuntimeError('Attempt checkout does not match frozen shared source: '+', '.join(mismatches))
