import asyncio
import hashlib
import json
import socket
import sys
import subprocess
from pathlib import Path

import pytest
from backend import atomic_probe
from backend.model_paths import checked_path
from backend.atomic_mcp import catalog
from backend.agent_errors import AgentError
from test_unified_mcp import fixture_app

atomic_probe.checked_path = checked_path


def test_file_probes_content_tail_hash_usage_and_protection(tmp_path):
    (tmp_path/'a.txt').write_text('first\nneedle\nlast\n',encoding='utf-8')
    (tmp_path/'b.txt').write_text('needle again\n',encoding='utf-8')
    (tmp_path/'.env').write_text('needle secret',encoding='utf-8')
    args=dict(path=str(tmp_path),query='needle',regex=False,recursive=True,file_pattern='*',offset=0,page_size=1)
    first=atomic_probe.atomic_probe('search_file_contents',args)
    assert first['has_more'] and first['items'][0]['line']==2
    second=atomic_probe.atomic_probe('search_file_contents',dict(args,offset=first['next_offset']))
    assert second['items'][0]['path'].endswith('b.txt')
    assert not second['has_more'] and second['skipped']>=1
    tail=atomic_probe.atomic_probe('tail_server_file',dict(path=str(tmp_path/'a.txt'),lines=1))
    assert tail['content']=='last'
    hashed=atomic_probe.atomic_probe('hash_server_file',dict(path=str(tmp_path/'a.txt'),algorithm='sha256'))
    assert hashed['digest']==hashlib.sha256((tmp_path/'a.txt').read_bytes()).hexdigest()
    usage=atomic_probe.atomic_probe('get_directory_usage',dict(path=str(tmp_path),depth=1,offset=0,page_size=100))
    assert usage['total_bytes']==(tmp_path/'a.txt').stat().st_size+(tmp_path/'b.txt').stat().st_size
    assert usage['skipped']==1
    for name,extra in [('tail_server_file',dict(lines=1)),('hash_server_file',dict(algorithm='sha256'))]:
        with pytest.raises(ValueError):atomic_probe.atomic_probe(name,dict(path=str(tmp_path/'.env'),**extra))


def test_tcp_probe_real_socket():
    with socket.socket() as listener:
        listener.bind(('127.0.0.1',0));listener.listen()
        args=dict(address='127.0.0.1',port=listener.getsockname()[1],timeout_seconds=1)
        assert atomic_probe.atomic_probe('test_tcp_connection',args)['connected']
    assert not atomic_probe.atomic_probe('test_tcp_connection',args)['connected']


def test_shared_catalog_scope_schema_and_actual_remote_script(tmp_path):
    async def run():
        app=fixture_app(tmp_path/'app');service=app.state.mcp_service.scoped({}, {'a'})
        assert set(catalog()) <= service.catalog().keys()
        removed = {'list_automations', 'create_automation', 'update_automation', 'run_automation',
                   'cancel_automation', 'set_automation_enabled', 'list_automation_runs'}
        assert removed.isdisjoint(service.catalog())
        assert not hasattr(app.state, 'automation')
        assert not any(route.path.startswith('/api/automations') for route in app.routes)
        for name in removed:
            with pytest.raises(AgentError, match='INVALID_ARGUMENT'):
                await service.call(name, {})
        examples={
            'get_ssh_config':{},'test_tcp_connection':dict(port=22),'test_ssh_authentication':{},
            'list_command_jobs':{},'search_file_contents':dict(path='/tmp',query='x'),
            'tail_server_file':dict(path='/tmp/a'),'hash_server_file':dict(path='/tmp/a'),
            'get_directory_usage':dict(path='/tmp'),'get_systemd_unit_status':dict(unit='test.service'),
            'read_systemd_journal':dict(unit='test.service'),
            'save_terminal_snippet':dict(name='x',command='ls'),'delete_terminal_snippet':dict(snippet_id='x')}
        for name,example in examples.items():
            with pytest.raises(AgentError,match='HOST_NOT_FOUND|INVALID_ARGUMENT'):
                await service.call(name,dict(host_id='b',**example))
        with pytest.raises(AgentError):await service.call('get_systemd_unit_status',dict(host_id='a',unit='--bad; command'))
        target=tmp_path/'plain.txt';target.write_text('alpha\nbeta\n')
        calls=[]
        async def remote(host,command,source):
            calls.append(host['id'])
            done=await asyncio.to_thread(subprocess.run,[sys.executable,'-'],input=source,text=True,encoding="utf-8",capture_output=True)
            assert done.returncode == 0, done.stderr
            return done.returncode,done.stdout,done.stderr
        app.state.ssh.run=remote
        # A POSIX-style path is required in the catalog; execute the composed
        # source against a local fixture by replacing only its test path.
        async def remote_fixture(host,command,source):
            source=source.replace("'/fixture.txt'",repr(str(target)))
            return await remote(host,command,source)
        app.state.ssh.run=remote_fixture
        result=await service.call('tail_server_file',dict(host_id='a',path='/fixture.txt',lines=1))
        assert result['data']['content']=='beta' and calls==['a']
        app.state.agent_chat.store.db.close()
    asyncio.run(run())


