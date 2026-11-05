import asyncio
import json
from pathlib import Path
from backend.probe_cache import ProbeCache


def test_cache_miss_uploads_once_and_fast_poll_omits_slow_request():
    class SSH:
        def __init__(self): self.calls=[]
        async def run(self, host, command, source=None):
            self.calls.append((command,source))
            if len(self.calls)==1: return 73,'Welcome to server\nIWB_CACHE_MISS\n',''
            slow = "True" in command
            raw={'tmux': {'items': []}, 'users': {'out':'1 root'}} if slow else {}
            return 0,'IWB_JSON:'+json.dumps(raw),''
    async def scenario():
        ssh=SSH(); cache=ProbeCache('print("hello")',clock=lambda:0)
        await cache.run(ssh,{'id':'a'})
        await cache.run(ssh,{'id':'a'})
        assert [source for _,source in ssh.calls] == [None,'print("hello")',None]
        assert cache.slow['a']['data']['tmux']=={'items':[]}
        assert len(ssh.calls[2][0]) < 5000
    asyncio.run(scenario())


def test_key_monitor_session_is_shared_between_concurrent_collectors(tmp_path):
    from backend.ssh import SSHService
    class Connection:
        def is_closed(self): return False
    async def scenario():
        service=SSHService(tmp_path); calls=[]; connection=Connection()
        async def connect(host,password,key_only=False, monitor=False):
            calls.append(host);await asyncio.sleep(0);return connection
        async def effective(host): return {}
        service.effective=effective
        service.password_connection=connect
        await asyncio.gather(*(service.ensure_monitor_session({'id':'a'}) for _ in range(3)))
        assert len(calls)==1
        assert service.sessions['a'] is connection
    asyncio.run(scenario())

def test_slow_fields_expire_and_do_not_cross_host_identity():
    class SSH:
        def __init__(self): self.slow=[]
        async def run(self, host, command, source=None):
            self.slow.append(' True ' in command)
            raw={'tmux': {'items': []}, 'users': {'out':'1 old-user'}} if self.slow[-1] else {}
            return 0,'IWB_JSON:'+json.dumps(raw),''
    async def scenario():
        now=[0];ssh=SSH();cache=ProbeCache('pass',clock=lambda:now[0])
        host={'id':'a','target':'first'}
        await cache.run(ssh,host)
        raw=json.loads((await cache.run(ssh,host))[1].split('IWB_JSON:')[1])
        assert raw['users']['out']==''
        now[0]=60
        await cache.run(ssh,host)
        await cache.run(ssh,dict(host,target='second'))
        assert ssh.slow==[True,False,True,True]
    asyncio.run(scenario())


def test_read_only_cache_falls_back_to_in_memory_probe():
    class SSH:
        def __init__(self): self.calls=[]
        async def run(self,host,command,source=None):
            self.calls.append((command,source))
            return (0,'IWB_JSON:{}','') if command.startswith('python3 - #') else (73,'IWB_CACHE_MISS','')
    async def scenario():
        ssh=SSH();result=await ProbeCache('pass').run(ssh,{'id':'a'})
        assert result[0]==0
        assert len(ssh.calls)==3
        assert ssh.calls[-1][1]=='pass'
    asyncio.run(scenario())


def test_monitor_failure_uses_cooldown_for_native_fallback(tmp_path):
    from backend.ssh import SSHService
    async def scenario():
        service=SSHService(tmp_path);calls=[]
        async def connect(*args,**kwargs):
            calls.append(1);raise OSError('unsupported agent')
        service.password_connection=connect
        await service.ensure_monitor_session({'id':'a'})
        await service.ensure_monitor_session({'id':'a'})
        assert calls==[1]
        assert service.sessions=={}
    asyncio.run(scenario())

