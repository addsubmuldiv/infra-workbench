import asyncio
import io
import json
import subprocess
import sys
from pathlib import Path

import pytest
from httpx import ASGITransport,AsyncClient

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from backend.app import create_app
from backend.log_download import download_script,receive_file,download_filename


def probe(path):
    return subprocess.run([sys.executable,'-B','-X','utf8','-c',download_script(str(path))],capture_output=True,timeout=10)


def test_remote_download_preserves_raw_bytes_and_does_not_require_json(tmp_path):
    path=tmp_path/'训练; $(bad) 日志.log'
    raw=b'header\r\nnot JSON\r\n\xff\x00'+('中文原始输出\n'*3).encode()
    path.write_bytes(raw)
    response=probe(path)
    header,body=response.stdout.split(b'\n',1)
    assert response.returncode==0 and json.loads(header.removeprefix(b'IWB_FILE:'))['size']==len(raw)
    assert body==raw
    assert '训练' not in download_script(str(path)).splitlines()[0]


def test_download_missing_directory_and_safe_filename(tmp_path):
    for path in (tmp_path,tmp_path/'missing.log'):
        response=probe(path)
        assert json.loads(response.stdout.removeprefix(b'IWB_FILE:'))['ok'] is False
    name=download_filename('NPU:server','/logs/精度\r\n"坏.log')
    assert '\r' not in name and '\n' not in name and '"' not in name


def test_receiver_rejects_truncated_or_excess_output_and_reports_remote_errors():
    async def scenario():
        async def receive(data):
            reader=asyncio.StreamReader();reader.feed_data(data);reader.feed_eof()
            target=io.BytesIO()
            return await receive_file(reader,target)
        header=b'IWB_FILE:{"ok":true,"size":4}\n'
        assert (await receive(b'login banner\n'+header+b'abcd'))['size']==4
        for value in (header+b'abc',header+b'abcde',b'IWB_FILE:{"ok":true,"size":-1}\n'):
            with pytest.raises(ValueError): await receive(value)
        with pytest.raises(ValueError,match='权限'):
            await receive(b'IWB_FILE:{"ok":false,"error":"'+ '权限不足'.encode()+b'"}\n')
    asyncio.run(scenario())


def test_native_ssh_raw_log_download_and_http_error_are_not_fake_success(tmp_path):
    import asyncssh
    async def scenario():
        path=tmp_path/'raw \u65e5\u5fd7.log'
        raw=b'not json\r\n'+json.dumps(dict(loss=2,iteration='1/300')).encode()+b'\n\xff\x00'
        path.write_bytes(raw)
        class Server(asyncssh.SSHServer):
            def begin_auth(self,username): return False
        async def process(proc):
            assert proc.command=='python3 -'
            script=await proc.stdin.read()
            done=subprocess.run([sys.executable,'-B','-X','utf8','-c',script.decode()],capture_output=True,timeout=10)
            proc.stdout.write(done.stdout);proc.stderr.write(done.stderr);proc.exit(done.returncode)
        key=asyncssh.generate_private_key('ssh-ed25519')
        listener=await asyncssh.create_server(Server,'127.0.0.1',0,server_host_keys=[key],process_factory=process,encoding=None)
        known=tmp_path/'known_hosts'
        known.write_text(f'[127.0.0.1]:{listener.get_port()} '+key.export_public_key().decode())
        app=create_app(tmp_path/'data',start_poll=False)
        app.state.ssh.custom_known_hosts=True;app.state.ssh.known_hosts=known
        app.state.hosts.append(dict(id='download',target='127.0.0.1',user='test',port=listener.get_port(),manual=True,auth='key'))
        try:
            async with AsyncClient(transport=ASGITransport(app=app),base_url='http://testserver') as client:
                body=dict(host_id='download',path=str(path))
                assert (await client.post('/api/logs/download',json=body)).status_code==403
                response=await client.post('/api/logs/download',headers={'X-IWB':'1'},json=body)
                assert response.status_code==200,response.text
                assert response.content==raw
                assert int(response.headers['content-length'])==len(raw)
                assert "filename*=UTF-8''" in response.headers['content-disposition']
                # Existing password sessions use a separate binary channel;
                # finishing a download must never close the parent connection.
                connection=await asyncssh.connect('127.0.0.1',port=listener.get_port(),username='test',known_hosts=str(known),config=None)
                app.state.ssh.sessions['download']=connection
                app.state.ssh.connection_configs[connection]=await app.state.ssh.effective(app.state.hosts[0])
                cached=await client.post('/api/logs/download',headers={'X-IWB':'1'},json=body)
                assert cached.status_code==200 and cached.content==raw and not connection.is_closed()
                missing=await client.post('/api/logs/download',headers={'X-IWB':'1'},json=dict(host_id='download',path=str(tmp_path/'missing')))
                assert missing.status_code==400 and missing.headers['content-type'].startswith('application/json')
                assert (await client.post('/api/logs/download',headers={'X-IWB':'1'},json=dict(host_id='download',path='a\nb'))).status_code==422
        finally:
            await app.state.ssh.close();listener.close();await listener.wait_closed()
    asyncio.run(scenario())
