import {UI_SERVICE_POLL_MS} from './internalDefaults.ts';
import './servicePanel.css';
import {useEffect,useState} from 'react';
import {t} from './i18n';
type Rule={id:string;name:string;remote_port:number;local_port:number;bound_port:number|null;status:string;url:string|null;error:string};
async function request(host:string,path='',method='GET',body?:unknown){
  const response=await fetch(`/api/hosts/${encodeURIComponent(host)}/services${path}`,{method,headers:{'Content-Type':'application/json','X-IWB':'1'},body:body===undefined?undefined:JSON.stringify(body)});
  const data=await response.json();if(!response.ok)throw new Error(typeof data.detail==='string'?data.detail:t('操作失败','Operation failed'));return data;
}
export function ServicePanel({host,close}:{host:{id:string;target:string};close:()=>void}){
  const [rules,setRules]=useState<Rule[]>([]),[error,setError]=useState(''),[busy,setBusy]=useState(false);
  const [name,setName]=useState('TensorBoard'),[remote,setRemote]=useState(6006),[local,setLocal]=useState(0);
  useEffect(()=>{let alive=true;const load=()=>request(host.id).then(data=>{if(alive)setRules(data)}).catch(e=>{if(alive)setError(String(e.message))});void load();const timer=setInterval(load,UI_SERVICE_POLL_MS);return()=>{alive=false;clearInterval(timer)}},[host.id]);
  async function act(path:string,method='POST',body?:unknown){setBusy(true);setError('');try{await request(host.id,path,method,body);setRules(await request(host.id))}catch(e){setError(e instanceof Error?e.message:String(e))}finally{setBusy(false)}}
  return <div className="modal-shade"><section className="modal service-panel" role="dialog" aria-modal="true" aria-label={t('远程服务','Remote services')} style={{width:'min(760px,95vw)',maxHeight:'85vh',overflow:'auto'}}>
    <h2>{host.target} · {t('远程服务','Remote services')}</h2><p>{t('仅将远端 127.0.0.1 端口转发到本机。请先在远端启动服务。关闭此面板后转发仍会运行，退出软件后停止。','Forwards remote loopback ports to this computer. Start the service remotely first. Tunnels continue after closing this panel and stop when the app exits.')}</p>
    <form onSubmit={e=>{e.preventDefault();void act('','POST',{name,remote_port:remote,local_port:local})}}>
      <label>{t('预设','Preset')} <select onChange={e=>{const preset=e.target.value;setName(preset==='custom'?'HTTP':preset);setRemote(preset==='TensorBoard'?6006:preset==='Jupyter'?8888:8080)}}><option>TensorBoard</option><option>Jupyter</option><option value="custom">{t('自定义 HTTP','Custom HTTP')}</option></select></label>
      <label>{t('名称','Name')} <input required maxLength={80} value={name} onChange={e=>setName(e.target.value)}/></label>
      <label>{t('远端端口','Remote port')} <input required type="number" min={1} max={65535} value={remote} onChange={e=>setRemote(Number(e.target.value))}/></label>
      <label>{t('本地端口（0 自动分配）','Local port (0 for automatic)')} <input required type="number" min={0} max={65535} value={local} onChange={e=>setLocal(Number(e.target.value))}/></label>
      <button disabled={busy}>{t('保存规则','Save rule')}</button>
    </form>
    {error&&<p role="alert">{error}</p>}
    {rules.map(rule=><article key={rule.id} style={{borderTop:'1px solid var(--border)',padding:'12px 0'}}><strong>{rule.name}</strong><p>127.0.0.1:{rule.bound_port??(rule.local_port||'auto')} → 127.0.0.1:{rule.remote_port} · {rule.status==='active'?t('转发运行中','Tunnel active'):rule.status==='error'?t('启动失败','Failed'):t('已停止','Stopped')}</p>{rule.error&&<p role="alert">{rule.error}</p>}
      <button disabled={busy} onClick={()=>void act(`/${rule.id}/${rule.status==='active'?'stop':'start'}`)}>{rule.status==='active'?t('停止','Stop'):t('启动','Start')}</button>{rule.status==='active'&&rule.url&&<a href={rule.url} target="_blank" rel="noreferrer">{t('打开服务','Open service')}</a>} <button className="secondary" disabled={busy} onClick={()=>void act(`/${rule.id}`,'DELETE')}>{t('删除','Delete')}</button>
    </article>)}
    <p>{t('Jupyter 的令牌请在服务页面自行输入；软件不会读取令牌。转发运行不代表远端 HTTP 服务健康。','Enter Jupyter tokens in its own page. Tunnel status does not indicate HTTP service health.')}</p><button className="secondary" onClick={close}>{t('关闭','Close')}</button>
  </section></div>
}
