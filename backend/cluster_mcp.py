"""Cluster tools use the same validated services as the HTTP interface."""
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field
from .agent_errors import response
from .agent_schema import envelope
from .cluster_routes import CreateCluster, BatchCommand
from .cluster_terminals import TerminalBatchArgs

class Empty(BaseModel):
    model_config=ConfigDict(extra='forbid')

class ClusterID(Empty):
    cluster_id:str

class Revision(ClusterID):
    revision:int=Field(ge=1)

class Rename(Revision):
    name:str=Field(min_length=1,max_length=80)

class Members(Revision):
    host_ids:list[str]=Field(max_length=10000,description='明确指定最终成员集合；可将已有机器移动到此集群。')

class BatchID(Empty):
    batch_id:str

class BatchPage(BatchID):
    offset:int=Field(default=0,ge=0)
    limit:int=Field(default=100,ge=1,le=100)

class Output(BatchID):
    item_id:str
    stream:Literal['stdout','stderr']='stdout'
    offset:int=Field(default=0,ge=0,le=1048576)

class Cancel(BatchID):
    item_ids:list[str]|None=Field(default=None,min_length=1,max_length=100,description='省略时取消整个批次，必须有全部目标机器权限。')

DEFINITIONS={
    'list_clusters':(Empty,'列出集群；受限会话只显示当前允许的机器，不包含隐藏成员名称和数量。',True),
    'get_cluster':(ClusterID,'读取集群 revision 和当前允许的成员，执行前重新核对目标。',True),
    'create_cluster':(CreateCluster,'创建单层集群，可明确指定已有机器；不会修改 SSH 配置。',False),
    'update_cluster':(Rename,'用期望 revision 重命名集群；必须拥有全部成员范围。',False),
    'delete_cluster':(Revision,'删除集群并解除成员归类，保留机器及历史任务；导入进行中不可删除。',False),
    'update_cluster_members':(Members,'用期望 revision 替换集群成员集合，可移动机器；必须拥有相关集群全部成员范围。',False),
    'open_cluster_terminals':(TerminalBatchArgs,'创建本次专用的持久终端会话，最多 100 台、并发 5；返回逐机结果和应用工作区入口。返回入口不代表客户端已经打开窗口；不安装依赖。',False),
    'execute_cluster_command':(BatchCommand,'提交用户授权的相同 Shell 命令，固定目标与 revision；request_id 防止重复提交。默认需要整个集群权限，可显式指定授权 host_ids 子集。不会自动重试。命令正文保存在本地历史，请勿包含明文凭据。',False),
    'list_cluster_command_batches':(Empty,'列出当前允许范围内的批量命令记录，不返回命令正文摘要。',True),
    'get_cluster_command_batch':(BatchPage,'分页读取允许范围内的逐机状态与汇总；unknown 不能当作停止或完成。',True),
    'get_cluster_command_output':(Output,'读取指定授权成员的有界 stdout 或 stderr；临时远端输出可能已被清理。',True),
    'cancel_cluster_command_batch':(Cancel,'停止排队项并取消指定运行项；整个批次取消需要全部成员权限。请求取消不代表已停止，不回滚已有副作用。',False),
    'resume_cluster_command_batch':(BatchID,'用户明确要求后继续后端重启时暂停的未启动项；需全部批次目标权限。',False),
}

def catalog():
    return {name:dict(name=name,title=desc.split('；')[0],description=desc,inputSchema=model.model_json_schema(),outputSchema=envelope({}),annotations=dict(readOnlyHint=read,destructiveHint=not read,idempotentHint=read,openWorldHint=True)) for name,(model,desc,read) in DEFINITIONS.items()}

async def call(app,name,arguments,allowed=None):
    args=DEFINITIONS[name][0].model_validate(arguments).model_dump()
    service=app.state.clusters
    if name=='list_clusters':data=service.list(allowed)
    elif name=='get_cluster':data=service.get(args['cluster_id'],allowed)
    elif name=='create_cluster':data=service.create(args['name'],args['host_ids'],allowed)
    elif name=='update_cluster':data=service.update(args['cluster_id'],args['name'],args['revision'],allowed)
    elif name=='delete_cluster':data=service.delete(args['cluster_id'],args['revision'],allowed)
    elif name=='update_cluster_members':data=service.members(args['cluster_id'],args['host_ids'],args['revision'],allowed)
    elif name=='open_cluster_terminals':data=await app.state.cluster_terminals.create(args,allowed)
    elif name=='execute_cluster_command':data=await service.submit(args,allowed)
    elif name=='list_cluster_command_batches':data=await service.batches(allowed)
    elif name=='get_cluster_command_batch':
        data=await service.batch(args['batch_id'],allowed)
        items=data['items'];start=args['offset'];end=start+args['limit']
        data.update(items=items[start:end],offset=start,next_offset=min(end,len(items)),has_more=end<len(items))
    elif name=='get_cluster_command_output':data=await service.output(args['batch_id'],args['item_id'],args['stream'],args['offset'],allowed)
    elif name=='cancel_cluster_command_batch':data=await service.cancel(args['batch_id'],args['item_ids'],allowed)
    elif name=='resume_cluster_command_batch':data=await service.resume(args['batch_id'],allowed)
    limited=allowed is not None
    return response(data,partial=limited,warnings=['仅显示或操作当前允许的机器范围。'] if limited else None)
