import React,{useId,useRef,useState} from 'react';
import type {SkillMeta} from './skills';
import {skillMention} from './skillMention';

export function SkillMessageInput({text,onChange,skills,selected,onSelect,disabled,error,onSend}:{text:string;onChange:(value:string)=>void;skills:SkillMeta[];selected:string[];onSelect:(value:string[])=>void;disabled:boolean;error:string;onSend:()=>void}){
  const input=useRef<HTMLTextAreaElement>(null),id=useId();
  const [cursor,setCursor]=useState(0),[open,setOpen]=useState(false),[active,setActive]=useState(0);
  const mention=skillMention(text,cursor);
  const choices=selected.length>=16?[]:skills.filter(skill=>skill.enabled&&!selected.includes(skill.name)&&(!mention?.query||`${skill.name} ${skill.description}`.toLocaleLowerCase().includes(mention.query)));
  const visible=open&&!!mention&&!disabled;
  const index=Math.min(active,Math.max(0,choices.length-1));
  const choose=(skill:SkillMeta)=>{
    if(!mention)return;
    const next=text.slice(0,mention.start)+text.slice(mention.end);
    onChange(next);onSelect([...selected,skill.name]);setOpen(false);setCursor(mention.start);
    requestAnimationFrame(()=>{input.current?.focus();input.current?.setSelectionRange(mention.start,mention.start)});
  };
  return <div className="skill-message-input">
    {!!selected.length&&<div className="skill-mentions" aria-label="本轮已选技能">{selected.map(name=><button type="button" key={name} disabled={disabled} aria-label={`移除技能 ${name}`} onClick={()=>onSelect(selected.filter(value=>value!==name))}>@{name}<span aria-hidden="true">×</span></button>)}</div>}
    {visible&&<div className="skill-mention-menu"><div className="skill-mention-heading">选择技能 <small>↑ ↓ 选择 · Enter 确认 · Esc 关闭</small></div><div id={id} role="listbox" aria-label="选择技能">{choices.length?choices.map((skill,i)=><button type="button" role="option" aria-selected={i===index} id={`${id}-${i}`} key={skill.name} onMouseDown={event=>event.preventDefault()} onMouseEnter={()=>setActive(i)} onClick={()=>choose(skill)} ref={element=>{if(i===index)element?.scrollIntoView({block:'nearest'})}}><strong>@{skill.name}<small>v{skill.version}</small></strong><span>{skill.description}</span></button>):<p role="status">{error?'技能列表加载失败，请稍后重试。':selected.length>=16?'本轮最多选择 16 个技能。':'没有匹配的可用技能'}</p>}</div></div>}
    <textarea ref={input} aria-label="对话消息输入" aria-autocomplete="list" aria-controls={visible?id:undefined} aria-expanded={visible} aria-activedescendant={visible&&choices.length?`${id}-${index}`:undefined} placeholder="描述要完成的操作，输入 @ 选择技能" value={text} maxLength={4000} rows={3} disabled={disabled} onBlur={()=>setOpen(false)} onChange={event=>{onChange(event.target.value);setCursor(event.target.selectionStart);setActive(0);setOpen(true)}} onSelect={event=>{setCursor(event.currentTarget.selectionStart)}} onClick={()=>setOpen(true)} onKeyDown={event=>{
      if(event.nativeEvent.isComposing||event.nativeEvent.keyCode===229)return;
      if(visible){
        if(event.key==='Escape'){event.preventDefault();setOpen(false);return}
        if(choices.length&&['ArrowDown','ArrowUp','Enter','Tab'].includes(event.key)&&!event.ctrlKey&&!event.metaKey&&!event.shiftKey){event.preventDefault();if(event.key==='ArrowDown')setActive((index+1)%choices.length);else if(event.key==='ArrowUp')setActive((index+choices.length-1)%choices.length);else choose(choices[index]);return}
      }
      if(event.key==='Enter'&&!event.shiftKey&&!event.altKey){event.preventDefault();onSend()}
    }}/>
  </div>;
}
