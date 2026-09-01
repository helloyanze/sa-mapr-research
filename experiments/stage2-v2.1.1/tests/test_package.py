import csv, json, os, sys, tempfile, unittest
from pathlib import Path
from unittest import mock
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from contract_builder import allowed_source_files, build_contract, load_registry, validate_contract
from common import is_defects4j_checkout, safe_rmtree
from manifest_loader import code_contexts, load_runtime_dataset
from llm_client import chat_completion
from prompting import audit_prompt_text, live_code_contexts, parse_model_output, render_user_prompt
from patching import apply_patch, patch_files, repair_hunk_counts
from preflight_gate import api_response_recorded
from preflight_check import required_environment_ready
from spotbugs_utils import warning_delta
from stage2_runner import finalize_run_metrics
from verifier import build_evidence_report, validate_claimed_mapping
from revised_common import canonical_json, sha256_text
from revised_contract import build_contract_v2_1, load_registry as load_registry_v21, raw_static_evidence, validate_contract_v2_1
from revised_prompting import audit_structured_payload, build_prompt_record
from revised_verifier import build_attempt_evidence, validate_claimed_mapping as validate_claimed_mapping_v21
class TestPackage(unittest.TestCase):
 def test_manifest(self):
  with (ROOT/'frozen_inputs/stage2_20bug_input_manifest.csv').open(encoding='utf-8-sig',newline='') as f: rows=list(csv.DictReader(f))
  self.assertEqual(len(rows),20); self.assertEqual(sum(r['preflight']=='true' for r in rows),3)
 def test_safe_input(self):
  rows=[json.loads(x) for x in (ROOT/'runtime_safe/stage2_safe_bug_inputs.jsonl').read_text(encoding='utf-8').splitlines() if x]
  self.assertEqual(len(rows),20)
  forbidden={'final_human_label','first_ai_label','second_ai_label','fixed_context','developer_change_observed'}
  for r in rows: self.assertFalse(forbidden & set(r))
 def test_contracts(self): self.assertEqual(len(list((ROOT/'contracts').glob('*.json'))),20)
 def test_runtime_dataset_and_built_contracts(self):
  data=load_runtime_dataset(ROOT); registry=load_registry(ROOT)
  self.assertEqual(len(data),20)
  for item in data.values(): validate_contract(build_contract(item,registry),ROOT/'schemas/executable_evidence_contract.schema.json')
 def test_codec_multifile_and_fair_context(self):
  item=load_runtime_dataset(ROOT)['Codec-1']; contract=build_contract(item,load_registry(ROOT))
  self.assertEqual(len(allowed_source_files(contract)),3); self.assertEqual(len(code_contexts(item)),3)
  a=render_user_prompt('A',item,item['target_file'],None); b=render_user_prompt('B',item,item['target_file'],contract)
  for context in code_contexts(item): self.assertIn(context['code'],a); self.assertIn(context['code'],b)
  self.assertNotIn('Executable evidence contract:',a); self.assertIn('Executable evidence contract:',b)
 def test_live_buggy_context_uses_configured_window_for_both_groups(self):
  item=load_runtime_dataset(ROOT)['Chart-22']; contract=build_contract(item,load_registry(ROOT))
  with tempfile.TemporaryDirectory() as d:
   source=Path(d)/'KeyedObjects2D.java'
   source.write_text('\n'.join(f'line {n}' for n in range(1,301))+'\n',encoding='utf-8')
   contexts=live_code_contexts(item,{item['target_file']:source},120)
  numbered=contexts[0]['code'].splitlines()
  self.assertEqual(len(numbered),120)
  self.assertTrue(numbered[0].startswith('176: ')); self.assertTrue(numbered[-1].startswith('295: '))
  a=render_user_prompt('A',item,item['target_file'],None,contexts=contexts)
  b=render_user_prompt('B',item,item['target_file'],contract,contexts=contexts)
  self.assertIn(contexts[0]['code'],a); self.assertIn(contexts[0]['code'],b)
 def test_prompt_leakage_guard(self): self.assertFalse(audit_prompt_text('developer patch')['pass'])
 def test_parser(self):
  x=parse_model_output('{"patch":"--- a/x.java\\n+++ b/x.java\\n@@ -1 +1 @@\\n-a\\n+b\\n","summary":"x"}','A')
  self.assertIn('+++',x['patch'])
 def test_patch_files(self): self.assertEqual(patch_files('--- a/src/X.java\n+++ b/src/X.java\n@@ -1 +1 @@\n-a\n+b\n'),['src/X.java'])
 def test_repair_hunk_counts(self):
  malformed='--- a/source/X.java\n+++ b/source/X.java\n@@ -10,7 +10,7 @@\n one\n two\n-old\n+new\n three\n four\n five\n'
  repaired=repair_hunk_counts(malformed)
  self.assertIn('@@ -10,6 +10,6 @@',repaired)
 def test_apply_patch_repairs_counts_and_ignores_line_ending_whitespace(self):
  malformed='--- a/source/X.java\n+++ b/source/X.java\n@@ -10,7 +10,7 @@\n one\n two\n-old\n+new\n three\n four\n five\n'
  with tempfile.TemporaryDirectory() as d:
   root=Path(d); (root/'.git').mkdir(); patch_path=root/'candidate.diff'; log=root/'apply.log'
   cfg={'git_bin':'git','patch_bin':'patch'}
   with mock.patch('patching.run_cmd',side_effect=[(0,''),(0,'')]) as run:
    result=apply_patch(cfg,root,malformed,patch_path,['source/X.java'],log)
   self.assertEqual(result['status'],'applied')
   self.assertTrue(result['hunk_counts_repaired'])
   self.assertIn('@@ -10,6 +10,6 @@',patch_path.read_text(encoding='utf-8'))
   self.assertIn('--ignore-space-change',run.call_args_list[0].args[0])
   self.assertIn('--ignore-space-change',run.call_args_list[1].args[0])
 def test_patch_scope_blocks_tests_before_tool(self):
  with tempfile.TemporaryDirectory() as d:
   cfg={'git_bin':'git','patch_bin':'patch'}; p=Path(d)/'x.diff'; log=Path(d)/'apply.log'
   result=apply_patch(cfg,Path(d),'--- a/src/test/X.java\n+++ b/src/test/X.java\n@@ -1 +1 @@\n-a\n+b\n',p,['src/main/X.java'],log)
   self.assertEqual(result['status'],'blocked_scope')
 def test_warning_delta(self):
  evidence=[{'pattern':'P','location':{'file':'X.java','method':'m'}}]
  before=[{'pattern':'P','file':'X.java','method':'m'}]; after=[]
  delta=warning_delta(before,after,evidence); self.assertTrue(delta['target_warning_removed']); self.assertEqual(delta['new_same_warning_count'],0)
 def test_realized_mapping_is_obligation_level(self):
  item=load_runtime_dataset(ROOT)['Chart-22']; contract=build_contract(item,load_registry(ROOT)); target=contract['repair_obligations'][0]['target']
  ast={target['file']:{'status':'ok','unchanged':True,'imports_changed':False,'fields_changed':False,'added_private_methods':[],
       'changed_methods':[{'key':target['method']+'()','name':target['method'],'status':'modified','ast_nodes':['IfStmt'],'after_source':'if (x) {}'}]}}
  claimed=[{'obligation_id':o['id'],'patch_location':o['target']['file']+'::'+o['target']['method'],'justification':'test'} for o in contract['repair_obligations']]
  ok,problems=validate_claimed_mapping(contract,claimed); self.assertTrue(ok,problems)
  report=build_evidence_report('B',contract,claimed,ok,problems,{'status':'applied','scope_ok':True,'files':[target['file']]},True,True,True,
      {'target_warning_removed':True,'new_same_warning_count':0},ast,Path(tempfile.gettempdir())/'samapr_test_report.json')
  self.assertTrue(report['realized_mapping_success']); self.assertEqual(len(report['realized_obligation_mapping']),len(contract['repair_obligations']))
 def test_final_metrics_cover_all_attempts_not_only_best_patch(self):
  cfg={'llm':{'input_price_per_million':0.5,'output_price_per_million':1.0}}
  row=finalize_run_metrics({'attempts_used':1,'input_tokens':10,'output_tokens':5},cfg,3,100,20,12.3456)
  self.assertEqual(row['attempts_used'],3)
  self.assertEqual(row['input_tokens'],100)
  self.assertEqual(row['output_tokens'],20)
  self.assertAlmostEqual(row['total_cost'],0.00007)
  self.assertEqual(row['execution_time'],12.346)
 def test_deepseek_request_is_reproducibly_configured(self):
  cfg=json.loads((ROOT/'config/stage2_config.json').read_text(encoding='utf-8'))['llm']
  cfg['reasoning_effort']='high'
  with mock.patch.dict(os.environ,{cfg['api_key_env']:'test-key'}), mock.patch('llm_client.urllib.request.urlopen') as open_url:
   open_url.return_value.__enter__.return_value.read.return_value=json.dumps({
       'choices':[{'message':{'content':'ok'},'finish_reason':'stop'}], 'usage':{'prompt_tokens':1,'completion_tokens':1}
   }).encode()
   result=chat_completion(cfg,[{'role':'user','content':'ping'}])
  request=open_url.call_args.args[0]; payload=json.loads(request.data.decode('utf-8'))
  self.assertEqual(request.full_url,'https://api.deepseek.com/chat/completions')
  self.assertEqual(payload['model'],'deepseek-v4-pro')
  self.assertEqual(payload['thinking'],{'type':'disabled'})
  self.assertEqual(payload['temperature'],0)
  self.assertNotIn('reasoning_effort',payload)
  self.assertEqual(result['content'],'ok')
  self.assertEqual(result['finish_reason'],'stop')
  self.assertFalse(result['has_reasoning_content'])
 def test_reasoning_metadata_is_auditable_without_becoming_content(self):
  cfg=json.loads((ROOT/'config/stage2_config.json').read_text(encoding='utf-8'))['llm']
  with mock.patch.dict(os.environ,{cfg['api_key_env']:'test-key'}), mock.patch('llm_client.urllib.request.urlopen') as open_url:
   open_url.return_value.__enter__.return_value.read.return_value=json.dumps({
       'choices':[{'message':{'content':'','reasoning_content':'hidden trace'},'finish_reason':'length'}],
       'usage':{'prompt_tokens':2,'completion_tokens':3}
   }).encode()
   result=chat_completion(cfg,[{'role':'user','content':'ping'}])
  self.assertEqual(result['content'],'')
  self.assertEqual(result['finish_reason'],'length')
  self.assertTrue(result['has_reasoning_content'])
  self.assertEqual(result['raw']['choices'][0]['message']['reasoning_content'],'hidden trace')
 def test_preflight_response_check_uses_artifact_files(self):
  with tempfile.TemporaryDirectory() as d:
   out=Path(d); (out/'responses').mkdir()
   self.assertFalse(api_response_recorded(out,'Chart-1','A'))
   (out/'responses/Chart-1_A_attempt1.json').write_text('{}',encoding='utf-8')
   self.assertTrue(api_response_recorded(out,'Chart-1','A'))
 def test_preflight_blocks_api_when_tools_or_distro_are_wrong(self):
  complete={key:True for key in ('tool_defects4j_bin','tool_spotbugs_bin','tool_git_bin','tool_patch_bin','tool_java_bin','tool_maven_bin')}
  complete['wsl_distro']=True
  self.assertTrue(required_environment_ready(complete))
  complete['tool_java_bin']=False
  self.assertFalse(required_environment_ready(complete))
  complete['tool_java_bin']=True; complete['wsl_distro']=False
  self.assertFalse(required_environment_ready(complete))
 def test_generated_tree_cleanup_and_checkout_validation(self):
  root=Path(tempfile.mkdtemp())
  (root/'nested').mkdir(); (root/'nested/file.txt').write_text('x')
  self.assertFalse(is_defects4j_checkout(root))
  (root/'.defects4j.config').write_text('pid=Codec\nvid=1b\n')
  self.assertTrue(is_defects4j_checkout(root))
  safe_rmtree(root)
  self.assertFalse(root.exists())
 def revised_fixture(self,bug='Chart-22'):
  item=load_runtime_dataset(ROOT)[bug]; contract=build_contract_v2_1(item,load_registry_v21(ROOT))
  shared={'schema_version':'2.1','run_id':'test','bug_key':bug,'project_id':item['project_id'],'bug_id':str(item['bug_id']),
          'buggy_version':str(item['bug_id'])+'b','trigger_tests':item['trigger_tests'],'failure_summary':'Failing tests: 1',
          'trigger_failure_outputs':['Failing tests: 1'],'allowed_source_files':contract['hard_repair_scope']['allowed_source_files'],
          'source_root':'source','source_policy':'full_allowed_files','source_context_truncated':False,
          'source_files':[{'file':x,'project_path':'source/'+x,'sha256':'fixture','line_count':1,'content':'1: class Fixture {}'} for x in contract['hard_repair_scope']['allowed_source_files']],
          'fairness_parameters':{'model':'m','model_version':'v','temperature':0,'top_p':1,'max_output_tokens':1,'token_budget':10,'maximum_attempts':3,'timeouts':{},'patch_quantity_limit':1}}
  return item,contract,shared
 def test_v21_contract_schema_and_three_enforcement_classes(self):
  for item in load_runtime_dataset(ROOT).values():
   contract=build_contract_v2_1(item,load_registry_v21(ROOT)); validate_contract_v2_1(contract,ROOT/'schemas/executable_evidence_contract_v2_1.schema.json')
   classes={x['severity'] for x in contract['repair_obligations']+contract['verification_obligations']}
   self.assertEqual(classes,{'blocking','advisory','metric_only'})
   self.assertTrue(contract['hard_repair_scope']['file_level'])
 def test_v21_shared_context_hash_and_group_treatment_isolation(self):
  item,contract,shared=self.revised_fixture(); digest=sha256_text(canonical_json(shared))
  baseline=(ROOT/'prompts/revised_baseline_system.md').read_text(encoding='utf-8'); csystem=(ROOT/'prompts/revised_contract_system.md').read_text(encoding='utf-8')
  a=build_prompt_record('A',baseline,shared,digest); r=build_prompt_record('R',baseline,shared,digest,raw_static_evidence(item)); c=build_prompt_record('C',csystem,shared,digest,raw_static_evidence(item),contract)
  self.assertTrue(a['leakage_audit']['pass'],a['leakage_audit']); self.assertTrue(r['leakage_audit']['pass'],r['leakage_audit']); self.assertTrue(c['leakage_audit']['pass'],c['leakage_audit'])
  self.assertEqual({a['shared_context_sha256'],r['shared_context_sha256'],c['shared_context_sha256']},{digest})
  self.assertEqual({a['base_prompt_sha256'],r['base_prompt_sha256'],c['base_prompt_sha256']},{a['base_prompt_sha256']})
  self.assertEqual(len({a['treatment_appendix_sha256'],r['treatment_appendix_sha256'],c['treatment_appendix_sha256']}),3)
  atext=canonical_json(a['messages']).lower(); rtext=canonical_json(r['messages']).lower(); ctext=canonical_json(c['messages']).lower()
  self.assertNotIn('spotbugs',atext); self.assertNotIn('claimed_mapping',atext); self.assertIn('spotbugs',rtext); self.assertNotIn('repair_obligations',rtext); self.assertIn('repair_obligations',ctext)
 def test_v21_file_scope_allows_non_anchor_method_and_functional_veto(self):
  _,contract,_=self.revised_fixture(); source=contract['hard_repair_scope']['allowed_source_files'][0]
  ast={source:{'status':'ok','unchanged':True,'imports_changed':False,'fields_changed':False,'added_private_methods':[],
               'changed_methods':[{'key':'differentMethod()','name':'differentMethod','status':'modified','ast_nodes':['IfStmt'],'after_source':'void differentMethod() {}'}]}}
  claimed=[{'obligation_id':x['id'],'patch_location':source+'::differentMethod()','justification':'fixture'} for x in contract['repair_obligations']]
  claimed_ok,problems=validate_claimed_mapping_v21(contract,claimed); self.assertTrue(claimed_ok,problems)
  delta={'target_warning_removed':True,'new_same_warning_count':0,'targets':[{'pattern':x['pattern'],'file':x['file'],'method':x['method'],'removed':True} for x in contract['evidence_anchor']]}
  with tempfile.TemporaryDirectory() as d:
   report=build_attempt_evidence('C',contract,claimed,claimed_ok,problems,{'status':'applied','scope_ok':True,'files':[source]},True,False,False,delta,ast,Path(d)/'evidence.json')
  self.assertTrue(report['hard_repair_scope']['pass']); self.assertEqual(report['hard_repair_scope']['changed_methods'][source],['differentMethod()'])
  self.assertTrue(report['mapping']['mapping_consistent']); self.assertEqual(report['obligation_compliance']['advisory_obligations_pass'],report['obligation_compliance']['advisory_obligations_total'])
  self.assertFalse(report['verifier_decisions']['would_accept_test_only']); self.assertFalse(report['verifier_decisions']['would_accept_generic']); self.assertFalse(report['verifier_decisions']['would_accept_hybrid'])
  with tempfile.TemporaryDirectory() as d:
   prefixed=build_attempt_evidence('C',contract,claimed,claimed_ok,problems,{'status':'applied','scope_ok':True,'files':['source/'+source]},True,True,True,delta,ast,Path(d)/'evidence.json')
  self.assertTrue(prefixed['blocking_checks']['TESTS_UNCHANGED']); self.assertTrue(prefixed['hard_repair_scope']['pass'])
  self.assertTrue(prefixed['verifier_decisions']['would_accept_hybrid'])
 def test_v21_structured_leakage_blocks_posthoc_labels(self):
  audit=audit_structured_payload({'bug_key':'X','evidence_relevance':'supporting'},'shared_context')
  self.assertFalse(audit['pass']); self.assertGreater(audit['forbidden_findings'],0)
if __name__=='__main__': unittest.main()
