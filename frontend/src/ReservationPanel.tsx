import React,{useEffect,useState} from 'react';
import {Bell,CalendarClock,Check,Clock3,Plus,Trash2,X} from 'lucide-react';
import {browserStorage} from './preferences';
import {countdown,loadWaitMinutes,saveWaitMinutes,waitSeconds,type Reservation,type ReservationHost} from './reservations';
import './reservations.css';
import {mailRequest,mailStatusText,type MailView} from './mailSettings';

type CreateBody={host_id:string;devices:string[];mode:'fixed'|'count';required_count?:number;kind?:string;wait_seconds:number;minimum_gib:number;email_notify:boolean};
export type ReservationDraft={hostId?:string;devices?:string[];minimum?:number};
export function ReservationDialog({hosts,draft,close,save,openSettings,countEnabled=false}:{hosts:ReservationHost[];draft:ReservationDraft;close:()=>void;save:(body:CreateBody)=>Promise<void>;openSettings:()=>void;countEnabled?:boolean}){
  const [hostId,setHostId]=useState(draft.hostId||hosts[0]?.id||'');
  const [devices,setDevices]=useState<string[]>(draft.devices||[]);
  const [mode,setMode]=useState<'fixed'|'count'>(countEnabled&&!draft.devices?.length?'count':'fixed');
  const [count,setCount]=useState('1');
  const [kind,setKind]=useState(hosts.find(host=>host.id===(draft.hostId||hosts[0]?.id))?.snapshot.devices[0]?.kind||'GPU');
  const [minutes,setMinutes]=useState(()=>String(loadWaitMinutes(browserStorage())));
  const [minimum,setMinimum]=useState(String(draft.minimum??1));
  const [loading,setLoading]=useState(false),[error,setError]=useState('');
  const [emailNotify,setEmailNotify]=useState(false),[emailAvailable,setEmailAvailable]=useState(false),[checkingMail,setCheckingMail]=useState(true),[mailError,setMailError]=useState('');
  useEffect(()=>{
    let active=true;
    mailRequest<MailView>().then(view=>{if(active)setEmailAvailable(view.reservation_available===true)}).catch(()=>{if(active)setMailError('无法读取邮箱配置，请到设置中检查。')}).finally(()=>{if(active)setCheckingMail(false)});
    return()=>{active=false};
  },[]);
  const host=hosts.find(host=>host.id===hostId);
  const total=host?.snapshot.devices.filter(device=>device.kind===kind).length??0;
  const submit=async(event:React.FormEvent)=>{
    event.preventDefault();setLoading(true);setError('');
    try{
      if(!host?.snapshot.fresh)throw new Error('机器数据已过期，请先刷新机器');
      if(mode==='fixed'&&!devices.length)throw new Error('请选择至少一个设备');
      if(mode==='count'&&(!Number.isInteger(Number(count))||Number(count)<1||Number(count)>Math.min(64,total)))throw new Error('需要的设备数必须为 1～'+Math.min(64,total)+' 的整数');
      if(minutes.trim()===''||minimum.trim()==='')throw new Error('请填写等待时间和剩余显存');
      const wait=waitSeconds(Number(minutes)),memory=Number(minimum);
      if(!Number.isFinite(memory)||memory<0||memory>100000)throw new Error('请输入有效的剩余显存');
      await save({host_id:hostId,mode,devices:mode==='fixed'?devices:[],...(mode==='count'?{required_count:Number(count),kind}:{}),wait_seconds:wait,minimum_gib:memory,email_notify:emailNotify&&emailAvailable});
      saveWaitMinutes(browserStorage(),Number(minutes));close();
    }catch(e){setError(e instanceof Error?e.message:String(e))}finally{setLoading(false)}
  };
  return <div className="modal-shade"><section className="modal reservation-dialog" role="dialog" aria-modal="true" aria-labelledby="reservation-title"><div className="modal-header"><div><div className="eyebrow">WAIT / NOTIFY</div><h2 id="reservation-title">预约设备空闲提醒</h2></div><button className="icon-button" aria-label="关闭预约" disabled={loading} onClick={close}><X size={20}/></button></div>
    <form onSubmit={submit}><label className="form-label">机器<select aria-label="预约机器" value={hostId} disabled={loading} onChange={event=>{setHostId(event.target.value);setDevices([]);setCount('1');setKind(hosts.find(host=>host.id===event.target.value)?.snapshot.devices[0]?.kind||'GPU')}}>{hosts.map(host=><option key={host.id} value={host.id}>{host.target}</option>)}</select></label>
      <div className="reservation-mode" role="group" aria-label="预约方式"><button type="button" className={mode==='count'?'active':''} disabled={loading||!countEnabled} aria-pressed={mode==='count'} title={countEnabled?'任意满足条件的设备即可':'请重启本地服务以启用按数量预约'} onClick={()=>setMode('count')}>按数量预约</button><button type="button" className={mode==='fixed'?'active':''} disabled={loading} aria-pressed={mode==='fixed'} onClick={()=>setMode('fixed')}>指定卡号</button></div>
      {!countEnabled&&<p className="reservation-note">按数量预约需要重启本地服务后启用，现有指定卡号预约仍可使用。</p>}
      {mode==='count'&&<div className="form-row"><label className="form-label">设备类型<select aria-label="预约设备类型" value={kind} disabled={loading} onChange={event=>{setKind(event.target.value);setCount('1')}}>{[...new Set(host?.snapshot.devices.map(device=>device.kind)||[kind])].map(value=><option key={value}>{value}</option>)}</select></label><label className="form-label">需要多少个空闲设备<input aria-label="预约需要设备数" type="number" min="1" max={Math.min(64,total)} step="1" required value={count} disabled={loading} onChange={event=>setCount(event.target.value)}/><span className="subtle">机器共有 {total} 个 {kind}，不限制设备编号</span></label></div>}
      {mode==='fixed'&&<fieldset className="reservation-devices" disabled={loading}><legend>选择设备 · 可选择正在占用的设备</legend><div className="reservation-device-actions"><span>已选 {host?.snapshot.devices.filter(device=>devices.includes(device.id)).length??0} / {host?.snapshot.devices.length??0} 个设备</span><button type="button" className="text-button" disabled={!host?.snapshot.devices.length||host.snapshot.devices.every(device=>devices.includes(device.id))} onClick={()=>setDevices(host?.snapshot.devices.map(device=>device.id)||[])}>全选</button><button type="button" className="text-button" disabled={!devices.length} onClick={()=>setDevices([])}>清空</button></div>{host?.snapshot.devices.map(device=><label key={device.id}><input type="checkbox" checked={devices.includes(device.id)} onChange={()=>setDevices(old=>old.includes(device.id)?old.filter(id=>id!==device.id):[...old,device.id])}/><span>{device.kind} {device.display_id??device.id}<small>{!device.processes_known?'进程未知':device.processes.length?'正在占用':'无计算进程'}</small></span></label>)}{!host?.snapshot.devices.length&&<p>暂无设备，请先成功采集机器信息。</p>}</fieldset>}
      <div className="form-row"><label className="form-label">连续空闲多久后提醒（分钟）<input aria-label="预约等待分钟" type="number" min="0" max="1440" step="any" required value={minutes} disabled={loading} onChange={event=>setMinutes(event.target.value)}/></label><label className="form-label">每个设备剩余显存（GiB）<input aria-label="预约每设备剩余显存" type="number" min="0" max="100000" step="any" required value={minimum} disabled={loading} onChange={event=>setMinimum(event.target.value)}/></label></div>
      <p className="reservation-note">{mode==='count'?'只要机器持续有足够数量的设备满足条件，就会提醒，不绑定卡号。期间可用数量不足时重新计时；设备编号变化但数量始终足够，不会重新计时。':'所有所选设备都空闲后开始计时。中途出现任务、显存不足或无法确认状态，重新计时。'}等待时间会记住，方便下次预约。</p>
      <div className="reservation-notification"><label><input type="checkbox" aria-label="使用邮箱通知" aria-describedby="reservation-mail-help" checked={emailNotify&&emailAvailable} disabled={loading||checkingMail||!emailAvailable} onChange={event=>setEmailNotify(event.target.checked)}/><span>使用邮箱通知</span></label><p id="reservation-mail-help">{checkingMail?'正在检查邮箱配置…':mailError||(!emailAvailable?'请先在设置中启用邮件通知，并保存邮箱配置和授权码。':'默认使用 Windows 通知；勾选后，同时发送邮件提醒。')}</p>{!checkingMail&&!emailAvailable&&<button type="button" className="text-button" disabled={loading} onClick={openSettings}>前往邮箱设置</button>}</div>
      {!host?.snapshot.fresh&&<p className="reservation-error">机器信息尚未更新，请先在总览刷新机器。</p>}{error&&<p role="alert" className="reservation-error">{error}</p>}
      <div className="reservation-actions"><button type="button" className="secondary" disabled={loading} onClick={close}>取消</button><button className="primary" disabled={loading||!host?.snapshot.fresh||(mode==='fixed'?!devices.length:total===0)}><CalendarClock size={16}/>{loading?'正在保存…':'添加预约'}</button></div>
    </form></section></div>;
}

