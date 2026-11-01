import {useWorkspaceRestore} from './workspaceHooks';
import {workspaceStorage} from './workspaceState';
import React,{useEffect,useState} from 'react';
import {Activity,ArrowUp,Check,Download,FileText,FolderOpen,LoaderCircle,RefreshCw,Save,Trash2,X} from 'lucide-react';
import './precision.css';
import {downloadOriginalLog} from './logDownload';

type Host={id:string;target:string};
type Location={host_id:string;path:string};
type RecordRow={step:number;line:number;source:string;metrics:Record<string,number>};
type Group={key:string;rank:string;segment:number;count:number;duplicates:number;unique_steps:number;start:number;end:number;metrics:string[];preview:RecordRow[]};
type Snapshot={id:string;path:string;groups:Group[];total_lines:number;skipped_lines:number;invalid_values:number;file:{size:number;mtime:number|null};demo?:boolean};
type Point={step:number;baseline:number;candidate:number;difference:number;absolute_error:number;baseline_line:number;candidate_line:number};
type Series={step:number;value:number}[];
type Metric={name:string;count:number;missing_metric_steps:number;mae:number|null;max_abs_error:number|null;max_error_step:number|null;points:Point[];baseline_series:Series;candidate_series:Series};
type Result={baseline:string;candidate:string;metrics:Metric[];alignment:{common_steps:number;baseline_only:number;candidate_only:number};range:{start:number;end:number};learning_rate_mismatch_count:number;learning_rate_first_mismatch:number|null};
type Draft={id?:string;name:string;baseline:Location;candidate:Location;metrics:string[];baseline_group:string|null;candidate_group:string|null;duplicate_policy:string;start:number|null;end:number|null};
type Config=Draft&{id:string};
type Directory={path:string;parent:string;entries:{name:string;path:string;directory:boolean;size:number}[];truncated:boolean};
const KEY='iwb.precision.draft.v1';
const empty:Draft={name:'',baseline:{host_id:'',path:''},candidate:{host_id:'',path:''},metrics:['loss','grad_norm'],baseline_group:null,candidate_group:null,duplicate_policy:'error',start:null,end:null};
function restore():Draft{try{const d=JSON.parse(workspaceStorage.getItem(KEY)||'null');if(d&&typeof d.baseline?.path==='string'&&typeof d.candidate?.path==='string'&&Array.isArray(d.metrics))return {...empty,...d}}catch{}return {...empty}}
async function api(path:string,method='GET',body?:unknown){const r=await fetch('/api/logs'+path,{method,headers:{'Content-Type':'application/json','X-IWB':'1'},body:body===undefined?undefined:JSON.stringify(body)});const data=await r.json();if(!r.ok)throw new Error(typeof data.detail==='string'?data.detail:'操作失败');return data}
const num=(n:number|null|undefined)=>n==null?'—':n===0?'0':Math.abs(n)<0.0001||Math.abs(n)>=1000000?n.toExponential(8):Number(n.toPrecision(12)).toString();
const axisNum=(n:number)=>n===0?'0':Math.abs(n)<.001||Math.abs(n)>=10000?n.toExponential(2):Number(n.toPrecision(4)).toString();
const groupOf=(s:Snapshot|null,key:string|null)=>s?.groups.find(g=>g.key===key)||(s?.groups.length===1?s.groups[0]:undefined);

