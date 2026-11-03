import {useLocale} from './i18n';
import {toolText as tt} from './toolI18n';
import {useWorkspaceRestore} from './workspaceHooks';
import {workspaceStorage} from './workspaceState';
import React,{useEffect,useRef,useState} from 'react';
import {createPortal} from 'react-dom';
import {examples,variables,renderTemplate,type Snippet} from './terminalTemplates';
import {fitFileWindow,moveFileWindow,type WindowFrame} from './fileWindow';
import type {HistoryCommand} from './terminalSuggestions';
import {activateFloatingWindow,registerFloatingWindow} from './windowLayers';

const frameKey='iwb-terminal-command-window';
const viewport=()=>({width:window.innerWidth,height:window.innerHeight});
function initialFrame():WindowFrame{
  const size=viewport();
  const fallback={x:(size.width-900)/2,y:Math.max(24,(size.height-640)/2),width:900,height:640};
  try{
    const value=JSON.parse(workspaceStorage.getItem(frameKey)||'null');
    if(value&&['x','y','width','height'].every(key=>typeof value[key]==='number'&&Number.isFinite(value[key])))return fitFileWindow(value,size);
  }catch{}
  return fitFileWindow(fallback,size);
}

export default function TerminalCommands({host,workspace,action,insert,close}:{host:string;workspace:any;action:(value:object)=>void;insert:(text:string)=>boolean;close:()=>void}){
  useLocale();
  const [item,setItem]=useState<Snippet|null>(null),[values,setValues]=useState<Record<string,string>>({}),[section,setSection]=useState('commands');
  const [source,setSource]=useState('new'),[pending,setPending]=useState<{item:Snippet;baseline:unknown}|null>(null),[message,setMessage]=useState('');
  const [frame,setFrame]=useState(initialFrame),[maximized,setMaximized]=useState(false),[minimized,setMinimized]=useState(false);
  const remoteFrame=useWorkspaceRestore(frameKey,initialFrame,setFrame);
  const gesture=useRef<{pointer:number;kind:'move'|'resize';x:number;y:number;frame:WindowFrame}|null>(null);
  const preview=renderTemplate(item?.command||'',values),settings=workspace.settings;
  const select=(value:Snippet,origin='new')=>{setItem({...value,...(origin==='template'?{name:tt(value.name)}:{})});setValues({});setSource(origin);setMessage('')};
  const useCommand=(value:Snippet)=>{
    if(variables(value.command).length){select(value,'saved');return}
    if(insert(value.command))close();
  };
  useEffect(()=>{
    const resize=()=>setFrame(old=>fitFileWindow(old,viewport()));
    window.addEventListener('resize',resize);return()=>window.removeEventListener('resize',resize);
  },[]);
  useEffect(()=>{if(remoteFrame?.current){remoteFrame.current=false;return}try{workspaceStorage.setItem(frameKey,JSON.stringify(frame))}catch{}},[frame]);
  useEffect(()=>{
    if(!pending||workspace.snippets===pending.baseline)return;
    const saved=workspace.snippets.find((value:Snippet)=>value.name===pending.item.name&&value.command===pending.item.command&&(!pending.item.id||value.id===pending.item.id));
    if(saved){
      setPending(null);setMessage(tt("已保存到我的收藏"));
      if(item&&item.command===pending.item.command&&item.name.trim()===pending.item.name){setItem(null);setSection('commands')}
    }
  },[workspace.snippets,pending]);
  useEffect(()=>{
    if(!pending)return;
    const timer=setTimeout(()=>{setPending(null);setMessage(tt("尚未确认保存，请检查终端中的错误提示后重试"))},6000);
    return()=>clearTimeout(timer);
  },[pending]);
  const save=()=>{
    if(!item||pending)return;
    const snippet={...item,name:item.name.trim()};
    setPending({item:snippet,baseline:workspace.snippets});setMessage(tt("正在保存…"));action({action:'save_snippet',snippet});
  };
  const startGesture=(event:React.PointerEvent,kind:'move'|'resize')=>{
    if(event.button!==0||gesture.current||maximized)return;
    if(kind==='move'&&(event.target as HTMLElement).closest('button,input,select,textarea,a'))return;
    event.preventDefault();event.currentTarget.setPointerCapture(event.pointerId);
    gesture.current={pointer:event.pointerId,kind,x:event.clientX,y:event.clientY,frame};
  };
  const moveGesture=(event:React.PointerEvent)=>{
    const start=gesture.current;if(!start||start.pointer!==event.pointerId)return;
    const dx=event.clientX-start.x,dy=event.clientY-start.y;
    setFrame(start.kind==='move'?moveFileWindow(start.frame,dx,dy,viewport(),minimized):fitFileWindow({...start.frame,width:start.frame.width+dx,height:Math.max(360,start.frame.height+dy)},viewport()));
  };
  const endGesture=(event:React.PointerEvent)=>{if(gesture.current?.pointer===event.pointerId)gesture.current=null};
  const dimensions=minimized?{left:Math.max(8,Math.min(frame.x,window.innerWidth-328)),top:frame.y,width:Math.min(320,window.innerWidth-16),height:56}:maximized?{left:12,top:12,width:window.innerWidth-24,height:window.innerHeight-24}:{left:frame.x,top:frame.y,width:frame.width,height:frame.height};
  const editing=item&&(section==='commands'||section==='templates');

  return createPortal(<section data-floating-window="commands" ref={registerFloatingWindow} onPointerDownCapture={activateFloatingWindow} onFocusCapture={activateFloatingWindow} className={'terminal-tools '+(minimized?'minimized':'')} role="dialog" aria-modal="false" aria-label={host+tt(" 命令与设置")} style={dimensions} onPointerMove={moveGesture} onPointerUp={endGesture} onPointerCancel={endGesture} onLostPointerCapture={endGesture}>
    <header className="terminal-tools-heading" onPointerDown={event=>startGesture(event,'move')} onDoubleClick={event=>{if(!(event.target as HTMLElement).closest('button')){setMaximized(!maximized);setMinimized(false)}}}>
      <div><strong>{host} {tt(" · 命令与设置")}</strong>{!minimized&&<small>{tt("拖动标题移动 · 右下角拉伸大小")}</small>}</div>
      <div className="terminal-tools-window-actions"><button aria-label={minimized?tt("恢复命令窗口"):tt("最小化命令窗口")} onClick={()=>setMinimized(!minimized)}>{minimized?tt("恢复"):tt("最小化")}</button>{!minimized&&<button aria-label={maximized?tt("还原命令窗口"):tt("最大化命令窗口")} onClick={()=>setMaximized(!maximized)}>{maximized?tt("还原"):tt("最大化")}</button>}<button onClick={close}>{tt("关闭")}</button></div>
    </header>
    <div className="terminal-tools-body" hidden={minimized}>
      <nav>{[['commands',`${tt("我的收藏 (")}${workspace.snippets.length})`],['templates',tt("内置模板")],['history',tt("历史")],['settings',tt("设置")]].map(([id,label])=><button key={id} onClick={()=>{setSection(id);setItem(null);setMessage('')}} aria-pressed={section===id}>{label}</button>)}</nav>
      {message&&<p className="terminal-command-message" role="status">{tt(message)}</p>}
      {editing?<div className="terminal-command-editor">
        <div className="terminal-command-heading"><button onClick={()=>setItem(null)}>{tt("← 返回列表")}</button><strong>{item.id?tt("编辑收藏"):source==='template'?tt(item.name):tt("新建收藏")}</strong></div>
        <div className="terminal-form-scroll">
          {source==='template'?<details className="terminal-template-source"><summary>{tt("修改模板名称或命令")}</summary><label>{tt("名称")}<input value={item.name} onChange={event=>setItem({...item,name:event.target.value})} maxLength={80}/></label><textarea aria-label={tt("收藏命令")} rows={3} value={item.command} onChange={event=>setItem({...item,command:event.target.value})}/></details>:<><label>{tt("收藏名称")}<input value={item.name} onChange={event=>setItem({...item,name:event.target.value})} maxLength={80} placeholder={tt("例如：查看 GPU 占用")}/></label><label>{tt("命令内容")}<textarea aria-label={tt("收藏命令")} rows={4} value={item.command} placeholder={tt("输入命令；可用 {{script}} 表示参数")} onChange={event=>setItem({...item,command:event.target.value})}/></label></>}
          {!!variables(item.command).length&&<><h4>{tt("填写参数")}</h4><div className="terminal-template-values">{variables(item.command).map(key=><label key={key}>{key}<input value={values[key]||''} onChange={event=>setValues({...values,[key]:event.target.value})}/></label>)}</div></>}
          <h4>{tt("将填入终端的命令")}</h4><pre>{preview.error||preview.command||tt("输入命令后在此预览")}</pre><p>{tt("只填入，不自动执行。参数作为单个 Shell 参数转义，变量请放在引号外。")}</p>
        </div>
        <footer><button disabled={!!pending||!item.name.trim()||!item.command.trim()} onClick={save}>{pending?tt("正在保存…"):item.id?tt("保存修改"):source==='template'?tt("收藏此模板"):tt("保存收藏")}</button>{item.id&&<button onClick={()=>{action({action:'delete_snippet',id:item.id});setItem(null);setMessage(tt("已发送删除请求"))}}>{tt("删除收藏")}</button>}<button className="terminal-command-primary" disabled={!!preview.error||!preview.command} onClick={()=>{if(insert(preview.command))close()}}>{tt("填入终端")}</button></footer>
      </div>:<div className="terminal-command-content">
        {section==='commands'&&<><div className="terminal-command-heading"><strong>{tt("我的收藏 · ")}{workspace.snippets.length} {tt(" 条")}</strong><button onClick={()=>select({name:'',command:''})}>{tt("＋ 新建收藏")}</button></div>
          {workspace.snippets.length===0?<div className="terminal-command-empty"><strong>{tt("这台机器还没有收藏命令")}</strong><p>{tt("可以自己新建，也可以从历史记录中收藏。训练、日志等示例在「内置模板」中。")}</p><button onClick={()=>setSection('history')}>{tt("去历史记录收藏")}</button></div>:<div className="terminal-command-cards">{workspace.snippets.map((snippet:Snippet)=><article key={snippet.id}><div><strong>{snippet.name}</strong><div><button aria-label={tt("编辑收藏 ")+snippet.name} onClick={()=>select(snippet,'saved')}>{tt("编辑")}</button><button aria-label={tt("填入收藏 ")+snippet.name} onClick={()=>useCommand(snippet)}>{tt("填入")}</button></div></div><code title={snippet.command}>{snippet.command}</code></article>)}</div>}
        </>}
        {section==='templates'&&<><p>{tt("以下是内置示例，不是已保存的收藏。选择后填参数，再填入终端；常用的也可以收藏。")}</p><div className="terminal-command-cards">{examples.map(snippet=><article key={snippet.name}><div><strong>{tt(snippet.name)}</strong><button aria-label={tt("使用模板 ")+tt(snippet.name)} onClick={()=>select(snippet,'template')}>{tt("使用模板")}</button></div><code>{snippet.command}</code></article>)}</div></>}
        {section==='history'&&<><label><input type="checkbox" checked={settings.history_enabled!==false} onChange={event=>action({action:'settings',settings:{history_enabled:event.target.checked}})}/>{tt("启用历史命令提示")}</label><p>{tt("最近 200 条命令。敏感命令请在开头加空格，或关闭记录。")}</p><button onClick={()=>action({action:'clear_history'})}>{tt("清空历史")}</button>{!workspace.history.length&&<p>{tt("暂无历史记录。")}</p>}<div className="terminal-history">{workspace.history.map((entry:HistoryCommand)=><div key={entry.command}><code>{entry.command}</code><button onClick={()=>insert(entry.command)}>{tt("填入")}</button><button onClick={()=>{select({name:entry.command.slice(0,60),command:entry.command});setSection('commands')}}>{tt("收藏")}</button></div>)}</div></>}
        {section==='settings'&&<><label><input type="checkbox" checked={!!settings.sudo_reuse} onChange={event=>action({action:'settings',settings:{sudo_reuse:event.target.checked}})}/>{tt("允许此机器终端使用已保存的 sudo 密码")}</label><p>{tt("在机器的 sudo 设置中保存密码后，等待密码时点击按钮或按 Alt+Enter。每条命令只尝试一次。")}</p><label><input type="checkbox" checked={settings.notify_enabled!==false} onChange={event=>action({action:'settings',settings:{notify_enabled:event.target.checked}})}/>{tt("长命令结束后通知")}</label><label>{tt("最短执行时间（秒）")}<input type="number" min={1} max={86400} defaultValue={settings.notify_seconds??60} onBlur={event=>{const value=Number(event.target.value);if(Number.isInteger(value)&&value>=1&&value<=86400)action({action:'settings',settings:{notify_seconds:value}});else event.target.value=String(settings.notify_seconds??60)}}/></label><p>{tt("只在确认命令结束时提醒，显示耗时和退出码。SSH 断开和重连保持静默。")}</p></>}
      </div>}
    </div>
    {!minimized&&!maximized&&<div className="terminal-tools-resize" role="separator" aria-label={tt("调整命令窗口大小")} tabIndex={0} onPointerDown={event=>startGesture(event,'resize')} onKeyDown={event=>{const offsets:Record<string,[number,number]>={ArrowLeft:[-20,0],ArrowRight:[20,0],ArrowUp:[0,-20],ArrowDown:[0,20]};const offset=offsets[event.key];if(offset){event.preventDefault();setFrame(old=>fitFileWindow({...old,width:old.width+offset[0],height:Math.max(360,old.height+offset[1])},viewport()))}}}/>}
  </section>,document.body);
}
