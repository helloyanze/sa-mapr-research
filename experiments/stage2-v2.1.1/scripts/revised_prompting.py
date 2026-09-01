from __future__ import annotations

import json

from prompting import parse_model_output
from revised_common import canonical_json,sha256_text

GLOBAL_FORBIDDEN_PHRASES=(
    'developer patch','developer fixed source','fixed-version spotbugs','human confirmation',
    'this bug is direct','this bug is supporting','dual-ai audit reason','dual-ai confidence',
)
GLOBAL_FORBIDDEN_KEYS={
    'final_human_label','final_correctness','human_notes','human_rationale','developer_change_observed',
    'fixed_context','first_ai_label','second_ai_label','first_ai_reason','second_ai_rationale',
    'candidate_relevance_label','evidence_relevance','direct_supporting_label','dual_ai_audit_reason','dual_ai_confidence',
}

def _structured_forbidden(value,path=''):
    findings=[]
    if isinstance(value,dict):
        for key,item in value.items():
            if str(key).lower() in GLOBAL_FORBIDDEN_KEYS: findings.append(f'forbidden key {path}/{key}')
            findings.extend(_structured_forbidden(item,f'{path}/{key}'))
    elif isinstance(value,list):
        for index,item in enumerate(value): findings.extend(_structured_forbidden(item,f'{path}/{index}'))
    return findings

def audit_structured_payload(value,kind: str):
    findings=_structured_forbidden(value)
    text=canonical_json(value).lower()
    findings += [f'forbidden phrase in {kind}: {term}' for term in GLOBAL_FORBIDDEN_PHRASES if term in text]
    return {'pass':not findings,'forbidden_findings':len(findings),'findings':findings}

def render_shared_context(shared: dict) -> str:
    file_blocks=[]
    for source in shared['source_files']:
        file_blocks.append(f"FILE: {source['file']}\nSHA256: {source['sha256']}\nLINES: {source['line_count']}\n{source['content']}")
    return '\n\n'.join([
        f"Bug ID: {shared['bug_key']}",
        'Allowed production source files (file-level repair scope):\n'+'\n'.join('- '+x for x in shared['allowed_source_files']),
        'Failing / triggering tests:\n'+'\n'.join(shared['trigger_tests']),
        'Frozen buggy test failure summary:\n'+shared['failure_summary'],
        'Frozen buggy source context shared by A/R/C:\n'+'\n\n'.join(file_blocks),
    ])

def render_user_prompt(group: str,shared: dict,raw_evidence: list[dict]|None=None,contract: dict|None=None,feedback: str='') -> str:
    if group not in ('A','R','C'): raise ValueError('group must be A, R, or C')
    sections=[render_shared_context(shared)]
    if group in ('R','C'):
        sections += ['Raw buggy-version SpotBugs evidence (no repair hints):',json.dumps(raw_evidence or [],ensure_ascii=False,indent=2)]
    if group=='C':
        sections += ['Executable Evidence Contract v2.1:',json.dumps(contract,ensure_ascii=False,indent=2),
                     'Claim how each repair obligation maps to actual patch locations using claimed_mapping. Mapping consistency does not establish functional correctness.']
    if feedback: sections += ['Previous validation feedback:',feedback]
    sections += ['Return a minimal unified diff whose paths are relative to the checkout root.',
                 'You may edit any production method in the allowed source files.']
    if group in ('R','C'):
        sections += ['The static-evidence method is an evidence anchor, not a mandatory edit location.']
    return '\n\n'.join(sections)

def audit_generation_prompt(group: str,system: str,user: str) -> dict:
    text=(system+'\n'+user).lower(); findings=[]
    findings += [f'global forbidden phrase: {term}' for term in GLOBAL_FORBIDDEN_PHRASES if term in text]
    if group=='A':
        for term in ('spotbugs','raw buggy-version','evidence contract','repair obligation','claimed_mapping','warning line'):
            if term in text: findings.append(f'group A treatment leakage: {term}')
    if group=='R':
        for term in ('evidence contract','repair_obligations','claimed_mapping','contract-aware','severity'):
            if term in text: findings.append(f'group R contract leakage: {term}')
    return {'pass':not findings,'forbidden_findings':len(findings),'findings':findings}

def build_prompt_record(group: str,system: str,shared: dict,shared_hash: str,raw_evidence=None,contract=None,feedback=''):
    user=render_user_prompt(group,shared,raw_evidence,contract,feedback)
    audit=audit_generation_prompt(group,system,user)
    messages=[{'role':'system','content':system},{'role':'user','content':user}]
    base_user='\n\n'.join([
        render_shared_context(shared),
        'Return a minimal unified diff whose paths are relative to the checkout root.',
        'You may edit any production method in the allowed source files.',
    ])
    treatment_record={'group':group,'system':system,'raw_evidence':raw_evidence if group in ('R','C') else None,
                      'contract':contract if group=='C' else None,'feedback':feedback}
    return {'group':group,'shared_context_sha256':shared_hash,'messages':messages,
            'base_prompt_sha256':sha256_text(base_user),
            'treatment_appendix_sha256':sha256_text(canonical_json(treatment_record)),
            'prompt_sha256':sha256_text(canonical_json(messages)),'leakage_audit':audit}

def parse_revised_output(text: str,group: str):
    return parse_model_output(text,'B' if group=='C' else 'A')
