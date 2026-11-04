"""Validated HTTP adapter for resource history; date boundaries use IANA zones."""
import asyncio
import sqlite3
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from fastapi import HTTPException, Request


def history_time_range(args, zone, now=None):
    day=datetime.strptime(args['date'],'%Y-%m-%d').replace(tzinfo=zone)
    start,end=day.timestamp(),(day+timedelta(days=1)).timestamp()
    custom='start_time' in args or 'end_time' in args
    if 'window_hours' in args:
        if custom: raise ValueError('快捷时段和自定义时间不能同时指定')
        hours=int(args['window_hours'])
        if hours not in (1,3,6,12): raise ValueError('快捷时段应为1、3、6或12小时')
        clock=time.time() if now is None else now
        finish=min(end,clock) if clock>start else end
        return max(start,finish-hours*3600),finish
    if custom:
        if not args.get('start_time') or not args.get('end_time'):raise ValueError('请同时选择开始和结束时间')
        def local(value):
            if value=='24:00':return day+timedelta(days=1)
            point=datetime.strptime(args['date']+' '+value,'%Y-%m-%d %H:%M').replace(tzinfo=zone)
            if datetime.fromtimestamp(point.timestamp(),zone).replace(tzinfo=None)!=point.replace(tzinfo=None):
                raise ValueError('所选时间在该时区不存在，请调整时间')
            return point
        start,end=local(args['start_time']).timestamp(),local(args['end_time']).timestamp()
        if end<=start:raise ValueError('结束时间必须晚于开始时间')
    return start,end


def register_resource_history_routes(app, service, hosts):
    @app.get('/api/resource-history')
    async def resource_history(request: Request):
        args=request.query_params
        if set(args)-{'host_ids','date','timezone','kind','from','to','window_hours','start_time','end_time'}:
            raise HTTPException(400,'不支持的历史查询参数')
        try:
            zone_name=args.get('timezone','UTC')
            zone=ZoneInfo(zone_name)
            if args.get('date'):
                if 'from' in args or 'to' in args: raise ValueError('日期与绝对时间范围不能同时指定')
                start,end=history_time_range(args,zone)
            else:
                if any(key in args for key in ('window_hours','start_time','end_time')):raise ValueError('快捷或自定义时段必须指定日期')
                def timestamp(value):
                    try: return float(value)
                    except ValueError:
                        parsed=datetime.fromisoformat(value.replace('Z','+00:00'))
                        if parsed.tzinfo is None: raise ValueError('绝对时间必须包含时区')
                        return parsed.timestamp()
                start,end=timestamp(args['from']),timestamp(args['to'])
            ids=list(dict.fromkeys(x for x in args.get('host_ids','').split(',') if x))
            current=hosts() if callable(hosts) else hosts
            if isinstance(current,dict): current=current.values()
            current=list(current)
            available={h['id'] for h in current}
            # Archived hosts remain available through their durable sample identity.
            archived=await asyncio.to_thread(service.archived_host_ids,ids)
            if any(host_id not in available|archived for host_id in ids):
                raise HTTPException(404,'机器不存在')
            result=await asyncio.to_thread(service.query,ids,start,end,kind=args.get('kind','GPU'),timezone=zone_name)
            names={h['id']:h.get('alias') or h.get('target') or h['id'] for h in current}
            for host in result['hosts']:
                if host['name']==host['host_id']:
                    host['name']=names.get(host['host_id'],host['host_id'])
            return result
        except HTTPException: raise
        except sqlite3.Error:
            raise HTTPException(503,'资源历史数据库暂时无法读取') from None
        except (ValueError,KeyError,OverflowError,ZoneInfoNotFoundError) as exc:
            raise HTTPException(400,str(exc)) from None
