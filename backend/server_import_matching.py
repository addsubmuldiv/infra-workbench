"""Match spreadsheet rows to existing hosts without changing SSH configuration."""
from pathlib import Path

from .core import discover_aliases
from .server_import import WorkbookError
from .ssh_passwords import connection_identity


def new_import_host(row):
    alias = row.target.casefold() in {name.casefold() for name in discover_aliases(Path.home()/'.ssh'/'config')}
    return dict(target=row.target, user=row.user,
                port=row.port if row.port_explicit or not alias else None, manual=not alias)


async def resolve_row(row, ssh):
    candidate = new_import_host(row)
    try:
        config = await ssh.effective_details(candidate)
        resolved_identity = connection_identity(config)
        if row.resolved_identity and row.resolved_identity != resolved_identity:
            raise WorkbookError('导入预览后 SSH 别名配置已变化，请重新选择 Excel 并核对')
        if not row.port_explicit:
            row.port = int(config.get('port') or 22)
        if row.resolved_identity is None:
            row.resolved_identity = resolved_identity
    except WorkbookError:
        raise
    except Exception:
        raise WorkbookError('无法解析本机 SSH 别名，请检查 SSH 配置后重新选择 Excel') from None


async def configurations(hosts,ssh):
    values={}
    for host in hosts:
        try:
            values[host['id']]=await ssh.effective_details(host)
        except Exception:
            values[host['id']]=None
    return values


def choose_existing(row,hosts,configs):
    if row.host_id:
        host=next((h for h in hosts if h['id']==row.host_id),None)
        cfg=configs.get(row.host_id)
        if host is None or cfg is None or connection_identity(cfg)!=row.expected_identity:
            raise WorkbookError('已有机器的配置已变化或已删除，请重新选择 Excel 并核对后再保存密码')
        return host
    candidates=[];named=[]
    for host in hosts:
        cfg=configs.get(host['id'])
        if cfg is None:
            if host['target'].casefold()==row.target.casefold():
                raise WorkbookError('无法解析已有机器的 SSH 配置，请修复后重新选择 Excel')
            continue
        if cfg.get('user')!=row.user or int(cfg.get('port') or 22)!=row.port:continue
        if host['target'].casefold()==row.target.casefold():named.append(host)
        if (str(cfg.get('hostname','')).casefold()==row.target.casefold()
                or row.resolved_identity and connection_identity(cfg)==row.resolved_identity):candidates.append(host)
    candidates=named or candidates
    if len(candidates)>1:
        raise WorkbookError('匹配到多台已有机器，请在 IP / 主机列填写唯一 SSH 别名后重新导入')
    return candidates[0] if candidates else None


async def find_existing(row,hosts,ssh):
    await resolve_row(row,ssh)
    selected=[h for h in hosts if not row.host_id or h['id']==row.host_id]
    return choose_existing(row,hosts,await configurations(selected,ssh))


async def prepare_existing(rows,hosts,ssh):
    # Resolve existing hosts once; each row may override its alias user or port.
    configs=await configurations(list(hosts),ssh);seen={};seen_targets={}
    for row in rows:
        if row.status!='ready':continue
        try:
            await resolve_row(row,ssh)
            host=choose_existing(row,hosts,configs)
            target_identity=row.resolved_identity or (row.target.casefold(),row.user,row.port)
            if target_identity in seen_targets:
                row.status='skipped';row.reason=f'与文件第 {seen_targets[target_identity]} 行指向同一 SSH 目标，已跳过'
                row.password=None
                if row.password_status=='pending':row.password_status='not_saved';row.password_reason='重复目标，未保存本行密码'
                continue
            seen_targets[target_identity]=row.row
            if not host:continue
            row.host_id=host['id'];row.expected_identity=connection_identity(configs[host['id']])
            if host['id'] in seen:
                row.status='skipped';row.reason=f'与文件第 {seen[host["id"]]} 行指向同一台已有机器，已跳过'
                row.password=None
                if row.password_status=='pending':row.password_status='not_saved';row.password_reason='重复目标，未保存本行密码'
            else:
                seen[host['id']]=row.row
                row.reason='已匹配 '+host['target']+'；将验证并补存 SSH 密码，保留原配置'
        except WorkbookError as exc:
            row.status='invalid';row.reason=str(exc);row.password=None
            if row.password_status=='pending':row.password_status='not_saved';row.password_reason='未能唯一确认已有机器，未保存密码'
