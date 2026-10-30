import json
import subprocess
import sys
import asyncio
from pathlib import Path
from httpx import ASGITransport,AsyncClient

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from backend.app import create_app


class LocalClient:
    """In-process ASGI requests; no listener, background thread or external SSH."""
    def __init__(self,app): self.app=app
    def __enter__(self): return self
    def __exit__(self,*args): pass
    def request(self,method,path,**kwargs):
        async def send():
            async with AsyncClient(transport=ASGITransport(app=self.app),base_url='http://testserver') as client:
                return await client.request(method,path,**kwargs)
        return asyncio.run(send())
    def post(self,path,**kwargs): return self.request('POST',path,**kwargs)
    def get(self,path,**kwargs): return self.request('GET',path,**kwargs)
    def delete(self,path,**kwargs): return self.request('DELETE',path,**kwargs)


def test_cross_host_log_read_compare_save_and_path_is_stdin_only(tmp_path):
    app=create_app(tmp_path,start_poll=False)
    app.state.hosts.extend([dict(id='gpu',target='GPU'),dict(id='npu',target='NPU')])
    first=tmp_path/'gpu ; $(echo hacked) 日志.log'
    second=tmp_path/'npu.log'
    for path,values in ((first,[2,4]),(second,[3,2])):
        path.write_text('header\n'+''.join(json.dumps(dict(iteration=f'{i}/300',loss=v,grad_norm=2*v))+'\n' for i,v in enumerate(values,1)),encoding='utf-8')
    calls=[]
    async def run(host,command,source=None):
        calls.append((host['id'],command,source))
        assert command=='python3 -' and 'sudo' not in command
        done=subprocess.run([sys.executable,'-B','-X','utf8','-c',source],capture_output=True,text=True,encoding='utf-8',timeout=10)
        return done.returncode,done.stdout,done.stderr
    app.state.ssh.run=run
    headers={'X-IWB':'1'}
    with LocalClient(app) as client:
        assert client.post('/api/logs/read',json=dict(host_id='gpu',path=str(first))).status_code==403
        a=client.post('/api/logs/read',headers=headers,json=dict(host_id='gpu',path=str(first))).json()
        b=client.post('/api/logs/read',headers=headers,json=dict(host_id='npu',path=str(second))).json()
        assert 'groups' in a,a
        assert a['groups'][0]['count']==2 and b['groups'][0]['count']==2
        assert [c[0] for c in calls]==['gpu','npu']
        result=client.post('/api/logs/compare',headers=headers,json=dict(baseline=a['id'],candidate=b['id'],metrics=['loss','grad_norm']))
        assert result.status_code==200 and result.json()['metrics'][0]['mae']==1.5
        detail=client.get('/api/logs/'+a['id']+'/record',params=dict(group=a['groups'][0]['key'],line=2)).json()
        assert detail['step']==1 and '"loss": 2' in detail['source']
        saved=client.post('/api/logs/configs',headers=headers,json=dict(name='GPU/NPU 精度',baseline=dict(host_id='gpu',path=str(first)),candidate=dict(host_id='npu',path=str(second)),metrics=['loss'])).json()
        assert saved['id'] and client.get('/api/logs/configs').json()[0]['name']=='GPU/NPU 精度'
        assert client.post('/api/logs/compare',headers=headers,json=dict(baseline='expired',candidate=b['id'],metrics=['loss'])).status_code==410
        missing=client.post('/api/logs/read',headers=headers,json=dict(host_id='gpu',path=str(tmp_path/'missing')))
        assert missing.status_code==400 and '找不到' in missing.json()['detail']
        assert client.post('/api/logs/read',headers=headers,json=dict(host_id='gpu',path='a\nb')).status_code==422
        assert client.delete('/api/logs/configs/'+saved['id'],headers=headers).status_code==200
        assert client.get('/api/logs/configs').json()==[]