export function PrecisionCompare({hosts}:{hosts:Host[]}){
  const [draft,setDraft]=useState<Draft>(restore),[configs,setConfigs]=useState<Config[]>([]);
  useWorkspaceRestore(KEY,restore,setDraft);
  const [a,setA]=useState<Snapshot|null>(null),[b,setB]=useState<Snapshot|null>(null),[result,setResult]=useState<Result|null>(null);
  const [busy,setBusy]=useState(''),[error,setError]=useState(''),[notice,setNotice]=useState(''),[readAt,setReadAt]=useState('');
  const [active,setActive]=useState('loss'),[sort,setSort]=useState('error'),[picked,setPicked]=useState<Point|null>(null);
  const [source,setSource]=useState<{baseline:RecordRow;candidate:RecordRow}|null>(null);
  const [browser,setBrowser]=useState<'baseline'|'candidate'|null>(null),[directory,setDirectory]=useState<Directory|null>(null),[folder,setFolder]=useState('~');
  useEffect(()=>{api('/configs').then(setConfigs).catch(e=>setError(e.message))},[]);
  useEffect(()=>{try{workspaceStorage.setItem(KEY,JSON.stringify(draft))}catch{}},[draft]);
  const clearResult=()=>{setResult(null);setPicked(null);setSource(null)};
  const update=(change:Partial<Draft>)=>{setDraft(d=>({...d,...change}));clearResult()};
  const setLocation=(side:'baseline'|'candidate',change:Partial<Location>)=>{update({[side]:{...draft[side],...change},[side+'_group']:null});if(side==='baseline')setA(null);else setB(null)};
  const execute=async(label:string,fn:()=>Promise<void>)=>{setBusy(label);setError('');setNotice('');try{await fn()}catch(e){setError(e instanceof Error?e.message:String(e))}finally{setBusy('')}};
  const options=()=>({metrics:draft.metrics,duplicate_policy:draft.duplicate_policy,start:draft.start,end:draft.end});
  const compare=async(left:Snapshot,right:Snapshot)=>{
    const ag=groupOf(left,draft.baseline_group),bg=groupOf(right,draft.candidate_group);
    if(!ag||!bg)throw new Error('存在多个 rank 或训练段，请在双方日志卡片中选择轨迹后点击“计算误差”。');
    const value:Result=await api('/compare','POST',{baseline:left.id,candidate:right.id,baseline_group:ag.key,candidate_group:bg.key,...options()});
    setResult(value);setActive(value.metrics.some(m=>m.name===active)?active:value.metrics[0].name);setPicked(null);setSource(null);
  };
  const readBoth=()=>execute('read',async()=>{
    clearResult();setA(null);setB(null);
    const reads=await Promise.allSettled([api('/read','POST',draft.baseline),api('/read','POST',draft.candidate)]);
    const left=reads[0].status==='fulfilled'?reads[0].value as Snapshot:null;
    const right=reads[1].status==='fulfilled'?reads[1].value as Snapshot:null;
    setA(left);setB(right);setReadAt(new Date().toLocaleTimeString('zh-CN',{hour12:false}));
    const errors=reads.flatMap((r,i)=>r.status==='rejected'?[(i===0?'基准':'待验证')+'：'+String(r.reason.message||r.reason)]:[]);
    if(errors.length)throw new Error(errors.join('；'));
    if(left&&right)await compare(left,right);
  });
  const demo=()=>execute('demo',async()=>{clearResult();const value=await api('/demo','POST');setA(value.baseline);setB(value.candidate);setReadAt(new Date().toLocaleTimeString());await compare(value.baseline,value.candidate)});
  const browse=async(side:'baseline'|'candidate',path:string)=>{
    const value:Directory=await api('/browse','POST',{host_id:draft[side].host_id,path});setDirectory(value);setFolder(value.path);setBrowser(side);
  };
  const inspect=(point:Point)=>execute('source',async()=>{
    setPicked(point);setSource(null);if(!a||!b)return;
    const values=await Promise.all([api('/'+a.id+'/record?'+new URLSearchParams({group:groupOf(a,draft.baseline_group)!.key,line:String(point.baseline_line)})),api('/'+b.id+'/record?'+new URLSearchParams({group:groupOf(b,draft.candidate_group)!.key,line:String(point.candidate_line)}))]);
    setSource({baseline:values[0],candidate:values[1]});
  });
  const save=()=>execute('save',async()=>{
    if(!draft.name.trim())throw new Error('请给这个对比配置起一个名称');
    const value:Config=await api('/configs','POST',draft);setDraft(value);setConfigs(await api('/configs'));setNotice('对比配置已保存，下次选择后重新读取日志即可。');
  });
  const downloadLog=(side:'baseline'|'candidate')=>execute('download-'+side,async()=>{
    const file=await downloadOriginalLog(draft[side]);
    const url=URL.createObjectURL(file.blob),link=document.createElement('a');
    link.href=url;link.download=(side==='baseline'?'基准-':'待验证-')+file.filename;
    document.body.appendChild(link);link.click();link.remove();
    setTimeout(()=>URL.revokeObjectURL(url),60000);
    setNotice((side==='baseline'?'基准':'待验证')+'原始日志已交给浏览器下载：'+link.download);
  });
  const exportCSV=()=>{
    if(!result)return;
    const rows=['metric,step,baseline,candidate,difference,absolute_error'];
    for(const m of result.metrics){const name=/^[=+\-@\t\r]/.test(m.name)?"'"+m.name:m.name;for(const p of m.points)rows.push('"'+name.replaceAll('"','""')+'",'+[p.step,p.baseline,p.candidate,p.difference,p.absolute_error].join(','))}
    const url=URL.createObjectURL(new Blob(['\uFEFF'+rows.join('\r\n')],{type:'text/csv;charset=utf-8'}));
    const link=document.createElement('a');link.href=url;link.download='training-precision.csv';link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
  };
  const ag=groupOf(a,draft.baseline_group),bg=groupOf(b,draft.candidate_group);
  const available=Array.from(new Set([...(ag?.metrics||a?.groups.flatMap(g=>g.metrics)||[]),...(bg?.metrics||b?.groups.flatMap(g=>g.metrics)||[]),'loss','grad_norm']));
  const metric=result?.metrics.find(m=>m.name===active)||result?.metrics[0];
  const table=metric?[...metric.points].sort((x,y)=>sort==='error'?y.absolute_error-x.absolute_error:x.step-y.step):[];
  const card=(side:'baseline'|'candidate',s:Snapshot|null)=>{
    const group=groupOf(s,draft[side+'_group' as 'baseline_group'|'candidate_group']);
    return <section className={'precision-card '+side}>
      <div className="precision-card-title"><span className="precision-letter">{side==='baseline'?'A':'B'}</span><div><h2>{side==='baseline'?'基准日志':'待验证日志'}</h2><p>{side==='baseline'?'例如 GPU 训练结果':'例如 NPU 训练结果'}</p></div><FileText size={19}/></div>
      <label className="precision-label">机器<select aria-label={side==='baseline'?'基准机器':'待验证机器'} disabled={!!busy} value={draft[side].host_id} onChange={e=>setLocation(side,{host_id:e.target.value})}><option value="">选择已连接的机器</option>{hosts.map(h=><option key={h.id} value={h.id}>{h.target}</option>)}{draft[side].host_id&&!hosts.some(h=>h.id===draft[side].host_id)&&<option value={draft[side].host_id}>此机器已移除，请重新选择</option>}</select></label>
      <label className="precision-label">远端日志路径<div className="precision-path"><input aria-label={side==='baseline'?'基准日志路径':'待验证日志路径'} placeholder="/workspace/train.log 或 ~/logs/train.jsonl" disabled={!!busy} value={draft[side].path} onChange={e=>setLocation(side,{path:e.target.value})}/><button type="button" className="secondary" aria-label={side==='baseline'?'浏览基准日志':'浏览待验证日志'} disabled={!!busy||!draft[side].host_id} onClick={()=>execute('browse',()=>browse(side,draft[side].path||'~'))}><FolderOpen size={15}/></button></div></label>
      <div className="precision-download-row"><button type="button" className="secondary" aria-label={side==='baseline'?'下载基准原始日志':'下载待验证原始日志'} disabled={!!busy||!draft[side].host_id||!draft[side].path} title="下载开始时的完整文件内容，不受指标筛选和对比范围影响" onClick={()=>downloadLog(side)}>{busy==='download-'+side?<LoaderCircle size={14} className="spin"/>:<Download size={14}/ >}{busy==='download-'+side?'正在下载…':'下载原始日志'}</button><small>无需先解析，保留完整原文</small></div>
      {s?<div className="precision-extracted"><div className="precision-extraction-heading"><Check size={14}/>{s.demo?'示例数据 · 非真实服务器':'已识别 JSON 训练日志'}<span>{s.total_lines-s.skipped_lines} 条指标记录</span></div>
        <label className="precision-label">训练轨迹<select aria-label={side==='baseline'?'基准训练轨迹':'待验证训练轨迹'} disabled={!!busy} value={group?.key||''} onChange={e=>update({[side+'_group']:e.target.value||null})}><option value="">请选择 rank / 训练段</option>{s.groups.map(g=><option key={g.key} value={g.key}>{'rank '+g.rank+' · 第 '+g.segment+' 段 · step '+g.start+'–'+g.end+' · '+g.count+' 条'+(g.duplicates?' · '+g.duplicates+' 条重复':'')}</option>)}</select></label>
        {s.groups.length>1&&<p className="precision-warning">发现多个 rank 或 step 回退，请明确选择训练轨迹。</p>}
        {(group?.duplicates||0)>0&&<p className="precision-warning">有重复 step，请在下方选择处理方式。</p>}
        <div className="precision-preview">{(group?.preview||[]).slice(0,2).map(r=><div key={r.line}><span>行 {r.line} → step {r.step}</span><code>{Object.entries(r.metrics).slice(0,4).map(([k,v])=>k+'='+num(v)).join(' · ')}</code><details><summary>查看原文</summary><pre>{r.source}</pre></details></div>)}</div>
        <p className="precision-small">跳过 {s.skipped_lines} 行非指标/不完整 JSON · 忽略 {s.invalid_values} 个非有限值{s.file.size>0&&` · ${(s.file.size/1024).toFixed(1)} KiB`}</p>
      </div>:<div className="precision-placeholder"><Activity size={18}/><span>自动提取 iteration、loss、grad_norm<br/>无需手写正则表达式</span></div>}
    </section>;
  };
  return <div className="precision-page">
    <div className="precision-configs"><div><Save size={16}/><select aria-label="已保存的精度对比" disabled={!!busy} value={draft.id||''} onChange={e=>{const config=configs.find(c=>c.id===e.target.value);setDraft(config||{...empty});setA(null);setB(null);clearResult()}}><option value="">新建对比配置</option>{configs.map(c=><option key={c.id} value={c.id}>{c.name}</option>)}</select></div><input aria-label="对比配置名称" placeholder="给这组对比起个名字…" value={draft.name} disabled={!!busy} onChange={e=>setDraft(d=>({...d,name:e.target.value}))}/><button className="secondary" disabled={!!busy||!draft.baseline.host_id||!draft.candidate.host_id} onClick={save}><Save size={14}/>保存配置</button>{draft.id&&<><button className="text-button" disabled={!!busy} onClick={()=>setDraft(d=>({...d,id:undefined,name:d.name+' 副本'}))}>另存为</button><button className="icon-button" aria-label="删除对比配置" disabled={!!busy} onClick={()=>execute('delete',async()=>{await api('/configs/'+draft.id,'DELETE');setConfigs(await api('/configs'));setDraft(d=>({...d,id:undefined}));setNotice('已删除保存的配置，远端日志保持原样。')})}><Trash2 size={15}/></button></>}</div>
    <div className="precision-pair">{card('baseline',a)}{card('candidate',b)}</div>
    <section className="precision-options"><div className="precision-metric-options"><strong>比较指标</strong>{available.map(name=><label key={name}><input type="checkbox" disabled={!!busy} checked={draft.metrics.includes(name)} onChange={()=>update({metrics:draft.metrics.includes(name)?draft.metrics.filter(n=>n!==name):[...draft.metrics,name].slice(0,8)})}/>{name}</label>)}</div><div className="precision-controls"><label>起始 step<input aria-label="起始 step" type="number" min="0" placeholder="不限" disabled={!!busy} value={draft.start??''} onChange={e=>update({start:e.target.value===''?null:+e.target.value})}/></label><label>结束 step<input aria-label="结束 step" type="number" min="0" placeholder="不限" disabled={!!busy} value={draft.end??''} onChange={e=>update({end:e.target.value===''?null:+e.target.value})}/></label><label>重复 step<select aria-label="重复 step 处理" disabled={!!busy} value={draft.duplicate_policy} onChange={e=>update({duplicate_policy:e.target.value})}><option value="error">提示错误，不自动合并</option><option value="first">保留首条</option><option value="last">保留末条</option></select></label><div className="precision-run"><button className="secondary" disabled={!!busy||!a||!b||!draft.metrics.length} onClick={()=>execute('compare',async()=>{if(a&&b)await compare(a,b)})}>计算误差</button><button className="primary" disabled={!!busy||!draft.baseline.host_id||!draft.baseline.path||!draft.candidate.host_id||!draft.candidate.path||!draft.metrics.length} onClick={readBoth}>{busy==='read'?<LoaderCircle size={15} className="spin"/>:<RefreshCw size={15}/>}读取并对比</button></div></div></section>
    {error&&<div role="alert" className="precision-error">{error}</div>}{notice&&<div role="status" className="precision-success">{notice}</div>}
    {result&&metric?<><div className="precision-result-heading"><h2>对比结果 <small>step {result.range.start}–{result.range.end}</small></h2><span>快照读取于 {readAt} · 日志更新后重新读取</span><button className="text-button" onClick={exportCSV}><Download size={14}/>导出全部 CSV</button></div>
      {(a?.demo||b?.demo)&&<div className="precision-warning precision-demo">当前是示例对比：待验证数值为人为偏移，用于展示流程，不代表真实服务器精度。</div>}
      <div className="precision-alignment"><span>共同 step <strong>{result.alignment.common_steps}</strong></span><span>仅基准存在 <strong>{result.alignment.baseline_only}</strong></span><span>仅待验证存在 <strong>{result.alignment.candidate_only}</strong></span><span>按真实 step 对齐，不插值、不平滑</span></div>
      {result.learning_rate_mismatch_count>0&&<div className="precision-warning precision-demo">{result.learning_rate_mismatch_count} 个共同 step 的 learning_rate 不一致，首次出现在 step {result.learning_rate_first_mismatch}，请核对训练配置。</div>}
      <div className="precision-tabs">{result.metrics.map(m=><button key={m.name} className={m.name===metric.name?'chosen':''} onClick={()=>{setActive(m.name);setPicked(null);setSource(null)}}>{m.name}<small>{m.count} 个有效配对</small></button>)}</div>
      <div className="precision-scores"><div><span>平均绝对误差 · MAE</span><strong>{num(metric.mae)}</strong><small>Σ |待验证 − 基准| / 有效配对数</small></div><div><span>最大绝对误差</span><strong>{num(metric.max_abs_error)}</strong><small>{metric.max_error_step!=null?'step '+metric.max_error_step:'无有效配对'}</small></div><div><span>有效配对</span><strong>{metric.count}<small> / {result.alignment.common_steps}</small></strong><small>{metric.missing_metric_steps} 个共同 step 缺少此指标</small></div></div>
      {metric.count>0?<><div className="precision-charts"><MetricChart title={metric.name+' 原始曲线'} series={[{label:'基准 A',color:'var(--accent)',points:metric.baseline_series},{label:'待验证 B',color:'var(--precision-blue)',points:metric.candidate_series}]} points={metric.points} picked={picked?.step} onPick={p=>{setPicked(p);setSource(null)}}/><MetricChart title="逐步绝对误差" series={[{label:'|B − A|',color:'var(--amber)',points:metric.points.map(p=>({step:p.step,value:p.absolute_error}))}]} points={metric.points} picked={picked?.step} onPick={p=>{setPicked(p);setSource(null)}}/></div>
        {picked&&<div className="precision-picked"><span>step {picked.step} · A {num(picked.baseline)} · B {num(picked.candidate)} · |Δ| {num(picked.absolute_error)}</span><button className="text-button" disabled={!!busy} onClick={()=>inspect(picked)}>查看此步原文</button></div>}
        <section className="precision-diff"><div className="precision-result-heading"><h2>逐步误差</h2><label>排序<select aria-label="误差表排序" value={sort} onChange={e=>setSort(e.target.value)}><option value="error">绝对误差从大到小</option><option value="step">step 从小到大</option></select></label></div><div className="precision-table-wrap"><table><thead><tr><th>step</th><th>基准 A</th><th>待验证 B</th><th>B − A</th><th>绝对误差</th><th>日志原文</th></tr></thead><tbody>{table.slice(0,200).map(p=><tr key={p.step} className={picked?.step===p.step?'selected':''}><td>{p.step}</td><td>{num(p.baseline)}</td><td>{num(p.candidate)}</td><td>{num(p.difference)}</td><td>{num(p.absolute_error)}</td><td><button className="text-button" disabled={!!busy} onClick={()=>inspect(p)}>A:{p.baseline_line} / B:{p.candidate_line}</button></td></tr>)}</tbody></table></div>{table.length>200&&<p className="precision-small">表格展示前 200 行；统计使用全部配对，CSV 导出全部记录。</p>}</section>
        {source&&<section className="precision-source"><h2>step {picked?.step} 日志原文</h2><div><article><h3>基准 · 行 {source.baseline.line}</h3><pre>{source.baseline.source}</pre></article><article><h3>待验证 · 行 {source.candidate.line}</h3><pre>{source.candidate.source}</pre></article></div><small>单行原文最多展示 800 字符；提取数值不受此展示长度限制。</small></section>}</>:<div className="precision-placeholder">此指标在共同 step 中没有有效配对，请选择其他指标。</div>}
    </>:<div className="precision-welcome"><Activity size={28}/><h2>把两台机器的训练日志放在一起看</h2><p>直接读取远端 JSON 日志，自动提取 step 和指标。日志不需要先下载，也不用填写正则。</p><button className="secondary" disabled={!!busy} onClick={demo}>载入示例，看看对比效果</button></div>}
    <p className="precision-footnote">使用现有 SSH 账号只读访问，不使用 sudo，不修改远端文件。每份日志上限 64 MiB、10,000 条训练记录；结果快照保留约 30 分钟，配置单独保存。曲线可能抽样绘制，MAE 始终使用全部有效配对。</p>
    {browser&&<div className="modal-shade"><section role="dialog" aria-modal="true" aria-label="选择远端日志" className="modal precision-browser"><div className="modal-header"><div><h2>选择远端日志</h2><p className="subtle">{hosts.find(h=>h.id===draft[browser].host_id)?.target}</p></div><button className="icon-button" disabled={!!busy} aria-label="关闭日志浏览" onClick={()=>setBrowser(null)}><X size={18}/></button></div><form className="precision-browse-path" onSubmit={e=>{e.preventDefault();execute('browse',()=>browse(browser,folder))}}><input aria-label="远端目录路径" value={folder} disabled={!!busy} onChange={e=>setFolder(e.target.value)}/><button className="secondary" disabled={!!busy}>前往</button><button type="button" className="secondary" aria-label="上一级日志目录" disabled={!!busy} onClick={()=>execute('browse',()=>browse(browser,directory?.parent||'~'))}><ArrowUp size={16}/></button></form><div className="precision-file-list">{directory?.entries.map(entry=><button type="button" key={entry.path} disabled={!!busy} onClick={()=>{if(entry.directory)execute('browse',()=>browse(browser,entry.path));else{setLocation(browser,{path:entry.path});setBrowser(null)}}}>{entry.directory?<FolderOpen size={16}/>:<FileText size={16}/>}<span>{entry.name}</span><small>{entry.directory?'目录':(entry.size/1024).toFixed(1)+' KiB'}</small></button>)}{directory?.entries.length===0&&<p className="subtle">当前目录没有可见文件。</p>}</div>{directory?.truncated&&<p className="precision-warning">仅显示前 500 项，可在路径栏输入更具体的目录。</p>}</section></div>}
  </div>;
}

