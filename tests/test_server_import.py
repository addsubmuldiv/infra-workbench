import asyncio
import io
import json

import pytest
from openpyxl import Workbook, load_workbook

from backend.server_import import parse_workbook, import_template, ImportRow, safe_failure
from backend.server_import_jobs import ImportJobs


def workbook(rows):
    book=Workbook();sheet=book.active
    for row in rows:sheet.append(row)
    output=io.BytesIO();book.save(output);book.close();return output.getvalue()


def test_import_parser_keeps_password_exact_but_never_in_public_preview():
    rows=parse_workbook(workbook([['IP','账号','密码','端口'],['192.0.2.10','tester','  fake-only secret  ',2222],['192.0.2.11','other',None,None]]))
    assert len(rows)==2 and rows[0].password.get_secret_value()=='  fake-only secret  '
    assert rows[0].port==2222 and rows[1].port==22
    assert rows[0].row==2 and rows[0].status=='ready'
    assert 'fake-only' not in json.dumps([r.view() for r in rows]) and 'fake-only' not in repr(rows)


def test_parser_reports_bad_rows_and_duplicate_rows_without_discarding_good_rows():
    rows=parse_workbook(workbook([['host','username','password','port'],['192.0.2.10','u','fake',22],['192.0.2.10','u','fake',22],['bad address','u','private',22],['192.0.2.12',None,'private',22],['192.0.2.13','u','private',70000],['192.0.2.14','u',123456,22],[],['192.0.2.15','u','=1+1',22]]))
    assert [r.status for r in rows]==['ready','skipped','invalid','invalid','invalid','ready','invalid']
    assert '第 2 行' in rows[1].reason
    assert rows[5].password.get_secret_value()=='123456'
    assert all(r.password is None for r in rows if r.status!='ready')
    assert all(r.reason for r in rows if r.status!='ready')


def test_bad_workbooks_and_limits_are_rejected_with_safe_messages():
    for data in [b'not excel',workbook([['something'],['fake']]),workbook([['IP','账号','用户名'],['a','b','c']]),workbook([['IP','账号']]+[['192.0.2.1',str(i)] for i in range(101)])]:
        with pytest.raises(ValueError):parse_workbook(data)
    with pytest.raises(ValueError):parse_workbook(b'x'*(2*1024*1024+1))


def test_template_is_readable_and_password_columns_are_text():
    data=import_template();book=load_workbook(io.BytesIO(data));sheet=book.worksheets[0]
    assert [c.value for c in sheet[1]]==['IP','账号','密码','端口']
    assert sheet['C2'].number_format=='@' and sheet.freeze_panes=='A2'
    book.close();assert len(parse_workbook(data))==2


def test_failure_text_never_echoes_server_supplied_secrets():
    for error in [RuntimeError('Permission denied: fake-secret'),TimeoutError('fake-secret'),RuntimeError('Host key is not trusted fake-secret'),RuntimeError('unexpected fake-secret')]:
        assert 'fake-secret' not in safe_failure(error)


def test_numeric_password_display_formats_are_not_silently_changed():
    book=Workbook();sheet=book.active
    sheet.append(['IP','账号','密码']);sheet.append(['192.0.2.10','u',1234]);sheet['C2'].number_format='000000'
    data=io.BytesIO();book.save(data);book.close()
    row=parse_workbook(data.getvalue())[0]
    assert row.status=='invalid' and row.password is None and '文本' in row.reason


def test_underreported_excel_dimensions_cannot_silently_hide_server_rows():
    import zipfile
    book=Workbook();page=book.active;page.append(['IP','账号']);page.append(['192.0.2.10','u']);page.cell(1200,1,'192.0.2.11');page.cell(1200,2,'u')
    data=io.BytesIO();book.save(data);book.close();output=io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(data.getvalue())) as source,zipfile.ZipFile(output,'w') as target:
        for name in source.namelist():
            raw=source.read(name)
            if name=='xl/worksheets/sheet1.xml':raw=raw.replace(b'ref="A1:B1200"',b'ref="A1:B2"')
            target.writestr(name,raw)
    with pytest.raises(ValueError,match='1000'):parse_workbook(output.getvalue())


def test_import_progress_finishes_before_background_provision_and_keeps_partial_success():
    async def scenario():
        gate=asyncio.Event();calls=[];hosts=[]
        async def connect(row):
            calls.append(row.target)
            if row.target=='denied':raise RuntimeError('Permission denied fake-only-password')
            result=dict(host_id=row.target);hosts.append(dict(id=row.target,target=row.target,user=row.user,port=row.port,manual=True));return result
        async def provision(row):await gate.wait();return dict(ok=row.target!='key-denied',reason='免密验证失败')
        manager=ImportJobs(hosts,connect,provision)
        try:
            job=manager.create([ImportRow(2,'good','u',22,'fake-only-password'),ImportRow(3,'denied','u',22,'fake-only-password'),ImportRow(4,'key-denied','u',22,'fake-only-password')])
            manager.start(job['id'],True);manager.start(job['id'],True)
            await asyncio.wait_for(manager.jobs[job['id']]['import_task'],1)
            result=manager.view(job['id'])
            assert result['status']=='complete' and result['processed']==3 and result['success']==2 and result['failed']==1
            assert result['key_total']==2 and result['key_done']==0
            assert calls==['good','denied','key-denied']
            assert 'fake-only-password' not in json.dumps(result)
            gate.set();await asyncio.wait_for(manager.jobs[job['id']]['key_task'],1)
            result=manager.view(job['id'])
            assert result['success']==2 and result['key_done']==2 and result['key_failed']==1
            assert all(row.password is None for row in manager.jobs[job['id']]['rows'])
        finally:await manager.close()
    asyncio.run(scenario())


def test_existing_hosts_are_skipped_and_close_releases_unused_passwords():
    async def scenario():
        async def forbidden(row):raise AssertionError('must not connect')
        hosts=[dict(id='existing',target='192.0.2.1',user='u',port=22,manual=True)]
        manager=ImportJobs(hosts,forbidden,forbidden)
        job=manager.create([ImportRow(2,'192.0.2.1','u',22,None)]);manager.start(job['id'],False)
        await manager.jobs[job['id']]['import_task']
        assert manager.view(job['id'])['skipped']==1 and len(hosts)==1
        preview=manager.create([ImportRow(2,'192.0.2.2','u',22,'fake')])
        await manager.close()
        assert all(r.password is None for job in manager.jobs.values() for r in job['rows'])
    asyncio.run(scenario())
