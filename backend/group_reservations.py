"""Persistent multi-host reminders; snapshots qualify only after rule activation."""
import copy
import math
import threading
import time
import uuid
from .reminder_links import reservation_link

TERMINAL = {'ready', 'cancelled'}


class GroupReservationService:
    def __init__(self, store, hosts, snapshots, clusters, mail):
        self.store, self.hosts, self.snapshots, self.clusters, self.mail = store, hosts, snapshots, clusters, mail
        self.lock = threading.RLock()
        self.items = store.load('group_reservations', [])
        self.started = time.time()
        self.clocks = {}
        self.host_clocks = {}
        # A previous run cannot supply observations for a new confirmation window.
        self.baseline = {h: s.get('collected_at') for h,s in snapshots.items()}
        for item in self.items:
            if item['status'] not in TERMINAL:
                item.update(status='unknown',idle_since=None,last_observed=None)
        store.save('group_reservations',self.items)

    def _validate(self, body, saved_scope=None):
        data = copy.deepcopy(body)
        if data.get('mode') not in ('specified','cluster_any'): raise ValueError('请选择多机预约方式')
        ids=data.get('candidate_host_ids')
        if not isinstance(ids,list) or len(ids)>100 or any(not isinstance(h,str) or not 1<=len(h)<=200 for h in ids) or len(set(ids))!=len(ids): raise ValueError('候选机器编号无效、重复或超过 100 台')
        if len(ids)<(2 if data['mode']=='specified' else 1): raise ValueError('指定多台至少需要两台机器')
        if not set(ids)<={h['id'] for h in self.hosts}: raise ValueError('机器已移除，请重新选择')
        if data.get('kind') not in ('GPU','NPU'): raise ValueError('设备类型应为 GPU 或 NPU')
        for key,default,low,high in [('required_devices',1,1,64),('required_hosts',len(ids),1,len(ids)),('wait_seconds',120,0,86400),('minimum_gib',1,0,100000)]:
            value=data.get(key,default)
            if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or value<low or (high is not None and value>high) or (key in ('required_devices','required_hosts') and not isinstance(value,int)): raise ValueError(key+' 数值无效')
            data[key]=value
        if data['mode']=='specified':data['required_hosts']=len(ids)
        if not isinstance(data.get('email_notify',False),bool):raise ValueError('邮件选项无效')
        if data.get('email_notify') and (self.mail is None or not self.mail.view()['reservation_available']):raise ValueError('请先配置可用的邮件通知')
        request=data.get('request_id')
        if not isinstance(request,str) or not 1<=len(request)<=200:raise ValueError('request_id 无效')
        if data.get('cluster_id') and saved_scope is None:
            cluster=self.clusters.get(data['cluster_id'])
            if cluster['revision']!=data.get('revision'):raise ValueError('CONFLICT: 集群成员已变化，请刷新后提交')
            if not set(ids)<=set(cluster['host_ids']):raise ValueError('候选机器不属于该集群')
            data.update(cluster_name=cluster['name'],cluster_revision=cluster['revision'])
        elif data['mode']=='cluster_any' and not data.get('cluster_id'):raise ValueError('请选择集群')
        if saved_scope:
            data.update(cluster_name=saved_scope.get('cluster_name'),cluster_revision=saved_scope.get('cluster_revision'))
            if saved_scope.get('cluster_id'):data['revision']=saved_scope.get('cluster_revision')
        known=0;possible=0
        for h in ids:
            snap=self.snapshots.get(h,{})
            if snap.get('status')!='online':possible+=1;continue
            count=sum(d.get('kind')==data['kind'] for d in snap.get('devices',[]))
            known+=1
            if count>=data['required_devices']:possible+=1
            elif data['mode']=='specified':raise ValueError('所需设备数超过机器已确认容量')
        if not known:raise ValueError('请先完成一次有效采集以确认设备容量')
        if possible<data['required_hosts']:raise ValueError('可能满足条件的候选机器不足')
        return data

    def create(self, body, now=None):
        with self.lock:
            for existing in self.items:
                if existing['request_id']==body.get('request_id'):
                    if existing['request_payload']!=body:raise ValueError('CONFLICT: request_id 已用于不同预约')
                    return self.get(existing['id'])
            if sum(item['status'] not in TERMINAL for item in self.items)>=100:raise ValueError('最多同时保留 100 条等待中的多机预约')
            data=self._validate(body);now=time.time() if now is None else now
            data.update(id=uuid.uuid4().hex,version=1,request_payload=copy.deepcopy(body),created_at=now,updated_at=now,status='unknown',idle_since=None,last_observed=None,notified_at=None,host_states=[],matched_hosts=[])
            self.items.append(data)
            try:self.store.save('group_reservations',self.items)
            except Exception:self.items.pop();raise
            return self.get(data['id'])

    def _item(self,id):
        for item in self.items:
            if item['id']==id:return item
        raise KeyError(id)

    def get(self,id):
        with self.lock:
            result=copy.deepcopy(self._item(id));result.pop('request_payload',None)
            result['counts']={state:sum(h['state']==state for h in result.get('host_states',[])) for state in ('ready','not_ready','unknown')}
            result.update(revision_changed=False,cluster_deleted=False)
            if result.get('cluster_id') and self.clusters:
                try:result['revision_changed']=self.clusters.get(result['cluster_id'])['revision']!=result.get('cluster_revision')
                except Exception:result['cluster_deleted']=True
            result['remaining_seconds']=max(0,result['wait_seconds']-result.get('confirmed_seconds',0))
            result['desktop_delivery']=self.store.desktop_statuses([id]).get(id)
            delivery=self.store.db.execute('SELECT status,error,updated FROM mail_outbox WHERE id=?',(id,)).fetchone()
            result['mail_delivery']=dict(zip(('status','error','updated'),delivery)) if delivery else None
            return result

    def list(self):
        with self.lock:return {'items':[self.get(i['id']) for i in self.items]}

    def update(self,id,body,now=None):
        with self.lock:
            old=self._item(id)
            if old['status'] in TERMINAL:raise ValueError('已结束的预约请再次预约')
            if not isinstance(body.get('version'),int) or isinstance(body.get('version'),bool):raise ValueError('编辑预约必须提供 version')
            if body['version']!=old.get('version',1):raise ValueError('CONFLICT: 预约已变化，请刷新后修改')
            body={k:v for k,v in body.items() if k!='version'}
            merged=dict(old['request_payload'],**body);merged['request_id']=old['request_id']
            scope_keys=('mode','candidate_host_ids','cluster_id')
            unchanged=all(merged.get(key)==old['request_payload'].get(key) for key in scope_keys)
            data=self._validate(merged,saved_scope=old if unchanged else None);now=time.time() if now is None else now
            replacement=dict(old,**data);replacement.update(version=old.get('version',1)+1,request_payload=merged,updated_at=now,status='unknown',idle_since=None,last_observed=None,host_states=[],matched_hosts=[],confirmed_seconds=0)
            index=self.items.index(old);self.items[index]=replacement
            try:self.store.save('group_reservations',self.items)
            except Exception:self.items[index]=old;raise
            self.clocks.pop(id,None)
            return self.get(id)

    def cancel(self,id):
        with self.lock:
            item=self._item(id)
            if item['status']=='ready':raise ValueError('已提醒的预约不能取消')
            item.update(status='cancelled',idle_since=None,version=item.get('version',1)+1);self.clocks.pop(id,None)
            self.store.save('group_reservations',self.items);return self.get(id)

    def rebook(self,id,body=None,now=None):
        with self.lock:
            original=self._item(id)
            data=dict(original['request_payload'],**(body or {}))
            if data['request_id']==original['request_id']:raise ValueError('再次预约需要新的 request_id')
            return self.create(data,now)

    def delete(self,id):
        with self.lock:
            item=self._item(id)
            if item['status'] not in TERMINAL:raise ValueError('请先取消预约再删除')
            before=self.items[:];self.items.remove(item)
            try:self.store.save('group_reservations',self.items)
            except Exception:self.items[:]=before;raise
            return {'ok':True}

    @staticmethod
    def _device(device,minimum):
        util=device.get('utilization');memory=device.get('memory_free')
        valid=lambda n:isinstance(n,(int,float)) and not isinstance(n,bool) and math.isfinite(n)
        if device.get('health')=='Alarm' or device.get('processes') or (valid(util) and util>0) or (valid(memory) and memory<minimum):return 'not_ready'
        if not device.get('id') or device.get('processes_known') is not True or not valid(util) or util!=0 or not valid(memory):return 'unknown'
        return 'ready'

    def _host(self,item,h,now):
        snap=self.snapshots.get(h,{})
        result=dict(host_id=h,target=next((v['target'] for v in self.hosts if v['id']==h),h),state='unknown',reason='尚无规则生效后的有效采样',devices=[],labels=[])
        observed=snap.get('collected_at');started=snap.get('collection_started_at');fresh=snap.get('freshness_seconds',50)
        if h not in {v['id'] for v in self.hosts}:result['reason']='机器已删除';return result
        if snap.get('status')!='online':result['reason']='采集失败';return result
        if not isinstance(observed,(int,float)) or not isinstance(started,(int,float)) or not 0<=now-started<=fresh or observed>now:result['reason']='数据已过期';return result
        if observed<=item['updated_at'] or started<item['updated_at'] or observed==self.baseline.get(h):return result
        devices=sorted([d for d in snap.get('devices',[]) if d.get('kind')==item['kind']],key=lambda d:str(d.get('id','')))
        states=[self._device(d,item['minimum_gib']*1024**3) for d in devices]
        ready=[d for d,state in zip(devices,states) if state=='ready']
        unknown=states.count('unknown');required=item['required_devices']
        result.update(state='ready' if len(ready)>=required else 'unknown' if len(ready)+unknown>=required else 'not_ready',available_count=len(ready),unknown_count=unknown,observed_at=observed,fresh_until=started+fresh,reason=f'{len(ready)}/{required} 个设备符合',devices=[d['id'] for d in ready[:required]],labels=[d.get('display_id',d['id']) for d in ready[:required]])
        return result

    def observe(self,host_id,now=None):
        self.tick(now)

    def tick(self,now=None):
        with self.lock:
            wall=time.time() if now is None else now;clock=time.monotonic() if now is None else now
            before=copy.deepcopy(self.items);clocks=copy.deepcopy(self.clocks);host_clocks=copy.deepcopy(self.host_clocks)
            events=[];desktop=[];mail=[]
            for item in self.items:
                if item['status'] in TERMINAL:continue
                rows=[self._host(item,h,wall) for h in item['candidate_host_ids']]
                for row in rows:row['status']=row['state']
                live={h['id'] for h in self.hosts};remaining=len(set(item['candidate_host_ids'])&live)
                for row in rows:
                    key=(item['id'],row['host_id'])
                    if row['state']=='ready':self.host_clocks.setdefault(key,clock)
                    else:self.host_clocks.pop(key,None)
                ready=[r for r in rows if r['state']=='ready'];unknown=sum(r['state']=='unknown' for r in rows)
                needs=remaining<item['required_hosts'] or (item['mode']=='specified' and remaining<len(rows))
                status='needs_selection' if needs else 'settling' if len(ready)>=item['required_hosts'] else 'unknown' if len(ready)+unknown>=item['required_hosts'] else 'waiting'
                if status!='settling':self.clocks.pop(item['id'],None);item['idle_since']=None
                else:
                    previous=self.clocks.get(item['id'])
                    # A suspended event loop must not silently bridge an observation gap.
                    prior_ready=[r for r in item.get('host_states',[]) if r['state']=='ready']
                    expiries=sorted((r.get('fresh_until',0) for r in prior_ready),reverse=True)
                    gap=len(expiries)>=item['required_hosts'] and wall>expiries[item['required_hosts']-1]
                    if previous is None or clock<previous or gap:self.clocks[item['id']]=clock;item['idle_since']=wall
                elapsed=max(0,clock-self.clocks[item['id']]) if status=='settling' else 0
                item.update(status=status,host_states=rows,confirmed_seconds=elapsed,last_observed=max((r.get('observed_at',0) for r in rows),default=0) or None)
                if status=='settling' and elapsed>=item['wait_seconds']:
                    ready.sort(key=lambda r:(self.host_clocks[(item['id'],r['host_id'])],r['host_id']))
                    item.update(status='ready',notified_at=wall,matched_hosts=copy.deepcopy(ready[:item['required_hosts']]))
                    description='；'.join(r['target']+' · 设备 '+', '.join(r['labels']) for r in item['matched_hosts'])
                    events.append(('', '多机预约条件已满足：'+description+'。启动前请再次检查当前占用。'))
                    desktop.append(dict(id=item['id'],url=reservation_link(item)))
                    if self.mail:
                        payload=self.mail.prepare_group(item)
                        if payload:mail.append(payload)
            if self.items!=before:
                try:self.store.save_with_events('group_reservations',self.items,events,wall,mail=mail,desktop=desktop)
                except Exception:self.items[:]=before;self.clocks=clocks;self.host_clocks=host_clocks;raise
