"""Real loopback HTTP + independent SSH clients; exclusively synthetic secrets."""
import asyncio
import json
import os
import socket
import subprocess
import sys
from pathlib import Path
from urllib.request import Request,build_opener,ProxyHandler

import asyncssh
import uvicorn
from backend.app import create_app
from mcp.client import Client


class Vault:
    supported=True
    def __init__(self):self.values={}
    def get(self,key):return self.values.get(key)
    def put(self,key,value):self.values[key]=value
    def delete(self,key):self.values.pop(key,None)


def test_real_mcp_discovery_then_independent_key_and_password_ssh(tmp_path):
    async def scenario():
        secret='SYNTHETIC-ONLY-中文-password';seen=[]
        key=asyncssh.generate_private_key('ssh-ed25519');clientkey=asyncssh.generate_private_key('ssh-ed25519')
        class Server(asyncssh.SSHServer):
            def begin_auth(self,username):return True
            def password_auth_supported(self):return True
            def validate_password(self,username,password):return username=='fixture' and password==secret
            def public_key_auth_supported(self):return True
            def validate_public_key(self,username,key):return key==clientkey.convert_to_public()
        async def process(proc):
            seen.append(proc.command);proc.stdout.write('INDEPENDENT_CLIENT_OK\n');proc.exit(0)
        listener=await asyncssh.create_server(Server,'127.0.0.1',0,server_host_keys=[key],process_factory=process)
        ssh_port=listener.get_port();known=tmp_path/'known_hosts';identity=tmp_path/'identity'
        known.write_bytes(f'[127.0.0.1]:{ssh_port} '.encode()+key.export_public_key())
        identity.write_bytes(clientkey.export_private_key('openssh'))
        if os.name=='nt':
            user=subprocess.check_output(['whoami'],text=True).strip()
            subprocess.run(['icacls',str(identity),'/inheritance:r','/grant:r',user+':F'],check=True,capture_output=True)
        else:identity.chmod(0o600)
        app=create_app(tmp_path/'data',start_poll=False,ssh_credential_store=Vault())
        ssh=app.state.ssh;ssh.known_hosts=known;ssh.custom_known_hosts=True
        host=dict(id='syntheticid',target='127.0.0.1',user='fixture',port=ssh_port,manual=True,key_path=str(identity))
        app.state.hosts.append(host)
        import time
        app.state.agent_service.snapshots[host['id']]=dict(status='online',collected_at=time.time(),devices=[dict(id=str(i),kind='NPU',name='Synthetic 910B3',memory_free=48*1024**3,memory_total=64*1024**3,health='Warning',processes_known=True,processes=[]) for i in range(8)])
        sock=socket.socket();sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
        server=uvicorn.Server(uvicorn.Config(app,log_level='error',access_log=False));task=asyncio.create_task(server.serve(sockets=[sock]))
        for _ in range(200):
            if server.started:break
            await asyncio.sleep(.01)
        assert server.started
        async def tool(name,args):
            async with Client(f'http://127.0.0.1:{port}/mcp') as client:
                result=await client.call_tool(name,args)
                assert not result.is_error, result.structured_content
                return result.structured_content
        try:
            found=await tool('search_hosts',dict(kind='NPU',count=6,min_free_gib=40,idle=True))
            selected=found['data']['items'][0]['host_id'];assert selected==host['id']
            info=(await tool('get_ssh_info',dict(host_id=selected)))['data']
            assert info['port']==ssh_port and info['identity_files'][0]==str(identity)
            assert info['auth']['ssh_password_available'] is False
            native=await asyncio.create_subprocess_exec(*info['ssh_argv'],'printf mcp-native',stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE)
            out,err=await asyncio.wait_for(native.communicate(),10)
            assert native.returncode==0 and b'INDEPENDENT_CLIENT_OK' in out,err.decode()
            def save():
                req=Request(f'http://127.0.0.1:{port}/api/hosts/{selected}/ssh-password',data=json.dumps({'password':secret}).encode(),headers={'X-IWB':'1','Content-Type':'application/json'})
                with build_opener(ProxyHandler({})).open(req,timeout=10) as result:return result.read()
            saved=await asyncio.to_thread(save)
            assert secret not in saved.decode() and json.loads(saved)['password_saved']
            credential=(await tool('get_ssh_password',dict(host_id=selected)))['data']
            assert credential['password']==secret
            independent=await asyncssh.connect(credential['hostname'],port=credential['port'],username=credential['user'],password=credential['password'],client_keys=[],agent_path=None,known_hosts=str(known),config=None)
            result=await independent.run('printf mcp-password')
            assert result.exit_status==0 and 'INDEPENDENT_CLIENT_OK' in result.stdout
            independent.close();await independent.wait_closed()
            assert seen==['printf mcp-native','printf mcp-password']
        finally:
            server.should_exit=True;await task
            listener.close();await listener.wait_closed();sock.close()
    asyncio.run(scenario())
