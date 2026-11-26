"""Short-lived import jobs; temporary password copies are released after use."""
import asyncio
import secrets
import time

from .server_import import safe_failure


class ImportJobs:
    def __init__(self,hosts,connect,provision,*,clock=time.monotonic,clusters=None):
        self.hosts,self.connect,self.provision,self.clock=hosts,connect,provision,clock
        self.jobs={};self.clusters=clusters

    def _prune(self):
        now=self.clock()
        for key,job in list(self.jobs.items()):
            active=any(job.get(field) and not job[field].done() for field in ('import_task','key_task'))
            if not active and now-job['updated']>(600 if job['status']=='preview' else 3600):
                for row in job['rows']:row.password=None
                del self.jobs[key]

    def _job(self,key):
        self._prune()
        if key not in self.jobs:raise KeyError('导入记录已过期，请重新选择表格')
        return self.jobs[key]

    def create(self,rows):
        self._prune()
        if len(self.jobs)>=10:raise ValueError('导入记录数量已达上限，请稍后重试')
        for row in rows:
            existing=self._existing(row) if row.status=='ready' else None
            if existing:
                row.host_id=existing['id']
                if row.password:row.reason='已匹配 '+existing['target']+'；将验证并补存 SSH 密码，保留原配置'
                else:row.status='skipped';row.reason='机器已存在，未提供密码，保留原配置'
        key=secrets.token_urlsafe(24)
        self.jobs[key]=dict(id=key,status='preview',rows=rows,updated=self.clock(),provision=False,import_task=None,key_task=None)
        return self.view(key)

    def view(self,key):
        job=self._job(key);rows=job['rows']
        keys=[row for row in rows if row.key_status!='not_requested']
        return dict(id=key,status=job['status'],cluster_id=job.get('cluster_id'),total=len(rows),
                    processed=sum(row.status in ('invalid','failed','imported','skipped') for row in rows),
                    success=sum(row.status=='imported' for row in rows),failed=sum(row.status in ('invalid','failed') for row in rows),
                    skipped=sum(row.status=='skipped' for row in rows),valid=sum(row.status=='ready' for row in rows),
                    password_saved=sum(row.password_status=='saved' for row in rows),
                    password_failed=sum(row.password_status=='failed' for row in rows),
                    key_total=len(keys),key_done=sum(row.key_status in ('done','failed') for row in keys),
                    key_failed=sum(row.key_status=='failed' for row in keys),rows=[row.view() for row in rows])

    def latest(self):
        self._prune()
        key=next((key for key in reversed(self.jobs) if self.jobs[key]['status']!='preview'),None)
        return self.view(key) if key else None

    def start(self,key,provision,cluster_id=None):
        job=self._job(key)
        if job['status']!='preview':return self.view(key)
        if any(other['status']=='running' or (other.get('key_task') and not other['key_task'].done()) for other in self.jobs.values()):
            raise ValueError('已有批量导入或免密配置任务正在运行，请等待该任务完成')
        clusters=self.clusters() if callable(self.clusters) else self.clusters
        if cluster_id is not None:
            if clusters is None:raise ValueError('集群服务不可用')
            clusters.pin_import(cluster_id)
        job.update(status='running',provision=provision,cluster_id=cluster_id,clusters=clusters,updated=self.clock())
        job['import_task']=asyncio.create_task(self._run(job))
        return self.view(key)

    def _existing(self,row):
        if row.host_id:return next((h for h in self.hosts if h['id']==row.host_id),None)
        return next((h for h in self.hosts if h.get('manual') and h['target'].lower()==row.target.lower()
                     and h.get('user')==row.user and (h.get('port') or 22)==row.port),None)

    async def _run(self,job):
        try:
            for row in job['rows']:
                if row.status!='ready':continue
                existing=self._existing(row)
                if existing and not row.password:
                    row.status='skipped';row.reason='机器已存在，保留原配置';row.host_id=existing['id'];row.password=None;continue
                row.status='connecting'
                try:
                    result=await asyncio.wait_for(self.connect(row),45)
                    if row.password:
                        row.password_status='not_saved' if result.get('password_not_verified') else 'saved' if result.get('password_saved') else 'failed'
                        row.password_reason=('已使用已有免密登录；未验证或保存表格密码' if result.get('password_not_verified') else
                                            '已存入系统凭据管理器，可在机器的 SSH 密码设置中删除' if result.get('password_saved')
                                             else '密码保存失败或无法确认，请在机器的 SSH 密码设置中重试；连接结果不受影响')
                    if result.get('skipped'):
                        row.status='skipped';row.host_id=result['host_id']
                        row.reason=('机器已存在，SSH 密码已保存，原配置保持不变' if result.get('password_saved') else
                                    '机器已存在，密码保存失败，原配置保持不变' if result.get('password_save_failed') else '机器已存在，保留原配置')
                        continue
                    row.host_id=result['host_id'];row.status='imported';row.reason='登录成功，已添加'
                    if job.get('cluster_id') is not None:job['clusters'].assign_import(row.host_id,job['cluster_id'])
                    if job['provision'] and row.password and not result.get('password_not_verified'):row.key_status='queued'
                    elif job['provision']:row.key_status='done';row.key_reason='已通过无密码登录验证'
                except Exception as exc:
                    row.status='failed';row.reason=safe_failure(exc)
                    if row.password:
                        row.password_status='not_saved';row.password_reason='本次连接未验证成功，未更新已保存的密码'
                finally:
                    if row.key_status!='queued':row.password=None
                    job['updated']=self.clock()
            # This is independent of key_task: importing is already complete.
            job['status']='complete'
            if any(row.key_status=='queued' for row in job['rows']):job['key_task']=asyncio.create_task(self._keys(job))
        finally:
            if job.get('cluster_id') is not None:job['clusters'].unpin_import(job['cluster_id'])
            if job['status']=='running':job['status']='interrupted'
            if job['status']!='complete':
                for row in job['rows']:row.password=None
            job['updated']=self.clock()

    async def _keys(self,job):
        try:
            for row in job['rows']:
                if row.key_status!='queued':continue
                row.key_status='running'
                try:
                    result=await asyncio.wait_for(self.provision(row),90)
                    row.key_status='done' if result.get('ok') else 'failed'
                    row.key_reason='已通过独立免密连接验证' if result.get('ok') else safe_failure(result.get('reason',''),key=True)
                except Exception as exc:row.key_status='failed';row.key_reason=safe_failure(exc,key=True)
                finally:row.password=None;job['updated']=self.clock()
        finally:
            for row in job['rows']:
                if row.key_status in ('queued','running'):row.key_status='failed';row.key_reason='后台配置已中断，可在单机添加界面重试'
                row.password=None
            job['updated']=self.clock()

    def discard(self,key):
        job=self._job(key)
        if job['status']!='preview':raise ValueError('只能丢弃尚未开始的预览，已开始的任务会继续执行')
        for row in job['rows']:row.password=None
        del self.jobs[key]

    async def close(self):
        tasks=[job[field] for job in self.jobs.values() for field in ('import_task','key_task') if job.get(field)]
        for task in tasks:
            if not task.done():task.cancel()
        await asyncio.gather(*tasks,return_exceptions=True)
        for job in self.jobs.values():
            for row in job['rows']:row.password=None

    async def maintain(self):
        while True:
            await asyncio.sleep(30)
            self._prune()
