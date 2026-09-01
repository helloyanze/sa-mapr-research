from __future__ import annotations

import json
import re
from pathlib import Path

from common import run_cmd, save_json


def run_javaparser(cfg, before_file: Path, after_file: Path, out_json: Path, log: Path):
    jar=Path(cfg['javaparser_checker_jar']).resolve()
    if not jar.exists(): return {'status':'tool_missing','unchanged':False,'changed_methods':[],'added':[],'removed':[]}
    code,_=run_cmd([cfg['java_bin'],'-jar',str(jar),'--before',str(before_file),'--after',str(after_file),'--out',str(out_json)],None,log,120)
    if not out_json.exists(): return {'status':'failed','unchanged':False,'changed_methods':[],'added':[],'removed':[],'returncode':code}
    result=json.loads(out_json.read_text(encoding='utf-8')); result['returncode']=code
    return result


def run_javaparser_files(cfg, before_files: dict[str,Path], after_files: dict[str,Path], out_dir: Path, log_dir: Path, tag: str):
    results={}
    for index, source_file in enumerate(sorted(before_files),1):
        before=before_files[source_file]; after=after_files.get(source_file)
        if after is None or not after.exists():
            results[source_file]={'status':'after_missing','unchanged':False,'changed_methods':[]}
            continue
        results[source_file]=run_javaparser(cfg,before,after,out_dir/f'{tag}_{index}.json',log_dir/f'{tag}_javaparser_{index}.log')
    return results


def validate_claimed_mapping(contract: dict, claimed):
    valid_ids={o['id'] for o in contract.get('repair_obligations',[])}
    if not isinstance(claimed,list) or not claimed: return False, ['missing claimed mapping']
    problems=[]; claimed_ids=set()
    for x in claimed:
        if not isinstance(x,dict): problems.append('mapping entry is not object'); continue
        oid=str(x.get('obligation_id','')); claimed_ids.add(oid)
        if oid not in valid_ids: problems.append('unknown obligation '+oid)
        if not str(x.get('patch_location','')).strip(): problems.append('missing patch_location for '+oid)
        if not str(x.get('justification','')).strip(): problems.append('missing justification for '+oid)
    if not valid_ids.issubset(claimed_ids): problems.append('not all repair obligations are claimed')
    return not problems, problems


def evaluate_scope(contract: dict, ast_results: dict, patch_scope_ok: bool):
    allowed_methods: dict[str,set[str]]={}
    for obligation in contract.get('repair_obligations',[]):
        target=obligation.get('target',{}); file=target.get('file'); method=target.get('method')
        if file and method: allowed_methods.setdefault(file,set()).add(method)
    warnings=[]; failures=[]
    if not patch_scope_ok: failures.append('patch changed a file outside Contract targets')
    for source_file,result in ast_results.items():
        if result.get('status')!='ok': failures.append(f'JavaParser failed for {source_file}'); continue
        if result.get('imports_changed'): warnings.append(f'{source_file}: imports changed')
        if result.get('fields_changed'): warnings.append(f'{source_file}: fields changed')
        private_added=set(result.get('added_private_methods',[]))
        for method in result.get('changed_methods',[]):
            if method.get('name') in allowed_methods.get(source_file,set()): continue
            if method.get('status')=='added' and method.get('key') in private_added:
                warnings.append(f"{source_file}: private helper added {method.get('key')}")
            else: failures.append(f"{source_file}: unrelated method changed {method.get('key')}")
    return {'valid':not failures,'warnings':warnings,'failures':failures}