def test_real_key_ssh_connection_is_reused(tmp_path):
    import asyncssh
    from backend.ssh import SSHService
    async def scenario():
        client_key=asyncssh.generate_private_key('ssh-ed25519')
        server_key=asyncssh.generate_private_key('ssh-ed25519')
        key_path=tmp_path/'id_ed25519'
        key_path.write_bytes(client_key.export_private_key())
        accepted=[]
        class Server(asyncssh.SSHServer):
            def connection_made(self,conn): accepted.append(conn)
            def begin_auth(self,username): return True
            def public_key_auth_supported(self): return True
            def validate_public_key(self,username,key): return key==client_key.convert_to_public()
        async def process(proc):
            proc.stdout.write('probe ok')
            proc.exit(0)
        listener=await asyncssh.create_server(Server,'127.0.0.1',0,server_host_keys=[server_key],process_factory=process)
        port=listener.get_port()
        known=tmp_path/'known_hosts'
        known.write_text('[127.0.0.1]:'+str(port)+' '+server_key.export_public_key().decode())
        service=SSHService(tmp_path,known_hosts=known)
        cfg=dict(hostname='127.0.0.1',user='test',port=str(port),identityfile=[str(key_path)],identitiesonly='yes')
        async def effective(host): return cfg
        service.effective=service.effective_details=effective
        try:
            host={'id':'a','target':'local','key_path':str(key_path)}
            for _ in range(2):
                assert await service.run(host,'echo probe # IWB_MONITOR')==(0,'probe ok','')
            assert len(accepted)==1
            assert 'a' in service.monitor_sessions
        finally:
            await service.close()
            listener.close()
            await listener.wait_closed()
    asyncio.run(scenario())

def test_monitor_honors_disabled_agent(tmp_path, monkeypatch):
    import asyncssh
    from backend.ssh import SSHService
    class Connection: pass
    async def scenario():
        service=SSHService(tmp_path)
        async def effective(host):
            return dict(hostname='example',user='user',port='22',identityagent='none',identityfile=['none'])
        async def connect(**options):
            assert options['agent_path'] is None
            assert options['client_keys']==[]
            assert options['preferred_auth']==['publickey']
            assert options['keepalive_interval']==60
            return Connection()
        service.effective_details=effective
        monkeypatch.setattr(asyncssh,'connect',connect)
        await service.password_connection({'id':'a'},None,monitor=True)
    asyncio.run(scenario())


def test_probe_payload_statistics_and_safe_detail_reuse():
    class SSH:
        def __init__(self): self.pid_start='100'; self.boot='fixture-boot'; self.calls=[]
        async def run(self,host,command,source=None):
            slow=' True ' in command
            detail=dict(identity_verified=True,start_ticks=self.pid_start,command='python train.py' if slow else None,
                        cwd='/synthetic' if slow else None,details_collected_at=123 if slow else None)
            out='IWB_JSON:'+json.dumps({'boot_id':self.boot,'process_details':{'42':detail}},ensure_ascii=False)
            self.calls.append((command,source,out))
            return 0,out,'中文'
    async def scenario():
        ssh=SSH();cache=ProbeCache('pass',clock=lambda:0);host={'id':'a','target':'first'}
        await cache.run(ssh,host)
        code,out,err=await cache.run(ssh,host)
        detail=json.loads(out.split('IWB_JSON:')[1])['process_details']['42']
        assert detail['command']=='python train.py' and detail['details_collected_at']==123
        command,source,wire_out=ssh.calls[-1]
        assert cache.stats['a']==dict(request_bytes=len(command.encode()),response_bytes=len(wire_out.encode())+len('中文'.encode()),commands=1)
        ssh.pid_start='200'
        out=(await cache.run(ssh,host))[1]
        assert json.loads(out.split('IWB_JSON:')[1])['process_details']['42']['command'] is None
        out=(await cache.run(ssh,host,force_slow=True))[1]
        assert json.loads(out.split('IWB_JSON:')[1])['process_details']['42']['command']=='python train.py'
        ssh.boot='rebooted'
        out=(await cache.run(ssh,host))[1]
        assert json.loads(out.split('IWB_JSON:')[1])['process_details']['42']['command'] is None
        out=(await cache.run(ssh,dict(host,target='second')))[1]
        assert ' True ' in ssh.calls[-1][0]
    asyncio.run(scenario())
