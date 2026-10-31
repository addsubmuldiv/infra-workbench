"""Publish application-owned skills and truthful UI/transport handoffs."""
import re
from pathlib import Path

from .agent_errors import AgentError, response
from .agent_schema import envelope

ROOT = Path(__file__).with_name('skills')
ENTRIES = {
    'credentials': 'SSH、sudo、模型和邮箱凭据在软件连接/设置界面输入和保存，不经模型传递。',
    'server_import': '在服务器导入界面选择 Excel，或客户端以原始字节 POST /api/imports/preview（上限 2 MiB，X-IWB: 1）。然后用 get_import_status/start_import。',
    'upload': '先 create_upload，再由本机客户端以原始字节 PUT /api/files/uploads/{id}，X-IWB: 1。文件夹使用应用规定的归档格式。get_upload 查询状态。',
    'terminal': '在软件终端界面选择机器。客户端 POST /api/hosts/{host_id}/terminal-ticket（X-IWB: 1）取得短效票据，再连接同源 WebSocket /api/terminal/{host_id}，子协议 iwb-terminal 和票据。MCP 不转发交互键盘或任意命令。',
    'model_settings': '在设置 → Agent 模型接口选择模型、填写地址与凭据并测试，不允许当前 Agent 修改自身模型连接。',
    'mail_settings': '在设置 → 邮件通知配置邮箱和授权码；get_mail_settings 只读查看可用状态。',
}


def spec(name, description, properties, required):
    return dict(name=name, title=description, description=description,
                inputSchema=dict(type='object', properties=properties, required=required, additionalProperties=False),
                outputSchema=envelope({}), annotations=dict(readOnlyHint=True, destructiveHint=False, idempotentHint=True))


CATALOG = {
    'list_skills': spec('list_skills', '列出软件内置业务技能及适用说明，按需 read_skill。', {}, []),
    'read_skill': spec('read_skill', '读取一个内置业务技能的完整说明，不接受文件路径。',
                       {'name': {'type': 'string', 'pattern': '^[a-z0-9-]{1,100}$'}}, ['name']),
    'get_workbench_entry': spec('get_workbench_entry', '查询凭据配置、导入、上传或交互终端的客户端交接方式；不会执行这些操作。',
                               {'feature': {'type': 'string', 'enum': list(ENTRIES)}}, ['feature']),
}


def call(name, args):
    if name == 'get_workbench_entry':
        return response(dict(status='handoff_required', feature=args['feature'], instructions=ENTRIES[args['feature']]))
    if name == 'read_skill':
        key = args['name']
        if not re.fullmatch(r'[a-z0-9-]{1,100}', key):
            raise AgentError('INVALID_ARGUMENT', '技能名称无效。')
        path = ROOT / key / 'SKILL.md'
        if not path.is_file():
            raise AgentError('SKILL_NOT_FOUND', '没有此内置技能，请先 list_skills。')
        return response(dict(name=key, content=path.read_text(encoding='utf-8')))
    items = []
    for path in sorted(ROOT.glob('*/SKILL.md')):
        text = path.read_text(encoding='utf-8')
        description = next((line[len('description:'):].strip() for line in text.splitlines() if line.startswith('description:')), '')
        items.append(dict(name=path.parent.name, description=description))
    return response(dict(items=items))
