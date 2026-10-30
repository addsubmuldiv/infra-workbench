import contextlib
import io
import json
import os
from pathlib import Path

import pytest
from backend import file_ops as ops


def test_save_preserves_utf8_bom_crlf_and_executable_permissions(tmp_path):
    path=tmp_path/'训练; $(not-a-command).sh'
    path.write_bytes(b'\xef\xbb\xbfecho old\r\n')
    path.chmod(0o755)
    original_mode=path.stat().st_mode
    doc=ops.perform(dict(op='read',path=str(path)))
    assert doc['content']=='echo old\n' and doc['newline']=='CRLF'
    saved=ops.perform(dict(op='save',path=str(path),revision=doc['revision'],content='echo 新内容\n'))
    assert path.read_bytes()==b'\xef\xbb\xbf'+'echo 新内容\r\n'.encode()
    assert saved['revision']!=doc['revision']
    assert path.stat().st_mode==original_mode
    assert not list(tmp_path.glob('.iwb-*'))


def test_stale_edit_is_rejected_and_remote_changes_survive(tmp_path):
    path=tmp_path/'a.py';path.write_text('original')
    doc=ops.perform(dict(op='read',path=str(path)))
    path.write_text('changed by somebody else')
    with pytest.raises(ops.Conflict):
        ops.perform(dict(op='save',path=str(path),revision=doc['revision'],content='my edit'))
    assert path.read_text()=='changed by somebody else'


def test_second_conflict_check_protects_changes_during_save(tmp_path,monkeypatch):
    path=tmp_path/'a.py';path.write_text('original')
    doc=ops.perform(dict(op='read',path=str(path)))
    original=ops.text_file
    calls=0
    def read(actual):
        nonlocal calls
        calls+=1
        if calls==2: path.write_text('concurrent change')
        return original(actual)
    monkeypatch.setattr(ops,'text_file',read)
    with pytest.raises(ops.Conflict):
        ops.perform(dict(op='save',path=str(path),revision=doc['revision'],content='my edit'))
    assert path.read_text()=='concurrent change'
    assert not list(tmp_path.glob('.iwb-*'))


@pytest.mark.parametrize('raw',[b'\0binary',b'\xff\xfe',b'a'*(ops.TEXT_LIMIT+1)])
def test_binary_non_utf8_and_large_files_are_not_opened_as_text(tmp_path,raw):
    path=tmp_path/'file';path.write_bytes(raw)
    with pytest.raises(ValueError): ops.perform(dict(op='read',path=str(path)))
    assert path.read_bytes()==raw


def test_create_copy_move_rename_and_directory_copy_are_no_clobber(tmp_path):
    src=tmp_path/'原始目录';dst=tmp_path/'复制目录'
    ops.perform(dict(op='mkdir',path=str(src)))
    file=src/'a.txt'
    ops.perform(dict(op='create',path=str(file)))
    doc=ops.perform(dict(op='read',path=str(file)))
    ops.perform(dict(op='save',path=str(file),revision=doc['revision'],content='hello'))
    ops.perform(dict(op='copy',path=str(src),destination=str(dst)))
    assert (dst/'a.txt').read_text()=='hello' and file.exists()
    moved=tmp_path/'moved.txt'
    ops.perform(dict(op='move',path=str(dst/'a.txt'),destination=str(moved)))
    assert not (dst/'a.txt').exists() and moved.read_text()=='hello'
    for op in ('copy','move'):
        with pytest.raises(FileExistsError): ops.perform(dict(op=op,path=str(file),destination=str(moved)))
    assert file.read_text()==moved.read_text()=='hello'
    with pytest.raises(FileExistsError): ops.perform(dict(op='create',path=str(moved)))
    with pytest.raises(ValueError): ops.perform(dict(op='copy',path=str(src),destination=str(src/'nested')))
    assert not list(tmp_path.glob('.iwb-*'))


def test_copy_limit_fails_before_destination_and_partial_copy_is_not_published(tmp_path,monkeypatch):
    path=tmp_path/'source';path.write_bytes(b'123456')
    dest=tmp_path/'dest'
    monkeypatch.setattr(ops,'COPY_LIMIT',2)
    with pytest.raises(ValueError): ops.perform(dict(op='copy',path=str(path),destination=str(dest)))
    assert not dest.exists()
    # Simulate a source growing after the preflight.
    monkeypatch.setattr(ops,'copy_budget',lambda _:None)
    with pytest.raises(ValueError): ops.perform(dict(op='copy',path=str(path),destination=str(dest)))
    assert not dest.exists() and path.read_bytes()==b'123456'
    assert not list(tmp_path.glob('.iwb-*'))


def test_symbolic_links_and_hardlinks_are_not_replaced_by_editing(tmp_path):
    target=tmp_path/'target';target.write_text('original')
    link=tmp_path/'link'
    try: os.symlink(target,link)
    except OSError: pytest.skip('symlink creation is unavailable')
    with pytest.raises(ValueError): ops.perform(dict(op='read',path=str(link)))
    hard=tmp_path/'hard';os.link(target,hard)
    doc=ops.perform(dict(op='read',path=str(hard)))
    with pytest.raises(ValueError): ops.perform(dict(op='save',path=str(hard),revision=doc['revision'],content='edited'))
    assert target.read_text()=='original'


def test_operation_route_transports_text_over_ssh_without_shell_or_disk_cache(tmp_path):
    from fastapi import FastAPI,HTTPException
    from backend.file_routes import register_file_routes,FileOperation
    path=tmp_path/'中文; $(bad).txt';path.write_text('IWB_FILE_OP:literal text')
    class SSH:
        async def run(self,host,command,source):
            assert command=='python3 -' and host['id']=='test'
            output=io.StringIO()
            with contextlib.redirect_stdout(output): exec(source,{})
            return 0,output.getvalue(),''
    app=FastAPI();register_file_routes(app,SSH(),lambda _:dict(id='test'))
    endpoint=next(route.endpoint for route in app.routes if route.path=='/api/files/operation')
    async def scenario():
        doc=await endpoint(FileOperation(host_id='test',path=str(path),op='read'))
        assert doc['content']=='IWB_FILE_OP:literal text'
        await endpoint(FileOperation(host_id='test',path=str(path),op='save',revision=doc['revision'],content='new text'))
        assert path.read_text()=='new text'
        with pytest.raises(HTTPException) as error:
            await endpoint(FileOperation(host_id='test',path=str(path),op='save',revision=doc['revision'],content='stale'))
        assert error.value.status_code==409
    with pytest.raises(StopIteration): scenario().send(None)
