import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from deadline_harness import DeadlineHarness, DeadlineError
from work_context import record_dispatch
import test_deadline_harness as fixtures

class SupportAcceptanceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.state = self.root / '.de67/state/deadlines.sqlite3'
        self.h = DeadlineHarness(self.state)
        self.fs = self.root / '.de67/FS.md'
        self.fs.write_text('Frozen\n')
        self.h.start_task('project', 'edit', 'editorial', 100, now=1)
        self.h.claim_worker('project','edit','worker','coordinator','supervisor',now=2)
        self.packet = self.root / '.de67/state/worker-dispatch/packet.md'
        self.packet.parent.mkdir()
        self.seal('Own assigned exploration work edit for outcome editorial. Scope: task-specific ledger assignment. Staged method candidate: editorial outcome\nNo product FS slice or gameplay acceptance is implied by this assignment.')
        receipt = fixtures.DeadlineHarnessTests.worker_receipt(self,'edit','editorial','worker','completed')
        self.rid = self.h.record_worker_result_receipt('project','edit','worker',receipt,now=3)['receipt_id']
        self.h.complete_task('project','edit','edited',receipt_id=self.rid,now=4)
    def tearDown(self):
        self.h.close();self.tmp.cleanup()
    def seal(self,text):
        self.packet.write_text(text)
        record_dispatch(self.root,self.state,'project','edit',self.packet,hashlib.sha256(self.packet.read_bytes()).hexdigest(),{'claim_id':'editorial'})
    def accept(self,**kw):
        return self.h.accept_support_claim('project','editorial','edit','reviewed',receipt_id=self.rid,now=5,**kw)
    def test_accept_idempotent_reopen_preserves_clock_task_and_no_gap(self):
        before=tuple(self.h.connection.execute('select * from tasks').fetchone())
        self.assertTrue(self.accept()['recorded'])
        self.h.close();self.h=DeadlineHarness(self.state)
        self.assertFalse(self.accept()['recorded'])
        self.assertEqual(before,tuple(self.h.connection.execute('select * from tasks').fetchone()))
        self.assertEqual(0,self.h.connection.execute('select count(*) from closure_gaps').fetchone()[0])
        self.assertIsNone(self.h.connection.execute('select closure_sequence from claim_acceptances').fetchone()[0])
        self.assertTrue(self.h.status_task('project','edit',now=500)['completion_accepted'])
    def test_product_and_unsealed_dispatch_rejected(self):
        self.fs.write_text('<!-- DE67:DFS-SLICE:BEGIN claim=editorial -->\n')
        with self.assertRaises(DeadlineError):self.accept()
        self.fs.write_text('Frozen\n');self.packet.write_text('tampered')
        with self.assertRaises(DeadlineError):self.accept()
    def test_product_packet_not_eligible(self):
        self.seal('ordinary gameplay task')
        with self.assertRaises(DeadlineError):self.accept()
    def test_incomplete_sibling_blocks(self):
        self.h.start_task('project','other','editorial',100,now=5)
        with self.assertRaisesRegex(DeadlineError,'sibling'):self.accept()
    def test_wrong_receipt_and_claim_rejected(self):
        with self.assertRaises(DeadlineError):self.h.accept_support_claim('project','editorial','edit','reviewed',receipt_id='bad',now=5)
        with self.assertRaises(DeadlineError):self.h.accept_support_claim('project','wrong','edit','reviewed',receipt_id=self.rid,now=5)
    def test_existing_product_route_still_requires_closure(self):
        with self.assertRaisesRegex(DeadlineError,'closure'):self.h.accept_claim('project','editorial','edit','reviewed',now=5)
    def test_incomplete_and_integrity_rejected(self):
        # Deliberately construct invalid states to exercise the acceptance boundary.
        self.h.connection.execute("UPDATE tasks SET attempt_terminal_kind='finding' WHERE task_id='edit'")
        self.h.connection.commit()
        with self.assertRaisesRegex(DeadlineError,'completed'):self.accept()
        self.h.connection.execute("UPDATE tasks SET attempt_terminal_kind='completed', integrity_breached_at=4 WHERE task_id='edit'")
        self.h.connection.commit()
        with self.assertRaisesRegex(DeadlineError,'intact'):self.accept()
    def test_changed_acceptance_not_duplicated(self):
        self.accept()
        with self.assertRaises(DeadlineError):
            self.h.accept_support_claim('project','editorial','edit','different',receipt_id=self.rid,now=6)
        self.assertEqual(1,self.h.connection.execute('select count(*) from claim_acceptances').fetchone()[0])
    def test_actual_cli(self):
        cmd=[sys.executable,str(Path(__file__).resolve().parents[1]/'scripts/deadline_harness.py'),'--state',str(self.state),'accept-support-claim','--lineage','project','--claim','editorial','--task','edit','--receipt',self.rid,'--evidence','reviewed']
        p=subprocess.run(cmd,text=True,capture_output=True)
        self.assertEqual(p.returncode,0,p.stderr)
        self.assertTrue(json.loads(p.stdout)['recorded'])

class DeliveredGuidanceTests(unittest.TestCase):
    def test_observation_is_not_bug_attribution_or_terminal_acceptance(self):
        import policy_kernel
        text=policy_kernel.worker_outcome_contract()
        self.assertIn('Report observations and suspected issues promptly',text)
        self.assertIn('code-grounded causal evidence',text)
        self.assertIn('Reporting, bug attribution, repair verification and acceptance',text)
        self.assertIn('compatible checkpoint replay or a fresh start',text)
        self.assertIn('cheaper valid route',text)
    def test_role_checks_retained_with_nonritual_reuse(self):
        import coordinator_supervisor as supervisor
        # This is the emitted coordinator contract, not a separate guide.
        import inspect
        names=[name for name,value in vars(supervisor).items() if inspect.isfunction(value) and name.endswith('contract')]
        texts=[]
        for name in names:
            fn=getattr(supervisor,name)
            if not inspect.signature(fn).parameters:
                texts.append(fn())
        text=' '.join(texts)
        self.assertIn('consequential uncertainty',text)
        self.assertIn('Preserve each role',text)
        self.assertIn('accept-support-claim',text)

if __name__=='__main__':unittest.main()
