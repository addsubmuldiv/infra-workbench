import asyncio

import pytest

from backend.codex_interactions import CodexInteractions


def test_idle_watchdog_waits_for_human_review_but_keeps_model_timeout():
    from backend.codex_host import next_native_event
    async def scenario():
        queue=asyncio.Queue()
        broker=CodexInteractions({},lambda:None,'run','ask')
        broker.pending['review']=object()
        task=asyncio.create_task(next_native_event(queue,broker,idle_timeout=.01))
        await asyncio.sleep(.04)
        assert not task.done()
        await queue.put({'method':'accepted'})
        assert await task=={'method':'accepted'}
        broker.pending.clear()
        with pytest.raises(TimeoutError):await next_native_event(queue,broker,idle_timeout=.01)
    asyncio.run(scenario())


def test_codex_options_reject_relative_cwd_and_unknown_fields(tmp_path):
    from backend.agent_chat import ChatMessageRequest
    from pydantic import ValidationError
    request = ChatMessageRequest(content='test', engine='codex', codex_options={'cwd': str(tmp_path), 'multi_agent': True})
    assert request.codex_options.cwd == str(tmp_path.resolve())
    for options in ({'cwd': 'relative'}, {'cwd': str(tmp_path), 'unsafe': True}, {'effort': 'invented'}):
        with pytest.raises(ValidationError): ChatMessageRequest(content='test', codex_options=options)


def test_scrub_long_native_output_is_bounded_and_still_redacts_assignments():
    import subprocess
    import sys
    # Separate process gives the test a hard bound if the regex becomes quadratic.
    code = "from backend.chat_tools import scrub; value=scrub('x'*1048576+'\\napi_key=private-value'); assert 'private-value' not in value; assert value.startswith('x'*100)"
    subprocess.run([sys.executable, '-c', code], check=True, timeout=8)


def test_discovery_exposes_only_sanitized_metadata(tmp_path, monkeypatch):
    from backend.codex_discovery import discover_codex
    import backend.codex_agent as agent
    seen = []
    class Connection:
        def __init__(self, *args, **kwargs): pass
        async def start(self): pass
        async def close(self): pass
        async def request(self, method, params, **kwargs):
            seen.append(method)
            if method == 'config/read': return {'config': {'mcp_servers': {'project': {'url': 'SECRET-URL', 'http_headers': {'Authorization': 'SECRET-HEADER'}}}}}
            if method == 'model/list': return {'data': [{'id': 'model', 'isDefault': True, 'secret': 'DO-NOT-EXPOSE'}]}
            if method == 'account/read': return {'account': {'type': 'chatgpt', 'email': 'private@example.com'}}
            if method == 'skills/list': return {'data': [{'skills': [{'name': 'skill', 'path': str(tmp_path/'SKILL.md'), 'description': 'help', 'enabled': True}]}]}
            raise ValueError('unsupported')
    monkeypatch.setattr(agent, 'CodexConnection', Connection)
    monkeypatch.setattr(agent, 'resolve_codex', lambda: 'fake')
    result = asyncio.run(discover_codex(str(tmp_path)))
    assert result['models'][0]['id'] == 'model'
    assert result['skills'][0]['name'] == 'skill'
    assert result['account']['status'] == 'chatgpt'
    assert 'DO-NOT-EXPOSE' not in str(result) and 'private@example.com' not in str(result)
    assert result['mcp_servers'][0]['name']=='project'
    assert 'SECRET-URL' not in str(result) and 'SECRET-HEADER' not in str(result)


def test_native_requests_wait_for_bound_answer_and_reject_stale_duplicates():
    async def scenario():
        turn = {'id': 'run'}
        broker = CodexInteractions(turn, lambda: None, 'run', 'ask')
        request = {'id': 7, 'method': 'item/commandExecution/requestApproval',
                   'params': {'threadId': 'root', 'turnId': 't', 'itemId': 'cmd', 'command': 'echo test', 'cwd': '/tmp'}}
        task = asyncio.create_task(broker.handle(request))
        await asyncio.sleep(0)
        approval = turn['approvals'][0]
        assert not task.done()
        with pytest.raises(ValueError): broker.decide(approval['id'], 'old-run', 'approve')
        broker.decide(approval['id'], 'run', 'reject')
        assert await task == {'decision': 'decline'}
        with pytest.raises(ValueError): broker.decide(approval['id'], 'run', 'approve')
        broker.close()
    asyncio.run(scenario())


def test_question_is_blocking_validates_ids_and_does_not_persist_secret_answers():
    async def scenario():
        turn = {'id': 'run'}
        broker = CodexInteractions(turn, lambda: None, 'run', 'ask')
        task = asyncio.create_task(broker.handle({'id': 8, 'method': 'item/tool/requestUserInput', 'params': {
            'threadId': 'root', 'turnId': 't', 'questions': [{'id': 'q', 'question': 'Token?', 'isSecret': True}]}}))
        await asyncio.sleep(0)
        question = turn['codex_questions'][0]
        assert not task.done()
        with pytest.raises(ValueError): broker.answer(question['id'], 'run', {'wrong': {'answers': ['x']}})
        broker.answer(question['id'], 'run', {'q': {'answers': ['private-answer']}})
        assert await task == {'answers': {'q': {'answers': ['private-answer']}}}
        assert 'private-answer' not in str(turn)
        broker.close()
    asyncio.run(scenario())


