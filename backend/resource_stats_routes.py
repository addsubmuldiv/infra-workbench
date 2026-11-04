"""Validated HTTP adapter for resource history; date boundaries use IANA zones."""
import asyncio
import sqlite3
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from fastapi import HTTPException, Request


def register_resource_history_routes(app, service, hosts):
    @app.get('/api/resource-history')
    async def resource_history(request: Request):
        args=request.query_params
        if set(args)-{'host_ids','date','timezone','kind','from','to'}:
            raise HTTPException(400,'不支持的历史查询参数')
        try:
            zone_name=args.get('timezone','UTC')
            zone=ZoneInfo(zone_name)
            if args.get('date'):
                if 'from' in args or 'to' in args: raise ValueError('日期与绝对时间范围不能同时指定')
                day=datetime.strptime(args['date'],'%Y-%m-%d').replace(tzinfo=zone)
                start,end=day.timestamp(),(day+timedelta(days=1)).timestamp()
            else:
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
