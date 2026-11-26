"""Semantic output budgets: shorten pages, never identifiers or nested records."""
import copy
import json


def page(items, offset=0, limit=20, budget=10000):
    selected=[];size=0
    for item in items[offset:offset+limit]:
        length=len(json.dumps(item,ensure_ascii=False))
        if selected and size+length>budget:
            break
        selected.append(item);size+=length
    end=offset+len(selected)
    return dict(items=selected,total=len(items),offset=offset,
                next_offset=end if end<len(items) else None,has_more=end<len(items))


def shorten_page(value, arguments=None):
    """Only adjust known numeric row cursors; byte/journal cursors are opaque."""
    result=copy.deepcopy(value)
    data=result.get('data') if isinstance(result,dict) else None
    if not isinstance(data,dict):return None
    key=next((k for k in ('items','entries','events') if isinstance(data.get(k),list)),None)
    if key is None or not isinstance(data.get('next_offset'),int) or 'next_cursor' in data:
        return None
    rows=data[key]
    start=data.get('offset',(arguments or {}).get('offset'))
    if start is None:start=data['next_offset']-len(rows)
    if not isinstance(start,int) or start<0:return None
    data[key]=[];data.update(next_offset=start,has_more=True,truncated=True)
    result['partial']=True
    size=len(json.dumps(result,ensure_ascii=False));count=0
    for row in rows[:-1]:
        size+=len(json.dumps(row,ensure_ascii=False))+2
        if size>14500:break
        count+=1
    if count:
        data[key]=rows[:count];data['next_offset']=start+count
        return result
    return None
