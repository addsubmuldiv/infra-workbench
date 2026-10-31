"""Transport-independent agent errors with usable, structured recovery steps."""

def recovery(code,host_id=None):
    if code in ('HOST_NOT_FOUND','AMBIGUOUS_HOST'):
        return dict(tool='list_hosts',arguments={},message='读取真实 host_id 后重试；同名机器不要猜测。')
    if code in ('STALE_SNAPSHOT','INCOMPLETE_RESOURCE_QUERY'):
        return dict(tool='get_resources',arguments=dict(host_id=host_id,refresh=True) if host_id else dict(refresh=True),
                    message='更新采样并查看逐机状态；仍有 unknown 时检查机器连接和采集权限。')
    if code in ('SSH_PASSWORD_UNAVAILABLE','CREDENTIAL_IDENTITY_CHANGED','CREDENTIAL_STORE_UNAVAILABLE'):
        return dict(user_action='在 Workbench 中打开对应机器的 SSH 密码设置，核对账号和目标后验证保存；也可使用自己的密钥。',host_id=host_id)
    if code=='SSH_CONFIG_UNRESOLVED':
        return dict(user_action='在电脑上核对该机器的 SSH 别名、账号、跳板和配置文件。',host_id=host_id)
    return dict(user_action='按 tools/list 中此工具的 inputSchema 修正参数；只用已公布的工具和参数。')


class AgentError(Exception):
    def __init__(self,code,message,next_action=None):
        self.code,self.message=code,message
        self.next_action=next_action if isinstance(next_action,dict) else recovery(code)
        super().__init__(code+': '+message)

    def as_dict(self):
        return dict(code=self.code,message=self.message,next_action=self.next_action)


def response(data=None,error=None,partial=False,warnings=None):
    return dict(schema_version='1',ok=error is None,partial=partial,data=data,
                warnings=warnings or [],error=error.as_dict() if error else None)