def test_config_and_snippets_use_bound_host(tmp_path):
    async def run():
        app=fixture_app(tmp_path);service=app.state.mcp_service.scoped({}, {'a'})
        async def effective(host):return dict(hostname='example',user='user',port='22',proxycommand='secret command')
        app.state.ssh.effective=effective;app.state.ssh.effective_details=effective
        async with app.state.agent_chat.tools.session({}, {'a'}) as session:
            tools={item.name for item in (await session.list_tools()).tools}
            assert set(catalog()) <= tools
            through_sdk=await session.call_tool('get_ssh_config',dict(host_id='a'))
            assert not through_sdk.is_error and through_sdk.structured_content['data']['hostname']=='example'
            blocked=await session.call_tool('get_ssh_config',dict(host_id='b'))
            assert blocked.is_error
        result=await service.call('get_ssh_config',dict(host_id='a'))
        assert result['data']['has_proxy_command'] and 'secret command' not in str(result)
        saved=await service.call('save_terminal_snippet',dict(host_id='a',name='List',command='ls'))
        item=saved['data'][0]
        updated=await service.call('save_terminal_snippet',dict(host_id='a',snippet_id=item['id'],name='List all',command='ls -a'))
        assert updated['data'][0]['command']=='ls -a'
        deleted=await service.call('delete_terminal_snippet',dict(host_id='a',snippet_id=item['id']))
        assert deleted['data']==[]
        app.state.agent_chat.store.db.close()
    asyncio.run(run())



def test_authentication_is_independent_and_does_not_provision(tmp_path):
    async def run():
        app=fixture_app(tmp_path);service=app.state.mcp_service.scoped({}, {'a'})
        calls=[]
        async def command(argv,source=None,timeout=15):
            calls.append(argv);return 255,'','permission denied password=hidden'
        app.state.ssh.command=command
        result=await service.call('test_ssh_authentication',dict(host_id='a'))
        assert not result['data']['authenticated'] and 'hidden' not in str(result)
        assert 'PreferredAuthentications=publickey' in calls[0]
        assert not app.state.ssh.sessions
        config=dict(hostname='node-a',user='fixture',port='22')
        async def effective(host):return config
        async def credential(host):return dict(hostname='node-a',user='fixture',port=22,password='fixture-secret')
        class Connection:
            def close(self):pass
            async def wait_closed(self):pass
        async def password_connection(host,password):
            assert host['_import_identity'] and password=='fixture-secret'
            return Connection()
        app.state.ssh.effective=effective
        app.state.ssh_passwords.get=credential
        app.state.ssh.password_connection=password_connection
        result=await service.call('test_ssh_authentication',dict(host_id='a',method='saved_password'))
        assert result['data']['authenticated'] and 'fixture-secret' not in str(result)
        app.state.agent_chat.store.db.close()
    asyncio.run(run())


