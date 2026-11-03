import {useLocale} from './i18n';
import {toolText as tt} from './toolI18n';
import React,{useEffect,useRef,useState} from 'react';
import {Download,FileSpreadsheet,LoaderCircle,Upload} from 'lucide-react';
import {importActive,importPercent,importRequest,validateImportFile,type ImportJob,type ImportRow} from './serverImportApi';
import './serverImport.css';

const statuses=():Record<string,string>=>({ready:tt("待导入"),invalid:tt("格式错误"),connecting:tt("连接中"),imported:tt("导入成功"),failed:tt("导入失败"),skipped:tt("已跳过")});
const passwordStatuses=():Record<string,string>=>({pending:tt("等待验证并保存"),saved:tt("已保存"),failed:tt("保存失败"),not_saved:tt("未保存")});
const keyStatuses=():Record<string,string>=>({not_requested:'—',queued:tt("等待配置"),running:tt("配置中"),done:tt("配置成功"),failed:tt("配置失败")});

function rowStatus(row:ImportRow){
  if(row.host_id&&row.status==='ready')return tt("待补存密码");
  if(row.host_id&&row.status==='connecting')return tt("验证密码中");
  if(row.status==='skipped'&&row.password_status==='saved')return tt("密码已保存");
  if(row.status==='skipped'&&row.password_status==='failed')return tt("密码保存失败");
  return statuses()[row.status]||row.status;
}