def test_readonly_denies_native_mutations_full_accepts_and_close_cancels_pending():
    async def scenario():
        msg = {'id': 1, 'method': 'item/fileChange/requestApproval', 'params': {'itemId': 'f'}}
        readonly = CodexInteractions({}, lambda: None, 'r', 'read_only')
        assert await readonly.handle(msg) == {'decision': 'decline'}
        full = CodexInteractions({}, lambda: None, 'r', 'full')
        assert await full.handle(msg) == {'decision': 'accept'}
        turn = {}
        ask = CodexInteractions(turn, lambda: None, 'r', 'ask')
        task = asyncio.create_task(ask.handle({'id':2,'method':'item/commandExecution/requestApproval','params':{'command':'echo test'}}))
        await asyncio.sleep(0)
        ask.close()
        with pytest.raises(asyncio.CancelledError): await task
        assert turn['approvals'][0]['status'] == 'cancelled'
    asyncio.run(scenario())


def test_file_approval_waits_for_diff_and_rejects_missing_or_truncated_patch():
    async def scenario():
        turn = {'codex_items': [{'id':'f','thread_id':'root','data':{'changes':[{'path':'file','diff':'+test'}]}}]}
        broker = CodexInteractions(turn, lambda: None, 'run', 'ask')
        msg = {'id':1,'method':'item/fileChange/requestApproval','params':{'itemId':'f','threadId':'root'}}
        task=asyncio.create_task(broker.handle(msg))
        await asyncio.sleep(0)
        approval=turn['approvals'][0]
        assert approval['arguments']['file_changes']['changes'][0]['diff']=='+test'
        broker.decide(approval['id'],'run','approve')
        assert await task=={'decision':'accept'}
        turn['codex_items'][0]['output_truncated']=True
        with pytest.raises(ValueError,match='review limit'):await broker.handle(msg)
        broker.close()
    asyncio.run(scenario())


def test_native_output_api_requires_run_item_membership_and_delete_cleans_files(tmp_path,monkeypatch):
    from backend.app import create_app
    from backend.codex_host import NativeItems,output_page
    from fastapi.testclient import TestClient
    monkeypatch.setenv('IWB_DATA',str(tmp_path))
    app=create_app(tmp_path,start_poll=False)
    with TestClient(app) as client:
        service=app.state.agent_chat
        chat=service.get(service.create()['id'])
        turn={'id':'run','role':'assistant','content':'done','created':1,'tools':[]}
        chat['turns'].append(turn)
        native=NativeItems(turn,'root',lambda:None,chat_id=chat['id'],run_id='run')
        native.record('item/completed',{'threadId':'root','item':{'id':'command','type':'commandExecution','status':'completed','aggregatedOutput':'x'*40000}})
        service.save(chat)
        url=f"/api/assistant/chats/{chat['id']}/codex-items/command/output"
        result=client.get(url,params={'run_id':'run','thread_id':'root','offset':32000,'limit':8000})
        assert result.status_code==200 and len(result.json()['text'])==8000
        assert result.json()['next_offset'] is None
        assert client.get(url,params={'run_id':'different','thread_id':'root'}).status_code==404
        assert client.get(url,params={'run_id':'run','thread_id':'child'}).status_code==404
        assert client.get(url,params={'run_id':'run','thread_id':'root','offset':-1}).status_code==422
        assert client.delete(f"/api/assistant/chats/{chat['id']}",headers={'X-IWB':'1'}).status_code==200
        with pytest.raises(ValueError):output_page(chat['id'],'run','root','command')


def test_branch_restores_resolved_default_workspace_and_copies_output_pages(tmp_path,monkeypatch):
    from backend.agent_chat import AgentChat
    from backend.store import Store
    from backend.codex_host import NativeItems,output_page
    monkeypatch.setenv('IWB_DATA',str(tmp_path))
    class Provider:config={}
    class Tools:
        def inventory(self,*args):return []
    service=AgentChat(Store(tmp_path/'test.db'),Provider(),Tools())
    chat=service.get(service.create()['id'])
    chat.update(engine='codex',request_scope=None,codex_fingerprint='fingerprint')
    old={'id':'previous-run','role':'assistant','content':'old','created':1,'tools':[]}
    NativeItems(old,'root',lambda:None,chat_id=chat['id'],run_id=old['id']).record('item/completed',{
        'threadId':'root','item':{'id':'cmd','type':'commandExecution','aggregatedOutput':'x'*40000}})
    chat['turns']=[old,{'id':'user','role':'user','content':'branch this','request':{'content':'branch this','codex_options':{'cwd':''}},'model_history_before':[]},
                   {'id':'latest','role':'assistant','content':'done','codex_options':{'cwd':str(tmp_path)}}]
    service.save(chat)
    result=service.branch(chat['id'])
    assert result['draft']['codex_options']['cwd']==str(tmp_path)
    assert output_page(result['chat']['id'],'previous-run','root','cmd',32000)['text']=='x'*8000
