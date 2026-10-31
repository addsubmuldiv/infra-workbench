import asyncio
import hashlib
import io
import json
import os
import sys

import pytest
from httpx import ASGITransport,AsyncClient

from backend.folder_upload_probe import receive,publish_directory
from backend.app import create_app


def bundle(files=None,directories=None):
    files=files or []
    manifest=dict(version=1,files=[dict(path=path,size=len(raw)) for path,raw in files],directories=directories or [])
    return b'IWB_FOLDER:1\n'+json.dumps(manifest,ensure_ascii=True).encode()+b'\n'+b''.join(raw for _,raw in files)


def request(parent,raw,**updates):
    info=dict(directory=str(parent),name='project',size=len(raw),sha256=hashlib.sha256(raw).hexdigest());info.update(updates)
    return io.BytesIO(json.dumps(info).encode()+b'\n'+raw)


def test_folder_upload_keeps_nested_hidden_binary_and_empty_directories(tmp_path):
    raw=bundle([('子目录/raw.bin',b'\0\xff\r\n'),('.hidden',b'data')],['empty'])
    result=receive(request(tmp_path,raw))
    assert result['sha256']==hashlib.sha256(raw).hexdigest() and result['size']==len(raw)
    assert (tmp_path/'project'/'子目录'/'raw.bin').read_bytes()==b'\0\xff\r\n'
    assert (tmp_path/'project'/'.hidden').read_bytes()==b'data'
    assert (tmp_path/'project'/'empty').is_dir()
    assert not list(tmp_path.glob('.iwb-folder-upload-*'))


@pytest.mark.parametrize('path',['../escape','/absolute','a/../../escape','a\\b','a//b','a/./b','C:/escape','a\0b'])
def test_folder_upload_rejects_unsafe_paths_without_publishing(tmp_path,path):
    with pytest.raises(ValueError):receive(request(tmp_path,bundle([(path,b'data')])))
    assert list(tmp_path.iterdir())==[]


def test_partial_hash_mismatch_duplicates_and_path_conflicts_leave_no_folder(tmp_path):
    raw=bundle([('a',b'data')])
    cases=[request(tmp_path,raw[:-1],size=len(raw),sha256=hashlib.sha256(raw).hexdigest()),
           request(tmp_path,raw,sha256='0'*64),request(tmp_path,raw+b'extra'),
           request(tmp_path,bundle([('a',b'1'),('a',b'2')])),
           request(tmp_path,bundle([('a',b'1'),('a/b',b'2')]))]
    for stream in cases:
        with pytest.raises(ValueError):receive(stream)
        assert list(tmp_path.iterdir())==[]


def test_existing_or_racing_destination_is_never_overwritten(tmp_path):
    destination=tmp_path/'project';destination.mkdir();(destination/'keep').write_bytes(b'original')
    with pytest.raises(FileExistsError):receive(request(tmp_path,bundle()))
    source=tmp_path/'staging';source.mkdir()
    with pytest.raises(FileExistsError):publish_directory(str(source),str(destination))
    assert (destination/'keep').read_bytes()==b'original' and source.is_dir()
    # Empty directories also must not be replaced (ordinary POSIX rename would).
    empty=tmp_path/'empty';empty.mkdir()
    with pytest.raises(FileExistsError):publish_directory(str(source),str(empty))
    assert source.is_dir() and empty.is_dir()


def test_empty_root_folder_upload(tmp_path):
    receive(request(tmp_path,bundle()))
    assert (tmp_path/'project').is_dir() and not list((tmp_path/'project').iterdir())


def test_folder_upload_api_uses_existing_progress_and_cancel_transport(tmp_path):
    class ProcessSSH:
        sessions={}
        def arguments(self,host):
            return [sys.executable,'-u','-c',"import sys,shlex;exec(compile(shlex.split(sys.argv[-1])[-1],'<folder-upload>','exec'))",'--']
    async def scenario():
        app=create_app(tmp_path/'app',start_poll=False)
        app.state.hosts.append(dict(id='test',target='test',auth='key'));app.state.file_transfers.ssh=ProcessSSH()
        raw=bundle([('sub/binary',b'\0\xff')],['empty'])
        try:
            async with AsyncClient(transport=ASGITransport(app=app),base_url='http://testserver') as client:
                headers={'X-IWB':'1'};meta=dict(host_id='test',path=str(tmp_path),name='project',size=len(raw),kind='folder')
                assert (await client.get('/api/files/capabilities')).json()['folder_upload'] is True
                assert (await client.post('/api/files/uploads',json=meta)).status_code==403
                key=(await client.post('/api/files/uploads',headers=headers,json=meta)).json()['id']
                response=await client.put('/api/files/uploads/'+key,headers=headers,content=raw)
                assert response.status_code==200,response.text
                task=app.state.file_transfers.get(key).get('task')
                if task:await asyncio.wait_for(task,15)
                status=(await client.get('/api/files/uploads/'+key)).json()
                assert status['status']=='done' and status['sent']==len(raw),status
                assert (tmp_path/'project'/'sub'/'binary').read_bytes()==b'\0\xff'
        finally:await app.state.file_transfers.close();await app.state.ssh.close()
    asyncio.run(scenario())


