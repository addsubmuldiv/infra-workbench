import {ui} from './assistantLocale';
import React,{useEffect,useLayoutEffect,useRef,useState} from 'react';
import {createPortal} from 'react-dom';
import {Check,ChevronDown,LoaderCircle,Settings2} from 'lucide-react';
import {agentRequest,type AgentView} from './agentSettings';
import {modelCacheKey,readModelCache,writeModelCache} from './modelCache';

export function ChatModelPicker({model,openSettings}:{model?:string;openSettings?:()=>void}){
  const [current,setCurrent]=useState(model),[view,setView]=useState<AgentView|null>(null),[models,setModels]=useState<string[]|null>(null);
  const [loading,setLoading]=useState(false),[switching,setSwitching]=useState(''),[truncated,setTruncated]=useState(false);
  const [filter,setFilter]=useState(''),[error,setError]=useState('');
  const [open,setOpen]=useState(false),[position,setPosition]=useState({left:12,bottom:0,width:280,maxHeight:320});
  const trigger=useRef<HTMLButtonElement>(null),menu=useRef<HTMLDivElement>(null),generation=useRef(0);
  useEffect(()=>{
    const invalidate=()=>{generation.current++;setOpen(false);setModels(null);setView(null);setLoading(false)};
    window.addEventListener('infra-workbench:agent-settings-changed',invalidate);
    return()=>{generation.current++;window.removeEventListener('infra-workbench:agent-settings-changed',invalidate)};
  },[]);
  useLayoutEffect(()=>{
    if(!open)return;
    const rect=trigger.current!.getBoundingClientRect(),width=Math.min(300,window.innerWidth-24);
    setPosition({left:Math.max(12,Math.min(rect.left,window.innerWidth-width-12)),bottom:window.innerHeight-rect.top+8,width,maxHeight:Math.max(80,rect.top-20)});
    const outside=(event:PointerEvent)=>{if(!trigger.current?.contains(event.target as Node)&&!menu.current?.contains(event.target as Node))setOpen(false)};
    const dismiss=(event:Event)=>{if(!menu.current?.contains(event.target as Node))setOpen(false)};
    document.addEventListener('pointerdown',outside);window.addEventListener('resize',dismiss);window.addEventListener('scroll',dismiss,true);
    menu.current?.querySelector('input')?.focus();
    return()=>{document.removeEventListener('pointerdown',outside);window.removeEventListener('resize',dismiss);window.removeEventListener('scroll',dismiss,true)};
  },[open]);
  useEffect(()=>setCurrent(model),[model]);
  useEffect(()=>{
    void load();
    const timer=window.setInterval(()=>void load(),60*60*1000);
    return()=>window.clearInterval(timer);
  },[]);
  const close=()=>setOpen(false);
  const load=async(force=false)=>{
    const ticket=++generation.current;
    setLoading(true);setError('');setFilter('');
    try{
      const next=await agentRequest<AgentView>();
      if(ticket!==generation.current)return;
      setView(next);setCurrent(next.model);
      const cacheKey=modelCacheKey(next),cached=readModelCache(cacheKey);
      if(cached){setModels(cached.models);setTruncated(cached.truncated);if(!force&&!cached.stale)return}
      else setModels(null);
      const list=await agentRequest<{models:string[];truncated:boolean}>('/models','POST',{
        profile_id:next.active_id,base_url:next.base_url,protocol:next.protocol,model:next.model,
        timeout_seconds:next.timeout_seconds,context_window:next.context_window
      });
      if(ticket!==generation.current)return;
      writeModelCache(cacheKey,list);
      setView(next);setCurrent(next.model);setModels(list.models);setTruncated(list.truncated);
    }catch(e){if(ticket===generation.current)setError(e instanceof Error?e.message:ui("无法获取模型列表"))}
    finally{if(ticket===generation.current)setLoading(false)}
  };
  const switchModel=async(name:string)=>{
    if(switching||!view)return;
    setSwitching(name);setError('');
    try{
      const value=await agentRequest<AgentView>('/model','PUT',{model:name,profile_id:view?.active_id});
      setView(value);setCurrent(value.model);
      window.dispatchEvent(new Event('infra-workbench:agent-settings-changed'));
      close();
    }catch(e){setError(e instanceof Error?e.message:ui("模型切换失败"))}
    finally{setSwitching('')}
  };
  const query=filter.trim().toLowerCase();
  const visible=(models||[]).filter(item=>!query||item.toLowerCase().includes(query));
  return <div className="chat-model-picker">
    <button ref={trigger} type="button" className="text-button" aria-expanded={open} aria-haspopup="dialog" onClick={()=>{if(open)close();else{setOpen(true);void load()}}} title={ui("切换模型")} aria-label={ui("切换模型")}>{switching&&<LoaderCircle size={12} className="spin"/>}<span>{current||ui("配置模型")}</span><ChevronDown size={12}/></button>
    {open&&createPortal(<div ref={menu} className="chat-model-menu" role="dialog" aria-label={ui("选择模型")} style={position} onKeyDown={event=>{if(event.key==='Escape'){event.preventDefault();event.stopPropagation();close();trigger.current?.focus()}}}>
      {models===null?(loading&&<p className="chat-model-state"><LoaderCircle size={13} className="spin"/>{ui("正在获取模型列表…")}</p>):<>
        <input aria-label={ui("筛选模型")} placeholder={ui("筛选模型")} autoComplete="off" spellCheck={false} value={filter} onChange={event=>setFilter(event.target.value)}/>
        <div className="chat-model-list">{visible.map(item=><button type="button" key={item} className={item===current?'active':''} disabled={!!switching} aria-pressed={item===current} onClick={()=>void switchModel(item)}><span>{item}</span>{item===current?<Check size={13}/>:switching===item?<LoaderCircle size={13} className="spin"/>:null}</button>)}
          {!visible.length&&<p className="chat-model-state">{ui("没有匹配的模型")}</p>}
        </div>
        {truncated&&<p className="chat-model-state">{ui("模型较多，仅显示前 500 个；其他模型可在设置中手动填写。")}</p>}
      </>}
      {error&&<><p className="chat-model-state error" role="alert">{error}</p><button type="button" onClick={()=>void load(true)}>{ui("重新获取模型列表")}</button>{view&&<><input aria-label={ui("手动输入模型 ID")} placeholder={ui("或手动输入模型 ID")} value={filter} onChange={event=>setFilter(event.target.value)}/><button type="button" disabled={!filter.trim()||!!switching} onClick={()=>void switchModel(filter.trim())}>{ui("切换到此模型")}</button></>}</>}
      {models!==null&&<button type="button" className="chat-model-settings" disabled={loading} onClick={()=>void load(true)}>{ui("重新获取模型列表")}</button>}
      <button type="button" className="chat-model-settings" onClick={()=>{close();openSettings?.()}}><Settings2 size={13}/>{ui("打开模型设置")}</button>
    </div>,document.body)}
  </div>;
}
