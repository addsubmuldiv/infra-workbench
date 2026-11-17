import {ui} from './assistantLocale';
import React,{useId,useLayoutEffect,useRef,useState} from 'react';
import {createPortal} from 'react-dom';
import {Check,ChevronDown,MessageSquare} from 'lucide-react';
import type {ChatItem} from './agentChat';

export function ChatSessionPicker({items,value,disabled,onChange}:{items:ChatItem[];value:string;disabled:boolean;onChange:(id:string)=>void}){
  const [open,setOpen]=useState(false);
  const trigger=useRef<HTMLButtonElement>(null),menu=useRef<HTMLDivElement>(null),id=useId();
  const enterOnOpen=useRef<'first'|'last'|null>(null);
  const visible=open&&!disabled;
  const close=(restore=false)=>{setOpen(false);if(restore)trigger.current?.focus()};
  const options=()=>Array.from(menu.current?.querySelectorAll<HTMLButtonElement>('button')??[]);
  const focusOption=(option?:HTMLButtonElement)=>{
    (option??menu.current)?.focus({preventScroll:true});
    option?.scrollIntoView({block:'nearest',inline:'nearest'});
  };
  useLayoutEffect(()=>{
    if(!visible)return;
    const button=trigger.current!,popup=menu.current!;
    const position=()=>{
      const rect=button.getBoundingClientRect();
      const margin=12,gap=6;
      const width=Math.max(0,Math.min(Math.max(rect.width,320),window.innerWidth-2*margin));
      popup.style.width=width+'px';
      popup.style.left=Math.max(margin,Math.min(rect.left,window.innerWidth-width-margin))+'px';
      const below=window.innerHeight-rect.bottom-gap-margin,above=rect.top-gap-margin;
      const flip=below<Math.min(360,popup.scrollHeight+2)&&above>below;
      popup.style.top=flip?'auto':rect.bottom+gap+'px';
      popup.style.bottom=flip?window.innerHeight-rect.top+gap+'px':'auto';
      popup.style.maxHeight=Math.max(0,Math.min(360,flip?above:below))+'px';
    };
    position();
    const edge=enterOnOpen.current;
    if(edge){
      const entries=options();
      focusOption(edge==='last'?entries[entries.length-1]:entries[0]);
    }
    enterOnOpen.current=null;
    const outside=(event:PointerEvent)=>{if(!button.contains(event.target as Node)&&!popup.contains(event.target as Node))close()};
    const dismiss=(event:Event)=>{if(!menu.current?.contains(event.target as Node))close()};
    document.addEventListener('pointerdown',outside);window.addEventListener('resize',position);
    window.addEventListener('scroll',dismiss,true);
    return()=>{document.removeEventListener('pointerdown',outside);window.removeEventListener('resize',position);window.removeEventListener('scroll',dismiss,true)};
  },[visible]);
  const onBlur=(event:React.FocusEvent)=>{
    const next=event.relatedTarget as Node|null;
    if(next!==trigger.current&&!menu.current?.contains(next))close();
  };
  return <><button ref={trigger} type="button" className="chat-session-picker" aria-label={ui("选择对话")} aria-haspopup="menu" aria-expanded={visible} aria-controls={visible?id:undefined} disabled={disabled} onBlur={onBlur} onClick={event=>{
    if(visible){close();return}
    enterOnOpen.current=event.detail===0?'first':null;setOpen(true);
  }} onKeyDown={event=>{
    if(visible&&event.key==='Escape'){event.preventDefault();event.stopPropagation();close();return}
    if(event.key!=='ArrowDown'&&event.key!=='ArrowUp')return;
    event.preventDefault();
    const last=event.key==='ArrowUp';
    if(visible){const entries=options();focusOption(last?entries[entries.length-1]:entries[0]);return}
    enterOnOpen.current=last?'last':'first';setOpen(true);
  }}><MessageSquare size={16}/><span>{items.find(item=>item.id===value)?.title||ui("新对话")}</span><ChevronDown size={13}/></button>{visible&&createPortal(<div ref={menu} id={id} className="chat-session-menu" role="menu" tabIndex={-1} aria-label={ui("选择对话")} onBlur={onBlur} onKeyDown={event=>{
    if(event.key==='Escape'){event.preventDefault();event.stopPropagation();close(true);return}
    if(event.key==='Tab'){close(true);return}
    if(!['ArrowDown','ArrowUp','Home','End'].includes(event.key))return;
    const entries=options();
    if(!entries.length)return;
    event.preventDefault();
    const index=entries.indexOf(document.activeElement as HTMLButtonElement);
    const next=event.key==='Home'?0:event.key==='End'?entries.length-1:(index+(event.key==='ArrowDown'?1:entries.length-1))%entries.length;
    focusOption(entries[next]);
  }}>{items.length?items.map(item=><button type="button" tabIndex={-1} role="menuitemradio" aria-checked={item.id===value} key={item.id} title={item.title} onClick={()=>{close(true);if(item.id!==value)onChange(item.id)}}><span>{item.active_run?ui("处理中 · "):''}{item.title}</span>{item.id===value&&<Check size={15}/>}</button>):<p>{ui("暂无历史对话")}</p>}</div>,document.body)}</>;
}
