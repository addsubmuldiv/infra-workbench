import {useEffect,useRef,useState} from 'react';
import {createPortal} from 'react-dom';
import {Settings2,X} from 'lucide-react';
import {t} from './i18n';
import TerminalHighlightSettings from './TerminalHighlightSettings';
import TerminalImageSettings from './TerminalImageSettings';

export default function TerminalDisplaySettings({font,setFont}:{font:number;setFont:(update:(value:number)=>number)=>void}){
 const [position,setPosition]=useState<{top:number;left:number}|null>(null);
 const trigger=useRef<HTMLButtonElement>(null),panel=useRef<HTMLDivElement>(null);
 useEffect(()=>{
  if(!position)return;
  const close=(event:PointerEvent)=>{if(!panel.current?.contains(event.target as Node)&&!trigger.current?.contains(event.target as Node)&&!(event.target as Element).closest('.terminal-highlight-panel'))setPosition(null)};
  const key=(event:KeyboardEvent)=>{if(event.key==='Escape'){setPosition(null);trigger.current?.focus()}};
  const resize=()=>setPosition(null);
  document.addEventListener('pointerdown',close);document.addEventListener('keydown',key);window.addEventListener('resize',resize);
  return()=>{document.removeEventListener('pointerdown',close);document.removeEventListener('keydown',key);window.removeEventListener('resize',resize)};
 },[position]);
 return <><button ref={trigger} aria-label={t('终端显示设置','Terminal display settings')} title={t('终端显示设置：字号、关键词高亮、图片','Terminal display: font size, keyword highlights and images')} aria-expanded={!!position} onClick={()=>{const r=trigger.current!.getBoundingClientRect();setPosition(position?null:{top:Math.max(8,Math.min(r.bottom+6,innerHeight-200)),left:Math.max(8,Math.min(r.right-280,innerWidth-288))})}}><Settings2 size={15}/></button>{position&&createPortal(<div ref={panel} className="terminal-display-settings" style={position} role="group" aria-label={t('终端显示设置','Terminal display settings')}>
 <header><strong>{t('显示设置','Display settings')}</strong><button aria-label={t('关闭显示设置','Close display settings')} onClick={()=>{setPosition(null);trigger.current?.focus()}}><X size={14}/></button></header>
 <div className="terminal-font-controls"><span>{t('字号','Font size')}</span><button aria-label={t('减小终端字号','Decrease terminal font size')} disabled={font<=10} onClick={()=>setFont(f=>Math.max(10,f-1))}>A−</button><output>{font}</output><button aria-label={t('增大终端字号','Increase terminal font size')} disabled={font>=22} onClick={()=>setFont(f=>Math.min(22,f+1))}>A+</button></div>
 <TerminalHighlightSettings/><TerminalImageSettings/>
 </div>,document.body)}</>;
}
