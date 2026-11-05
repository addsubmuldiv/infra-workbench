"""Compact resource views with separate, lossless process text pages."""
from .mcp_output import page


def resource_view(result, options):
    from .chat_tools import scrub
    devices=result['devices']
    by_pid={}
    for device in devices:
        for proc in device.get('processes',[]):
            pid=proc.get('pid')
            if pid is None:continue
            record=by_pid.setdefault(pid,dict({k:v for k,v in proc.items() if k!='memory_used'},device_ids=[],device_memory_used={}))
            if device['id'] not in record['device_ids']:record['device_ids'].append(device['id'])
            record['device_memory_used'][device['id']]=proc.get('memory_used')
    known=result['fresh'] and bool(devices) and all(d.get('processes_known') is True for d in devices)
    result.update(process_count=len(by_pid) if known else None,
                  observed_process_count=len(by_pid),process_count_complete=known)
    result['view']=options.get('view','summary')
    if result['view']=='detail':return result
    if result['view']=='processes':
        rows=[];start=options.get('text_offset',0);length=options.get('text_limit',500)
        for pid in sorted(by_pid):
            if options.get('pid') is not None and pid!=options['pid']:continue
            record=by_pid[pid]
            total=0
            for key in ('command','cwd','executable','name'):
                value=record.get(key)
                if isinstance(value,str):
                    # Redact the complete field before paging: a secret split
                    # across two chunks must not bypass per-response scrubbing.
                    value=scrub(value)
                    total=max(total,len(value));record[key]=value[start:start+length]
            record.update(text_offset=start,text_total_chars=total,
                          text_next_offset=start+length if start+length<total else None,
                          text_truncated=start>0 or start+length<total)
            rows.append(record)
        result.pop('devices')
        result.update(page(rows,options.get('offset',0),options.get('limit',5),budget=8000))
        return result
    for device in devices:
        # Per-card memory usage remains per-card; command identity is queried
        # once per PID using view=processes instead of repeated for every card.
        processes=device.get('processes',[])
        device.update(process_count=len(processes) if result['fresh'] and device.get('processes_known') is True else None,
                      observed_process_count=len(processes),processes_truncated=len(processes)>20)
        device['processes']=[{key:p[key] for key in ('pid','memory_used') if key in p}
                             for p in processes[:20]]
    selected=page(devices,options.get('device_offset',0),options.get('device_limit',10),budget=8000)
    result.update(devices=selected['items'],device_offset=selected['offset'],
                  next_device_offset=selected['next_offset'],devices_has_more=selected['has_more'],
                  process_details=dict(tool='get_resources',arguments=dict(host_id=result['host_id'],view='processes')))
    return result