def test_linux_probe_scripts_jobs_symlinks_and_journal_pagination():
    import shutil
    if not shutil.which('wsl.exe'):
        pytest.skip('WSL integration test requires Windows with WSL')
    source='\n'.join(Path('backend',name).read_text(encoding='utf-8') for name in ('model_paths.py','command_probe.py','atomic_probe.py'))
    harness=r'''
import tempfile,uuid,shutil
with tempfile.TemporaryDirectory(prefix='iwb-atomic-test-') as root:
    root=Path(root)
    (root/'visible.txt').write_text('hello\nneedle\n')
    (root/'.env').write_text('needle secret')
    (root/'link.txt').symlink_to(root/'.env')
    result=atomic_probe('search_file_contents',dict(path=str(root),query='needle',regex=False,recursive=True,file_pattern='*',offset=0,page_size=10))
    assert len(result['items'])==1 and result['skipped']==2,result
    key=uuid.uuid4().hex; folder=job_folder(key,create=True)
    try:
        write_state(folder,dict(status='completed',exit_code=0,started_at=1))
        result=atomic_probe('list_command_jobs',dict(offset=0,page_size=1000,status='completed'))
        assert any(row['job_id']==key for row in result['items']),result
    finally:
        assert folder.name==key and folder.parent==Path('/tmp')/('iwb-command-'+str(os.geteuid()))
        shutil.rmtree(folder)
    binary=root/'journalctl'
    binary.write_text('#!/usr/bin/env python3\nimport json,sys\nstart=0\nfor arg in sys.argv[1:]:\n if arg.startswith("--after-cursor="): start=int(arg.split("=",1)[1])+1\nfor i in range(start,5): print(json.dumps({"__CURSOR":str(i),"MESSAGE":"line-"+str(i)}))\n')
    binary.chmod(0o700);os.environ['PATH']=str(root)+':'+os.environ['PATH']
    args=dict(unit='fixture.service',lines=2,cursor='0',since=None)
    first=atomic_probe('read_systemd_journal',args)
    assert [r['MESSAGE'] for r in first['items']]==['line-1','line-2'],first
    second=atomic_probe('read_systemd_journal',dict(args,cursor=first['next_cursor']))
    assert [r['MESSAGE'] for r in second['items']]==['line-3','line-4'],second
    binary.write_text('#!/usr/bin/env python3\nimport json\nprint(json.dumps({"__CURSOR":"large","MESSAGE":"x"*100000}))\n')
    binary.chmod(0o700)
    large=atomic_probe('read_systemd_journal',dict(args,cursor='previous'))
    assert large['next_cursor']=='large' and large['items'][0]['message_truncated'],large
    binary=root/'systemctl'
    binary.write_text('#!/usr/bin/env python3\nprint("ActiveState=active\\nMainPID=123\\nExecMainStatus=0")\n')
    binary.chmod(0o700)
    status=atomic_probe('get_systemd_unit_status',dict(unit='fixture.service'))
    assert status['properties']['MainPID']=='123',status
print('linux probes verified')
'''
    done=subprocess.run(['wsl.exe','-e','python3','-'],input=(source+'\n'+harness).encode('utf-8'),capture_output=True,timeout=60)
    assert done.returncode==0,done.stderr.decode('utf-8','replace')
    assert b'linux probes verified' in done.stdout


def test_content_search_never_emits_multiline_private_keys(tmp_path):
    (tmp_path/'backup.txt').write_text('safe\n-----BEGIN OPENSSH PRIVATE KEY-----\nprivate-body\n-----END OPENSSH PRIVATE KEY-----\nafter\n')
    args=dict(path=str(tmp_path),query='.*',regex=True,recursive=True,file_pattern='*',offset=0,page_size=1)
    first=atomic_probe.atomic_probe('search_file_contents',args)
    second=atomic_probe.atomic_probe('search_file_contents',dict(args,offset=1))
    assert first['items'][0]['text']=='safe'
    assert second['items'][0]['text']=='after'
    assert 'private-body' not in str(first)+str(second)
    tail=atomic_probe.atomic_probe('tail_server_file',dict(path=str(tmp_path/'backup.txt'),lines=10))
    assert 'private-body' not in tail['content']
