import React,{useEffect,useRef,useState} from 'react';
import {BookOpen,Download,Plus,Upload} from 'lucide-react';
import {useAppConfirm} from './AppConfirm';
import {copySkillFiles,exportSkill,importSkill,skillMarkdown,skillRequest,type SkillDetail,type SkillDraft,type SkillMeta,type SkillValidation} from './skills';
import './skills.css';

const initial=()=>({'SKILL.md':skillMarkdown('my-skill','描述技能的用途，以及什么时候使用。','# 操作步骤\n\n1. 确定用户需求和目标。\n2. 使用当前可用的 MCP 工具完成操作。\n3. 根据实际结果说明完成情况。')});
type DraftItem={id:string;revision:number;name?:string;skill_name?:string;created?:number};
export function SkillsSettings(){
  const [items,setItems]=useState<SkillMeta[]>([]),[detail,setDetail]=useState<SkillDetail|null>(null),[draft,setDraft]=useState<SkillDraft|null>(null);
  const [drafts,setDrafts]=useState<DraftItem[]>([]);
  const [files,setFiles]=useState<Record<string,string>>(initial),[file,setFile]=useState('SKILL.md'),[editing,setEditing]=useState(false),[copyName,setCopyName]=useState('');
  const [pending,setPending]=useState('load'),[error,setError]=useState(''),[message,setMessage]=useState(''),[validation,setValidation]=useState<SkillValidation|null>(null);
  const alive=useRef(true),request=useRef<AbortController|null>(null),selection=useRef(0),busy=useRef(false),upload=useRef<HTMLInputElement>(null);
  const {confirm,confirmation}=useAppConfirm();
  const refresh=async(signal?:AbortSignal)=>{const [value,saved]=await Promise.all([skillRequest<{items:SkillMeta[]}>('','GET',undefined,signal),skillRequest<{items:DraftItem[]}>('/drafts','GET',undefined,signal)]);if(alive.current&&!signal?.aborted){setItems(value.items);setDrafts(saved.items??[])}};
  useEffect(()=>{alive.current=true;const controller=new AbortController();void refresh(controller.signal).catch(e=>{if(!controller.signal.aborted)setError(e.message)}).finally(()=>{if(alive.current)setPending('')});return()=>{alive.current=false;controller.abort();request.current?.abort()}},[]);
  useEffect(()=>{let controller:AbortController|undefined;const load=()=>{controller?.abort();controller=new AbortController();void refresh(controller.signal).catch(()=>{})};window.addEventListener('focus',load);window.addEventListener('infra-workbench:skills-changed',load);return()=>{controller?.abort();window.removeEventListener('focus',load);window.removeEventListener('infra-workbench:skills-changed',load)}},[]);
  const act=async(label:string,fn:(signal:AbortSignal)=>Promise<void>)=>{
    if(busy.current)return;busy.current=true;const controller=new AbortController();request.current=controller;setPending(label);setError('');setMessage('');
    try{await fn(controller.signal)}catch(e){if(alive.current&&!controller.signal.aborted)setError(e instanceof Error?e.message:'技能操作失败')}
    finally{busy.current=false;if(request.current===controller)request.current=null;if(alive.current)setPending('')}
  };
  const select=async(name:string)=>{if(editing&&!await confirm('切换技能会收起当前编辑内容，未保存的修改将丢失，是否继续？'))return;const seq=++selection.current;void act('detail',async signal=>{const value=await skillRequest<SkillDetail>('/'+encodeURIComponent(name),'GET',undefined,signal);if(alive.current&&seq===selection.current){setDetail(value);setEditing(false);setDraft(null);setValidation(null);setCopyName(name+'-copy')}})};
  const beginNew=async()=>{if(editing&&!await confirm('新建技能会替换当前编辑内容，是否继续？'))return;selection.current++;setDetail(null);setDraft(null);setFiles(initial());setFile('SKILL.md');setEditing(true);setValidation(null);setMessage('');setError('')};
  const edit=()=>{if(!detail)return;setFiles({...detail.files});setFile('SKILL.md');setDraft(null);setEditing(true);setValidation(null);setError('')};
  const resume=async(id:string)=>{if(editing&&!await confirm('打开草稿会替换当前编辑内容，未保存的修改将丢失，是否继续？'))return;void act('draft',async signal=>{const value=await skillRequest<SkillDraft>('/drafts/'+encodeURIComponent(id),'GET',undefined,signal);if(alive.current){setDetail(null);setDraft(value);setFiles(value.files);setFile('SKILL.md');setEditing(true);setValidation(null);setMessage('已打开保存的草稿。')}})};
  const change=(content:string)=>{setFiles(old=>({...old,[file]:content}));setValidation(null)};
  const saveDraft=async(signal:AbortSignal)=>{
    const value=draft?await skillRequest<SkillDraft>('/drafts/'+draft.id,'PUT',{revision:draft.revision,files},signal):await skillRequest<SkillDraft>('/drafts','POST',{files,...(detail?.source==='user'?{skill_name:detail.name,base_version:detail.version}:{})},signal);
    if(alive.current){setDraft(value);setFiles(value.files)}return value;
  };
  const validate=()=>act('validate',async signal=>{const value=await saveDraft(signal);const result=await skillRequest<SkillValidation>('/drafts/'+value.id+'/validate','POST',{revision:value.revision},signal);await refresh(signal);if(alive.current){setValidation(result);setMessage('草稿已保存。静态校验不代表已实际执行。')}});
  const install=()=>act('install',async signal=>{
    const value=await saveDraft(signal);const report=await skillRequest<SkillValidation>('/drafts/'+value.id+'/validate','POST',{revision:value.revision},signal);if(alive.current)setValidation(report);
    if(!report.valid)throw new Error('草稿未通过校验，请修改后再安装。');
    await skillRequest('/drafts/'+value.id+'/install','POST',{revision:value.revision},signal);await refresh(signal);
    if(alive.current){setEditing(false);setDraft(null);setDetail(null);setMessage('技能已安装并启用，下一轮对话生效。');window.dispatchEvent(new Event('infra-workbench:skills-changed'))}
  });
  const receive=async(picked:File)=>{if(editing&&!await confirm('导入文件会替换当前编辑内容，是否继续？'))return;void act('import',async signal=>{const value=await importSkill(picked,signal);if(!alive.current)return;setDetail(null);setDraft(value);setFiles(value.files);setFile('SKILL.md');setEditing(true);setValidation(null);setMessage('已导入为草稿，请检查内容并校验。')})};
  const mutate=(path:string,method:string,body?:unknown)=>act('update',async signal=>{await skillRequest(path,method,body,signal);await refresh(signal);if(!alive.current)return;if(detail){const value=await skillRequest<SkillDetail>('/'+encodeURIComponent(detail.name),'GET',undefined,signal);if(alive.current)setDetail(value)}setMessage('已更新，下一轮对话生效。');window.dispatchEvent(new Event('infra-workbench:skills-changed'))});
  const remove=async()=>{if(!detail||!await confirm(`卸载技能 ${detail.name} 及其版本？历史对话记录会保留。`))return;void act('delete',async signal=>{await skillRequest('/'+encodeURIComponent(detail.name)+'?expected_version='+detail.version,'DELETE',undefined,signal);await refresh(signal);if(alive.current){setDetail(null);setMessage('已卸载，下一轮对话不再加载此技能。');window.dispatchEvent(new Event('infra-workbench:skills-changed'))}})};
  const download=()=>{if(!detail)return;void act('export',async()=>{const blob=await exportSkill(detail.name,detail.version);const url=URL.createObjectURL(blob);const link=document.createElement('a');link.href=url;link.download=detail.name+'.zip';link.click();setTimeout(()=>URL.revokeObjectURL(url),1000)})};
  const copy=()=>{if(!detail||!copyName.trim())return;void act('copy',async signal=>{const blob=await exportSkill(detail.name,detail.version);if(signal.aborted)return;const imported=await importSkill(new File([blob],detail.name+'.zip'),signal);const renamed=copySkillFiles(imported.files,copyName);const value=await skillRequest<SkillDraft>('/drafts/'+imported.id,'PUT',{revision:imported.revision,files:renamed},signal);if(alive.current){setFiles(value.files);setDetail(null);setDraft(value);setFile('SKILL.md');setEditing(true);setValidation(null);setMessage('已复制为草稿，附件已保留。')}})};
  return <section className="settings-page skills-settings" aria-label="技能管理">
    <div className="settings-section-title"><BookOpen size={20}/><div><h2>技能</h2><p>把操作流程保存为技能，让 Agent 按需使用。也可以直接在聊天里要求创建并安装技能。</p></div></div>
    <div className="skills-actions"><button className="secondary" disabled={!!pending} onClick={beginNew}><Plus size={15}/>新建 / 粘贴技能</button><button className="secondary" disabled={!!pending} onClick={()=>upload.current?.click()}><Upload size={15}/>导入 Markdown / ZIP</button><button className="text-button" disabled={!!pending} onClick={()=>act('load',signal=>refresh(signal))}>刷新</button><input ref={upload} hidden type="file" accept=".md,.zip" aria-label="导入技能文件" onChange={event=>{const picked=event.target.files?.[0];event.target.value='';if(picked)void receive(picked)}}/></div>
    {error&&<div className="settings-error" role="alert">{error}</div>}{message&&<div className="settings-success" role="status">{message}</div>}
    {pending&&<p role="status">正在处理…</p>}
    <div className="skills-layout"><nav className="skills-list" aria-label="技能与草稿"><h3>已安装</h3>{!items.length&&!pending&&<p>暂无已安装技能。</p>}{items.map(item=><button key={item.name} disabled={!!pending} className={detail?.name===item.name?'selected':''} onClick={()=>select(item.name)}><strong>{item.name}</strong><span>{item.description}</span><small>{item.source==='builtin'?'内置':'用户'} · v{item.version} · {item.enabled?'已启用':'已停用'}</small></button>)}<h3>草稿</h3>{!drafts.length&&!pending&&<p>暂无未安装草稿。</p>}{drafts.map(item=><button key={item.id} className={draft?.id===item.id?'selected':''} disabled={!!pending} onClick={()=>resume(item.id)}><strong>{item.name||item.skill_name||'未命名草稿'}</strong><small>修订 {item.revision}{item.created?' · '+new Date(item.created*1000).toLocaleString('zh-CN'):''}</small></button>)}</nav>
    <div className="settings-card skill-detail">{editing?<>
      <h3>{detail?'编辑 '+detail.name:'技能草稿'}</h3><p className="settings-help">在 SKILL.md 中填写名称、描述和步骤。参考资料保持相对路径。安装不会增加 MCP 权限；脚本不会执行。</p>
      <fieldset disabled={!!pending}><label className="form-label">编辑文件<select aria-label="技能文件" value={file} onChange={event=>setFile(event.target.value)}>{Object.keys(files).map(name=><option key={name}>{name}</option>)}</select></label>
      <textarea className="skill-editor" aria-label="技能文件内容" spellCheck={false} value={files[file]??''} onChange={event=>change(event.target.value)}/>
      <FileAdder onAdd={name=>{setFiles(old=>({...old,[name]:''}));setFile(name);setValidation(null)}} names={Object.keys(files)}/>
      {file!=='SKILL.md'&&<button className="text-button" onClick={()=>{setFiles(old=>Object.fromEntries(Object.entries(old).filter(([name])=>name!==file)));setFile('SKILL.md');setValidation(null)}}>移除此文件</button>}
      <div className="skills-actions"><button className="secondary" onClick={validate}>保存草稿并校验</button><button className="primary" onClick={install}>安装并启用</button><button className="text-button" onClick={async()=>{if(await confirm('收起编辑会丢弃未保存的修改，是否继续？'))setEditing(false)}}>收起编辑</button></div></fieldset>
      {draft&&<p className="settings-help">草稿 {draft.id} · 修订 {draft.revision}</p>}
      {!!draft?.file_manifest?.some(item=>!item.text)&&<p className="settings-help">保留的二进制附件：{draft.file_manifest.filter(item=>!item.text).map(item=>item.path).join('、')}；当前 Agent 不读取这些附件。</p>}
      {validation&&<div className="skill-validation" role="status"><strong>{validation.valid?'格式与声明依赖校验通过':'校验未通过'}</strong>{validation.errors?.map((value,i)=><p key={'e'+i}>{value}</p>)}{validation.warnings?.map((value,i)=><p key={'w'+i}>{value}</p>)}<small>此结果不代表技能已实际试运行。</small></div>}
    </>:detail?<>
      <h3>{detail.name} <small>v{detail.version}</small></h3><p>{detail.description}</p><p className="settings-help">{detail.source==='builtin'?'内置技能只读，可以复制后修改。':'用户技能'} · {detail.enabled?'已启用':'已停用'}</p>
      {detail.warnings?.map((warning,i)=><p className="settings-help" key={i}>{warning}</p>)}
      <div className="skills-actions"><button className="secondary" disabled={!!pending} onClick={download}><Download size={14}/>导出 ZIP</button>{detail.source==='user'&&<><button className="secondary" disabled={!!pending} onClick={edit}>编辑</button><button className="secondary" disabled={!!pending} onClick={()=>mutate('/'+encodeURIComponent(detail.name)+'/enabled','PUT',{enabled:!detail.enabled,expected_version:detail.version})}>{detail.enabled?'停用':'启用'}</button><button className="text-button" disabled={!!pending} onClick={remove}>卸载</button></>}</div>
      <div className="skill-copy"><label className="form-label">复制为新技能<input aria-label="复制后的技能名称" maxLength={64} value={copyName} disabled={!!pending} onChange={event=>setCopyName(event.target.value)}/></label><button className="secondary" disabled={!!pending||!copyName.trim()||copyName.trim()===detail.name} onClick={copy}>复制并编辑</button></div>
      <h4>文件</h4>{Object.entries(detail.files).map(([name,content])=><details key={name} open={name==='SKILL.md'}><summary>{name}</summary><pre>{content}</pre></details>)}
      {!!detail.file_manifest?.some(item=>!item.text)&&<p>二进制附件：{detail.file_manifest.filter(item=>!item.text).map(item=>item.path).join('、')}</p>}
      {detail.source==='user'&&<><h4>历史版本</h4><ul className="skill-versions">{detail.versions?.map(version=><li key={version.version}>v{version.version}{version.created&&<small> · {new Date(version.created*1000).toLocaleString('zh-CN')}</small>}{version.version===detail.version?<span> 当前版本</span>:<button className="text-button" disabled={!!pending} onClick={()=>mutate('/'+encodeURIComponent(detail.name)+'/rollback','POST',{version:version.version,expected_version:detail.version})}>切换至此版本</button>}</li>)}</ul></>}
    </>:<p className="settings-help">选择一个技能查看详情，或新建、导入技能。安装和停用均在下一轮对话生效。</p>}</div></div>{confirmation}
  </section>;
}
function FileAdder({onAdd,names}:{onAdd:(name:string)=>void;names:string[]}){
  const [name,setName]=useState('');const valid=!!name.trim()&&!names.includes(name.trim())&&!/(^\/|\\|(^|\/)\.\.?($|\/)|:)/.test(name.trim());
  return <div className="skill-copy"><label className="form-label">新增文本文件<input aria-label="新增技能文件路径" value={name} placeholder="references/guide.md" onChange={event=>setName(event.target.value)}/></label><button type="button" className="secondary" disabled={!valid} onClick={()=>{onAdd(name.trim());setName('')}}>添加文件</button></div>;
}

