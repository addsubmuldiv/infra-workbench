"""Pure, bounded inventory views; no SSH, DB, credentials or HTTP side effects."""
import copy
import math
import time

from .agent_errors import AgentError, response, recovery

GIB=1024**3


def resolve_host(hosts, selector):
    by_id=[h for h in hosts if h['id']==selector]
    matches=by_id or [h for h in hosts if h['target']==selector]
    if not matches:
        raise AgentError('HOST_NOT_FOUND','没有此机器，请先 list_hosts 取得真实 ID。')
    if len(matches)!=1:
        raise AgentError('AMBIGUOUS_HOST','别名对应多台机器，请使用完整 host_id。')
    return matches[0]


def age(snapshot, now):
    stamp=snapshot.get('collected_at')
    if not isinstance(stamp,(int,float)) or not math.isfinite(stamp) or stamp>now+5:
        return None
    return max(0,now-stamp)


def summary(host, now, max_age=30):
    snap=host.get('snapshot') or {}
    elapsed=age(snap,now)
    devices=snap.get('devices') or []
    return dict(host_id=host['id'],alias=host['target'],status=snap.get('status','connecting'),
                collected_at=snap.get('collected_at'),age_seconds=elapsed,
                fresh=snap.get('status')=='online' and elapsed is not None and elapsed<=max_age,
                device_kinds=sorted({d['kind'] for d in devices}),device_count=len(devices),
                connection_summary=dict(user=host.get('user'),port=host.get('port'),
                                        mode='manual' if host.get('manual') else 'ssh_config',
                                        software_auth=host.get('auth','unknown')))


def unit(devices):
    return 'chip' if any(str(d.get('id','')).startswith('chip:') for d in devices) else 'device'


def resource(host, now, max_age):
    snap=host.get('snapshot') or {}
    result=summary(host,now,max_age)
    result.update(system=copy.deepcopy(snap.get('system')),devices=copy.deepcopy(snap.get('devices',[])),
                  count_unit=unit(snap.get('devices',[])),process_scope='accelerator_processes',
                  error_stage=snap.get('error_stage'))
    return result


def compact_resource(host,now,max_age):
    result=summary(host,now,max_age)
    snap=host.get('snapshot') or {};devices=snap.get('devices') or []
    groups=[]
    for kind,name in sorted({(d['kind'],d.get('name','')) for d in devices}):
        ds=[d for d in devices if d['kind']==kind and d.get('name','')==name]
        groups.append(dict(kind=kind,name=name,count=len(ds),
            memory_free_bytes_total=sum(d['memory_free'] for d in ds) if all(d.get('memory_free') is not None for d in ds) else None,
            idle_devices=sum(d.get('processes_known') is True and not d.get('processes') and d.get('health')!='Alarm' for d in ds) if result['fresh'] else 0,
            occupied_devices=sum(bool(d.get('processes')) for d in ds) if result['fresh'] else 0,
            unknown_devices=sum(d.get('processes_known') is not True for d in ds) if result['fresh'] else len(ds),
            alarm_devices=sum(d.get('health')=='Alarm' for d in ds)))
    result.update(system=copy.deepcopy(snap.get('system')),count_unit=unit(devices),device_groups=groups)
    return result


