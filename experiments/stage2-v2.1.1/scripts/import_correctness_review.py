import argparse
from pathlib import Path
from common import read_csv, write_csv, RESULT_FIELDS
ROOT=Path(__file__).resolve().parents[1]
ap=argparse.ArgumentParser(); ap.add_argument('--review',default='outputs/stage2_correctness_review_template.csv'); args=ap.parse_args()
results=read_csv(ROOT/'outputs/stage2_bug_results.csv'); review=read_csv(ROOT/args.review)
rm={(r['bug_key'],r['experiment_group']):r for r in review}
allowed={'Correct','Incorrect','Overfitting-suspected','pending_human'}
for row in results:
 r=rm.get((row['bug_key'],row['experiment_group']))
 if r:
  label=r['final_correctness']
  if label not in allowed: raise SystemExit('Invalid correctness label: '+label)
  row['final_correctness']=label
write_csv(ROOT/'outputs/stage2_bug_results.csv',results,RESULT_FIELDS)
print('Imported correctness review')