export default function ServerImport({onChanged}:{onChanged:(ids:string[])=>void}){
  useLocale();
  const [job,setJob]=useState<ImportJob|null>(null),[busy,setBusy]=useState(false),[error,setError]=useState(''),[filename,setFilename]=useState(''),[provision,setProvision]=useState(false),[failedOnly,setFailedOnly]=useState(false);
  const current=useRef(job),changed=useRef(onChanged),seen=useRef(new Set<string>()),mounted=useRef(true),uploads=useRef<AbortController|null>(null),selecting=useRef(false);
  const starting=useRef(false);
  current.current=job;changed.current=onChanged;
  const receive=(value:ImportJob)=>{
    if(!mounted.current)return;
    setJob(value);
    const ids=value.rows.filter(row=>row.status==='imported'&&row.host_id&&!seen.current.has(row.host_id)).map(row=>row.host_id!);
    if(ids.length){ids.forEach(id=>seen.current.add(id));changed.current(ids)}
  };
  useEffect(()=>{
    mounted.current=true;const abort=new AbortController();
    importRequest('/latest',{signal:abort.signal}).then(value=>{if(value&&!selecting.current){value.rows.forEach((row:{host_id:string|null})=>{if(row.host_id)seen.current.add(row.host_id)});receive(value)}}).catch(e=>{if(!abort.signal.aborted&&!selecting.current)setError(e.message)});
    return()=>{
      mounted.current=false;abort.abort();uploads.current?.abort();
      if(current.current?.status==='preview'&&!starting.current)void importRequest('/'+current.current.id,{method:'DELETE'}).catch(()=>{});
    };
  },[]);
  const active=!!job&&importActive(job);
  useEffect(()=>{
    if(!job||!active)return;
    const abort=new AbortController();let timer:ReturnType<typeof setTimeout>|undefined;
    const poll=async()=>{
      try{
        const value=await importRequest('/'+job.id,{signal:abort.signal});
        if(abort.signal.aborted)return;
        receive(value);setError('');if(importActive(value))timer=setTimeout(poll,1000);
      }catch(e){if(!abort.signal.aborted){
        setError(e instanceof Error?e.message:tt("获取进度失败"));
        if(e instanceof Error&&'status' in e&&e.status===404)setJob(old=>old?{...old,status:'interrupted'}:null);
        else timer=setTimeout(poll,2500);
      }}
    };
    void poll();return()=>{abort.abort();if(timer)clearTimeout(timer)};
  },[job?.id,active]);
  const choose=async(file:File)=>{
    selecting.current=true;setError('');
    try{validateImportFile(file)}catch(e){setError((e as Error).message);return}
    setBusy(true);uploads.current?.abort();const abort=new AbortController();uploads.current=abort;
    try{
      if(current.current?.status==='preview'){await importRequest('/'+current.current.id,{method:'DELETE',signal:abort.signal});if(!abort.signal.aborted)setJob(null)}
      const value=await importRequest('/preview',{method:'POST',body:file,signal:abort.signal,headers:{'Content-Type':'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'}});
      if(abort.signal.aborted)return;
      setFilename(file.name);setFailedOnly(false);receive(value);
    }catch(e){if(!abort.signal.aborted)setError(e instanceof Error?e.message:tt("读取失败"))}
    finally{if(!abort.signal.aborted)setBusy(false)}
  };
  const start=async()=>{
    if(!job||starting.current)return;starting.current=true;setBusy(true);setError('');
    try{receive(await importRequest('/'+job.id+'/start',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({provision})}))}
    catch(e){if(mounted.current)setError(e instanceof Error?e.message:tt("开始导入失败"))}
    finally{starting.current=false;if(mounted.current)setBusy(false)}
  };
  const rows=job?.rows.filter(row=>!failedOnly||row.status==='invalid'||row.status==='failed'||row.key_status==='failed'||row.password_status==='failed')||[];
  const importing=job?.status==='running';
  return <div className="server-import">
    <div className="import-intro"><FileSpreadsheet size={24}/><div><strong>{tt("从 Excel 批量添加服务器或补存密码")}</strong><p>{tt("首行表头：IP、账号、密码、端口。IP 列也可填写 SSH 别名。端口留空按 22 处理，非标准端口请填写。读取第一个工作表，一次最多 100 台。")}</p></div></div>
    <div className="import-file-actions"><a className="secondary" href="/api/imports/template" download><Download size={15}/>{tt("下载 Excel 模板")}</a><label className={'primary '+(busy||active?'disabled':'')}><Upload size={15}/>{busy?tt("正在读取…"):tt("选择 Excel 文件")}<input aria-label={tt("选择服务器 Excel 文件")} type="file" accept=".xlsx" disabled={busy||active} onChange={e=>{const file=e.target.files?.[0];e.target.value='';if(file)void choose(file)}}/></label></div>
    <p className="subtle">{tt("提供的密码会在验证成功后自动存入系统凭据管理器，可在机器的「SSH 密码」中查看保存状态或删除。按 SSH 别名或实际地址、账号、端口匹配已有机器；只验证并补存密码，不重复添加，不修改原密钥和跳板。文件内重复目标会跳过。密码原文不显示在预览和报告中。未信任的主机指纹需先在终端核对。")}</p>
    {error&&<div className="connection-error" role="alert">{error}</div>}
    {job&&<>
      <div className="import-summary"><span>{tt("总数 ")}<b>{job.total}</b></span><span className="success">{tt("新增 ")}<b>{job.success}</b></span><span className="failure">{tt("失败 ")}<b>{job.failed}</b></span><span>{tt("跳过新增 ")}<b>{job.skipped}</b></span>{job.status==='preview'?<span>{tt("待处理 ")}<b>{job.valid}</b></span>:<><span className="success">{tt("密码已保存 ")}<b>{job.password_saved||0}</b></span>{!!job.password_failed&&<span className="failure">{tt("密码保存失败 ")}<b>{job.password_failed}</b></span>}</>}</div>
      {job.status==='preview'?<><p className="subtle">{filename} {tt(" · 请核对以下地址和账号，再开始导入。")}</p><label className="provision-option"><input type="checkbox" checked={provision} onChange={e=>setProvision(e.target.checked)} disabled={busy}/><div><strong>{tt("导入成功后，在后台配置免密登录")}</strong><p>{tt("先完成所有服务器的导入，再排队追加公钥并独立验证，不影响导入成功计数。")}</p></div></label></>:<>
        <div className="import-progress"><div><strong>{importing?tt("正在导入"):job.status==='complete'?tt("导入完成"):tt("导入已中断")}</strong><span>{job.processed} / {job.total} · {importPercent(job.processed,job.total)}%</span></div><progress aria-label={tt("服务器导入进度")} max={job.total||1} value={job.processed}/>{importing&&<p>{job.rows.find(row=>row.status==='connecting')?.target||tt("正在准备下一台机器…")}</p>}</div>
        {job.key_total>0&&<div className="import-progress key-progress"><div><strong>{job.status==='interrupted'?tt("免密配置状态待确认"):job.key_done<job.key_total?tt("后台配置免密登录"):tt("免密配置完成")}</strong><span>{job.key_done} / {job.key_total}{job.key_failed>0&&` · ${job.key_failed}${tt(" 台失败")}`}</span></div><progress aria-label={tt("后台免密配置进度")} max={job.key_total} value={job.key_done}/><p>{job.status==='interrupted'?tt("任务记录已失效，请到机器列表确认实际连接状态。"):job.key_done<job.key_total?tt("可关闭此窗口，保持本地软件运行；稍后进入批量导入可查看最近结果。"):tt("免密失败不影响已导入的机器，具体原因见明细。")}</p></div>}
      </>}
      <div className="import-result-heading"><strong>{job.status==='preview'?tt("预览明细"):tt("导入明细")}</strong><label><input type="checkbox" checked={failedOnly} onChange={e=>setFailedOnly(e.target.checked)}/>{tt("只看失败")}</label><a href={'/api/imports/'+job.id+'/report'} download><Download size={14}/>{tt("下载结果表")}</a></div>
      <div className="import-table-wrap"><table className="import-table"><thead><tr><th>{tt("Excel 行")}</th><th>{tt("IP / 主机")}</th><th>{tt("账号 / 端口")}</th><th>{tt("处理状态")}</th><th>{tt("原因 / 密码 / 免密配置")}</th></tr></thead><tbody>{rows.map(row=><tr key={row.row}><td>{row.row}</td><td>{row.target||'—'}</td><td>{row.user||'—'}<small>{tt("端口 ")}{row.port}</small></td><td className={row.status==='imported'||row.password_status==='saved'?'success':['failed','invalid'].includes(row.status)?'failure':''}>{row.status==='connecting'&&<LoaderCircle size={12} className="spin"/>}{rowStatus(row)}</td><td>{row.reason||tt("等待处理")}{row.password_status&&row.password_status!=='not_provided'&&<small className={row.password_status==='failed'?'failure':row.password_status==='saved'?'success':''}>{tt("SSH 密码：")}{passwordStatuses()[row.password_status]||row.password_status}{row.password_reason&&' · '+row.password_reason}</small>}{row.key_status!=='not_requested'&&<small className={row.key_status==='failed'?'failure':''}>{tt("免密：")}{keyStatuses()[row.key_status]}{row.key_reason&&' · '+row.key_reason}</small>}</td></tr>)}</tbody></table>{!rows.length&&<p className="subtle">{tt("没有失败记录。")}</p>}</div>
      {job.status==='preview'&&<div className="import-start"><span>{tt("关闭预览会清除本次暂存的密码。")}</span><button className="primary" disabled={busy||job.valid===0} onClick={()=>void start()}>{busy?<LoaderCircle size={15} className="spin"/>:<Upload size={15}/>}{tt("开始处理 ")}{job.valid} {tt(" 台")}</button></div>}
    </>}
  </div>;
}