def build_realized_mapping(contract: dict, ast_results: dict, api_unchanged: bool, scope_result: dict):
    rows=[]
    for obligation in contract.get('repair_obligations',[]):
        oid=obligation['id']; typ=obligation['type']; target=obligation.get('target',{})
        matched=False; matched_by=''; actual_nodes=[]; actual_method=''; reason=''
        if typ=='PUBLIC_API_UNCHANGED':
            matched=api_unchanged; matched_by='API_DIFF'; reason='public/protected API unchanged' if matched else 'API changed'
        elif typ=='SCOPE_LIMITATION':
            matched=bool(scope_result['valid']); matched_by='DIFF_AST_SCOPE'; reason='scope valid' if matched else '; '.join(scope_result['failures'])
        else:
            result=ast_results.get(target.get('file',''),{})
            candidates=[m for m in result.get('changed_methods',[]) if m.get('name')==target.get('method')]
            if candidates:
                method=candidates[0]; actual_method=method.get('key',''); actual_nodes=method.get('ast_nodes',[])
                expected=set(obligation.get('expected_ast_nodes',[])); node_match=not expected or bool(expected & set(actual_nodes))
                regex=obligation.get('source_regex',''); source_match=not regex or bool(re.search(regex,method.get('after_source',''),re.I|re.S))
                matched=node_match and source_match; matched_by='AST_PATTERN'
                if not node_match: reason='expected AST node not found'
                elif not source_match: reason='required source pattern not found'
                else: reason='target method changed with required AST/source pattern'
            else: reason='target method was not mechanically observed as changed'
        rows.append({
            'obligation_id':oid,'obligation_type':typ,'matched':matched,'matched_by':matched_by,
            'actual_file':target.get('file',''),'actual_method':actual_method,
            'changed_ast_nodes':actual_nodes,'reason':reason,
        })
    return rows


def compare_mappings(contract: dict, claimed: list, realized: list):
    claimed_by={str(x.get('obligation_id','')):x for x in claimed if isinstance(x,dict)}
    results=[]
    for row in realized:
        oid=row['obligation_id']; claim=claimed_by.get(oid); obligation=next(x for x in contract['repair_obligations'] if x['id']==oid); target=obligation.get('target',{})
        location=str(claim.get('patch_location','')) if claim else ''
        location_ok=bool(claim) and (target.get('file','') in location or target.get('method','') in location)
        results.append({'obligation_id':oid,'claimed':bool(claim),'realized':row['matched'],'location_consistent':location_ok})
    return {'entries':results,'consistent':bool(results) and all(x['claimed'] and x['realized'] and x['location_consistent'] for x in results)}


def build_evidence_report(group, contract, claimed, claimed_ok, claimed_problems, apply_info, compile_ok, trigger_ok, all_ok,
                          spotbugs_delta, ast_results, out_path: Path):
    api_unchanged=bool(ast_results) and all(x.get('status')=='ok' and x.get('unchanged',False) for x in ast_results.values())
    scope=evaluate_scope(contract,ast_results,apply_info['scope_ok'])
    realized=build_realized_mapping(contract,ast_results,api_unchanged,scope) if group=='B' else []
    mapping_compare=compare_mappings(contract,claimed,realized) if group=='B' else None
    realized_success=bool(realized) and all(x['matched'] for x in realized) if group=='B' else None
    checks={
        'PATCH_APPLY':apply_info['status']=='applied','COMPILE_SUCCESS':compile_ok,
        'FAILING_TEST_PASS':trigger_ok,'ALL_TEST_PASS':all_ok,
        'TARGET_WARNING_REMOVED':bool(spotbugs_delta.get('target_warning_removed')),
        'NO_NEW_SAME_WARNING':spotbugs_delta.get('new_same_warning_count')==0,
        'PUBLIC_API_UNCHANGED':api_unchanged,'SCOPE_LIMITATION':scope['valid'],
    }
    if group=='B':
        checks['CLAIMED_MAPPING_VALID']=claimed_ok
        checks['REALIZED_MAPPING_SUCCESS']=realized_success
    blocking_failures=[k for k,v in checks.items() if not v]
    report={
        'group':group,'contract_id':contract.get('contract_id'),'claimed_mapping_valid':claimed_ok if group=='B' else None,
        'claimed_mapping_problems':claimed_problems if group=='B' else [],'changed_files':apply_info['files'],
        'checks':checks,'spotbugs_delta':spotbugs_delta,'api_unchanged':api_unchanged,'scope':scope,
        'realized_obligation_mapping':realized,'mapping_comparison':mapping_compare,
        'blocking_failures':blocking_failures,'realized_mapping_success':realized_success,
        'verifier_decision':'accept' if not blocking_failures else 'reject',
    }
    save_json(out_path,report); return report
