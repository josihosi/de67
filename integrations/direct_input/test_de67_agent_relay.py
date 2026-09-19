import json
import queue
import io
import tempfile
import unittest
import urllib.error
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

    def image_message(self, id):
        message = self.message(id, "inspect this image")
        message["attachments"] = [{"id": "33", "filename": "image.jpg", "size": 5,
            "content_type": "image/jpeg", "url": "https://cdn.discordapp.com/attachments/image.jpg"}]
        return message

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

    def test_attachment_download_declares_user_agent_and_reuses_verified_file(self):
        self.relay.accept(self.image_message(1))
        job = self.relay.jobs['1']
        with patch('de67_agent_relay.urllib.request.urlopen', return_value=io.BytesIO(b'image')) as download:
            inputs = self.relay.input_for(job)
            self.assertEqual(self.relay.input_for(job), inputs)
            del job['input']
            self.assertEqual(self.relay.input_for(job), inputs)
        download.assert_called_once()
        request = download.call_args.args[0]
        self.assertEqual(request.full_url, job['attachments'][0]['url'])
        self.assertEqual(request.get_header('User-agent'), 'DE67AgentInput/1.0')
        self.assertIsNone(request.get_header('Authorization'))
        self.assertEqual(inputs[1]['type'], 'localImage')
        self.assertEqual(Path(inputs[1]['path']).read_bytes(), b'image')

    def test_incomplete_attachment_is_not_cached_or_submitted(self):
        self.relay.accept(self.image_message(1))
        job = self.relay.jobs['1']
        with patch('de67_agent_relay.urllib.request.urlopen', return_value=io.BytesIO(b'bad')):
            with self.assertRaisesRegex(ValueError, 'Attachment download was incomplete'):
                self.relay.input_for(job)
        self.assertNotIn('input', job)
        self.assertFalse((self.relay.root / 'media/1/33-image.jpg').exists())
        self.assertEqual(job['status'], 'pending')

    def assert_attachment_failure_does_not_block_next_message(self, active, error):
        atomic_json(self.relay.workspace / '.de67/state/workspace.json', {'persistent_mutator': True})
        self.relay.accept(self.image_message(1))
        self.relay.accept(self.message(2, 'You good?'))
        rpc = FakeRpc()
        self.relay.connect = lambda role: (self.binding(role), rpc) if active else None
        self.relay.history_connection = lambda: None
        class Process:
            pid = 12345
            stdin = io.StringIO()
            def poll(self): return None
            def terminate(self): pass
            def wait(self): return 0
        with patch('de67_agent_relay.urllib.request.urlopen', side_effect=error), \
                patch('de67_agent_relay.subprocess.Popen', return_value=Process()) as spawn:
            self.relay.reconcile()
        first = self.relay.jobs['1']
        self.assertEqual(first['status'], 'failed')
        self.assertNotIn('thread_id', first)
        self.assertNotIn('launch_dir', first)
        self.assertTrue(first['error_notified'])
        self.assertEqual(len(self.sent), 1)
        self.assertIn('Message was not delivered: Could not prepare message input:', self.sent[0][0])
        self.assertEqual(self.sent[0][1], '1')
        second = self.relay.jobs['2']
        if active:
            spawn.assert_not_called()
            self.assertEqual(second['status'], 'submitted')
            steers = [params for method, params in rpc.calls if method == 'turn/steer']
            self.assertEqual(len(steers), 1)
            self.assertEqual(steers[0]['clientUserMessageId'], 'discord:2')
        else:
            spawn.assert_called_once()
            self.assertEqual(second['status'], 'starting')
            initial = json.loads((Path(second['launch_dir']) / 'input.json').read_text())
            self.assertEqual(initial['client_id'], 'discord:2')

    def test_rejected_attachment_does_not_block_next_active_message(self):
        self.assert_attachment_failure_does_not_block_next_message(True,
            urllib.error.HTTPError('https://cdn.discordapp.com/image.jpg', 403, 'Forbidden', {}, None))

    def test_rejected_attachment_does_not_block_next_initial_message(self):
        self.assert_attachment_failure_does_not_block_next_message(False,
            urllib.error.HTTPError('https://cdn.discordapp.com/image.jpg', 403, 'Forbidden', {}, None))

    def test_attachment_io_failure_does_not_block_next_active_message(self):
        self.assert_attachment_failure_does_not_block_next_message(True, OSError('Connection lost'))

    def test_attachment_io_failure_does_not_block_next_initial_message(self):
        self.assert_attachment_failure_does_not_block_next_message(False, OSError('Connection lost'))

    def test_native_submission_io_failure_remains_uncertain(self):
        self.relay.accept(self.message(1, 'hello'))
        rpc = FakeRpc()
        rpc.error = OSError('Connection lost after sending')
        self.relay.connect = lambda role: (self.binding(role), rpc)
        self.relay.reconcile()
        self.assertEqual(self.relay.jobs['1']['status'], 'uncertain')
        self.assertEqual(sum(method == 'turn/steer' for method, _ in rpc.calls), 1)
        self.assertIn('Delivery could not be confirmed', self.sent[0][0])

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

    def test_owner_input_reaches_the_shared_conversation_during_review(self):
        self.relay.workspace.mkdir(parents=True)
        socket = self.root / 'review.sock'
        socket.touch()
        binding = self.binding('mutator', 'owner-thread')
        binding.update(workspace=str(self.relay.workspace), role='mutator', state='active',
                       session_kind='review', runner_pid=100, server_pid=101, socket=str(socket))
        atomic_json(self.relay.workspace / '.de67/state/mutator-input.json', binding)
        class ConnectedRpc(FakeRpc):
            def send(self, message): pass
            def call(client, method, params):
                if method == 'thread/read':
                    return {'thread': {'cwd': str(self.relay.workspace), 'status': {'type': 'active'}}}
                return super().call(method, params)
        rpc = ConnectedRpc()
        self.relay.accept(self.message(1, 'current owner correction'))
        with patch('de67_agent_relay.os.kill'), patch('de67_agent_relay.Rpc', return_value=rpc):
            self.relay.start_mutator = lambda job: self.fail('must use the active shared conversation')
            self.relay.reconcile()
        steers = [params for method, params in rpc.calls if method == 'turn/steer']
        self.assertEqual(len(steers), 1)
        self.assertEqual(steers[0]['threadId'], 'owner-thread')
        self.assertEqual(steers[0]['clientUserMessageId'], 'discord:1')
        self.assertEqual(self.relay.jobs['1']['status'], 'submitted')

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
