"""Match spreadsheet rows to existing hosts without changing SSH configuration."""
from .server_import import WorkbookError
from .ssh_passwords import connection_identity


async def configurations(hosts,ssh):
    values={}
    for host in hosts:
        try:
            values[host['id']]=(dict(hostname=host['target'],user=host.get('user'),port=str(host.get('port') or 22))
                                if host.get('manual') else await ssh.effective_details(host))
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
        if str(cfg.get('hostname','')).casefold()==row.target.casefold():candidates.append(host)
    candidates=named or candidates
    if len(candidates)>1:
        raise WorkbookError('匹配到多台已有机器，请在 IP / 主机列填写唯一 SSH 别名后重新导入')
    return candidates[0] if candidates else None


async def find_existing(row,hosts,ssh):
    selected=[h for h in hosts if not row.host_id or h['id']==row.host_id]
    return choose_existing(row,hosts,await configurations(selected,ssh))


async def prepare_existing(rows,hosts,ssh):
    # Resolve each alias only once per preview, rather than once per Excel row.
    configs=await configurations(list(hosts),ssh);seen={}
    for row in rows:
        if row.status!='ready':continue
        try:
            host=choose_existing(row,hosts,configs)
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
