from __future__ import annotations

import json
from pathlib import Path

from common import safe_rel_path

BLOCKING_TYPES=(
    ('PATCH_APPLIES','UnifiedDiffApplyChecker'),
    ('COMPILE_SUCCESS','Defects4JCompiler'),
    ('TRIGGER_TEST_PASS','Defects4JTestRunner'),
    ('ALL_TEST_PASS','Defects4JTestRunner'),
    ('TESTS_UNCHANGED','DiffFileScopeChecker'),
    ('PUBLIC_API_UNCHANGED','JavaParserApiDiff'),
    ('HARD_FILE_SCOPE','DiffFileScopeChecker'),
)

def load_registry(root: Path) -> dict:
    return json.loads((root/'config/obligation_registry.json').read_text(encoding='utf-8'))

def raw_static_evidence(item: dict) -> list[dict]:
    rows=[]
    for warning in item.get('buggy_spotbugs_warnings',[]):
        rows.append({
            'pattern':str(warning.get('spotbugs_pattern','')),
            'category':str(warning.get('spotbugs_category','')),
            'message':str(warning.get('message','')),
            'priority':str(warning.get('priority','')),
            'rank':str(warning.get('rank','')),
            'file':safe_rel_path(warning['target_file']),
            'method':str(warning.get('target_method','')),
            'line':str(warning.get('start_line','')),
        })
    return rows

def allowed_source_files_from_item(item: dict) -> list[str]:
    files=[safe_rel_path(x['target_file']) for x in item.get('buggy_spotbugs_warnings',[])]
    primary=safe_rel_path(item['target_file'])
    if primary not in files: files.insert(0,primary)
    return list(dict.fromkeys(files))

def build_contract_v2_1(item: dict,registry: dict) -> dict:
    raw=raw_static_evidence(item); anchors=[]; obligations=[]; seen=set()
    for index,evidence in enumerate(raw,1):
        anchor_id=f'E{index}'
        anchors.append({'id':anchor_id,'source':'SpotBugs_buggy_version',**evidence})
        pattern=evidence['pattern']
        if pattern not in registry: raise ValueError(f"{item['bug_key']}: unregistered SpotBugs pattern {pattern}")
        signature=(pattern,evidence['file'],evidence['method'])
        if signature in seen: continue
        seen.add(signature); spec=registry[pattern]
        obligations.append({
            'id':f'O{len(obligations)+1}','type':spec['type'],'severity':'advisory',
            'enforcement':'record_and_feedback','checker':'SpotBugsDeltaChecker','evidence_anchor_id':anchor_id,
            'description':f"Record whether buggy-version {pattern} evidence is resolved; this does not override functional tests.",
        })
    verification=[
        {'id':f'B{index}','type':typ,'severity':'blocking','enforcement':'reject','checker':checker}
        for index,(typ,checker) in enumerate(BLOCKING_TYPES,1)
    ]
    verification.append({'id':'M1','type':'PATCH_SIZE','severity':'metric_only','enforcement':'record_only','checker':'UnifiedDiffMetric'})
    return {
        'schema_version':'2.1','contract_id':f"C-{item['bug_key']}-v2.1-001",'bug_key':item['bug_key'],
        'evidence_anchor':anchors,
        'hard_repair_scope':{
            'allowed_source_files':allowed_source_files_from_item(item),'file_level':True,'tests_unchanged':True,
            'build_files_unchanged':True,'new_files_forbidden':True,'public_api_unchanged':True,
        },
        'repair_obligations':obligations,'verification_obligations':verification,
        'neutral_guidance':'Static evidence provides diagnostic constraints and clues. Warning location is not a mandatory edit location, and warning removal alone does not establish functional correctness.',
    }

def validate_contract_v2_1(contract: dict,schema_path: Path):
    try: import jsonschema
    except ImportError as exc: raise RuntimeError('Python dependency jsonschema is required') from exc
    jsonschema.validate(contract,json.loads(schema_path.read_text(encoding='utf-8')))

def allowed_source_files(contract: dict) -> list[str]:
    return [safe_rel_path(x) for x in contract['hard_repair_scope']['allowed_source_files']]
