import asyncio
import hashlib
import io
import json
import sys
from pathlib import Path

import pytest
from httpx import ASGITransport,AsyncClient

from backend.file_upload_probe import receive
from backend.file_transfers import FileTransfers
from backend.app import create_app
from backend.log_download import receive_file
from backend.terminal import directory_command


def payload(folder,name,raw,**updates):
    meta=dict(directory=str(folder),name=name,size=len(raw),sha256=hashlib.sha256(raw).hexdigest())
    meta.update(updates)
    return io.BytesIO(json.dumps(meta).encode()+b'\n'+raw)


def test_binary_upload_verifies_hash_and_publishes_only_complete_files(tmp_path):
    raw=b'\xff\0\r\n'+ '中文'.encode()
    result=receive(payload(tmp_path,'中文.bin',raw))
    assert Path(result['path']).read_bytes()==raw
    assert result['sha256']==hashlib.sha256(raw).hexdigest()
    with pytest.raises(FileExistsError): receive(payload(tmp_path,'中文.bin',b'overwrite'))
    assert (tmp_path/'中文.bin').read_bytes()==raw
    for name,stream in [('bad.bin',payload(tmp_path,'bad.bin',raw,sha256='0'*64)),
                        ('partial.bin',payload(tmp_path,'partial.bin',raw,size=len(raw)+1)),
                        ('extra.bin',payload(tmp_path,'extra.bin',raw,size=1))]:
        with pytest.raises(ValueError): receive(stream)
        assert not (tmp_path/name).exists()
    assert not list(tmp_path.glob('.iwb-upload-*'))


@pytest.mark.parametrize('name',['../escape','a/b','a\\b','..','bad\nname'])
def test_upload_names_cannot_escape_destination(tmp_path,name):
    with pytest.raises(ValueError): receive(payload(tmp_path,name,b'data'))
    assert list(tmp_path.iterdir())==[]


class ProcessSSH:
    """Replace only the SSH boundary; execute the real remote binary protocol."""
    sessions={}
    def arguments(self,host):
        return [sys.executable,'-u','-c',"import sys,shlex; exec(compile(shlex.split(sys.argv[-1])[-1],'<remote-upload>','exec'))",'--']


def test_api_upload_runs_background_transfer_and_never_overwrites(tmp_path):
    async def scenario():
        app=create_app(tmp_path/'app',start_poll=False)
        app.state.hosts.append(dict(id='test',target='test',auth='key'))
        app.state.file_transfers.ssh=ProcessSSH()
        async with AsyncClient(transport=ASGITransport(app=app),base_url='http://testserver') as client:
            headers={'X-IWB':'1'};raw=b'\0\xff'*256000
            meta=dict(host_id='test',path=str(tmp_path),name='binary.bin',size=len(raw))
            assert (await client.post('/api/files/uploads',json=meta)).status_code==403
            assert (await client.post('/api/files/uploads',headers=headers,json=dict(meta,name='../bad'))).status_code==422
            async def upload(data):
                response=await client.post('/api/files/uploads',headers=headers,json=dict(meta,size=len(data)))
                assert response.status_code==200,response.text
                key=response.json()['id']
                response=await client.put('/api/files/uploads/'+key,headers=headers,content=data)
                assert response.status_code==200,response.text
                task=app.state.file_transfers.get(key).get('task')
                if task: await asyncio.wait_for(task,15)
                return (await client.get('/api/files/uploads/'+key)).json()
            done=await upload(raw)
            assert done['status']=='done' and done['sent']==len(raw)
            assert (tmp_path/'binary.bin').read_bytes()==raw
            duplicate=await upload(b'not-the-original')
            assert duplicate['status']=='error' and '已存在' in duplicate['error']
            assert (tmp_path/'binary.bin').read_bytes()==raw
        await app.state.file_transfers.close();await app.state.ssh.close()
    asyncio.run(scenario())


def test_cancel_while_receiving_closes_spool_and_never_starts_remote_upload(tmp_path,monkeypatch):
    import backend.file_transfers as module
    files=[];original=module.tempfile.TemporaryFile
    def opened(*args,**kwargs):
        value=original(*args,**kwargs);files.append(value);return value
    monkeypatch.setattr(module.tempfile,'TemporaryFile',opened)
    async def scenario():
        transfers=FileTransfers(ProcessSSH());ready=asyncio.Event()
        key=transfers.create(dict(id='test'),str(tmp_path),'partial',100)['id']
        class Request:
            headers={}
            async def stream(self):
                yield b'a';ready.set();await asyncio.Event().wait()
        task=asyncio.create_task(transfers.receive(key,Request()))
        await ready.wait();await transfers.cancel(key)
        await asyncio.gather(task,return_exceptions=True)
        assert transfers.get(key)['status']=='cancelled'
        assert all(file.closed for file in files)
        assert not (tmp_path/'partial').exists()
    asyncio.run(scenario())


def test_download_progress_reports_remote_bytes_and_total():
    async def scenario():
        reader=asyncio.StreamReader();raw=b'original\0bytes'
        reader.feed_data(b'IWB_FILE:'+json.dumps(dict(ok=True,size=len(raw))).encode()+b'\n'+raw);reader.feed_eof()
        events=[];target=io.BytesIO()
        await receive_file(reader,target,on_progress=lambda received,total:events.append((received,total)))
        assert events[0]==(0,len(raw)) and events[-1]==(len(raw),len(raw))
        assert target.getvalue()==raw
    asyncio.run(scenario())


def test_directory_start_command_quotes_paths_as_data():
    import shlex
    path="/data/中文 'name'; $(touch should-not-run)"
    outer=shlex.split(directory_command(path))
    assert outer[:3]==['exec','/bin/sh','-c']
    words=shlex.split(outer[3]);assert words[:3]==['cd','--',path]
    for invalid in ('relative','/bad\npath','/bad\0path',False):
        with pytest.raises(ValueError): directory_command(invalid)
