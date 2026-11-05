import {useEffect,useId,useRef,useState} from 'react';
import {Check,ChevronDown} from 'lucide-react';

const intervals=[5,10,15,20,30];
export function RefreshIntervalPicker({label,title,value,disabled,format,onChange}:{label:string;title:string;value:number;disabled:boolean;format:(value:number)=>string;onChange:(value:number)=>Promise<void>}){
  const [open,setOpen]=useState(false);
  const root=useRef<HTMLDivElement>(null),trigger=useRef<HTMLButtonElement>(null);
  const id=useId();
  useEffect(()=>{
    if(!open)return;
    const outside=(event:PointerEvent)=>{if(!root.current?.contains(event.target as Node))setOpen(false)};
    document.addEventListener('pointerdown',outside);
    root.current?.querySelector<HTMLButtonElement>('[aria-checked="true"]')?.focus();
    return()=>document.removeEventListener('pointerdown',outside);
  },[open]);
  return <div ref={root} className="live refresh-control" title={title} onBlur={event=>{if(!event.currentTarget.contains(event.relatedTarget))setOpen(false)}} onKeyDown={event=>{
    if(event.key==='Escape'){event.preventDefault();setOpen(false);trigger.current?.focus()}
    if(open&&['ArrowDown','ArrowUp','Home','End'].includes(event.key)){
      event.preventDefault();const items=Array.from(root.current!.querySelectorAll<HTMLButtonElement>('[role="menuitemradio"]'));
      const index=items.indexOf(document.activeElement as HTMLButtonElement);
      items[event.key==='Home'?0:event.key==='End'?items.length-1:(index+(event.key==='ArrowDown'?1:items.length-1))%items.length]?.focus();
    }
  }}><i/><button ref={trigger} type="button" className="refresh-trigger" aria-label={`${label}: ${format(value)}`} aria-haspopup="menu" aria-expanded={open} aria-controls={open?id:undefined} disabled={disabled} onClick={()=>setOpen(!open)} onKeyDown={event=>{if(!open&&(event.key==='ArrowDown'||event.key==='ArrowUp')){event.preventDefault();setOpen(true)}}}>{format(value)}<ChevronDown size={13}/></button>
    {open&&<div id={id} className="refresh-menu" role="menu" aria-label={label}>{intervals.map(seconds=><button key={seconds} type="button" role="menuitemradio" aria-checked={seconds===value} onClick={()=>{setOpen(false);trigger.current?.focus();void onChange(seconds)}}><span>{format(seconds)}</span>{seconds===value&&<Check size={14}/>}</button>)}</div>}
  </div>;
}
