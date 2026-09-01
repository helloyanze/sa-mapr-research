from __future__ import annotations
import argparse, json, os, shutil, sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
from common import apply_java_home, is_defects4j_checkout, load_json, resolve_tool, run_cmd, safe_rmtree, save_json, now
from llm_client import chat_completion
from manifest_loader import load_runtime_dataset
from spotbugs_utils import run_spotbugs

ROOT=Path(__file__).resolve().parents[1]
REQUIRED_TOOL_CHECKS=tuple('tool_'+key for key in (
    'defects4j_bin','spotbugs_bin','git_bin','patch_bin','java_bin','maven_bin'
))

def required_environment_ready(checks: dict) -> bool:
    required=list(REQUIRED_TOOL_CHECKS)
    if 'wsl_distro' in checks:
        required.append('wsl_distro')
    return all(checks.get(key,False) for key in required)

def write_report(out: Path, checks: dict, details: dict) -> dict:
    report={'started_at':now(),'checks':checks,'details':details,'pass':all(checks.values())}
    save_json(out/'preflight_environment_report.json',report)
    lines=['# Stage 2 environment preflight','',f"Overall: {'PASS' if report['pass'] else 'FAIL'}",'']+[f"- [{'x' if v else ' '}] {k}" for k,v in checks.items()]
    (out/'preflight_environment_report.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False,indent=2))
    return report

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--config',default='config/stage2_config.json'); ap.add_argument('--skip-api',action='store_true'); ap.add_argument('--reuse-work',action='store_true'); ap.add_argument('--output-root')
    args=ap.parse_args(); cfg=load_json(ROOT/args.config); apply_java_home(cfg)
    configured_output=args.output_root or cfg.get('output_root') or cfg.get('revised_output_root')
    if not configured_output: raise SystemExit('Config must define output_root/revised_output_root or use --output-root')
    out=(ROOT/configured_output).resolve(); out.mkdir(parents=True,exist_ok=True)
    (out/'stage2_logs').mkdir(parents=True,exist_ok=True)
    (out/'spotbugs_reports').mkdir(parents=True,exist_ok=True)
    checks={}; details={};
    for key in ['defects4j_bin','spotbugs_bin','git_bin','patch_bin','java_bin','maven_bin']:
        resolved=resolve_tool(cfg[key]); checks['tool_'+key]=bool(resolved); details[key]=resolved
        if resolved: cfg[key]=resolved
    current_distro=os.environ.get('WSL_DISTRO_NAME','').strip()
    expected_distro=str(cfg.get('wsl_distro','') or '').strip()
    if current_distro and expected_distro:
        checks['wsl_distro']=current_distro==expected_distro
        details['wsl_distro']={'current':current_distro,'expected':expected_distro}
    jar=(ROOT/cfg['javaparser_checker_jar']).resolve()
    checks['javaparser_checker_built']=jar.exists()
    if not required_environment_ready(checks):
        checks['javaparser_selftest']=False
        checks['llm_api']=False
        details['llm_api']='skipped: required local tools or WSL distro check failed; no API request was sent'
        if current_distro and expected_distro and current_distro!=expected_distro:
            details['environment_hint']=f"Run this project in {expected_distro}: from PowerShell use `wsl -d {expected_distro}`."
        else:
            details['environment_hint']='Install or correct the configured paths for all required local tools before testing the API.'
        write_report(out,checks,details)
        return 2
    if not jar.exists() and checks.get('tool_maven_bin'):
        code,txt=run_cmd([cfg['maven_bin'],'-q','-f',str(ROOT/'tools/javaparser-checker/pom.xml'),'package'],ROOT,
                         out/'stage2_logs/preflight_maven_build.log',int(cfg['timeouts']['maven_build']))
        details['maven_build_returncode']=code
    checks['javaparser_checker_built']=jar.exists()
    if jar.exists():
        before=ROOT/'tools/javaparser-checker/src/test/resources/Before.java'; after=ROOT/'tools/javaparser-checker/src/test/resources/After.java'
        result=out/'preflight_javaparser_selftest.json'
        code,txt=run_cmd([cfg['java_bin'],'-jar',str(jar),'--before',str(before),'--after',str(after),'--out',str(result)],ROOT,
                         out/'stage2_logs/preflight_javaparser_selftest.log',120)
        checks['javaparser_selftest']=code==0 and result.exists()
    else: checks['javaparser_selftest']=False
    if not args.skip_api:
        try:
            res=chat_completion(cfg['llm'],[{'role':'user','content':'Reply with exactly OK.'}])
            checks['llm_api']=bool(res['content']); details['llm_api_usage']={'input_tokens':res['input_tokens'],'output_tokens':res['output_tokens']}
        except Exception as e:
            checks['llm_api']=False; details['llm_api_error']=str(e)
    else: checks['llm_api']=True; details['llm_api']='skipped'
    # Deep tool-chain check on the 3 preflight buggy versions, without patches.
    safe=load_runtime_dataset(ROOT)
    work_root=(ROOT/cfg['work_root']).resolve(); work_root.mkdir(parents=True,exist_ok=True)
    preflight_bug_keys = cfg.get('preflight_bug_keys') or cfg.get('revised_preflight_bug_keys')
    if not preflight_bug_keys:
        raise ValueError('configuration must define preflight_bug_keys or revised_preflight_bug_keys')
    for bug_key in preflight_bug_keys:
        item=safe[bug_key]; wd=work_root/'_environment_preflight'/bug_key
        if args.reuse_work and is_defects4j_checkout(wd):
            code=0; details[f'{bug_key}_checkout']='reused existing environment-preflight checkout'
        else:
            if wd.exists(): safe_rmtree(wd)
            code,_=run_cmd([cfg['defects4j_bin'],'checkout','-p',item['project_id'],'-v',f"{item['bug_id']}b",'-w',str(wd)],ROOT,
                           out/f'stage2_logs/{bug_key}_environment_checkout.log',int(cfg['timeouts']['checkout']))
        checks[f'{bug_key}_checkout']=code==0
        if code!=0: continue
        code,_=run_cmd([cfg['defects4j_bin'],'compile'],wd,out/f'stage2_logs/{bug_key}_environment_compile.log',int(cfg['timeouts']['compile']))
        checks[f'{bug_key}_compile_command']=code in (0,1)
        trig=item['trigger_tests'][0]
        code,txt=run_cmd([cfg['defects4j_bin'],'test','-t',trig],wd,out/f'stage2_logs/{bug_key}_environment_trigger.log',int(cfg['timeouts']['trigger_test']))
        checks[f'{bug_key}_trigger_command']=code in (0,1)
        code,txt=run_cmd([cfg['defects4j_bin'],'test'],wd,out/f'stage2_logs/{bug_key}_environment_alltests.log',int(cfg['timeouts']['all_tests']))
        checks[f'{bug_key}_alltests_command']=code in (0,1)
        report=out/f'spotbugs_reports/{bug_key}_environment_buggy.xml'
        ok,_=run_spotbugs(cfg,wd,report,out/f'stage2_logs/{bug_key}_environment_spotbugs.log','buggy')
        checks[f'{bug_key}_spotbugs']=ok
    report=write_report(out,checks,details)
    return 0 if report['pass'] else 2
if __name__=='__main__': raise SystemExit(main())
