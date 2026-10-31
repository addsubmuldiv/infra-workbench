import asyncio
import csv
import io

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel

from .server_import import MAX_FILE, import_template, parse_workbook
from .server_import_jobs import ImportJobs


class ImportOptions(BaseModel):
    provision:bool=False


def register_import_routes(app,hosts,connect,provision,prepare=None):
    manager=ImportJobs(hosts,connect,provision);app.state.server_imports=manager
    parsing=asyncio.Semaphore(2)

    def view(key):
        try:return manager.view(key)
        except KeyError:raise HTTPException(404,'导入记录已过期，请重新选择表格') from None

    def public(data):return JSONResponse(data,headers={'Cache-Control':'no-store'})

    @app.get('/api/imports/template')
    async def template():
        return Response(await asyncio.to_thread(import_template),media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                        headers={'Content-Disposition':'attachment; filename="server-import-template.xlsx"','Cache-Control':'no-store'})

    @app.post('/api/imports/preview')
    async def preview(request:Request):
        async with parsing:
            data=bytearray()
            async for chunk in request.stream():
                if len(data)+len(chunk)>MAX_FILE:raise HTTPException(413,'Excel 文件不能超过 2 MiB')
                data.extend(chunk)
            try:
                rows=await asyncio.to_thread(parse_workbook,bytes(data))
                if prepare:await prepare(rows)
                return public(manager.create(rows))
            except ValueError as exc:raise HTTPException(400,str(exc)) from None
            finally:data.clear()

    @app.get('/api/imports/latest')
    async def latest():return public(manager.latest())

    @app.get('/api/imports/{key}')
    async def status(key:str):return public(view(key))

    @app.post('/api/imports/{key}/start')
    async def start(key:str,body:ImportOptions):
        view(key)
        try:return public(manager.start(key,body.provision))
        except ValueError as exc:raise HTTPException(409,str(exc)) from None

    @app.delete('/api/imports/{key}')
    async def discard(key:str):
        view(key)
        try:manager.discard(key)
        except ValueError as exc:raise HTTPException(409,str(exc)) from None
        return public({'discarded':True})

    @app.get('/api/imports/{key}/report')
    async def report(key:str):
        job=view(key);output=io.StringIO();writer=csv.writer(output)
        statuses={'ready':'待导入','invalid':'格式错误','connecting':'连接中','imported':'导入成功','failed':'导入失败','skipped':'已跳过'}
        keys={'not_requested':'未要求','queued':'等待配置','running':'配置中','done':'配置成功','failed':'配置失败'}
        passwords={'not_provided':'未提供','pending':'等待验证并保存','saved':'已保存','failed':'保存失败','not_saved':'未保存'}
        def cell(value):
            text=str(value)
            return "'"+text if text.lstrip().startswith(('=','+','-','@')) or text.startswith(('\t','\r','\n')) else text
        writer.writerow(['Excel 行号','IP / 主机','账号','端口','导入结果','原因','SSH 密码保存','密码保存说明','免密配置','免密说明'])
        for row in job['rows']:
            writer.writerow([cell(value) for value in (row['row'],row['target'],row['user'],row['port'],statuses[row['status']],row['reason'],passwords[row['password_status']],row['password_reason'],keys[row['key_status']],row['key_reason'])])
        return Response(output.getvalue().encode('utf-8-sig'),media_type='text/csv; charset=utf-8',
                        headers={'Content-Disposition':'attachment; filename="server-import-results.csv"','Cache-Control':'no-store'})

    return manager
