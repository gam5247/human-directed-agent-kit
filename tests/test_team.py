"""Exercise the real local mailbox through independent command processes."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


class TeamMailbox(unittest.TestCase):
    def setUp(self):
        self.base = (ROOT / '.test-runs').resolve()
        self.base.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=self.base)
        self.project = Path(self.temp.name) / 'shared project'
        self.project.mkdir()
        self.command = [sys.executable, str(ROOT / 'team.py'), '--root', str(self.project)]
        self.env = {**os.environ, 'PYTHONIOENCODING': 'utf-8'}

    def tearDown(self):
        if not Path(self.temp.name).resolve().is_relative_to(self.base):
            raise AssertionError('Unexpected temporary cleanup target')
        self.temp.cleanup()

    def call(self, *args, fail=False):
        result = subprocess.run(self.command + list(args), text=True, capture_output=True, encoding='utf-8', env=self.env)
        if fail:
            self.assertNotEqual(result.returncode, 0, result.stdout)
            return result.stderr
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_concurrent_claim_return_and_followup(self):
        self.call('init')
        task = self.call('send', '--worker', 'worker-1', '--scope', 'src/core', '--task', '입력 2와 3을 계산하고 실제 결과를 보고')
        processes = [subprocess.Popen(self.command + ['wait', '--worker', 'worker-1', '--seconds', '1'], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding='utf-8', env=self.env) for _ in range(2)]
        replies = []
        for process in processes:
            output, error = process.communicate(timeout=10)
            self.assertEqual(process.returncode, 0, error)
            replies.append(json.loads(output))
        claimed = [reply for reply in replies if reply.get('id') == task['id']]
        self.assertEqual(len(claimed), 1, replies)
        self.assertTrue(any(reply.get('busy') for reply in replies), replies)
        claim = claimed[0]
        self.assertEqual([item['worker'] for item in self.call('workers')], ['worker-1'])
        self.call('send', '--worker', 'worker-2', '--scope', 'src/core/file.py', '--task', 'conflict', fail=True)
        self.call('finish', '--id', task['id'], '--token', 'incorrect', '--result', 'wrong', fail=True)
        self.call('finish', '--id', task['id'], '--token', claim['token'], '--result', '2 + 3 = 5; scope src/core')
        status = self.call('status')
        self.assertEqual(status[0]['status'], 'done')
        self.assertEqual(status[0]['result'], '2 + 3 = 5; scope src/core')
        self.call('send', '--worker', 'worker-2', '--scope', 'src/core', '--task', 'followup')
        self.assertTrue(self.call('stop')['stopped'])
        self.assertTrue(self.call('wait', '--worker', 'worker-2', '--seconds', '1')['stopped'])

    def test_cancel_stale_report_and_input_files(self):
        self.call('init')
        task_file = self.project / 'task.txt'
        task_file.write_text("여러 줄\n따옴표 ' 와 단위 확인", encoding='utf-8')
        task = self.call('send', '--worker', 'worker-3', '--scope', 'analysis/out.json', '--task-file', str(task_file))
        claim = self.call('wait', '--worker', 'worker-3', '--seconds', '1')
        self.assertEqual(claim['task'], task_file.read_text(encoding='utf-8'))
        self.call('cancel', '--id', task['id'], '--reason', 'worker stopped')
        self.call('finish', '--id', task['id'], '--token', claim['token'], '--result', 'late', fail=True)
        self.call('send', '--worker', 'worker-4', '--scope', 'analysis/out.json', '--task', 'retry')
        for scope in ('../outside', '/absolute', 'src/*', '.'):
            self.call('send', '--worker', 'worker-5', '--scope', scope, '--task', 'invalid', fail=True)


if __name__ == '__main__':
    unittest.main()
