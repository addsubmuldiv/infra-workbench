import React,{useId,useLayoutEffect,useRef,useState} from 'react';
import {createPortal} from 'react-dom';
import {Check,ChevronDown,MessageSquare} from 'lucide-react';
import type {ChatItem} from './agentChat';

export function ChatSessionPicker({items,value,disabled,onChange}:{items:ChatItem[];value:string;disabled:boolean;onChange:(id:string)=>void}){
  const [open,setOpen]=useState(false),[position,setPosition]=useState({top:0,left:0,width:0});
  const trigger=useRef<HTMLButtonElement>(null),menu=useRef<HTMLDivElement>(null),id=useId();
  const visible=open&&!disabled;
  const close=(restore=false)=>{setOpen(false);if(restore)trigger.current?.focus()};
  useLayoutEffect(()=>{
    if(!visible)return;
    const rect=trigger.current!.getBoundingClientRect();
    const width=Math.min(Math.max(rect.width,320),window.innerWidth-24);
    setPosition({top:rect.bottom+6,left:Math.max(12,Math.min(rect.left,window.innerWidth-width-12)),width});
    const outside=(event:PointerEvent)=>{if(!trigger.current?.contains(event.target as Node)&&!menu.current?.contains(event.target as Node))close()};
    const dismiss=(event:Event)=>{if(!menu.current?.contains(event.target as Node))close()};
    document.addEventListener('pointerdown',outside);window.addEventListener('resize',dismiss);
    window.addEventListener('scroll',dismiss,true);
    return()=>{document.removeEventListener('pointerdown',outside);window.removeEventListener('resize',dismiss);window.removeEventListener('scroll',dismiss,true)};
  },[visible]);
  useLayoutEffect(()=>{
    if(visible)menu.current?.querySelector<HTMLButtonElement>('[aria-checked="true"],button')?.focus({preventScroll:true});
  },[visible]);
  return <><button ref={trigger} type="button" className="chat-session-picker" aria-label="选择对话" aria-haspopup="menu" aria-expanded={visible} aria-controls={visible?id:undefined} disabled={disabled} onClick={()=>setOpen(!visible)} onKeyDown={event=>{if(['ArrowDown','ArrowUp'].includes(event.key)){event.preventDefault();setOpen(true)}}}><MessageSquare size={16}/><span>{items.find(item=>item.id===value)?.title||'新对话'}</span><ChevronDown size={13}/></button>{visible&&createPortal(<div ref={menu} id={id} className="chat-session-menu" role="menu" aria-label="选择对话" style={{...position,maxHeight:Math.max(80,Math.min(360,window.innerHeight-position.top-12))}} onBlur={event=>{if(!event.currentTarget.contains(event.relatedTarget as Node))close()}} onKeyDown={event=>{
    if(event.key==='Escape'){event.preventDefault();event.stopPropagation();close(true);return}
    const options=Array.from(menu.current?.querySelectorAll<HTMLButtonElement>('button')||[]);
    const index=options.indexOf(document.activeElement as HTMLButtonElement);
    if(['ArrowDown','ArrowUp','Home','End'].includes(event.key)){event.preventDefault();const next=event.key==='Home'?0:event.key==='End'?options.length-1:(index+(event.key==='ArrowDown'?1:options.length-1))%options.length;options[next]?.focus({preventScroll:true})}
  }}>{items.length?items.map(item=><button type="button" role="menuitemradio" aria-checked={item.id===value} key={item.id} title={item.title} onClick={()=>{close(true);if(item.id!==value)onChange(item.id)}}><span>{item.active_run?'处理中 · ':''}{item.title}</span>{item.id===value&&<Check size={15}/>}</button>):<p>暂无历史对话</p>}</div>,document.body)}</>;
}
