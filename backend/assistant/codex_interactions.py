"""Run-bound native Codex approvals and blocking questions, without transport waits."""
import asyncio
import copy
import json
import time
import uuid

from .chat_tools import scrub


APPROVALS = {
    'item/commandExecution/requestApproval': 'codex_command',
    'item/fileChange/requestApproval': 'codex_file',
    'item/permissions/requestApproval': 'codex_permissions',
}


class CodexInteractions:
    def __init__(self, turn, save, run_id, mode, sanitize=None):
        self.turn, self.save, self.run_id, self.mode = turn, save, run_id, mode
        self.sanitize = sanitize or (lambda value: json.loads(scrub(value)))
        self.pending = {}
        self.closed = False

    async def handle(self, message):
        method, params = message['method'], copy.deepcopy(message.get('params', {}))
        question = method == 'item/tool/requestUserInput'
        if not question and method not in APPROVALS:
            raise ValueError('Unsupported Codex request')
        if self.closed:
            raise asyncio.CancelledError()
        permissions = method == 'item/permissions/requestApproval'

        def result(accepted):
            if permissions:
                # Grant exactly the requested permissions for this turn, never persistent rules.
                return {'permissions': params.get('permissions', {}) if accepted else {}, 'scope': 'turn'}
            return {'decision': 'accept' if accepted else 'decline'}

        if not question and self.mode in ('read_only', 'full'):
            accepted = self.mode == 'full'
            self.turn.setdefault('approvals', []).append(dict(
                id=uuid.uuid4().hex, run_id=self.run_id, tool=APPROVALS[method],
                arguments=self.sanitize(params), status='approved' if accepted else 'rejected',
                reason='原生权限策略 / Native permission policy', created=time.time(),
                decision='approve' if accepted else 'reject', can_session=False))
            self.save()
            return result(accepted)
        if len(json.dumps(params, ensure_ascii=False)) > 65536:
            raise ValueError('Codex request exceeds review limit; operation was not approved')
        record = dict(id=uuid.uuid4().hex, run_id=self.run_id, status='pending', created=time.time(),
                      thread_id=params.get('threadId'), turn_id=params.get('turnId'), item_id=params.get('itemId'))
        if question:
            questions = params.get('questions', [])
            ids = [q.get('id') for q in questions]
            if not ids or any(not isinstance(q, str) or not q for q in ids) or len(set(ids)) != len(ids):
                raise ValueError('Codex question IDs are missing or duplicated')
            record['questions'] = self.sanitize(questions)
            self.turn.setdefault('codex_questions', []).append(record)
        else:
            # File-change requests often contain only itemId: attach the already received diff.
            if method == 'item/fileChange/requestApproval':
                item = None
                for _ in range(100):
                    item = next((i for i in self.turn.get('codex_items', [])
                                 if i.get('id') == params.get('itemId') and i.get('thread_id') == params.get('threadId')), None)
                    if item and item.get('data'):break
                    if self.closed:raise asyncio.CancelledError()
                    await asyncio.sleep(.01)
                if item and item.get('data'):
                    params['file_changes'] = item.get('data', {})
                    if item.get('output_truncated'):
                        raise ValueError('File diff exceeds review limit; operation was not approved')
                else:
                    raise ValueError('File diff is unavailable; operation was not approved')
            record.update(tool=APPROVALS[method], arguments=self.sanitize(params),
                          target='Codex · 本机 / Local', can_session=False,
                          reason=params.get('reason') or 'Codex 请求本机操作批准 / Codex requests local approval')
            self.turn.setdefault('approvals', []).append(record)
        future = asyncio.get_running_loop().create_future()
        self.pending[record['id']] = (record, future, question, params)
        self.save()
        try:
            answer = await asyncio.wait_for(future, 1800)
            return {'answers': answer} if question else result(answer == 'approve')
        finally:
            self.pending.pop(record['id'], None)
            if record['status'] == 'pending':
                record['status'] = 'cancelled'
                self.save()

    def _request(self, request_id, run_id, question):
        item = self.pending.get(request_id)
        if self.closed or run_id != self.run_id or not item or item[2] != question:
            raise ValueError('此 Codex 请求已失效 / This Codex request is no longer active')
        record, future, _, params = item
        if future.done() or record['status'] != 'pending':
            raise ValueError('此 Codex 请求已处理 / This Codex request was already handled')
        return record, future, params

    def decide(self, request_id, run_id, decision):
        record, future, _ = self._request(request_id, run_id, False)
        if decision not in ('approve', 'reject'):
            raise ValueError('原生请求仅支持允许一次或拒绝 / Native requests support allow once or reject')
        record.update(status='approved' if decision == 'approve' else 'rejected', decision=decision, decided=time.time())
        future.set_result(decision)
        self.save()

    def answer(self, request_id, run_id, answers):
        record, future, params = self._request(request_id, run_id, True)
        ids = {q['id'] for q in params['questions']}
        if not isinstance(answers, dict) or set(answers) != ids:
            raise ValueError('请回答本次请求的全部问题 / Answer all questions in this request')
        for answer in answers.values():
            if not isinstance(answer, dict) or set(answer) != {'answers'}:
                raise ValueError('回答格式无效 / Invalid answer format')
            values = answer['answers']
            if not isinstance(values, list) or not 1 <= len(values) <= 20 or any(
                    not isinstance(v, str) or not v.strip() or len(v) > 12000 for v in values):
                raise ValueError('回答为空或过长 / Answer is empty or too long')
        if len(json.dumps(answers)) > 64000:
            raise ValueError('回答过长 / Answers exceed the limit')
        # Secrets are sent only over the live protocol, never saved to chat records.
        record.update(status='answered', decided=time.time())
        future.set_result(copy.deepcopy(answers))
        self.save()

    def close(self):
        self.closed = True
        for record, future, _, _ in self.pending.values():
            if record['status'] == 'pending': record['status'] = 'cancelled'
            if not future.done(): future.cancel()
        self.save()
