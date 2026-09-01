from __future__ import annotations
import csv, hashlib, json, os, re, shutil, subprocess, time
from pathlib import Path
from typing import Any, Iterable, Optional

RESULT_FIELDS = [
    'project_id','bug_id','bug_key','experiment_group','final_human_label','spotbugs_pattern',
    'model','model_version','temperature','maximum_attempts','attempts_used','input_tokens','output_tokens',
    'total_cost','execution_time','patch_apply_status','compile_status','trigger_test_status','all_test_status',
    'target_warning_removed','new_same_warning_count','public_api_unchanged','scope_result','patch_size_added',
    'patch_size_deleted','claimed_mapping_validity','realized_mapping_success','verifier_decision',
    'interception_reason','plausible_status','result_label','final_correctness','failure_reason','patch_path','log_path'
]

RUN_MANIFEST_FIELDS = [
    'sequence_id','project_id','bug_id','bug_key','experiment_group','phase','model','model_version',
    'temperature','top_p','max_output_tokens','maximum_attempts','token_budget','timeout_compile',
    'timeout_trigger_test','timeout_all_tests','timeout_spotbugs','patch_quantity_limit','status','started_at','finished_at'
]

FAILURE_FIELDS = ['project_id','bug_id','bug_key','experiment_group','attempt','stage','returncode','message','log_path']

def now():
    return time.strftime('%Y-%m-%dT%H:%M:%S%z')

def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding='utf-8'))

def save_json(path: Path, data: Any):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')

def read_csv(path: Path):
    with path.open('r', encoding='utf-8-sig', newline='') as f:
        return list(csv.DictReader(f))

def write_csv(path: Path, rows, fields):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', encoding='utf-8-sig', newline='') as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction='ignore')
        w.writeheader(); w.writerows(rows)

def upsert_csv(path: Path, row: dict, fields, key_fields):
    rows = read_csv(path) if path.exists() and path.stat().st_size else []
    key = tuple(str(row.get(k,'')) for k in key_fields)
    replaced = False
    for i, old in enumerate(rows):
        if tuple(str(old.get(k,'')) for k in key_fields) == key:
            rows[i] = {k: row.get(k,'') for k in fields}; replaced = True; break
    if not replaced:
        rows.append({k: row.get(k,'') for k in fields})
    write_csv(path, rows, fields)

def append_failure(path: Path, row: dict):
    rows = read_csv(path) if path.exists() and path.stat().st_size else []
    rows.append({k:row.get(k,'') for k in FAILURE_FIELDS})
    write_csv(path, rows, FAILURE_FIELDS)

def safe_rmtree(path: Path, attempts: int=6):
    """Remove a generated tree, tolerating short DrvFS directory-not-empty races."""
    path=Path(path)
    if not path.exists(): return
    last_error=None
    for attempt in range(attempts):
        try:
            shutil.rmtree(path)
            return
        except FileNotFoundError:
            return
        except OSError as exc:
            last_error=exc
            time.sleep(0.25*(attempt+1))
    raise last_error

def is_defects4j_checkout(path: Path) -> bool:
    path=Path(path)
    return path.is_dir() and (path/'.defects4j.config').is_file()

def run_cmd(cmd, cwd: Optional[Path], log_path: Path, timeout: int, env: Optional[dict]=None):
    log_path.parent.mkdir(parents=True, exist_ok=True)
    started = now(); started_clock=time.time(); stdout=''; stderr=''; returncode=125; timed_out=False
    try:
        p = subprocess.run(cmd, cwd=str(cwd) if cwd else None, stdout=subprocess.PIPE,
                           stderr=subprocess.PIPE, text=True, errors='replace', timeout=timeout, env=env)
        stdout=p.stdout or ''; stderr=p.stderr or ''; returncode=p.returncode
    except subprocess.TimeoutExpired as e:
        stdout=e.stdout or ''; stderr=e.stderr or ''; timed_out=True; returncode=124
        if isinstance(stdout, bytes): stdout=stdout.decode('utf-8', errors='replace')
        if isinstance(stderr, bytes): stderr=stderr.decode('utf-8', errors='replace')
    except Exception as e:
        stderr=f'{type(e).__name__}: {e}'; returncode=125
    finished=now(); duration=round(time.time()-started_clock,3)
    stdout_path=log_path.with_name(log_path.stem+'_stdout.log')
    stderr_path=log_path.with_name(log_path.stem+'_stderr.log')
    meta_path=log_path.with_name(log_path.stem+'_meta.json')
    stdout_path.write_text(stdout,encoding='utf-8',errors='replace')
    stderr_path.write_text(stderr,encoding='utf-8',errors='replace')
    meta_path.write_text(json.dumps({
        'started_at':started,'finished_at':finished,'duration_seconds':duration,
        'cwd':str(cwd) if cwd else None,'command':[str(x) for x in cmd],
        'timeout_seconds':timeout,'timed_out':timed_out,'returncode':returncode,
        'stdout_path':str(stdout_path),'stderr_path':str(stderr_path),
    },ensure_ascii=False,indent=2),encoding='utf-8')
    with log_path.open('w', encoding='utf-8', errors='replace') as f:
        f.write(f'# started: {started}\n# finished: {finished}\n# duration_seconds: {duration}\n# cwd: {cwd}\n# cmd: {cmd}\n')
        f.write(f'# returncode: {returncode}\n# stdout: {stdout_path.name}\n# stderr: {stderr_path.name}\n')
        if timed_out: f.write(f'# TIMEOUT after {timeout}s\n')
    combined=stdout + (('\n[stderr]\n'+stderr) if stderr else '')
    return returncode, combined


def apply_java_home(cfg: dict):
    java_home=str(cfg.get('java_home','') or '').strip()
    if java_home:
        os.environ['JAVA_HOME']=java_home
        bin_dir=str(Path(java_home)/'bin')
        current=os.environ.get('PATH','')
        if bin_dir not in current.split(os.pathsep):
            os.environ['PATH']=bin_dir+os.pathsep+current

def resolve_tool(name_or_path: str):
    p = Path(name_or_path)
    if p.is_absolute() and p.exists(): return str(p)
    return shutil.which(name_or_path) or ''

def defects4j_export(defects4j_bin: str, workdir: Path, prop: str, log: Path, timeout: int):
    code, out = run_cmd([defects4j_bin,'export','-p',prop], workdir, log, timeout)
    stdout = out.split('\n[stderr]\n',1)[0]
    if code != 0 or not stdout.strip(): return ''
    return stdout.strip().splitlines()[-1].strip()

def sha256(path: Path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda:f.read(1024*1024), b''): h.update(chunk)
    return h.hexdigest()

def parse_failing_count(output: str):
    m=re.search(r'Failing tests:\s*(\d+)', output, re.I)
    return int(m.group(1)) if m else None

def safe_rel_path(value: str):
    value=value.replace('\\','/').lstrip('./')
    p=Path(value)
    if p.is_absolute() or '..' in p.parts: raise ValueError(f'unsafe path: {value}')
    return value
