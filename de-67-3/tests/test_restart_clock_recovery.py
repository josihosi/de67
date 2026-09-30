from __future__ import annotations

from contextlib import redirect_stdout
import io
import hashlib
import json
import unittest
from unittest.mock import patch

import test_worker_library_recovery as recovery
from deadline_harness import DeadlineError, main
from test_worker_library import library, WorkerFixture, record_dispatch


class RestartClockRecoveryTests(WorkerFixture, unittest.TestCase):
    restart = recovery.WorkerLibraryRecoveryTests.restart

    def setUp(self):
        super().setUp()
        self.rpc = recovery.RecoveryRpc()
        self.dispatcher = library.WorkerDispatcher(self.workspace, self.rpc, self.binding)

    # This fixture owns only temporary databases, RPC and conversation bindings.
    TASK = 'R-CAOL-FIRST-SMOKE-exploration-048'
    CLAIM = 'R-CAOL-FIRST-SMOKE'
    STARTED = 1790726680.50245
    DEADLINE = 1792504099.461238
    NORMALIZED = 1790751741.761944
    CLAIM_STARTED = DEADLINE - 1814400

    def prepare_r048(self):
        self.worker()
        packet_dir = self.workspace / ".de67/state/worker-dispatch"
        packet_dir.mkdir(parents=True)
        packet = packet_dir / (self.TASK + ".md")
        packet.write_text("Continue the original live proof frontier")
        digest = hashlib.sha256(packet.read_bytes()).hexdigest()
        from policy_kernel import current_owner_contract
        record_dispatch(self.workspace, self.state, "project", self.TASK, packet, digest,
                        {"owner_contract_sha256": hashlib.sha256(current_owner_contract(self.workspace).encode()).hexdigest()})
        # Seed the exact historic clock/attempt split, before administrative reload.
        db = self.harness.connection
        db.execute("INSERT INTO claim_clocks (lineage_id,claim_id,estimate_seconds,started_at,deadline_at,phase) VALUES ('project',?,1814400,?,?,'exploration')", (self.CLAIM,self.CLAIM_STARTED,self.DEADLINE))
        db.execute("INSERT INTO claim_deadline_generations (lineage_id,claim_id,generation,estimate_seconds,started_at,deadline_at) VALUES ('project',?,20,1814400,?,?)", (self.CLAIM,self.CLAIM_STARTED,self.DEADLINE))
        db.execute("INSERT INTO claim_phase_events (lineage_id,claim_id,sequence,phase,recorded_at,basis_task_id) VALUES ('project',?,1,'exploration',?,?)", (self.CLAIM,self.CLAIM_STARTED,self.TASK))
        db.execute("INSERT INTO tasks (lineage_id,task_id,claim_id,estimate_seconds,started_at,deadline_at,deadline_generation,phase_at_dispatch,phase_sequence_at_dispatch) VALUES ('project',?,?,345600,?,?,20,'exploration',1)", (self.TASK,self.CLAIM,self.STARTED,self.DEADLINE))
        db.commit()
        self.assign(task_id=self.TASK,packet=(packet,digest))
        with patch('deadline_harness.time.time', return_value=self.NORMALIZED-1):
            self.dispatcher.process_pending()
        original = self.returned(text='Checkpoint evidence remains accepted')
        self.assertEqual(original['status'], 'returned')
        self.before_task = dict(self.harness._task('project',self.TASK))
        self.before_claim = dict(self.harness._task_claim('project',self.TASK))
        self.before_owner = dict(db.execute('SELECT * FROM worker_claims').fetchone())
        self.before_checkpoints = [tuple(row) for row in db.execute('SELECT * FROM worker_checkpoints')]
        return original

    def legacy_normalize(self, *, kind='restart_normalized', retirement_reason='external_supervisor_restart_normalization'):
        db = self.harness.connection
        db.execute("INSERT INTO external_supervisor_epochs VALUES ('project',1,?)", (self.NORMALIZED,))
        db.execute("UPDATE tasks SET terminal_at=?,attempt_terminal_at=?,attempt_terminal_kind=?,abandoned_at=?,abandonment_reason='external_supervisor_restart_normalization' WHERE task_id=?", (self.NORMALIZED,self.NORMALIZED,kind,self.NORMALIZED,self.TASK))
        db.execute("UPDATE worker_claims SET released_at=?,release_reason='restart_normalized' WHERE task_id=?", (self.NORMALIZED,self.TASK))
        db.execute('UPDATE claim_deadline_generations SET retired_at=?,retirement_reason=?', (self.NORMALIZED,retirement_reason))
        db.commit()

    def start_again(self, *, estimate=345600, now=None):
        output = io.StringIO()
        with redirect_stdout(output), patch('deadline_harness.time.time',return_value=now or self.NORMALIZED+10):
            code = main(['start','--state',str(self.state),'--lineage','project','--task',self.TASK,'--claim',self.CLAIM,'--estimate-seconds',str(estimate)])
        self.assertEqual(code,0,output.getvalue())
        return json.loads(output.getvalue())

    def test_legacy_normalized_r048_cli_start_resumes_same_named_worker(self):
        original = self.prepare_r048()
        self.legacy_normalize()
        result = self.start_again()
        self.assertFalse(result['created'])
        self.assertEqual(result['state'],'running')
        self.assertEqual(result['deadline_generation'],20)
        self.assertEqual(result['deadline_at'],self.DEADLINE)
        self.assertEqual(result['attempt_dispatched_at'],self.STARTED)
        self.assertEqual(result['attempt_estimate_seconds'],345600)
        self.assertEqual(dict(self.harness._task('project',self.TASK)),self.before_task)
        self.assertEqual(dict(self.harness._task_claim('project',self.TASK)),self.before_claim)
        self.assertEqual(dict(self.harness.connection.execute('SELECT * FROM worker_claims').fetchone()),self.before_owner)
        self.assertEqual([tuple(row) for row in self.harness.connection.execute('SELECT * FROM worker_checkpoints')],self.before_checkpoints)
        self.assertEqual(self.harness.connection.execute('SELECT COUNT(*) FROM external_supervisor_epochs').fetchone()[0],1)
        self.restart()
        request = library.message(self.workspace,'pilot','Continue the existing proof frontier',environment=self.env)
        with patch('deadline_harness.time.time',return_value=self.NORMALIZED+11):
            self.dispatcher.process_pending()
        self.assertEqual(library.request_status(self.workspace,request['request_id'])['state'],'submitted')
        current = library.describe(self.workspace,'pilot')['assignment']
        self.assertEqual(current['worker_id'],original['worker_id'])
        self.assertEqual(current['task_id'],self.TASK)
        self.assertEqual(self.harness.connection.execute('SELECT COUNT(*) FROM worker_claims').fetchone()[0],1)
        self.assertEqual([m for m,p in self.rpc.calls].count('thread/start'),1)
        resume = [p for m,p in self.rpc.calls if m=='thread/resume'][-1]
        self.assertEqual(resume['threadId'],original['worker_id'])
        self.assertEqual(self.rpc.turn_count,2)
        self.assertEqual(library._task(self.state,'project',self.TASK)['coordinator_session_id'],'sol-a')

    def test_future_restart_preserves_open_attempt_ownership_clock_and_epoch_audit(self):
        self.prepare_r048()
        self.harness.normalize_external_supervisor_start('project',now=self.NORMALIZED)
        self.assertEqual(dict(self.harness._task('project',self.TASK)),self.before_task)
        self.assertEqual(dict(self.harness._task_claim('project',self.TASK)),self.before_claim)
        self.assertEqual(dict(self.harness.connection.execute('SELECT * FROM worker_claims').fetchone()),self.before_owner)
        self.assertEqual(self.harness.connection.execute('SELECT normalized_at FROM external_supervisor_epochs').fetchone()[0],self.NORMALIZED)
        self.start_again()

    def test_wrong_estimate_does_not_restore_legacy_normalization(self):
        self.prepare_r048()
        self.legacy_normalize()
        with self.assertRaisesRegex(DeadlineError,'Repeated start cannot change estimate'):
            self.harness.start_task('project',self.TASK,self.CLAIM,1814400,attempt_estimate_seconds=1814400,now=self.NORMALIZED+10)
        self.assertEqual(self.harness._task('project',self.TASK)['attempt_terminal_kind'],'restart_normalized')
        self.assertIsNotNone(self.harness._task_claim('project',self.TASK)['retired_at'])

    def test_real_terminal_kinds_remain_terminal(self):
        for kind in ('completed','abandoned','finding','integrity_breach'):
            with self.subTest(kind=kind):
                # Explicit terminal states without the administrative abandonment marker.
                self.harness.start_task('project',kind,'R-'+kind,100,now=1)
                self.harness.connection.execute('UPDATE tasks SET attempt_terminal_kind=?,attempt_terminal_at=2,terminal_at=2 WHERE task_id=?',(kind,kind))
                self.harness.connection.commit()
                result = self.harness.start_task('project',kind,'R-'+kind,100,now=3)
                self.assertEqual(result['attempt_terminal_kind'],kind)
                self.assertEqual(result['attempt_terminal_at'],2)

    def test_mutation_retirement_is_not_reactivated(self):
        self.prepare_r048()
        self.legacy_normalize(retirement_reason='deadline_mutation')
        with self.assertRaisesRegex(DeadlineError,'retired'):
            self.harness.start_task('project',self.TASK,self.CLAIM,1814400,attempt_estimate_seconds=345600,now=self.NORMALIZED+10)
        self.assertEqual(self.harness._task('project',self.TASK)['attempt_terminal_kind'],'restart_normalized')

    def test_legacy_abandoned_format_restores_and_expired_clock_stays_expired(self):
        self.prepare_r048()
        self.legacy_normalize(kind='abandoned')
        result = self.start_again(now=self.DEADLINE+1)
        self.assertEqual(result['deadline_at'],self.DEADLINE)
        self.assertEqual(result['deadline_generation'],20)
        self.assertTrue(result['deadline_missed'])
        self.assertIsNone(self.harness._task('project',self.TASK)['attempt_terminal_kind'])

    def test_terminal_only_legacy_claim_continues_on_original_clock(self):
        self.harness.start_task('project','completed-old','R-terminal',100,now=1)
        self.harness.complete_task('project','completed-old','Existing proof',now=2)
        prior = dict(self.harness._task('project','completed-old'))
        self.harness.connection.execute("UPDATE claim_deadline_generations SET retired_at=3,retirement_reason='external_supervisor_restart_normalization'")
        self.harness.connection.commit()
        output = io.StringIO()
        with redirect_stdout(output), patch('deadline_harness.time.time', return_value=4):
            code = main(['start', '--state', str(self.state), '--lineage', 'project',
                         '--task', 'successor', '--claim', 'R-terminal',
                         '--estimate-seconds', '30'])
        self.assertEqual(code, 0, output.getvalue())
        result = json.loads(output.getvalue())
        self.assertTrue(result['attempt_created'])
        self.assertEqual(result['deadline_generation'],1)
        self.assertEqual(result['deadline_at'],101)
        self.assertEqual(result['claim_started_at'],1)
        self.assertEqual(dict(self.harness._task('project','completed-old')),prior)
        self.assertIsNone(self.harness._claim('project','R-terminal')['retired_at'])
        self.harness.complete_task('project','successor','More proof',now=5)
        self.harness.connection.execute("UPDATE claim_deadline_generations SET retired_at=6,retirement_reason='external_supervisor_restart_normalization'")
        self.harness.connection.commit()
        with self.assertRaisesRegex(DeadlineError,'Deadline mutation is pending'):
            self.harness.start_task('project','overdue-successor','R-terminal',100,attempt_estimate_seconds=30,now=102)
        retained = self.harness._claim('project','R-terminal')
        self.assertEqual(retained['deadline_generation'],1)
        self.assertEqual(retained['deadline_at'],101)
        self.assertIsNone(retained['retired_at'])
        self.assertEqual(self.harness.connection.execute('SELECT COUNT(*) FROM tasks').fetchone()[0],2)

    def test_normalized_attempt_requires_same_task_before_replacement(self):
        self.prepare_r048()
        self.legacy_normalize()
        with self.assertRaisesRegex(DeadlineError,'restore its existing task'):
            self.harness.start_task('project','replacement',self.CLAIM,1814400,attempt_estimate_seconds=345600,now=self.NORMALIZED+10)
        self.assertEqual(self.harness._task('project',self.TASK)['attempt_terminal_kind'],'restart_normalized')
        self.assertEqual(self.harness.connection.execute('SELECT COUNT(*) FROM tasks').fetchone()[0],1)

    def test_restart_retains_unconsumed_terminal_outcomes_before_and_after_reload(self):
        from policy_kernel import workspace_facts
        self.harness.start_task('project','before-reload','R-before',100,now=1)
        self.harness.complete_task('project','before-reload','Unconsumed proof',now=2)
        self.harness.normalize_external_supervisor_start('project',now=3)
        self.assertIn('worker_completed',workspace_facts(self.workspace,self.state,'project',now=4))
        self.harness.connection.execute("INSERT INTO claim_phase_events (lineage_id,claim_id,sequence,phase,recorded_at,basis_task_id) VALUES ('project','R-before',2,'closure',5,'before-reload')")
        self.harness.connection.commit()
        self.assertNotIn('worker_completed',workspace_facts(self.workspace,self.state,'project',now=5))
        self.harness.start_task('project','after-reload','R-after',100,now=6)
        self.harness.normalize_external_supervisor_start('project',now=7)
        self.harness.complete_task('project','after-reload','New proof',now=8)
        self.assertIn('worker_completed',workspace_facts(self.workspace,self.state,'project',now=9))


if __name__ == '__main__':
    unittest.main()
