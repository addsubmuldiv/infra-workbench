import asyncio
import io
import json
import os
import subprocess
import sys
import zipfile

import pytest
from httpx import ASGITransport,AsyncClient

from backend.folder_download_probe import build_archive
from backend.log_download import download_script
from backend.app import create_app


def test_folder_archive_preserves_tree_hidden_empty_unicode_and_binary(tmp_path):
    folder=tmp_path/'项目 $ (demo)';folder.mkdir()
    (folder/'空目录').mkdir();(folder/'子目录').mkdir()
    raw=b'\0\xff\r\n'+ '中文'.encode()
    (folder/'子目录'/"file's.bin").write_bytes(raw);(folder/'.hidden').write_text('hidden')
    target=io.BytesIO();result=build_archive(str(folder),target)
    assert result['skipped']==0
    with zipfile.ZipFile(target) as archive:
        assert archive.testzip() is None
        assert archive.read(folder.name+"/子目录/file's.bin")==raw
        assert archive.read(folder.name+'/.hidden')==b'hidden'
        assert folder.name+'/空目录/' in archive.namelist()
        assert all(not name.startswith('/') and '..' not in name.split('/') for name in archive.namelist())
    assert sorted(p.name for p in tmp_path.iterdir())==[folder.name]


def test_folder_archive_bounds_and_invalid_paths_fail_without_success(tmp_path):
    folder=tmp_path/'data';folder.mkdir();(folder/'a').write_bytes(b'x'*32)
    for kwargs,reason in [({'max_size':16},'16 B'),({'max_entries':1},'项')]:
        with pytest.raises(ValueError,match=reason):build_archive(str(folder),io.BytesIO(),**kwargs)
    with pytest.raises((NotADirectoryError,ValueError)):build_archive(str(folder/'a'),io.BytesIO())
    with pytest.raises(FileNotFoundError):build_archive(str(folder/'missing'),io.BytesIO())


def test_folder_archive_skips_links_without_reading_external_targets(tmp_path):
    folder=tmp_path/'data';folder.mkdir();outside=tmp_path/'secret';outside.write_bytes(b'not included')
    try:
        (folder/'outside').symlink_to(outside)
        (folder/'loop').symlink_to(folder,target_is_directory=True)
    except OSError:pytest.skip('symlink creation unavailable')
    target=io.BytesIO();result=build_archive(str(folder),target)
    assert result['skipped']==2
    with zipfile.ZipFile(target) as archive:assert archive.namelist()==['data/']
    with pytest.raises(ValueError,match='符号链接'):build_archive(str(folder/'loop'),io.BytesIO())


@pytest.mark.skipif(os.name=='nt',reason='Windows does not allow backslash in file names')
def test_folder_archive_rejects_names_that_windows_would_extract_as_paths(tmp_path):
    (tmp_path/'a\\..\\escape').write_text('data')
    with pytest.raises(ValueError,match='文件名'):build_archive(str(tmp_path),io.BytesIO())


def test_remote_folder_protocol_returns_complete_zip_or_error_header(tmp_path):
    (tmp_path/'a').write_bytes(b'hello')
    for path,ok in [(tmp_path,True),(tmp_path/'missing',False)]:
        done=subprocess.run([sys.executable,'-B','-X','utf8','-c',download_script(str(path),folder=True)],capture_output=True,timeout=10)
        header,body=done.stdout.split(b'\n',1);meta=json.loads(header.removeprefix(b'IWB_FILE:'))
        assert meta['ok'] is ok,done.stderr
        if ok:
            assert meta['size']==len(body)
            with zipfile.ZipFile(io.BytesIO(body)) as archive:assert archive.read(tmp_path.name+'/a')==b'hello'
        else:assert body==b''


def test_folder_archive_fails_on_unreadable_or_changed_files(tmp_path,monkeypatch):
    path=tmp_path/'data';path.mkdir();file=path/'a';file.write_bytes(b'a'*200000)
    original_open=os.open
    def denied(name,*args,**kwargs):
        if str(name)=='a' or str(name)==str(file):raise PermissionError('denied')
        return original_open(name,*args,**kwargs)
    with monkeypatch.context() as patch:
        patch.setattr(os,'open',denied)
        with pytest.raises(PermissionError):build_archive(str(path),io.BytesIO())
    original_read=os.read;changed=False
    def change_after_read(fd,size):
        nonlocal changed
        data=original_read(fd,size)
        if not changed:
            changed=True
            with file.open('ab') as output:output.write(b'new data')
        return data
    monkeypatch.setattr(os,'read',change_after_read)
    with pytest.raises(ValueError,match='发生变化'):build_archive(str(path),io.BytesIO())


