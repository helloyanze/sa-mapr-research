from __future__ import annotations

from common import save_json
from mapping_normalization import canonicalize_claimed_mappings, normalize_change_type, replay_mapping

def normalize_changed_files(allowed_files,changed_files):
    allowed={str(x).replace('\\','/').lstrip('./') for x in allowed_files}
    normalized=[]
    for raw in changed_files:
        path=str(raw).replace('\\','/').lstrip('./')
        matches=[source for source in allowed if path==source or path.endswith('/'+source)]
        normalized.append(matches[0] if len(matches)==1 else path)
    return normalized

def evaluate_file_scope(contract: dict,apply_info: dict,ast_results: dict):
    allowed=set(contract['hard_repair_scope']['allowed_source_files'])
    raw_changed=list(apply_info.get('files',[]))
    changed=set(normalize_changed_files(allowed,raw_changed)); failures=[]
    if not apply_info.get('scope_ok'): failures.append('patch file scope rejected before apply')
    if not changed: failures.append('patch changed no production source file')
    outside=sorted(changed-allowed)
    if outside: failures.append('files outside hard repair scope: '+', '.join(outside))
    for source,result in ast_results.items():
        if result.get('status')!='ok': failures.append(f'JavaParser failed for {source}')
    changed_methods={
        source:[m.get('key','') for m in result.get('changed_methods',[]) if m.get('status') in ('modified','added','removed')]
        for source,result in ast_results.items()
    }
    return {'pass':not failures,'allowed_source_files':sorted(allowed),'changed_files':sorted(changed),
            'changed_files_checkout_relative':raw_changed,
            'changed_methods':changed_methods,'failures':failures}

def validate_claimed_mapping(contract: dict,claimed):
    valid_ids=[x['id'] for x in contract.get('repair_obligations',[])]; problems=[]; seen=[]
    if not isinstance(claimed,list) or not claimed: return False,['missing claimed mapping']
    for entry in claimed:
        if not isinstance(entry,dict): problems.append('mapping entry is not object'); continue
        oid=str(entry.get('obligation_id','')); seen.append(oid)
        if oid not in valid_ids: problems.append('unknown obligation '+oid)
        has_location=(bool(str(entry.get('patch_location','')).strip())
                      or bool(str(entry.get('file','')).strip())
                      or isinstance(entry.get('target'),dict))
        if not has_location: problems.append('missing mapping target for '+oid)
        if not str(entry.get('justification','')).strip(): problems.append('missing justification for '+oid)
    if set(seen)!=set(valid_ids): problems.append('claimed obligation ids do not exactly match repair obligations')
    if len(seen)!=len(set(seen)): problems.append('duplicate obligation claim')
    for row in canonicalize_claimed_mappings(contract,claimed):
        if not row.get('valid'):
            problems.extend(f"{row.get('obligation_id') or '<missing>'}: {problem}" for problem in row.get('problems',[]))
    return not problems,problems

def advisory_compliance(contract: dict,spotbugs_delta: dict):
    anchors={x['id']:x for x in contract.get('evidence_anchor',[])}; targets=spotbugs_delta.get('targets',[]); rows=[]
    for obligation in contract.get('repair_obligations',[]):
        anchor=anchors.get(obligation.get('evidence_anchor_id'),{})
        matches=[x for x in targets if x.get('pattern')==anchor.get('pattern') and x.get('file')==anchor.get('file')
                 and (not anchor.get('method') or x.get('method')==anchor.get('method'))]
        passed=bool(matches) and all(x.get('removed') for x in matches)
        rows.append({'obligation_id':obligation['id'],'type':obligation['type'],'severity':obligation['severity'],
                     'checker':obligation['checker'],'pass':passed,'details':matches})
    return rows

def realized_mapping(contract: dict,ast_results: dict):
    anchors={x['id']:x for x in contract.get('evidence_anchor',[])}; rows=[]
    for obligation in contract.get('repair_obligations',[]):
        anchor=anchors.get(obligation.get('evidence_anchor_id'),{}); source=anchor.get('file',''); result=ast_results.get(source,{})
        locations=[]; targets=[]
        for method in result.get('changed_methods',[]):
            if method.get('status') in ('modified','added','removed'):
                signature=str(method.get('key') or method.get('name') or '')
                locations.append(source+'::'+signature)
                targets.append({'file':source,'method_signature':signature,'symbol':None,
                                'change_type':normalize_change_type(method.get('status'))})
        rows.append({'obligation_id':obligation['id'],'evidence_anchor_file':source,
                     'evidence_anchor_method':anchor.get('method',''),'actual_patch_locations':locations,
                     'actual_patch_targets':targets,
                     'realized':bool(locations)})
    return rows

