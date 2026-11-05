from .internal_defaults import SKILLS_MAX_FILES, SKILLS_FILE_MAX_BYTES, IMPORTS_WORKBOOK_MAX_BYTES, format_bytes
"""Publish application-owned skills and truthful UI/transport handoffs."""
import re
from pathlib import Path

from .agent_errors import AgentError, response
from .agent_schema import envelope

ROOT = Path(__file__).with_name('skills')
ENTRIES = {
    'credentials': 'SSH、sudo、模型和邮箱凭据在软件连接/设置界面输入和保存，不经模型传递。',
    'server_import': f'在服务器导入界面选择 Excel，或客户端以原始字节 POST /api/imports/preview（上限 {format_bytes(IMPORTS_WORKBOOK_MAX_BYTES)}，X-IWB: 1）。然后用 get_import_status/start_import。',
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


# Management tools write only to the application-owned user skill store.
FILES = {'type': 'object', 'minProperties': 1, 'maxProperties': SKILLS_MAX_FILES,
         'additionalProperties': {'type': 'string', 'maxLength': SKILLS_FILE_MAX_BYTES}}
REV = {'type': 'integer', 'minimum': 1}
NAME = {'type': 'string', 'pattern': '^[a-z0-9]+(?:-[a-z0-9]+)*$', 'maxLength': 64}

def management_spec(name, description, properties, required, readonly=False):
    value = spec(name, description, properties, required)
    value['annotations']['readOnlyHint'] = readonly
    value['annotations']['idempotentHint'] = readonly
    return value

MANAGEMENT = {
    'list_managed_skills': management_spec('list_managed_skills', '管理用途：列出所有内置和用户技能，含停用状态及最新版本。激活技能列表以本轮 list_skills 快照为准。', {}, [], True),
    'list_skill_drafts': management_spec('list_skill_drafts', '列出尚未安装的持久化技能草稿，用 get_skill_draft 继续编辑。', {}, [], True),
    'inspect_skill': management_spec('inspect_skill', '管理用途：读取当前或历史技能版本，包括停用技能。内容仅供编辑参考，不改变本轮激活快照。', {'name':NAME, 'version':REV}, ['name'], True),
    'get_skill_draft': management_spec('get_skill_draft', '读取技能草稿及修订号。', {'draft_id': {'type':'string'}}, ['draft_id'], True),
    'create_skill_draft': management_spec('create_skill_draft', '生成用户技能草稿，不安装。files 的键为包内相对路径，必须含 SKILL.md；name/description 遵循 Agent Skills 标准。声明依赖用 metadata.workbench-required-tools（空格分隔）。更新需传 skill_name 和 base_version；复制内置技能必须使用新名称。',
        {'files': FILES, 'skill_name': NAME, 'base_version': REV}, ['files']),
    'update_skill_draft': management_spec('update_skill_draft', '替换草稿文本文件，需要当前修订号；只改草稿，不改变已安装技能。',
        {'draft_id': {'type':'string'}, 'revision': REV, 'files': FILES}, ['draft_id','revision','files']),
    'validate_skill_draft': management_spec('validate_skill_draft', '检查草稿格式、文件引用和声明的工具依赖；通过不代表实际运行成功。',
        {'draft_id': {'type':'string'}, 'revision': REV}, ['draft_id','revision'], True),
    'install_skill_draft': management_spec('install_skill_draft', '仅在用户明确要求安装或更新技能时调用。重新校验指定草稿修订，安装不可变版本；下一轮生效，不能增加工具权限。',
        {'draft_id': {'type':'string'}, 'revision': REV}, ['draft_id','revision']),
    'set_skill_enabled': management_spec('set_skill_enabled', '按用户要求启用或停用用户技能，下一轮生效。内置技能不可修改。',
        {'name': NAME, 'enabled': {'type':'boolean'}, 'expected_version': REV}, ['name','enabled','expected_version']),
    'rollback_skill': management_spec('rollback_skill', '按用户要求将用户技能切换到指定历史版本，下一轮生效。',
        {'name': NAME, 'version': REV, 'expected_version': REV}, ['name','version','expected_version']),
}

def skill_catalog():
    catalog = dict(CATALOG, **MANAGEMENT)
    catalog['list_skills'] = spec('list_skills', '内置 Agent 列出本轮启用的技能快照；外部客户端列出当前技能库。管理含停用技能请用 list_managed_skills。', {}, [])
    catalog['read_skill'] = spec('read_skill', '按需读取一个技能正文或指定文本附件；默认只返回正文一份，字符分页。读取不表示执行。',
        {'name': NAME, 'version': REV,'path':{'type':'string','default':'SKILL.md'},
         'offset':{'type':'integer','minimum':0,'default':0},'limit':{'type':'integer','minimum':1,'maximum':6000,'default':4000}}, ['name'])
    for name in ('inspect_skill','get_skill_draft'):
        catalog[name]=dict(catalog[name],inputSchema=dict(catalog[name]['inputSchema'],properties=dict(
            catalog[name]['inputSchema']['properties'],path={'type':'string','default':'SKILL.md'},
            offset={'type':'integer','minimum':0,'default':0},limit={'type':'integer','minimum':1,'maximum':6000,'default':4000})))
    return catalog


def skill_read_view(data, args):
    path=args.get('path','SKILL.md')
    if path not in data.get('files',{}):raise AgentError('SKILL_FILE_NOT_FOUND','技能文本附件不存在。')
    text=data['files'][path];start=args.get('offset',0);end=start+args.get('limit',4000)
    value={k:v for k,v in data.items() if k not in ('files','versions','raw','content')}
    value.update(path=path,content=text[start:end],offset=start,total_chars=len(text),
                 next_offset=end if end<len(text) else None,truncated=start>0 or end<len(text))
    value['available_versions']=[v['version'] for v in data.get('versions',[])][:100]
    return value

def registry_call(service, name, args, tools):
    from .skill_service import SkillError
    try:
        if name == 'get_workbench_entry':
            return call(name, args)
        if name == 'list_skill_drafts':
            data = {'items': service.list_drafts()}
        elif name in ('list_skills', 'list_managed_skills'):
            data = {'items': service.catalog()}
        elif name in ('read_skill', 'inspect_skill'):
            data = service.read(args['name'],args.get('version'))
            data = skill_read_view(data,args)
        elif name == 'get_skill_draft':
            data = service.read_draft(args['draft_id'])
            data = skill_read_view(data,args)
        elif name in ('validate_skill_draft', 'install_skill_draft'):
            data = getattr(service, name.replace('_skill', ''))(args['draft_id'], args['revision'], list(tools))
        elif name == 'update_skill_draft':
            data = service.update_draft(args['draft_id'], args['revision'], args['files'])
        elif name == 'set_skill_enabled':
            data = service.set_enabled(**args)
        elif name == 'rollback_skill':
            data = service.rollback(**args)
        else:
            data = service.create_draft(**args)
        if name in ('create_skill_draft','update_skill_draft'):
            data={k:v for k,v in data.items() if k not in ('files','raw')}
        return response(data)
    except SkillError as exc:
        raise AgentError(exc.code, str(exc), {'user_action':'检查草稿、版本或工具依赖；冲突时重新读取最新版本，不盲目覆盖。'}) from None