def test_cancelled_stream_cleans_staging_and_limits_are_checked(tmp_path):
    raw=bundle([('nested/a',b'x'*200000)])
    with pytest.raises(ValueError):receive(request(tmp_path,raw[:-100],size=len(raw),sha256=hashlib.sha256(raw).hexdigest()))
    assert list(tmp_path.iterdir())==[]
    for manifest in [dict(version=1,files=[dict(path='a',size=512*1024*1024+1)],directories=[]),
                     dict(version=1,files=[],directories=['d'+str(i) for i in range(10001)]),
                     dict(version=1,files=[],directories=['/'.join(['d']*65)])]:
        bad=b'IWB_FOLDER:1\n'+json.dumps(manifest).encode()+b'\n'
        with pytest.raises(ValueError):receive(request(tmp_path,bad))
        assert list(tmp_path.iterdir())==[]


def test_folder_upload_through_real_native_and_cached_ssh(tmp_path):
    import asyncssh,shlex
    async def scenario():
        class Server(asyncssh.SSHServer):
            def begin_auth(self,username):return False
        async def process(proc):
            words=shlex.split(proc.command);assert words[:3]==['python3','-u','-c']
            local=await asyncio.create_subprocess_exec(sys.executable,'-u','-c',words[3],stdin=asyncio.subprocess.PIPE,stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE)
            async def feed():
                try:
                    while block:=await proc.stdin.read(65536):local.stdin.write(block);await local.stdin.drain()
                finally:local.stdin.close()
            async def output(reader,writer):
                while block:=await reader.read(65536):writer.write(block)
            await asyncio.gather(feed(),output(local.stdout,proc.stdout),output(local.stderr,proc.stderr))
            proc.exit(await local.wait())
        key=asyncssh.generate_private_key('ssh-ed25519')
        listener=await asyncssh.create_server(Server,'127.0.0.1',0,server_host_keys=[key],process_factory=process,encoding=None)
        known=tmp_path/'known_hosts';known.write_text(f'[127.0.0.1]:{listener.get_port()} '+key.export_public_key().decode())
        app=create_app(tmp_path/'app',start_poll=False);app.state.ssh.custom_known_hosts=True;app.state.ssh.known_hosts=known
        host=dict(id='ssh',target='127.0.0.1',user='test',port=listener.get_port(),manual=True,auth='key');app.state.hosts.append(host)
        raw=bundle([('sub/binary',b'\0\xff'*10000)],['empty'])
        try:
            async with AsyncClient(transport=ASGITransport(app=app),base_url='http://testserver') as client:
                for name,cached in [('native',False),('cached',True)]:
                    if cached:
                        connection=await asyncssh.connect('127.0.0.1',port=listener.get_port(),username='test',known_hosts=str(known),config=None)
                        app.state.ssh.sessions[host['id']]=connection;app.state.ssh.connection_configs[connection]=await app.state.ssh.effective(host)
                    meta=dict(host_id='ssh',path=str(tmp_path),name=name,kind='folder',size=len(raw))
                    key=(await client.post('/api/files/uploads',headers={'X-IWB':'1'},json=meta)).json()['id']
                    assert (await client.put('/api/files/uploads/'+key,headers={'X-IWB':'1'},content=raw)).status_code==200
                    task=app.state.file_transfers.get(key).get('task')
                    if task:await asyncio.wait_for(task,15)
                    status=(await client.get('/api/files/uploads/'+key)).json();assert status['status']=='done',status
                    assert (tmp_path/name/'sub'/'binary').read_bytes()==b'\0\xff'*10000
                    assert (tmp_path/name/'empty').is_dir()
                    if cached:assert not connection.is_closed()
        finally:await app.state.file_transfers.close();await app.state.ssh.close();listener.close();await listener.wait_closed()
    asyncio.run(scenario())