def mapping_metrics(contract: dict,claimed: list,realized: list,claimed_valid: bool):
    replay=replay_mapping(contract,claimed,realized,claimed_valid)
    return {**replay['metrics'],'entries':replay['comparison']['entries'],
            'claimed_normalized':replay['claimed_normalized'],'realized_normalized':replay['realized_normalized']}

def build_attempt_evidence(group: str,contract: dict,claimed: list,claimed_valid: bool,claimed_problems: list,
                           apply_info: dict,compile_ok: bool,trigger_ok: bool,full_ok: bool,spotbugs_delta: dict,
                           ast_results: dict,out_path):
    api_unchanged=bool(ast_results) and all(x.get('status')=='ok' and x.get('unchanged',False) for x in ast_results.values())
    hard_scope=evaluate_file_scope(contract,apply_info,ast_results)
    normalized_changed=normalize_changed_files(contract['hard_repair_scope']['allowed_source_files'],apply_info.get('files',[]))
    tests_unchanged=(bool(apply_info.get('scope_ok')) and bool(normalized_changed)
                     and all(x in set(contract['hard_repair_scope']['allowed_source_files']) for x in normalized_changed))
    checks={
        'PATCH_APPLIES':apply_info.get('status')=='applied','COMPILE_SUCCESS':compile_ok,
        'TRIGGER_TEST_PASS':trigger_ok,'ALL_TEST_PASS':full_ok,'TESTS_UNCHANGED':tests_unchanged,
        'PUBLIC_API_UNCHANGED':api_unchanged,'HARD_FILE_SCOPE':hard_scope['pass'],
    }
    blocking_rows=[]
    for obligation in contract['verification_obligations']:
        if obligation['severity']=='blocking':
            blocking_rows.append({**obligation,'pass':bool(checks.get(obligation['type'],False))})
    advisory_rows=advisory_compliance(contract,spotbugs_delta)
    blocking_pass=sum(1 for x in blocking_rows if x['pass']); advisory_pass=sum(1 for x in advisory_rows if x['pass'])
    denominator=len(blocking_rows)+len(advisory_rows)
    satisfaction=(blocking_pass+advisory_pass)/denominator if denominator else 1.0
    target_removed=bool(spotbugs_delta.get('target_warning_removed')); no_new=spotbugs_delta.get('new_same_warning_count')==0
    v0=checks['PATCH_APPLIES'] and compile_ok and trigger_ok and full_ok
    v1=v0 and target_removed and no_new
    v2=v0 and api_unchanged and hard_scope['pass'] and blocking_pass==len(blocking_rows)
    if group=='C':
        realized=realized_mapping(contract,ast_results); mapping=mapping_metrics(contract,claimed,realized,claimed_valid)
    else:
        realized=[]; mapping={'entries':[],'claimed_mapping_valid':None,'realized_mapping_success':None,
                              'mapping_consistent':None,'mapping_exact':None,'mapping_precision':None,'mapping_coverage':None}
    report={
        'protocol_version':'2.1','group':group,'contract_id':contract['contract_id'],'changed_files':apply_info.get('files',[]),
        'functional_correctness':{'compile':compile_ok,'trigger_test':trigger_ok,'full_test':full_ok,'plausible':v0,
                                  'manual_correct':None,'plausible_but_incorrect':None},
        'blocking_checks':checks,'blocking_obligations':blocking_rows,'advisory_obligations':advisory_rows,
        'obligation_compliance':{'blocking_obligations_total':len(blocking_rows),'blocking_obligations_pass':blocking_pass,
                                 'advisory_obligations_total':len(advisory_rows),'advisory_obligations_pass':advisory_pass,
                                 'obligation_satisfaction_rate':round(satisfaction,6)},
        'spotbugs_delta':spotbugs_delta,'public_api_unchanged':api_unchanged,'hard_repair_scope':hard_scope,
        'claimed_mapping':claimed if group=='C' else [],'claimed_mapping_problems':claimed_problems if group=='C' else [],
        'realized_mapping':realized,'mapping':mapping,
        'verifier_decisions':{'would_accept_test_only':v0,'would_accept_generic':v1,'would_accept_hybrid':v2},
        'decision_note':'Mapping consistency and advisory compliance do not replace functional correctness.',
    }
    save_json(out_path,report); return report
