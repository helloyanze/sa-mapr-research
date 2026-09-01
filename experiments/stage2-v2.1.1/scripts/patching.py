from __future__ import annotations
from collections.abc import Iterable
from pathlib import Path
import re
from common import run_cmd, safe_rel_path

HUNK_HEADER_RE=re.compile(
    r'^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@(.*)$'
)

def patch_files(patch: str):
    files=[]
    for line in patch.splitlines():
        if line.startswith('+++ '):
            p=line[4:].strip().split('\t')[0]
            if p=='/dev/null': continue
            if p.startswith('b/'): p=p[2:]
            files.append(safe_rel_path(p))
    return list(dict.fromkeys(files))

def normalize_target_paths(patch: str, allowed_project_files: Iterable[str]):
    allowed=[safe_rel_path(x) for x in allowed_project_files]
    out=[]
    for line in patch.splitlines():
        if line.startswith(('--- ','+++ ')):
            prefix=line[:4]; rest=line[4:]
            path=rest.split('\t')[0].strip(); tail=rest[len(path):]
            marker=''
            clean=path
            if clean.startswith(('a/','b/')): marker=clean[:2]; clean=clean[2:]
            matches=[x for x in allowed if x==clean or x.endswith('/'+clean)]
            if len(matches)==1: clean=matches[0]
            line=prefix+marker+clean+tail
        out.append(line)
    return '\n'.join(out)+'\n'

def repair_hunk_counts(patch: str):
    """Recompute unified-diff hunk counts without changing patch semantics."""
    lines=patch.splitlines(); out=[]; index=0
    while index < len(lines):
        line=lines[index]; match=HUNK_HEADER_RE.match(line)
        if not match:
            out.append(line); index+=1; continue
        body=[]; cursor=index+1; old_count=new_count=0
        while cursor < len(lines):
            candidate=lines[cursor]
            if candidate.startswith(('@@ ','--- ','+++ ','diff --git ')):
                break
            if candidate.startswith(' '):
                old_count+=1; new_count+=1
            elif candidate.startswith('-'):
                old_count+=1
            elif candidate.startswith('+'):
                new_count+=1
            elif candidate.startswith('\\ No newline at end of file'):
                pass
            else:
                break
            body.append(candidate); cursor+=1
        if not body:
            out.append(line); index+=1; continue
        old_start,_,new_start,_,suffix=match.groups()
        out.append(f'@@ -{old_start},{old_count} +{new_start},{new_count} @@{suffix}')
        out.extend(body); index=cursor
    return '\n'.join(out)+'\n'

def apply_patch(cfg, workdir: Path, patch_text: str, patch_path: Path, allowed_project_files, log: Path):
    if isinstance(allowed_project_files,str): allowed_project_files=[allowed_project_files]
    allowed=[safe_rel_path(x) for x in allowed_project_files]
    normalized_patch=normalize_target_paths(patch_text,allowed)
    patch_text=repair_hunk_counts(normalized_patch)
    hunk_counts_repaired=patch_text!=normalized_patch
    patch_path.parent.mkdir(parents=True, exist_ok=True); patch_path.write_text(patch_text, encoding='utf-8')
    files=patch_files(patch_text)
    forbidden=any('/test/' in ('/'+f.lower()+'/') or f.lower().startswith(('test/','tests/')) or
                  Path(f).name.lower() in {'pom.xml','build.gradle','build.xml'} for f in files)
    scope_ok=bool(files) and not forbidden and all(f in allowed for f in files)
    if not scope_ok:
        log.parent.mkdir(parents=True,exist_ok=True)
        log.write_text('Scope blocked. Changed files: '+repr(files)+'\nAllowed: '+repr(allowed)+'\nForbidden target: '+str(forbidden)+'\n', encoding='utf-8')
        return {'status':'blocked_scope','scope_ok':False,'files':files,'returncode':2,'output':'scope violation',
                'hunk_counts_repaired':hunk_counts_repaired}
    if (workdir/'.git').exists():
        code,out=run_cmd([cfg['git_bin'],'apply','--check','--ignore-space-change',str(patch_path)],workdir,log.with_name(log.stem+'_check.log'),120)
        if code==0:
            code,out=run_cmd([cfg['git_bin'],'apply','--ignore-space-change',str(patch_path)],workdir,log,120)
            return {'status':'applied' if code==0 else 'failed','scope_ok':True,'files':files,'returncode':code,'output':out,
                    'hunk_counts_repaired':hunk_counts_repaired}
    code,out=run_cmd([cfg['patch_bin'],'-p1','--forward','--batch','--ignore-whitespace','-i',str(patch_path)],workdir,log,120)
    return {'status':'applied' if code==0 else 'failed','scope_ok':True,'files':files,'returncode':code,'output':out,
            'hunk_counts_repaired':hunk_counts_repaired}

def patch_size(patch: str):
    add=delete=0
    for line in patch.splitlines():
        if line.startswith(('+++','---')): continue
        if line.startswith('+'): add+=1
        elif line.startswith('-'): delete+=1
    return add,delete
