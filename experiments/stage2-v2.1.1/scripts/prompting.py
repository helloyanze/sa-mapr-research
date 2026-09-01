from __future__ import annotations
import json, re
from pathlib import Path
from manifest_loader import code_contexts

FORBIDDEN_MARKERS = [
    'first_ai_label','second_ai_label','first_ai_reason','second_ai_rationale',
    'final_human_label','human_notes','developer_change_observed','fixed_context',
    'candidate_relevance_label','stage2_candidate_pool_human_confirmed',
    'private_audit','developer patch','developer fixed source','fixed-version spotbugs'
]

def load_template(path: Path): return path.read_text(encoding='utf-8')

def audit_prompt_text(prompt: str):
    findings=[m for m in FORBIDDEN_MARKERS if m.lower() in prompt.lower()]
    return {'pass':not findings,'findings':findings}

def live_code_contexts(item: dict, source_paths: dict[str, Path], window_lines: int):
    """Expand frozen warning snippets from the current buggy checkout only."""
    frozen=code_contexts(item); warnings=item.get('buggy_spotbugs_warnings',[]); expanded=[]
    window=max(1,int(window_lines))
    for context in frozen:
        path=source_paths.get(context['file'])
        if path is None or not Path(path).exists():
            expanded.append(context); continue
        centers=[int(w['start_line']) for w in warnings
                 if w.get('target_file')==context['file'] and w.get('target_method','')==context['method']
                 and str(w.get('start_line','')).isdigit()]
        if centers:
            center=centers[0]
        else:
            numbered=re.search(r'^\s*(\d+):',context.get('code',''),re.M)
            center=int(numbered.group(1)) if numbered else 1
        lines=Path(path).read_text(encoding='utf-8',errors='replace').splitlines()
        start=max(1,center-window//2); end=min(len(lines),start+window-1)
        start=max(1,end-window+1)
        code='\n'.join(f'{number}: {lines[number-1]}' for number in range(start,end+1))
        expanded.append({'file':context['file'],'method':context['method'],'code':code})
    return expanded

def render_user_prompt(group: str, item: dict, project_target_path: str, contract: dict|None,
                       feedback: str='', contexts: list[dict]|None=None):
    contexts=contexts if contexts is not None else code_contexts(item)
    base=[
        f"Bug: {item['bug_key']}",
        'Allowed buggy source targets (project source-relative):',
        '\n'.join(f"- {x['file']} :: {x['method']}" for x in contexts),
        'Failing trigger test information:', '\n'.join(item['trigger_tests']),
        'Buggy test failure summary:', item['buggy_test_failure_summary'],
        'Buggy code contexts shared by both experimental groups:',
        '\n\n'.join(f"FILE: {x['file']}\nMETHOD: {x['method']}\n{x['code']}" for x in contexts),
    ]
    if group == 'B':
        base += ['Buggy-version static-analysis warnings:', json.dumps(item['buggy_spotbugs_warnings'], ensure_ascii=False, indent=2),
                 'Executable evidence contract:', json.dumps(contract, ensure_ascii=False, indent=2)]
    if feedback:
        base += ['Previous validation feedback:', feedback]
    base += [
        'Return a minimal unified diff whose paths are relative to the checkout root.',
        'Only edit the allowed source targets listed above.',
    ]
    prompt='\n\n'.join(base)
    audit=audit_prompt_text(prompt)
    if not audit['pass']: raise RuntimeError('Prompt contains forbidden markers: '+', '.join(audit['findings']))
    return prompt

def parse_model_output(text: str, group: str):
    raw=text.strip()
    if raw.startswith('```'):
        raw=re.sub(r'^```(?:json)?\s*','',raw); raw=re.sub(r'\s*```$','',raw)
    obj=None
    try: obj=json.loads(raw)
    except Exception:
        start=raw.find('{'); end=raw.rfind('}')
        if start>=0 and end>start:
            try: obj=json.loads(raw[start:end+1])
            except Exception: obj=None
    if isinstance(obj,dict) and isinstance(obj.get('patch'),str):
        return {'patch':obj['patch'], 'summary':str(obj.get('summary','')),
                'claimed_mapping':obj.get('claimed_mapping',[]) if group=='B' else []}
    diff=''
    m=re.search(r'```diff\s*(.*?)```', text, re.S|re.I)
    if m: diff=m.group(1).strip()
    elif '--- ' in text and '+++ ' in text: diff=text[text.find('--- '):].strip()
    if diff:
        return {'patch':diff,'summary':'Parsed diff fallback','claimed_mapping':[]}
    raise ValueError('Model response did not contain a parseable patch')
