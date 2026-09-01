from __future__ import annotations

import hashlib, json, re
from pathlib import Path

from common import now, save_json, write_csv

GROUPS=('A','R','C')
PREFLIGHT_BUGS=('Chart-1','Codec-1','Chart-22')

MANIFEST_FIELDS=[
    'run_id','sequence_id','project_id','bug_id','bug_key','experiment_group','phase','protocol_version','protocol_lock_id',
    'shared_context_path','shared_context_sha256','model','model_version','temperature','top_p','max_output_tokens',
    'maximum_attempts','token_budget','timeout_compile','timeout_trigger_test','timeout_all_tests','timeout_spotbugs',
    'patch_quantity_limit','status','started_at','finished_at'
]

ATTEMPT_FIELDS=[
    'run_id','protocol_lock_id','bug_key','experiment_group','attempt','candidate_status','shared_context_sha256','base_prompt_sha256',
    'treatment_appendix_sha256','prompt_sha256',
    'input_tokens','output_tokens','estimated_cost','runtime_seconds','patch_apply','compile','trigger_test','full_test',
    'plausible','tests_unchanged','target_warning_removed','new_same_warning_count','public_api_unchanged','hard_scope_pass',
    'blocking_obligations_total','blocking_obligations_pass','advisory_obligations_total','advisory_obligations_pass',
    'obligation_satisfaction_rate','claimed_mapping_valid','realized_mapping_success','mapping_consistent','mapping_exact',
    'mapping_precision','mapping_coverage','would_accept_test_only','would_accept_generic','would_accept_hybrid',
    'evidence_relevance','manual_correct','plausible_but_incorrect','test_only_false_accept','generic_false_accept',
    'hybrid_false_accept','test_only_false_reject','generic_false_reject','hybrid_false_reject','hybrid_only_interception',
    'harmful_extra_rejection','prompt_path','response_path','patch_path','contract_path','evidence_path','failure_reason'
]

BUG_RESULT_FIELDS=[
    'run_id','protocol_lock_id','project_id','bug_id','bug_key','experiment_group','best_attempt','attempts_used','input_tokens','output_tokens',
    'estimated_cost','runtime_seconds','patch_apply','compile','trigger_test','full_test','plausible','target_warning_removed',
    'public_api_unchanged','hard_scope_pass','blocking_obligations_total','blocking_obligations_pass',
    'advisory_obligations_total','advisory_obligations_pass','obligation_satisfaction_rate','claimed_mapping_valid',
    'realized_mapping_success','mapping_consistent','mapping_exact','mapping_precision','mapping_coverage',
    'would_accept_test_only','would_accept_generic','would_accept_hybrid','final_correctness','best_patch_path',
    'best_evidence_path','status','failure_reason'
]

HASH_AUDIT_FIELDS=['run_id','bug_key','group_a_hash','group_r_hash','group_c_hash','all_equal','shared_context_path']

def canonical_json(data) -> str:
    return json.dumps(data,ensure_ascii=False,sort_keys=True,separators=(',',':'))

def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode('utf-8')).hexdigest()

def validate_run_id(run_id: str) -> str:
    if not re.fullmatch(r'[A-Za-z0-9_.-]+',run_id or ''):
        raise ValueError('run_id may contain only letters, digits, dot, underscore, and hyphen')
    return run_id

def revised_root(project_root: Path,cfg: dict,run_id: str) -> Path:
    return (project_root/cfg['revised_output_root']/validate_run_id(run_id)).resolve()

def initialize_run(project_root: Path,cfg: dict,run_id: str,resume: bool=False) -> Path:
    out=revised_root(project_root,cfg,run_id)
    if out.exists() and not resume:
        raise FileExistsError(f'immutable run directory already exists: {out}')
    out.mkdir(parents=True,exist_ok=True)
    for name in ('shared_contexts','prompts','responses','patches','contracts','evidence_reports','attempt_reports',
                 'api_diff','spotbugs_reports','logs'):
        (out/name).mkdir(parents=True,exist_ok=True)
    metadata_path=out/'run_metadata.json'
    if not metadata_path.exists():
        save_json(metadata_path,{
            'run_id':run_id,'protocol_version':'2.1','created_at':now(),'groups':list(GROUPS),
            'preflight_bug_keys':list(cfg['revised_preflight_bug_keys']),'canary_bug_key':cfg.get('canary_bug_key'),
            'full_mve_enabled':bool(cfg.get('full_mve_enabled',False)),'legacy_outputs_untouched':True,
        })
    config_snapshot=out/'stage2_v2_1_config.snapshot.json'
    if not config_snapshot.exists():
        save_json(config_snapshot,cfg)
    manifest=out/'revised_preflight_manifest.csv'
    if not manifest.exists():
        rows=[]; sequence=1
        from manifest_loader import load_runtime_dataset
        data=load_runtime_dataset(project_root)
        for bug_key in cfg['revised_preflight_bug_keys']:
            item=data[bug_key]
            for group in GROUPS:
                rows.append({
                    'run_id':run_id,'sequence_id':sequence,'project_id':item['project_id'],'bug_id':item['bug_id'],
                    'bug_key':bug_key,'experiment_group':group,'phase':'revised_preflight','protocol_version':'2.1',
                    'protocol_lock_id':cfg.get('protocol_lock_id',''),
                    'model':cfg['llm']['model'],'model_version':cfg['llm']['model_version'],
                    'temperature':cfg['llm']['temperature'],'top_p':cfg['llm']['top_p'],
                    'max_output_tokens':cfg['llm']['max_output_tokens'],'maximum_attempts':cfg['llm']['maximum_attempts'],
                    'token_budget':cfg['llm']['total_token_budget_per_bug_group'],'timeout_compile':cfg['timeouts']['compile'],
                    'timeout_trigger_test':cfg['timeouts']['trigger_test'],'timeout_all_tests':cfg['timeouts']['all_tests'],
                    'timeout_spotbugs':cfg['timeouts']['spotbugs'],'patch_quantity_limit':cfg['patch_quantity_limit_per_attempt'],
                    'status':'pending','started_at':'','finished_at':'','shared_context_path':'','shared_context_sha256':'',
                }); sequence+=1
        write_csv(manifest,rows,MANIFEST_FIELDS)
    for filename,fields in (
        ('revised_preflight_attempt_results.csv',ATTEMPT_FIELDS),
        ('revised_preflight_bug_results.csv',BUG_RESULT_FIELDS),
        ('shared_context_hash_audit.csv',HASH_AUDIT_FIELDS),
    ):
        path=out/filename
        if not path.exists(): write_csv(path,[],fields)
    return out
