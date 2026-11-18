from contextlib import closing
from datetime import datetime,timezone
import importlib.util,json,sqlite3,sys,tempfile,unittest,hashlib
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parent))
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'de-67-3/scripts'))
from campaign_fuel import read_campaign_fuel
from usage_projection import _schema,_ingest,checkpoint_thread_usage,_CHECKPOINTED
class FuelTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.w=Path(self.tmp.name);(self.w/'.de67/state').mkdir(parents=True)
  self.state=self.w/'.de67/state/deadlines.sqlite3';self.index=self.w/'.de67/state/work-context.sqlite3';self.sessions=self.w/'sessions';self.sessions.mkdir()
  (self.w/'.de67/state/workspace.json').write_text(json.dumps({'clock':{'state':str(self.state),'lineage':'L'}}))
  with sqlite3.connect(self.state) as d:d.executescript("CREATE TABLE supervisor_attempts(lineage_id,run_id,started_at,finished_at);CREATE TABLE worker_claims(lineage_id,worker_id,claimed_at,released_at);INSERT INTO supervisor_attempts VALUES('L','run',0,100);INSERT INTO worker_claims VALUES('L','worker',10,40);INSERT INTO worker_claims VALUES('L','worker',20,50);INSERT INTO worker_claims VALUES('other','foreign',0,NULL);")
  with sqlite3.connect(self.w/'state_5.sqlite') as d:d.executescript('CREATE TABLE thread_spawn_edges(parent_thread_id,child_thread_id);CREATE TABLE threads(id,rollout_path);')
  with sqlite3.connect(self.index) as d:_schema(d);d.executescript("CREATE TABLE runs(run_id,session_id,lineage);INSERT INTO runs VALUES('run','root','L');")
 def ingest(self,identity,records):
  path=self.w/(identity+'.jsonl');path.write_text(''.join(json.dumps(r)+'\n' for r in records))
  with sqlite3.connect(self.index) as d:
   d.row_factory=sqlite3.Row;_ingest(d,{'id':identity,'rollout_path':str(path)})
  return path
 def row(self,identity,rid,t,model='gpt-6.2-sol',n=10):
  turn=rid+'turn';return [{'type':'turn_context','payload':{'turn_id':turn,'model':model}}, {'type':'token_usage_record','timestamp':datetime.fromtimestamp(t,timezone.utc).isoformat(),'payload':{'thread_id':identity,'response_id':rid,'turn_id':turn,'usage':{'input_tokens':n,'cached_input_tokens':2,'output_tokens':2,'total_tokens':n+2}}}]
 def test_cumulative_restart_cleanup_day_and_model_switch(self):
  self.ingest('root',self.row('root','r0',5,n=5))
  records=self.row('worker','r1',12,n=10)+self.row('worker','r2',25,'gpt-6.1-terra',20)
  path=self.ingest('worker',records+records+self.row('foreign','bad',26,n=1000)+self.row('worker','outside',55,n=1000))
  first=read_campaign_fuel(self.w,self.sessions,now=60);self.assertEqual(sum(first['totals'].values()),35);self.assertEqual(first['totals']['terra'],20);self.assertEqual(first['response_count'],3)
  before=self.index.read_bytes();path.unlink()
  later=read_campaign_fuel(self.w,self.sessions,now=90000);self.assertEqual(later['totals'],first['totals']);self.assertEqual(sum(later['bins']),0);self.assertEqual(before,self.index.read_bytes());self.assertTrue(later['partial'])
 def test_rotation_and_duplicate_identity_do_not_erase_or_duplicate(self):
  p=self.ingest('worker',self.row('worker','r1',12,n=10))
  replacement=self.w/'new';replacement.write_text(''.join(json.dumps(r)+'\n' for r in self.row('worker','r1',12,n=10)+self.row('worker','r2',25,'gpt-6.1-terra',20)));replacement.replace(p)
  with sqlite3.connect(self.index) as d:d.row_factory=sqlite3.Row;_ingest(d,{'id':'worker','rollout_path':str(p)})
  self.assertEqual(sum(read_campaign_fuel(self.w,self.sessions,now=60)['totals'].values()),30)
 def test_checkpoint_existing_runner_boundary_is_durable(self):
  p=self.w/'live.jsonl';p.write_text(''.join(json.dumps(r)+'\n' for r in self.row('worker','r',12,'gpt-6.1-terra',12)))
  metadata={'records':[{'id':'worker','rollout_path':str(p)}]}
  with patch('work_context.thread_tree',return_value=metadata):
   _CHECKPOINTED.clear();v=checkpoint_thread_usage(self.w,'worker',force=True);self.assertFalse(v['errors']);self.assertEqual(checkpoint_thread_usage(self.w,'worker'),{'skipped':'interval'})
   checkpoint_thread_usage(self.w,'worker',force=True)
  p.unlink();self.assertEqual(read_campaign_fuel(self.w,self.sessions,now=60)['totals']['terra'],12)
 def test_missing_indexed_session_stays_partial(self):
  self.ingest('root',self.row('root','r',5));v=read_campaign_fuel(self.w,self.sessions,now=60);self.assertTrue(v['partial']);self.assertGreater(v['gap_count'],0)
 def test_deployed_visuals_all_roles(self):
  p=Path(__file__).with_name('de67_dashboard.py');s=importlib.util.spec_from_file_location('deployed',p);m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
  for values in [dict(astra=0,coordinator=0,sol=0,terra=0,luna=0,other=0),dict(astra=1,coordinator=2,sol=3,terra=7,luna=5,other=0)]:
   f=dict(available=True,totals=values,series={k:[0]*23+[v] for k,v in values.items()},partial=True)
   h=m.render_fuel(f)
   for role in ['astra','sol','terra','luna']:self.assertIn('data-role="'+role+'"',h);self.assertIn('>'+role+'</span>',h)
   self.assertIn('partial',h)
if __name__=='__main__':unittest.main()