def test_remote_directory_browser_and_saved_configuration_survive_app_restart(tmp_path):
    app=create_app(tmp_path,start_poll=False)
    app.state.hosts.append(dict(id='gpu',target='GPU'))
    async def run(host,command,source=None):
        done=subprocess.run([sys.executable,'-B','-X','utf8','-c',source],capture_output=True,text=True,encoding='utf-8',timeout=10)
        return done.returncode,done.stdout,done.stderr
    app.state.ssh.run=run
    (tmp_path/'log with spaces.jsonl').write_text('{"iteration":1,"loss":2}\n')
    headers={'X-IWB':'1'}
    location=dict(host_id='gpu',path=str(tmp_path))
    with LocalClient(app) as client:
        response=client.post('/api/logs/browse',headers=headers,json=location)
        assert response.status_code==200 and any(e['name']=='log with spaces.jsonl' for e in response.json()['entries'])
        saved=client.post('/api/logs/configs',headers=headers,json=dict(name='Persistent config',baseline=location,candidate=location)).json()
        assert saved['id']
        assert client.post('/api/logs/configs',headers=headers,json=dict(name='bad',baseline=location,candidate=location,start=2,end=1)).status_code==422
    restarted=create_app(tmp_path,start_poll=False)
    with LocalClient(restarted) as client:
        assert client.get('/api/logs/configs').json()[0]['id']==saved['id']


def test_native_ssh_reads_and_compares_controlled_remote_logs(tmp_path):
    import asyncssh
    async def scenario():
        first=tmp_path/'first.jsonl';second=tmp_path/'second.jsonl'
        first.write_text('{"iteration":"1/300","loss":2,"grad_norm":4}\n')
        second.write_text('{"iteration":"1/300","loss":3,"grad_norm":6}\n')
        class Server(asyncssh.SSHServer):
            def begin_auth(self,username): return False
        async def process(proc):
            assert proc.command=='python3 -'
            source=await proc.stdin.read()
            done=subprocess.run([sys.executable,'-B','-X','utf8','-c',source],capture_output=True,text=True,encoding='utf-8',timeout=10)
            proc.stdout.write(done.stdout);proc.stderr.write(done.stderr);proc.exit(done.returncode)
        key=asyncssh.generate_private_key('ssh-ed25519')
        listener=await asyncssh.create_server(Server,'127.0.0.1',0,server_host_keys=[key],process_factory=process)
        known=tmp_path/'known_hosts'
        known.write_text(f'[127.0.0.1]:{listener.get_port()} '+key.export_public_key().decode())
        app=create_app(tmp_path/'data',start_poll=False)
        app.state.ssh.custom_known_hosts=True;app.state.ssh.known_hosts=known
        app.state.hosts.append(dict(id='controlled',target='127.0.0.1',user='test',port=listener.get_port(),manual=True,auth='key'))
        try:
            async with AsyncClient(transport=ASGITransport(app=app),base_url='http://testserver',headers={'X-IWB':'1'}) as client:
                a=await client.post('/api/logs/read',json=dict(host_id='controlled',path=str(first)))
                b=await client.post('/api/logs/read',json=dict(host_id='controlled',path=str(second)))
                assert a.status_code==b.status_code==200,(a.text,b.text)
                result=await client.post('/api/logs/compare',json=dict(baseline=a.json()['id'],candidate=b.json()['id'],metrics=['loss','grad_norm']))
                assert result.status_code==200,result.text
                assert [m['mae'] for m in result.json()['metrics']]==[1,2]
        finally:
            await app.state.ssh.close();listener.close();await listener.wait_closed()
    asyncio.run(scenario())


def test_demo_is_labelled_and_evicted_snapshots_require_reread(tmp_path):
    app=create_app(tmp_path,start_poll=False)
    headers={'X-IWB':'1'}
    with LocalClient(app) as client:
        first=client.post('/api/logs/demo',headers=headers).json()
        assert first['baseline']['demo'] is True
        for _ in range(4): latest=client.post('/api/logs/demo',headers=headers).json()
        body=dict(baseline=first['baseline']['id'],candidate=first['candidate']['id'])
        assert client.post('/api/logs/compare',headers=headers,json=body).status_code==410
        body=dict(baseline=latest['baseline']['id'],candidate=latest['candidate']['id'])
        result=client.post('/api/logs/compare',headers=headers,json=body).json()
        assert abs(result['metrics'][0]['mae']-.006)<1e-12
