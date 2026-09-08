import json
import queue
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from de67_agent_relay import Relay, RpcError, atomic_json, is_owner_message, route_message, split_text


class FakeRpc:
    def __init__(self):
        self.calls = []
        self.notifications = []
        self.history = []
        self.error = None

    def call(self, method, params):
        self.calls.append((method, params))
        if method == "turn/steer" and self.error:
            raise self.error
        if method == "thread/items/list":
            return {"data": self.history, "nextCursor": None}
        return {"turnId": params.get("expectedTurnId")}

    def receive(self, timeout=0):
        raise queue.Empty

    def close(self):
        pass


class RelayTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.config = {"workspace": str(self.root / "workspace"), "stateDir": str(self.root / "relay"),
                       "ownerId": "11", "channelId": "22"}
        atomic_json(self.root / "relay/state.json", {"cursor": "0"})
        self.relay = Relay(self.config)
        self.sent = []
        self.relay.send = lambda *args: self.sent.append(args)

    def tearDown(self):
        self.relay.close()
        self.temp.cleanup()

    def message(self, id, text):
        return {"id": str(id), "content": text, "author": {"id": "11"}, "channel_id": "22"}

    def binding(self, role, thread="fresh"):
        return {"thread_id": thread, "turn_id": "turn", "run_id": "run", "role": role}

    def event(self, item, thread="fresh"):
        return {"method": "item/completed", "params": {"threadId": thread, "turnId": "turn", "item": item}}

    def test_route_is_per_message_and_owner_only(self):
        self.relay.accept(self.message(1, "coordinator: first"))
        self.relay.accept(self.message(2, "second"))
        self.relay.accept(self.message(1, "duplicate"))
        wrong = self.message(3, "coordinator: not owner")
        wrong["author"]["id"] = "other"
        self.relay.accept(wrong)
        bot = self.message(4, "bot")
        bot["author"]["bot"] = True
        self.relay.accept(bot)
        self.assertEqual([(j["role"], j["text"]) for j in self.relay.jobs.values()],
                         [("coordinator", "first"), ("mutator", "second")])
        self.assertEqual(route_message(" COORDINATOR:\nhello"), ("coordinator", "hello"))

    def test_first_owner_message_starts_one_mutator_and_recovers_native_receipt(self):
        atomic_json(self.relay.workspace / '.de67/state/workspace.json', {'persistent_mutator': True})
        self.relay.accept(self.message(1, 'remember orchard'))
        self.relay.jobs['1'].update(thread_id='old', turn_id='rejected-turn', run_id='old-run')
        self.relay.accept(self.message(2, 'second message'))
        self.relay.connect = lambda role: None
        class Process:
            pid = 12345
            stdin = io.StringIO()
            def poll(self): return None
            def terminate(self): pass
            def wait(self): return 0
        with patch('de67_agent_relay.subprocess.Popen', return_value=Process()) as spawn:
            self.relay.reconcile()
            self.assertEqual(spawn.call_count, 1)
        first = self.relay.jobs['1']
        self.assertEqual(first['status'], 'starting')
        self.assertNotIn('turn_id', first)
        self.assertNotIn('thread_id', first)
        self.assertEqual(self.relay.jobs['2']['status'], 'pending')
        initial = json.loads((Path(first['launch_dir']) / 'input.json').read_text())
        self.assertEqual(initial['client_id'], 'discord:1')
        self.assertIn('remember orchard', initial['input'][0]['text'])
        atomic_json(Path(first['launch_dir']) / 'receipt.json',
                    {'state': 'submitted', 'thread_id': 'astra', 'turn_id': 'first', 'run_id': 'owner-1'})
        self.relay.recover_launches()
        self.assertEqual(first['thread_id'], 'astra')
        self.assertEqual(first['status'], 'submitted')

    def test_finished_launch_recovers_reply_without_any_live_app_server(self):
        self.relay.accept(self.message(1, 'hello'))
        launch = self.root / 'launch'
        launch.mkdir()
        job = self.relay.jobs['1']
        job.update(status='starting', launch_dir=str(launch))
        atomic_json(launch / 'receipt.json', {'state': 'submitted', 'thread_id': 'fresh',
                                             'turn_id': 'turn', 'run_id': 'run'})
        events = [self.event({'type': 'userMessage', 'clientId': 'discord:1'}),
                  self.event({'type': 'agentMessage', 'id': 'final', 'phase': 'final_answer',
                              'text': 'Completed before attachment'})]
        (launch / 'output.jsonl').write_text(''.join(json.dumps({
            'type': 'app_server.notification', **event}) + '\n' for event in events))
        self.relay.connect = lambda role: None
        self.relay.history_connection = lambda: None
        self.relay.reconcile()
        self.relay.reconcile()
        self.assertEqual(job['status'], 'replied')
        self.assertEqual(len(self.sent), 1)
        self.assertIn('Completed before attachment', self.sent[0][0])

    def test_invalid_initial_message_does_not_block_the_next_owner_message(self):
        self.relay.accept(self.message(1, ''))
        self.relay.accept(self.message(2, 'valid message'))
        self.relay.connect = lambda role: None
        started = []
        def start(job):
            if not job['text']:
                raise ValueError('Message has no usable input')
            started.append(job['id'])
            job['status'] = 'starting'
            return True
        self.relay.start_mutator = start
        self.relay.reconcile()
        self.assertEqual(self.relay.jobs['1']['status'], 'failed')
        self.assertEqual(started, ['2'])
        self.assertEqual(len(self.sent), 1)
        self.assertIn('no usable input', self.sent[0][0])

    def test_input_enters_only_selected_context_without_starting_a_session(self):
        self.relay.accept(self.message(1, "coordinator: hello"))
        self.relay.accept(self.message(2, "inspect this"))
        calls = {}
        for role in ("coordinator", "mutator"):
            calls[role] = FakeRpc()
        self.relay.connect = lambda role: (self.binding(role, role), calls[role])
        self.relay.reconcile()
        for role, text in (("coordinator", "hello"), ("mutator", "inspect this")):
            self.assertEqual(calls[role].calls, [("turn/steer", {
                "threadId": role, "expectedTurnId": "turn",
                "input": [{"type": "text", "text": "User Message:\n" + text}],
                "clientUserMessageId": "discord:" + ("1" if role == "coordinator" else "2")} )])

    def test_inactive_message_waits_for_fresh_role_context_and_is_not_replayed(self):
        self.relay.accept(self.message(1, "hello"))
        self.relay.connect = lambda role: None
        self.relay.reconcile()
        self.relay.reconcile()
        self.assertEqual(len(self.sent), 1)
        self.assertEqual(self.relay.jobs["1"]["status"], "pending")
        rpc = FakeRpc()
        self.relay.connect = lambda role: (self.binding(role), rpc)
        self.relay.reconcile()
        self.relay.observe("mutator", self.event({"type": "userMessage", "clientId": "discord:1"}))
        answer = self.event({"type": "agentMessage", "id": "reply", "text": "received"})
        self.relay.observe("coordinator", answer)
        self.assertEqual(self.relay.jobs["1"]["status"], "applied")
        self.relay.observe("mutator", answer)
        self.relay.replies()
        self.relay.connect = lambda role: (self.binding(role, "reset-context"), rpc)
        self.relay.reconcile()
        self.assertEqual(len([m for m, _ in rpc.calls if m == "turn/steer"]), 1)
        self.assertEqual(self.relay.jobs["1"]["status"], "replied")

    def test_uncertain_delivery_is_recovered_from_history_without_resending(self):
        self.relay.accept(self.message(1, "hello"))
        rpc = FakeRpc()
        rpc.error = RpcError("receipt timed out; delivery may be uncertain")
        self.relay.connect = lambda role: (self.binding(role), rpc)
        self.relay.reconcile()
        self.assertEqual(self.relay.jobs["1"]["status"], "uncertain")
        rpc.error = None
        rpc.history = [
            {"item": {"type": "agentMessage", "id": "reply", "text": "same context"}},
            {"item": {"type": "userMessage", "clientId": "discord:1"}},
        ]
        self.relay.reconcile()
        self.relay.reconcile()
        self.assertEqual(len([m for m, _ in rpc.calls if m == "turn/steer"]), 1)
        self.assertEqual(self.relay.jobs["1"]["status"], "replied")
        self.assertEqual(sum("same context" in text for text, *_ in self.sent), 1)

    def test_final_buffer_is_drained_even_after_the_runner_removes_its_address(self):
        self.relay.accept(self.message(1, "hello"))
        job = self.relay.jobs["1"]
        job.update(status="submitted", thread_id="fresh", turn_id="turn")
        rpc = FakeRpc()
        rpc.notifications = [self.event({"type": "userMessage", "clientId": "discord:1"}),
                             self.event({"type": "agentMessage", "id": "reply", "text": "done"})]
        self.relay.connections["mutator"] = (self.binding("mutator"), rpc)
        self.relay.connect = lambda role: None
        self.relay.reconcile()
        self.assertEqual(job["status"], "replied")

    def test_acknowledgment_does_not_hide_the_final_answer(self):
        self.relay.accept(self.message(1, 'hello'))
        job = self.relay.jobs['1']
        job.update(status='applied', thread_id='fresh', turn_id='turn')
        self.relay.observe('mutator', self.event({'type': 'agentMessage', 'id': 'ack',
            'phase': 'commentary', 'text': 'Checking that now.'}))
        self.relay.replies()
        self.assertEqual(job['status'], 'awaiting_final')
        self.relay.observe('mutator', self.event({'type': 'agentMessage', 'id': 'noise',
            'phase': 'commentary', 'text': 'Routine unrelated progress.'}))
        self.relay.replies()
        self.assertEqual(len(self.sent), 1)
        self.relay.observe('mutator', self.event({'type': 'agentMessage', 'id': 'answer',
            'phase': 'final_answer', 'text': 'Here is the actual answer.'}))
        self.relay.replies()
        self.assertEqual(job['status'], 'replied')
        self.assertEqual(len(self.sent), 2)
        self.assertIn('actual answer', self.sent[-1][0])

    def test_final_in_same_buffer_replaces_unsent_acknowledgment(self):
        self.relay.accept(self.message(1, 'hello'))
        job = self.relay.jobs['1']
        job.update(status='applied', thread_id='fresh', turn_id='turn')
        for identity, phase in [('ack', 'commentary'), ('answer', 'final_answer')]:
            self.relay.observe('mutator', self.event({'type': 'agentMessage', 'id': identity,
                'phase': phase, 'text': identity}))
        self.relay.replies()
        self.assertEqual(len(self.sent), 1)
        self.assertIn('answer', self.sent[0][0])

    def test_history_before_owner_input_cannot_supply_its_answer(self):
        self.relay.accept(self.message(1, 'hello'))
        job = self.relay.jobs['1']
        job.update(status='awaiting_final', thread_id='fresh', turn_id='turn')
        rpc = FakeRpc()
        rpc.history = [
            {'item': {'type': 'userMessage', 'clientId': 'discord:1'}},
            {'item': {'type': 'agentMessage', 'id': 'old', 'phase': 'final_answer', 'text': 'Older answer'}},
        ]
        self.relay.recover_history('mutator', rpc)
        self.relay.replies()
        self.assertEqual(self.sent, [])
        self.assertEqual(job['status'], 'awaiting_final')

    def test_a_closed_turn_rejection_can_wait_for_the_next_instance(self):
        self.relay.accept(self.message(1, "hello"))
        rpc = FakeRpc()
        rpc.error = RpcError("no active turn", -32600)
        self.relay.connect = lambda role: (self.binding(role), rpc)
        self.relay.reconcile()
        self.assertEqual(self.relay.jobs["1"]["status"], "pending")
        rpc.error = None
        self.relay.connect = lambda role: (self.binding(role, "next-instance"), rpc)
        self.relay.reconcile()
        self.assertEqual(rpc.calls[-1][1]["threadId"], "next-instance")

    def test_restart_does_not_repeat_an_uncertain_submission(self):
        self.relay.accept(self.message(1, "hello"))
        self.relay.jobs["1"].update(status="submitting", thread_id="fresh", turn_id="turn")
        self.relay.save(self.relay.jobs["1"])
        other = Relay(self.config)
        self.assertEqual(other.jobs["1"]["status"], "uncertain")
        other.close()

    def test_ended_context_reports_unknown_delivery_and_never_replays_it(self):
        self.relay.accept(self.message(1, 'hello'))
        rpc = FakeRpc()
        self.relay.submit(self.relay.jobs['1'], self.binding('mutator'), rpc)
        self.relay.connect = lambda role: None
        self.relay.history_connection = lambda: None
        self.relay.reconcile()
        self.assertEqual(self.relay.jobs['1']['status'], 'uncertain')
        self.assertTrue(any('could not be confirmed' in text for text, *_ in self.sent))
        self.relay.connect = lambda role: (self.binding(role, 'new-context'), rpc)
        self.relay.reconcile()
        self.assertEqual(sum(method == 'turn/steer' for method, _ in rpc.calls), 1)
        history = [params for method, params in rpc.calls if method == 'thread/items/list']
        self.assertEqual(history[0]['threadId'], 'fresh')
        self.assertEqual(history[0]['turnId'], 'turn')

    def test_delivered_input_without_reply_is_reported_accurately(self):
        self.relay.accept(self.message(1, 'hello'))
        job = self.relay.jobs['1']
        job.update(status='applied', thread_id='fresh', turn_id='turn')
        self.relay.connect = lambda role: None
        self.relay.history_connection = lambda: None
        self.relay.reconcile()
        self.relay.reconcile()
        self.assertEqual(len(self.sent), 1)
        self.assertIn('Message reached the mutator', self.sent[0][0])
        self.assertEqual(job['status'], 'applied')

    def test_discord_content_limit_counts_surrogate_pairs(self):
        parts = split_text("☀️" * 1200 + "🌞" * 1200)
        self.assertEqual("".join(parts), "☀️" * 1200 + "🌞" * 1200)
        self.assertTrue(all(len(p.encode("utf-16-le")) // 2 <= 2000 for p in parts))


if __name__ == "__main__":
    unittest.main()