export function Reservations({items,create,update,remove,enableNotifications,notify}:{items:Reservation[];create:()=>void;update:(id:string,seconds:number)=>Promise<void>;remove:(id:string)=>Promise<void>;enableNotifications:()=>void;notify:boolean}){
  const pending=items.filter(item=>item.status!=='ready'),done=items.filter(item=>item.status==='ready');
  return <section className="reservations"><div className="reservation-heading"><div><h2>我的预约 <span>{pending.length} 条等待中</span></h2><p>满足所需数量或指定卡号的空闲条件后，发送一次提醒。</p></div><button className="secondary" onClick={enableNotifications}><Bell size={15}/>{notify?'浏览器通知已开启':'开启浏览器通知'}</button><button className="primary" onClick={create}><Plus size={16}/>新建预约</button></div>
    <div className="reservation-explainer"><Clock3 size={19}/><div><strong>空闲 → 持续确认 → 通知你</strong><p>默认等待 2 分钟，可单独调整。按数量预约不绑定卡号；可用数量不足、指定卡号未全部空闲或采集中断时，重新计时。</p><small>后台服务需保持运行。预约仅提醒，不锁定设备；收到提醒后，启动前请再次检查。</small></div></div>
    {!items.length&&<div className="empty"><CalendarClock size={32}/><h3>还没有预约</h3><p>选择机器和所需设备数，或指定卡号，满足空闲条件后再提醒你。</p><button className="secondary" onClick={create}>选择机器和设备</button></div>}
    <div className="reservation-list">{[...pending,...done].map(item=><ReservationRow key={item.id} item={item} update={update} remove={remove}/>)}</div>
  </section>;
}