def test_folder_download_over_real_ssh_supports_native_and_cached_sessions(tmp_path):
    import asyncssh
    async def scenario():
        folder=tmp_path/'project';folder.mkdir();(folder/'empty').mkdir();(folder/'raw.bin').write_bytes(b'\0\xff\r\n')
        class Server(asyncssh.SSHServer):
            def begin_auth(self,username):return False
        async def process(proc):
            assert proc.command=='python3 -'
            script=await proc.stdin.read()
            done=await asyncio.create_subprocess_exec(sys.executable,'-B','-X','utf8','-c',script.decode(),stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE)
            out,err=await done.communicate();proc.stdout.write(out);proc.stderr.write(err);proc.exit(done.returncode)
        key=asyncssh.generate_private_key('ssh-ed25519')
        listener=await asyncssh.create_server(Server,'127.0.0.1',0,server_host_keys=[key],process_factory=process,encoding=None)
        known=tmp_path/'known_hosts';known.write_text(f'[127.0.0.1]:{listener.get_port()} '+key.export_public_key().decode())
        app=create_app(tmp_path/'app',start_poll=False)
        app.state.ssh.custom_known_hosts=True;app.state.ssh.known_hosts=known
        host=dict(id='folder',target='127.0.0.1',user='test',port=listener.get_port(),manual=True,auth='key');app.state.hosts.append(host)
        try:
            async with AsyncClient(transport=ASGITransport(app=app),base_url='http://testserver') as client:
                body=dict(host_id='folder',path=str(folder),transfer_id='folder-download-native')
                assert (await client.get('/api/files/capabilities')).json()['folder_download'] is True
                assert (await client.post('/api/files/download-folder',json=body)).status_code==403
                for cached in [False,True]:
                    if cached:
                        connection=await asyncssh.connect('127.0.0.1',port=listener.get_port(),username='test',known_hosts=str(known),config=None)
                        app.state.ssh.sessions['folder']=connection
                        app.state.ssh.connection_configs[connection]=await app.state.ssh.effective(host)
                        body['transfer_id']='folder-download-cached'
                    result=await client.post('/api/files/download-folder',headers={'X-IWB':'1'},json=body)
                    assert result.status_code==200,result.text
                    assert result.headers['content-type']=='application/zip'
                    assert int(result.headers['content-length'])==len(result.content)
                    assert '.zip' in result.headers['content-disposition']
                    with zipfile.ZipFile(io.BytesIO(result.content)) as archive:
                        assert archive.read('project/raw.bin')==b'\0\xff\r\n'
                        assert 'project/empty/' in archive.namelist()
                    status=(await client.get('/api/files/downloads/'+body['transfer_id'])).json()
                    assert status['status']=='remote_done' and status['received']==len(result.content)
                    if cached:assert not connection.is_closed()
                bad=await client.post('/api/files/download-folder',headers={'X-IWB':'1'},json=dict(host_id='folder',path=str(folder/'missing')))
                assert bad.status_code==400 and bad.headers['content-type'].startswith('application/json')
        finally:
            await app.state.ssh.close();listener.close();await listener.wait_closed()
    asyncio.run(scenario())


def test_folder_packing_can_be_cancelled_before_archive_bytes_exist(monkeypatch):
    from fastapi import FastAPI
    import backend.file_routes as routes
    async def scenario():
        entered=asyncio.Event()
        async def packing(*args,**kwargs):entered.set();await asyncio.Event().wait()
        monkeypatch.setattr(routes,'original_log_response',packing)
        app=FastAPI();routes.register_file_routes(app,object(),lambda host_id:dict(id=host_id))
        endpoints={route.path:route.endpoint for route in app.routes if route.path.startswith('/api/files/')}
        key='folder-download-cancel'
        task=asyncio.create_task(endpoints['/api/files/download-folder'](routes.DownloadRequest(host_id='h',path='/data',transfer_id=key),object()))
        await entered.wait()
        cancel=next(route.endpoint for route in app.routes if route.path=='/api/files/downloads/{transfer_id}' and 'DELETE' in route.methods)
        await cancel(key);await asyncio.gather(task,return_exceptions=True)
        assert app.state.file_transfers.downloads[key]['status']=='cancelled'
        assert app.state.file_transfers.downloads[key]['task'] is None
    asyncio.run(scenario())
