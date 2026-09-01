from __future__ import annotations
import argparse,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
from common import load_json
from revised_common import initialize_run
ROOT=Path(__file__).resolve().parents[1]
def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--config',default='config/stage2_v2_1_config.json'); ap.add_argument('--run-id',required=True); ap.add_argument('--resume',action='store_true')
    args=ap.parse_args(); out=initialize_run(ROOT,load_json(ROOT/args.config),args.run_id,args.resume)
    print(json.dumps({'run_id':args.run_id,'output_root':str(out)},ensure_ascii=False)); return 0
if __name__=='__main__': raise SystemExit(main())