function MetricChart({title,series,points,picked,onPick}:{title:string;series:{label:string;color:string;points:Series}[];points:Point[];picked?:number;onPick:(p:Point)=>void}){
  const all=series.flatMap(s=>s.points),minX=Math.min(...all.map(p=>p.step)),maxX=Math.max(...all.map(p=>p.step));
  const scale=Math.max(...all.map(p=>Math.abs(p.value)),1e-300);
  const low=Math.min(...all.map(p=>p.value/scale)),high=Math.max(...all.map(p=>p.value/scale));
  const span=high-low||Math.max(Math.abs(high)*.1,.1),bottom=low-span*.08,top=high+span*.08;
  const x=(step:number)=>64+(step-minX)/(maxX-minX||1)*596;
  const y=(value:number)=>220-(value/scale-bottom)/(top-bottom)*190;
  const tick=(i:number)=>(bottom+(top-bottom)*i/4)*scale;
  return <section className="precision-chart"><h3>{title}</h3><div className="precision-legend">{series.map(s=><span key={s.label}><i style={{background:s.color}}/>{s.label}</span>)}</div><svg viewBox="0 0 690 255" role="img" aria-label={title+'，横轴为 step，点击曲线定位对应步数'} onClick={e=>{const rect=e.currentTarget.getBoundingClientRect(),svgX=(e.clientX-rect.left)/rect.width*690;const step=minX+(svgX-64)/596*(maxX-minX||1);if(points.length)onPick(points.reduce((best,p)=>Math.abs(p.step-step)<Math.abs(best.step-step)?p:best,points[0]))}}>
    {Array.from({length:5},(_,i)=><g key={i}><line x1="64" x2="660" y1={220-i*47.5} y2={220-i*47.5} className="precision-grid"/><text x="57" y={224-i*47.5} textAnchor="end">{axisNum(tick(i))}</text></g>)}
    {series.map(s=>{const stride=Math.max(1,Math.ceil(s.points.length/1500)),sample=s.points.filter((_,i)=>i%stride===0||i===s.points.length-1);return <g key={s.label}><polyline fill="none" stroke={s.color} strokeWidth="2" points={sample.map(p=>x(p.step)+','+y(p.value)).join(' ')}/>{sample.length<15&&sample.map(p=><circle key={p.step} cx={x(p.step)} cy={y(p.value)} r="3" fill={s.color}/>)}</g>})}
    {picked!=null&&<line x1={x(picked)} x2={x(picked)} y1="24" y2="220" className="precision-cursor"/>}<text x="64" y="246">{minX}</text><text x="660" y="246" textAnchor="end">{maxX} step</text>
  </svg><p>点击曲线定位 step；连线仅用于展示。</p></section>;
}
