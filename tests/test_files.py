import importlib.util
import asyncio
import json
import contextlib
import io
from pathlib import Path

import pytest

spec=importlib.util.spec_from_file_location('files_probe',Path(__file__).resolve().parents[1]/'backend'/'files_probe.py')
probe=importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)


def test_directory_lists_hidden_unicode_and_paginates_without_recursing(tmp_path):
    (tmp_path/'目录').mkdir()
    (tmp_path/'目录'/'nested').write_text('not in root')
    (tmp_path/'.hidden').write_bytes(b'abc')
    (tmp_path/'中文; $(bad).bin').write_bytes(b'\xff\0')
    first=probe.browse(str(tmp_path),0,2)
    assert first['entries'][0]['kind']=='directory'
    assert first['next_offset']==2 and first['total']==3
    second=probe.browse(str(tmp_path),2,2)
    names=[item['name'] for item in first['entries']+second['entries']]
    assert set(names)=={'目录','.hidden','中文; $(bad).bin'}
    assert all(Path(item['path']).parent==tmp_path for item in first['entries']+second['entries'])
    assert first['path']==str(tmp_path) and second['next_offset'] is None


def test_directory_errors_are_not_empty_success(tmp_path):
    with pytest.raises(FileNotFoundError): probe.browse(str(tmp_path/'missing'))
    file=tmp_path/'file';file.write_bytes(b'x')
    with pytest.raises(NotADirectoryError): probe.browse(str(file))
    for path in ('bad\0path','bad\npath','bad\rpath'):
        with pytest.raises(ValueError): probe.browse(path)
    with pytest.raises(ValueError): probe.browse(str(tmp_path),-1)


def test_files_routes_use_ssh_and_share_only_the_safe_download_transport(tmp_path,monkeypatch):
    from fastapi import FastAPI,HTTPException
    from backend.file_routes import register_file_routes,DirectoryRequest
    from backend.log_routes import LogLocation
    import backend.file_routes as routes
    folder=tmp_path/'目录';folder.mkdir()
    (folder/'binary.bin').write_bytes(b'\xff\0\r\n')
    host=dict(id='files',target='test-files')
    class SSH:
        async def run(self,actual,command,source=None):
            assert actual is host and command=='python3 -'
            output=io.StringIO()
            with contextlib.redirect_stdout(output): exec(source,{'__name__':'probe'})
            return 0,output.getvalue(),''
    calls=[]
    async def download(ssh,actual,path,request,label):
        calls.append((actual,path,label))
        return 'download-response'
    monkeypatch.setattr(routes,'original_log_response',download)
    app=FastAPI()
    register_file_routes(app,SSH(),lambda host_id:host)
    endpoints={route.path:route.endpoint for route in app.routes if route.path.startswith('/api/files/')}
    async def scenario():
        result=await endpoints['/api/files/browse'](DirectoryRequest(host_id='files',path=str(folder)))
        assert result['entries'][0]['name']=='binary.bin'
        with pytest.raises(HTTPException,match='不存在'):
            await endpoints['/api/files/browse'](DirectoryRequest(host_id='files',path=str(folder/'missing')))
        assert await endpoints['/api/files/download'](LogLocation(host_id='files',path=str(folder/'binary.bin')),object())=='download-response'
        assert calls==[(host,str(folder/'binary.bin'),'文件')]
        with pytest.raises(ValueError): DirectoryRequest(host_id='files',path='bad\npath')
    # All I/O boundaries above are synchronous fakes. Run the coroutine to
    # completion without opening Windows event-loop sockets in this unit test.
    with pytest.raises(StopIteration): scenario().send(None)
