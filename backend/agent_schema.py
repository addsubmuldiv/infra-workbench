"""Shared JSON schemas for MCP tool results; numeric memory fields use bytes."""
import copy


def obj(properties,required=()):
    return dict(type='object',properties=properties,required=list(required))
def array(item):return dict(type='array',items=item)
def scalar(kind,description='',nullable=False):
    return dict(type=[kind,'null'] if nullable else kind,description=description)
S=scalar('string');N=scalar('number',nullable=True);B=scalar('boolean')
HOST=obj(dict(host_id=S,alias=S,status=S,collected_at=scalar('number','Unix 时间戳（秒），无采样时 null。',nullable=True),age_seconds=scalar('number','采样年龄（秒），无法确定时 null。',nullable=True),fresh=B,
              device_kinds=array(S),device_count=scalar('integer'),connection_summary=obj(dict(user=scalar('string',nullable=True),port=scalar('integer',nullable=True),mode=S,software_auth=S))),('host_id','alias','status','fresh'))
PROCESS=obj({key:scalar('integer' if key in ('pid','uid','effective_uid','parent_pid','memory_used') else 'string',nullable=key!='pid') for key in ('pid','name','user','memory_used','uid','effective_uid','parent_pid','cwd','executable','command','detail_status')},('pid',))
PROCESS['properties']['memory_used']=scalar('integer','进程使用的设备显存，字节；无法读取时 null。',nullable=True)
DEVICE=obj(dict(id=S,kind=S,name=S,memory_total=N,memory_used=N,memory_free=N,utilization=N,temperature=N,
                health=S,processes_known=B,processes=array(PROCESS),card_id=scalar('string',nullable=True),chip_id=scalar('string',nullable=True),physical_id=scalar('string',nullable=True),display_id=scalar('string',nullable=True),uuid=scalar('string',nullable=True)),('id','kind','name'))
for key in ('memory_total','memory_used','memory_free'):
    DEVICE['properties'][key]=scalar('number','设备显存字节数；未知时 null。',nullable=True)
DEVICE['properties']['utilization']=scalar('number','计算利用率，百分比 0–100；未知时 null。',nullable=True)
DEVICE['properties']['temperature']=scalar('number','设备温度，摄氏度；未知时 null。',nullable=True)
RESOURCE=copy.deepcopy(HOST)
RESOURCE['properties'].update(system={'type':['object','null'],'description':'远端 /proc 指标；CPU 百分比、逻辑核数、内存字节数。','properties':dict(cpu_percent=N,cpu_cores=N,memory={'type':['object','null'],'properties':dict(memory_total=N,memory_used=N,memory_available=N)})},devices=array(DEVICE),count_unit=S,process_scope=S,error_stage=scalar('string',nullable=True))
GROUP=obj(dict(kind=S,count_unit=S,eligible_count=scalar('integer'),eligible_device_ids=array(S),devices=array(DEVICE)))
MATCH=copy.deepcopy(HOST);MATCH['properties']['matched_groups']=array(GROUP)
EXCLUSION=obj(dict(host_id=S,alias=S,reason_code=S,status=S,age_seconds=N,required_count=scalar('integer'),eligible_count=scalar('integer'),missing_count=scalar('integer'),device_reasons=array(obj(dict(device_id=S,reason_code=S,memory_free_bytes=N,minimum_free_bytes=N)))))
RESOLVED=obj(dict(computer=S,os=S,user=S))
CONNECTION=obj(dict(host_id=S,alias=S,hostname=S,user=S,port=scalar('integer'),proxy_jump=scalar('string',nullable=True),proxy_command=scalar('string',nullable=True),
                    identity_files=array(S),certificate_files=array(S),identities_only=B,identity_agent=scalar('string',nullable=True),host_key_alias=scalar('string',nullable=True),
                    user_known_hosts_files=array(S),ssh_config_path=S,ssh_argv=array(S),ssh_argv_auth_mode=S,resolved_on=RESOLVED,
                    auth=obj(dict(configured_methods=array(S),open_software_session=B,software_session_exportable=B,external_ssh_status=S,ssh_password_available=scalar('boolean',nullable=True),missing_requirements=array(S))),
                    dependencies=array({'type':'object','description':'按 type 区分密钥路径、jump、SSH agent 和本机 ProxyCommand；保留解析目标及依赖。'}),warnings=array(S)),('host_id','hostname','user','port','ssh_argv','auth'))

SUMMARY=copy.deepcopy(HOST)
SUMMARY['properties'].update(system=RESOURCE['properties']['system'],count_unit=S,
    device_groups=array(obj(dict(kind=S,name=S,count=scalar('integer'),
        memory_free_bytes_total=N,idle_devices=scalar('integer'),occupied_devices=scalar('integer'),
        unknown_devices=scalar('integer'),alarm_devices=scalar('integer')))))
HOST_DETAIL=copy.deepcopy(SUMMARY)
HOST_DETAIL['properties'].update(manual=B,user=scalar('string',nullable=True),port=scalar('integer',nullable=True))


def envelope(data_schema):
    return obj(dict(schema_version=dict(type='string',const='1'),ok=B,partial=B,
        data=dict(anyOf=[data_schema,{'type':'null'}]),warnings=array(S),
        error=dict(anyOf=[obj(dict(code=S,message=S,next_action=dict(type='object',description='下一步 MCP 工具与参数，或需要用户在 GUI 完成的动作。')),('code','message','next_action')),{'type':'null'}])),
        ('schema_version','ok','partial','data','warnings','error'))
