"""Mutation handoff retains conversation, while contracts/bindings are refreshed."""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import codex_runner as r
from work_context import record_run
from deadline_harness import DeadlineHarness

class ResumeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.w = Path(self.tmp.name).resolve()
        self.state = self.w / '.de67/state/deadlines.sqlite3'
        self.state.parent.mkdir(parents=True)
        with DeadlineHarness(self.state) as h:
            generation = h.request_coordinator_restart('test', 'Mutation fixed startup admission; retain accepted proof.')['coordinator_restart']['generation']
        self.env = dict(DE67_PROCESS_ROLE='coordinator', DE67_LINEAGE='test',
                        DE67_DEADLINE_STATE=str(self.state), DE67_COORDINATOR_RUN_ID='after',
                        DE67_COORDINATOR_RESTART_GENERATION=str(generation))
    def prior(self, session='existing-sol', role='coordinator', lineage='test', original=None):
        p = self.w / ('source-' + role + lineage); p.mkdir(exist_ok=True)
        (p/'events.jsonl').write_text(json.dumps(dict(type='thread.started', thread_id=original or session))+'\n')
        record_run(self.w, p, {**self.env, 'DE67_PROCESS_ROLE':role, 'DE67_LINEAGE':lineage, 'DE67_COORDINATOR_RUN_ID':'before'}, session_id=session)
    def test_old_supervisor_environment_resumes_original_coordinator_not_mutator_or_other_lineage(self):
        self.prior(); self.prior('reviewer', role='mutation-reviewer'); self.prior('other', lineage='other')
        r.resume_after_mutation(self.w, self.env)
        self.assertEqual(self.env['DE67_COORDINATOR_RESUME_SESSION'], 'existing-sol')
        command = r._command('/fake/codex', self.w, self.env)
        self.assertIn('resume', command); self.assertIn('existing-sol', command)
    def test_index_identity_disagreement_fails_without_fresh_start(self):
        self.prior(original='different')
        with self.assertRaisesRegex(r.RunnerError, 'disagrees'):
            r.resume_after_mutation(self.w, self.env)
        self.assertNotIn('DE67_COORDINATOR_RESUME_SESSION', self.env)
    def test_no_original_evidence_fails(self):
        self.prior(); (self.w/'source-coordinatortest/events.jsonl').write_text('{}\n')
        with self.assertRaisesRegex(r.RunnerError, 'original thread'):
            r.resume_after_mutation(self.w, self.env)
    def test_initial_start_without_predecessor_remains_possible(self):
        r.resume_after_mutation(self.w, self.env)
        self.assertNotIn('DE67_COORDINATOR_RESUME_SESSION', self.env)
    def test_no_mutation_and_reviewer_do_not_adopt_coordinator(self):
        self.prior()
        for env in [{**self.env, 'DE67_PROCESS_ROLE':'mutation-reviewer'}, {k:v for k,v in self.env.items() if k!='DE67_COORDINATOR_RESTART_GENERATION'}]:
            r.resume_after_mutation(self.w, env)
            self.assertNotIn('DE67_COORDINATOR_RESUME_SESSION', env)
    def test_mutation_resume_refreshes_current_and_legacy_prompts_preserving_bindings(self):
        self.prior(); r.resume_after_mutation(self.w, self.env)
        bindings = '\nCurrent invocation bindings (use these values directly; exact)\nACK-EXACT-RUN'
        for header in [f'You are the coordinator for Phase-3 delivery in {self.w}.\n', f'Act as a fresh Phase-3 delivery coordinator in {self.w}.\n']:
            out = r.current_coordinator_prompt(self.w, header+'STALE'+bindings, self.env)
            self.assertTrue(out.startswith('Resume the same coordinator conversation'))
            self.assertNotIn('STALE', out)
            self.assertIn('Mutation fixed startup admission', out)
            self.assertIn('DE67_COORDINATOR_ACK_ARGV_JSON', out)
            self.assertTrue(out.endswith(bindings))
        with DeadlineHarness(self.state) as h:
            self.assertTrue(h.coordinator_restart_status('test')['coordinator_restart']['pending'])
    def test_ordinary_continuation_not_reexpanded(self):
        env = {**self.env, 'DE67_COORDINATOR_RESUME_SESSION':'existing-sol'}
        del env['DE67_COORDINATOR_RESTART_GENERATION']
        self.assertEqual(r.current_coordinator_prompt(self.w, 'Continue same lifecycle.', env), 'Continue same lifecycle.')
    def test_runner_launches_resume_with_refreshed_prompt_from_old_supervisor_input(self):
        self.prior()
        captured = {}
        class Process:
            stdout = iter(['{"type":"thread.started","thread_id":"existing-sol"}\n'])
            def wait(self): return 0
        def launch(command, **kwargs):
            captured.update(command=command, env=kwargs['env'], prompt=kwargs['stdin'].read())
            return Process()
        prompt = f'You are the coordinator for Phase-3 delivery in {self.w}.\nSTALE\nCurrent invocation bindings (use these values directly;)\nEXACT-ACK'
        with patch('codex_runner.shutil.which', return_value='/fake/codex'), patch('codex_runner.subprocess.Popen', side_effect=launch):
            self.assertEqual(r.run(self.w, prompt, environment=self.env), 0)
        self.assertIn('resume', captured['command'])
        self.assertEqual(captured['env']['DE67_COORDINATOR_RESUME_SESSION'], 'existing-sol')
        self.assertIn('Resume the same coordinator conversation', captured['prompt'])
        self.assertIn('EXACT-ACK', captured['prompt'])
        self.assertNotIn('STALE', captured['prompt'])

if __name__ == '__main__': unittest.main()
