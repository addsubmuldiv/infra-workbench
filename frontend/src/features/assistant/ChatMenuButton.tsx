import {useEffect,useId,useLayoutEffect,useRef,useState,type FocusEvent,type ReactNode} from 'react';
import {createPortal} from 'react-dom';
import {Check} from 'lucide-react';

type MenuOption={
  id:string;
  label:string;
  title?:string;
  description?:string;
  disabled?:boolean;
};
type MenuAction={label:string;icon?:ReactNode;description?:string;disabled?:boolean;danger?:boolean;onSelect:()=>void};

type Props={
  label:string;
  triggerLabel?:string;
  triggerClassName:string;
  menuClassName?:string;
  disabled?:boolean;
  preferAbove?:boolean;
  value?:string;
  options?:MenuOption[];
  onChange?:(id:string)=>void;
  emptyLabel?:string;
  description?:string;
  actions?:MenuAction[];
  children:ReactNode;
};

export function ChatMenuButton({label,triggerLabel,triggerClassName,menuClassName,disabled,preferAbove=false,value,options=[],onChange,emptyLabel,description,actions=[],children}:Props){
  const [open,setOpen]=useState(false);
  const trigger=useRef<HTMLButtonElement>(null);
  const menu=useRef<HTMLDivElement>(null);
  const id=useId();
  const enterOnOpen=useRef<'first'|'last'|null>(null);
  const visible=open&&!disabled;
  const close=(restore=false)=>{
    setOpen(false);
    if(restore)trigger.current?.focus({preventScroll:true});
  };
  const entries=()=>Array.from(menu.current?.querySelectorAll<HTMLButtonElement>('button')??[]);
  const focusEntry=(entry?:HTMLButtonElement)=>{
    (entry??menu.current)?.focus({preventScroll:true});
    entry?.scrollIntoView({block:'nearest',inline:'nearest'});
  };
  useEffect(()=>{if(disabled)setOpen(false)},[disabled]);
  useLayoutEffect(()=>{
    if(!visible)return;
    const button=trigger.current!;
    const popup=menu.current!;
    const position=()=>{
      const rect=button.getBoundingClientRect();
      const margin=12,gap=6;
      const width=Math.min(Math.max(rect.width,320),window.innerWidth-2*margin);
      popup.style.width=width+'px';
      popup.style.left=Math.max(margin,Math.min(rect.left,window.innerWidth-width-margin))+'px';
      const availableBelow=window.innerHeight-rect.bottom-gap-margin;
      const availableAbove=rect.top-gap-margin;
      const required=Math.min(360,popup.scrollHeight+2);
      const above=preferAbove
        ?availableAbove>=required||availableAbove>=availableBelow
        :availableBelow<required&&availableAbove>availableBelow;
      popup.style.top=above?'auto':rect.bottom+gap+'px';
      popup.style.bottom=above?window.innerHeight-rect.top+gap+'px':'auto';
      popup.style.maxHeight=Math.max(0,Math.min(360,above?availableAbove:availableBelow))+'px';
    };
    position();
    if(enterOnOpen.current){
      const buttons=entries();
      focusEntry(enterOnOpen.current==='last'?buttons[buttons.length-1]:buttons[0]);
    }
    enterOnOpen.current=null;
    const outside=(event:PointerEvent)=>{
      const target=event.target as Node;
      if(!button.contains(target)&&!popup.contains(target))close();
    };
    const scroll=(event:Event)=>{if(!popup.contains(event.target as Node))close()};
    document.addEventListener('pointerdown',outside);
    window.addEventListener('resize',position);
    window.addEventListener('scroll',scroll,true);
    return()=>{
      document.removeEventListener('pointerdown',outside);
      window.removeEventListener('resize',position);
      window.removeEventListener('scroll',scroll,true);
    };
  },[visible,preferAbove]);

  const onBlur=(event:FocusEvent)=>{
    const next=event.relatedTarget as Node|null;
    if(next!==trigger.current&&!menu.current?.contains(next))close();
  };

  return <>
    <button ref={trigger} type="button" className={triggerClassName} aria-label={triggerLabel??label}
      aria-haspopup="menu" aria-expanded={visible} aria-controls={visible?id:undefined} disabled={disabled}
      onBlur={onBlur} onClick={()=>{
        if(visible){close();return}
        enterOnOpen.current='first';
        setOpen(true);
      }} onKeyDown={event=>{
        if(visible&&event.key==='Escape'){event.preventDefault();event.stopPropagation();close();return}
        if(event.key!=='ArrowDown'&&event.key!=='ArrowUp')return;
        event.preventDefault();
        const last=event.key==='ArrowUp';
        if(visible){const buttons=entries();focusEntry(last?buttons[buttons.length-1]:buttons[0]);return}
        enterOnOpen.current=last?'last':'first';
        setOpen(true);
      }}>{children}</button>
    {visible&&createPortal(<div ref={menu} id={id} className={menuClassName?'chat-session-menu '+menuClassName:'chat-session-menu'}
      role="menu" tabIndex={-1} aria-label={label} aria-describedby={description?id+'-description':undefined} onBlur={onBlur} onKeyDown={event=>{
        if(event.key==='Escape'){event.preventDefault();event.stopPropagation();close(true);return}
        if(event.key==='Tab'){close(true);return}
        if(!['ArrowDown','ArrowUp','Home','End'].includes(event.key))return;
        const buttons=entries();
        if(!buttons.length)return;
        event.preventDefault();
        const index=buttons.indexOf(document.activeElement as HTMLButtonElement);
        const next=event.key==='Home'?0:event.key==='End'?buttons.length-1:(index+(event.key==='ArrowDown'?1:buttons.length-1))%buttons.length;
        focusEntry(buttons[next]);
      }}>
      {description&&<p id={id+'-description'}>{description}</p>}
      {options.map(option=>{
        const checked=option.id===value;
        return <button type="button" tabIndex={-1} role="menuitemradio" aria-checked={checked} aria-disabled={option.disabled||undefined}
          aria-describedby={option.description?id+'-'+option.id:undefined} aria-label={option.description?option.label:undefined} key={option.id} title={option.title}
          onClick={()=>{if(!option.disabled){close(true);if(!checked)onChange?.(option.id)}}}>
          <span>{option.label}{option.description&&<small id={id+'-'+option.id}>{option.description}</small>}</span>
          {checked&&<Check size={15} aria-hidden="true"/>}
        </button>;
      })}
      {!options.length&&emptyLabel&&<p>{emptyLabel}</p>}
      {actions.map((action,index)=><button key={action.label} type="button" tabIndex={-1} role="menuitem"
        className={'chat-menu-action'+(action.danger?' danger':'')} aria-disabled={action.disabled||undefined}
        aria-label={action.label} aria-describedby={action.description?`${id}-action-${index}`:undefined}
        onClick={()=>{if(!action.disabled){close(true);action.onSelect()}}}>
        <span>{action.label}{action.description&&<small id={`${id}-action-${index}`}>{action.description}</small>}</span>{action.icon}
      </button>)}
    </div>,document.body)}
  </>;
}