function ReservationRow({item,update,remove}:{item:Reservation;update:(id:string,seconds:number)=>Promise<void>;remove:(id:string)=>Promise<void>}){
  const [editing,setEditing]=useState(false),[minutes,setMinutes]=useState(String(item.wait_seconds/60));
  const [busy,setBusy]=useState(false),[error,setError]=useState('');
  const labels={waiting:'等待设备空闲',settling:'正在确认持续空闲',unknown:'等待有效采集',needs_selection:'设备已变化，请重新预约',ready:'已发送空闲提醒'};
  const act=async(action:()=>Promise<void>)=>{setBusy(true);setError('');try{await action()}catch(e){setError(e instanceof Error?e.message:String(e))}finally{setBusy(false)}};
  return <article className={'reservation-row '+item.status}><div className="reservation-row-top"><span className="reservation-symbol">{item.status==='ready'?<Check size={20}/>:<CalendarClock size={20}/>}</span><div><h3>{item.target}</h3><p>{item.mode==='count'?<>任意 {item.required_count} 个 {item.kind}{item.status!=='ready'&&<> · 当前可用 {item.available_count??'未知'}</>}{item.status==='ready'&&<> · 提醒时可用：{item.labels.join(', ')}</>}</>:<>指定设备 {item.labels.join(', ')}</>} · 每设备剩余 ≥ {item.minimum_gib} GiB</p></div><span className={'reservation-status '+item.status}>{labels[item.status]}</span><button className="icon-button" aria-label={(item.status==='ready'?'删除预约记录 ':'取消预约 ')+item.target+' 设备 '+item.labels.join(', ')} disabled={busy} onClick={()=>act(()=>remove(item.id))}><Trash2 size={16}/></button></div>
    {item.status==='settling'&&<div className="reservation-progress"><div><span>已连续空闲 {countdown(item.idle_seconds)}</span><strong>还需 {countdown(item.remaining_seconds)}</strong></div><progress max={Math.max(1,item.wait_seconds)} value={item.idle_seconds}/></div>}
    <div className="reservation-row-bottom">{item.status==='ready'?<span>{item.notified_at?new Date(item.notified_at*1000).toLocaleString('zh-CN'):''} 已提醒 · 当前占用请查看设备列表</span>:<><span>连续空闲 {item.wait_seconds/60} 分钟后提醒</span><button className="text-button" disabled={busy} onClick={()=>{setMinutes(String(item.wait_seconds/60));setEditing(!editing)}}>修改等待时间</button></>}</div>
    <div className="reservation-channel">Windows 通知{item.email_notify?' + 邮箱通知':''}</div>
    {item.email&&<div className={'reservation-email '+item.email.status}>{mailStatusText[item.email.status]}{item.email.error&&<small>{item.email.error}</small>}</div>}
    {editing&&<form className="reservation-edit" onSubmit={event=>{event.preventDefault();void act(async()=>{if(minutes.trim()==='')throw new Error('请填写等待时间');await update(item.id,waitSeconds(Number(minutes)));setEditing(false)})}}><label>等待时间<input aria-label={'修改 '+item.target+' 预约等待分钟'} type="number" min="0" max="1440" step="any" required disabled={busy} value={minutes} onChange={event=>setMinutes(event.target.value)}/>分钟</label><button className="secondary" disabled={busy}>保存并重新计时</button><button type="button" className="text-button" disabled={busy} onClick={()=>setEditing(false)}>取消</button></form>}
    {error&&<p className="reservation-error" role="alert">{error}</p>}
  </article>;
}
