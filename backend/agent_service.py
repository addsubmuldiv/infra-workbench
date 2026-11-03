"""Shared query/credential operations; no CLI, tool transport or command relay."""
import asyncio
import time

from .agent_query import query_hosts,resolve_host
from .agent_tools import validate_call
from .connection_info import describe_connection
from .agent_errors import response


class AgentService:
    def __init__(self,hosts,snapshots,ssh,passwords,collect):
        self.hosts,self.snapshots,self.ssh,self.passwords,self.collect=hosts,snapshots,ssh,passwords,collect
        self.pending={}

    def inventory(self):
        return [dict(h,snapshot=self.snapshots.get(h['id'],dict(status='connecting',devices=[],collected_at=None))) for h in self.hosts]

    async def refresh(self,hosts,budget):
        task_hosts={}
        for host in hosts:
            key=host['id'];task=self.pending.get(key)
            if task is None or task.done():
                task=asyncio.create_task(self.collect(host));self.pending[key]=task
                task.add_done_callback(lambda t: t.exception() if not t.cancelled() else None)
            task_hosts[task]=key
        if not task_hosts:return set()
        done,pending=await asyncio.wait(task_hosts,timeout=budget)
        return {task_hosts[t] for t in pending}|{task_hosts[t] for t in done if t.cancelled() or t.exception() is not None}

    async def close(self):
        tasks=list(self.pending.values())
        for task in tasks:
            if not task.done():task.cancel()
        await asyncio.gather(*tasks,return_exceptions=True)

    async def call(self,name,arguments,budget=25):
        options=validate_call(name,arguments)
        if name=='find_hosts':
            inventory=[h for h in self.inventory() if (options.get('name') or '').casefold() in h['target'].casefold()]
            semaphore=asyncio.Semaphore(8)
            async def address(host):
                async with semaphore:
                    try:
                        cfg=await asyncio.wait_for(self.ssh.effective(host),timeout=5)
                        host['hostname']=cfg.get('hostname') or None
                    except Exception:
                        host['hostname']=host['target'] if host.get('manual') else None
            await asyncio.gather(*(address(h) for h in inventory))
            return query_hosts(inventory,name,options,time.time())
        if name in ('get_ssh_info','get_ssh_password'):
            host=resolve_host(self.hosts,options['host_id'])
            if name=='get_ssh_password':return response(await self.passwords.get(host))
            info=await describe_connection(self.ssh,self.passwords,host)
            return response(info,warnings=info['warnings'])
        failed=set()
        if options.get('refresh'):
            if options.get('host_id'):
                targets=[resolve_host(self.hosts,options['host_id'])]
            else:
                targets=[]
                for host in self.inventory():
                    if (options.get('name') or '').casefold() not in host['target'].casefold():continue
                    devices=host['snapshot'].get('devices',[])
                    if devices and name=='search_hosts' and not any((not options.get('kind') or d['kind']==options['kind']) and
                        (options.get('model') or '').casefold() in d.get('name','').casefold() for d in devices):continue
                    targets.append(host)
            failed=await self.refresh(targets,budget)
        inventory=self.inventory()
        for host in inventory:
            if host['id'] in failed:
                host['snapshot']=dict(host['snapshot'],status='refresh_timeout',error_stage='refresh')
        return query_hosts(inventory,name,options,time.time())
