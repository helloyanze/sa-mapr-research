from __future__ import annotations
import argparse, json
from pathlib import Path
from prompting import audit_prompt_text
def main():
 ap=argparse.ArgumentParser(); ap.add_argument('--prompts',default='outputs/prompts'); ap.add_argument('--report',default='outputs/stage2_prompt_leakage_audit.md')
 args=ap.parse_args(); root=Path(__file__).resolve().parents[1]; pdir=root/args.prompts; findings=[]; count=0
 for p in sorted(pdir.glob('*.json')):
  count+=1; text=p.read_text(encoding='utf-8',errors='replace')
  audit=audit_prompt_text(text)
  for term in audit['findings']: findings.append({'file':str(p.relative_to(root)),'term':term})
 report=root/args.report; report.parent.mkdir(parents=True,exist_ok=True)
 lines=['# Stage 2 prompt leakage audit','',f'- Prompt files checked: {count}',f"- Status: {'FAIL' if findings else 'PASS'}",'']
 lines += [f"- {x['file']}: forbidden term `{x['term']}`" for x in findings]
 report.write_text('\n'.join(lines)+'\n',encoding='utf-8')
 (report.with_suffix('.json')).write_text(json.dumps({'pass':not findings,'prompt_files_checked':count,'findings':findings},ensure_ascii=False,indent=2),encoding='utf-8')
 print(json.dumps({'pass':not findings,'count':count,'findings':findings},ensure_ascii=False,indent=2)); return 0 if not findings else 2
if __name__=='__main__': raise SystemExit(main())
