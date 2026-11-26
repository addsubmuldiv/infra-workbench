"""Compact MCP views for the same historical statistics used by the dashboard."""
from backend.common.agent_errors import AgentError
from .mcp_output import page

PAGE_PARAMETERS = {
    'offset': {'type': 'integer', 'minimum': 0, 'default': 0},
    'limit': {'type': 'integer', 'minimum': 1, 'maximum': 50, 'default': 20},
}
HOST_ID = {'type': 'string', 'minLength': 1, 'maxLength': 200, 'pattern': r'^[^,\s]+$'}
ABSOLUTE_TIME = {'type': ['string', 'number'], 'description': 'Unix 秒或包含时区的 ISO 8601 时间。'}
HISTORY_PARAMETERS = {
    'host_ids': {'type': 'array', 'minItems': 1, 'maxItems': 100, 'uniqueItems': True, 'items': HOST_ID},
    'date': {'type': 'string', 'pattern': r'^\d{4}-\d{2}-\d{2}$', 'description': '当地日期；与 from/to 二选一。'},
    'timezone': {'type': 'string', 'minLength': 1, 'maxLength': 100, 'default': 'UTC'},
    'kind': {'type': 'string', 'enum': ['GPU', 'NPU'], 'default': 'GPU'},
    'from': ABSOLUTE_TIME,
    'to': ABSOLUTE_TIME,
    'window_hours': {'type': 'integer', 'enum': [1, 3, 6, 12], 'description': '日期内最近几小时。'},
    'start_time': {'type': 'string', 'pattern': r'^\d{2}:\d{2}$'},
    'end_time': {'type': 'string', 'pattern': r'^\d{2}:\d{2}$'},
    'view': {'type': 'string', 'enum': ['summary', 'segments'], 'default': 'summary'},
    'segment_host_id': dict(HOST_ID, description='仅 view=segments 时使用；必须来自 host_ids。省略则返回整组时段。'),
    **PAGE_PARAMETERS,
}


def history_query(arguments, allowed):
    ids = arguments['host_ids']
    if allowed is not None and not set(ids) <= allowed:
        raise AgentError('HOST_NOT_FOUND', '历史查询包含不在当前范围内的机器。')
    host_id = arguments.get('segment_host_id')
    if host_id is not None and (host_id not in ids or arguments.get('view') != 'segments'):
        raise AgentError('INVALID_ARGUMENT', '请在 segments 视图中从 host_ids 选择逐机时段。')
    if 'date' not in arguments and not {'from', 'to'} <= arguments.keys():
        raise AgentError('INVALID_ARGUMENT', '请指定 date 或同时提供 from 和 to。')
    query = {k: v for k, v in arguments.items() if k not in ('view', 'segment_host_id', 'offset', 'limit')}
    query['host_ids'] = ','.join(ids)
    return query


def history_view(value, arguments):
    result = {k: v for k, v in value.items() if k not in ('hosts', 'segments')}
    view = arguments.get('view', 'summary')
    host_id = arguments.get('segment_host_id')
    if view == 'summary':
        items = [{k: v for k, v in host.items() if k != 'segments'} for host in value['hosts']]
    elif host_id is None:
        items = value['segments']
    else:
        host = next(host for host in value['hosts'] if host['host_id'] == host_id)
        items = host['segments']
        result['host_summary'] = host['summary']
    return dict(result, view=view, segment_host_id=host_id, host_count=len(value['hosts']),
                **page(items, arguments.get('offset', 0), arguments.get('limit', 20), budget=8000))
