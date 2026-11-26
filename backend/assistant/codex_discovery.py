"""Read-only native Codex model/skill metadata. No credentials leave the CLI."""
import asyncio
import os
from pathlib import Path


def extension_choices(config=None):
    import tomllib
    home=Path(os.environ.get('CODEX_HOME',str(Path.home()/'.codex')))
    if config is None:
        try:
            with (home/'config.toml').open('rb') as stream:config=tomllib.load(stream)
        except (OSError,ValueError):config={}
    # Only names and flags; URLs, headers, process env and auth never enter response.
    return {
        'mcp_servers':[{'name':name,'enabled':bool(value.get('enabled',True))}
                       for name,value in config.get('mcp_servers',{}).items() if isinstance(value,dict) and name!='infra_workbench'],
        'plugins':[{'id':name,'name':name,'enabled':bool(value.get('enabled',False))}
                   for name,value in config.get('plugins',{}).items() if isinstance(value,dict)],
    }


async def discover_codex(cwd=''):
    from .codex_agent import CodexConnection,resolve_codex
    if cwd and (not Path(cwd).is_absolute() or not Path(cwd).is_dir()):
        raise ValueError('Codex 工作目录不存在或不是绝对路径')
    limitations=[]
    connection=CodexConnection(resolve_codex())
    try:
        async with asyncio.timeout(60):
            await connection.start()
            effective_config=(await connection.request('config/read',{'cwd':cwd or None,'includeLayers':False})).get('config',{})
            choices=extension_choices(effective_config)
            del effective_config
            models=[];cursor=None
            for _ in range(10):
                params={'cursor':cursor} if cursor else {}
                result=await connection.request('model/list',params)
                for model in result.get('data',[]):
                    models.append({key:model[key] for key in ('id','displayName','isDefault','supportedReasoningEfforts','defaultReasoningEffort') if key in model})
                cursor=result.get('nextCursor')
                if not cursor:break
            if cursor:limitations.append('模型目录尚有更多页 / More model pages are available')
            if not models:raise ValueError('Codex 未返回可用模型，请检查 CLI 登录和网络')
            account={'status':'unknown'}
            try:
                result=await connection.request('account/read',{'refreshToken':False})
                value=result.get('account')
                account['status']=value.get('type','authenticated') if isinstance(value,dict) else 'login_required'
            except ValueError:limitations.append('CLI 不支持账号状态查询 / Account status query unavailable')
            skills=[];skills_supported=True
            try:
                result=await connection.request('skills/list',{'cwds':[cwd] if cwd else [],'forceReload':False})
                for group in result.get('data',[]):
                    for skill in group.get('skills',[]):
                        skills.append({key:skill[key] for key in ('name','description','path','enabled','scope') if key in skill})
                    if group.get('errors'):limitations.append('部分 Codex 技能无法加载 / Some Codex skills could not be loaded')
            except ValueError:
                skills_supported=False
                limitations.append('CLI 不支持原生技能发现 / Native skill discovery unavailable')
            features={}
            try:
                cursor=None
                for _ in range(10):
                    result=await connection.request('experimentalFeature/list',{'limit':200,**({'cursor':cursor} if cursor else {})})
                    features.update({item['name']:item for item in result.get('data',[])})
                    cursor=result.get('nextCursor')
                    if not cursor:break
            except ValueError:
                limitations.append('CLI 不支持功能探测，请升级后使用原生多 Agent / Feature detection unavailable; upgrade the CLI for native multi-agent')
            supported=lambda name: name in features and features[name].get('stage') not in ('removed','deprecated')
            # These are protocol integration capabilities; real model availability is tested per turn.
            limitations.append('当前宿主未开放原生浏览器、电脑控制和图像生成；支持原生联网搜索和本机图片读取。插件能力还取决于 CLI 和账号 / Native browser, computer control and image generation are not exposed by this host; native web search and local image reading are supported. Plugin capabilities also depend on the CLI and account')
            return dict(models=models,skills=skills,account=account,**choices,
                        capabilities=dict(native_tools=supported('shell_tool'),multi_agent=supported('multi_agent'),skills=skills_supported,extensions=supported('plugins'),limitations=limitations))
    finally:
        await connection.close()