def query_hosts(hosts, tool, options=None, now=None):
    options=options or {};now=time.time() if now is None else now
    max_age=options.get('max_age',30)
    ordered=sorted(hosts,key=lambda h:(h['target'].casefold(),h['id']))
    name=(options.get('name') or '').casefold()
    ordered=[h for h in ordered if name in h['target'].casefold()]
    if tool=='get_host' or (tool=='get_resources' and options.get('host_id')):
        host=resolve_host(hosts,options['host_id'])
        result=compact_resource(host,now,max_age) if tool=='get_host' else resource(host,now,max_age)
        if tool=='get_host':
            result.update(manual=bool(host.get('manual')),user=host.get('user'),port=host.get('port'))
        error=None
        if options.get('refresh') and not result['fresh']:
            error=AgentError('STALE_SNAPSHOT','未取得所需新鲜采样。',recovery('STALE_SNAPSHOT',host['id']))
        return response({'host' if tool=='get_host' else 'resource':result},error,bool(error))
    if tool=='list_hosts':
        return response(dict(items=[summary(h,now,max_age) for h in ordered]))
    if tool=='get_resources':
        items=[compact_resource(h,now,max_age) for h in ordered]
        stale=options.get('refresh') and any(not h['fresh'] for h in items)
        return response(dict(items=items),AgentError('STALE_SNAPSHOT','部分机器未取得新鲜采样。') if stale else None,bool(stale))
    if tool!='search_hosts':
        raise AgentError('INVALID_ARGUMENT','不支持的查询工具。')
    count=options.get('count',1);minimum=options.get('min_free_gib',0)*GIB
    kind=options.get('kind');model=(options.get('model') or '').casefold()
    items=[];excluded=[];uncertain=False
    for host in ordered:
        snap=host.get('snapshot') or {};all_devices=snap.get('devices') or []
        item=summary(host,now,max_age)
        matching=[d for d in all_devices if (not kind or d['kind']==kind) and model in d.get('name','').casefold()]
        if all_devices and not matching:
            excluded.append(dict(host_id=host['id'],alias=host['target'],reason_code='DEVICE_FILTER_MISMATCH'))
            continue
        if not item['fresh'] or not all_devices:
            uncertain=True
            excluded.append(dict(host_id=host['id'],alias=host['target'],reason_code='STALE_SNAPSHOT' if all_devices else 'UNKNOWN_DEVICES',
                                 status=item['status'],age_seconds=item['age_seconds']))
            continue
        groups=[];best=0;unknown=False;failures=[]
        for device_kind in sorted({d['kind'] for d in matching}):
            ds=[d for d in matching if d['kind']==device_kind];eligible=[]
            for d in ds:
                reason=None;free=d.get('memory_free')
                if d.get('health')=='Alarm':reason='DEVICE_ALARM'
                elif free is None:reason='UNKNOWN_MEMORY';unknown=True
                elif free<minimum:reason='INSUFFICIENT_MEMORY'
                elif options.get('idle',True) and not d.get('processes_known'):reason='UNKNOWN_PROCESSES';unknown=True
                elif options.get('idle',True) and d.get('processes'):reason='PROCESS_BUSY'
                if reason:
                    failures.append(dict(device_id=d['id'],reason_code=reason,memory_free_bytes=free,minimum_free_bytes=minimum))
                else:eligible.append(d)
            best=max(best,len(eligible))
            if len(eligible)>=count:
                groups.append(dict(kind=device_kind,count_unit=unit(ds),eligible_count=len(eligible),
                                   eligible_device_ids=[d['id'] for d in eligible],
                                   devices=[{k:d.get(k) for k in ('id','kind','name','memory_free','memory_total','health','card_id','chip_id','physical_id','display_id','uuid')} for d in eligible]))
        if groups:
            item['matched_groups']=groups;items.append(item)
        else:
            uncertain|=unknown
            excluded.append(dict(host_id=host['id'],alias=host['target'],reason_code='UNKNOWN_RESOURCE_STATE' if unknown else 'INSUFFICIENT_DEVICES',
                                 required_count=count,eligible_count=best,missing_count=max(0,count-best),device_reasons=failures))
    error=AgentError('INCOMPLETE_RESOURCE_QUERY','部分机器资源无法确认；有效结果仍保留。',
                     dict(tool='search_hosts',arguments=dict(options,refresh=True),message='保留原始条件更新采样；查看 excluded 中未知状态或采集权限原因。')) if uncertain else None
    return response(dict(items=items,excluded=excluded),error,uncertain)
