import {createPortal} from 'react-dom';
import {useState,useSyncExternalStore} from 'react';
import {t,useLocale} from './i18n';
import {workspaceStorage} from './workspaceState';
import {DEFAULT_HIGHLIGHTS,HIGHLIGHTS_KEY,normalizeHighlights,readHighlights,type HighlightPreferences} from './terminalHighlights';
const subscribe=(fn:()=>void)=>workspaceStorage.subscribe(HIGHLIGHTS_KEY,fn);
const snapshot=()=>workspaceStorage.getItem(HIGHLIGHTS_KEY);
export default function TerminalHighlightSettings(){
 useLocale();useSyncExternalStore(subscribe,snapshot,snapshot);
 const [open,setOpen]=useState(false),[position,setPosition]=useState({top:0,left:0});const prefs=readHighlights(workspaceStorage);
 const save=(value:HighlightPreferences)=>workspaceStorage.setItem(HIGHLIGHTS_KEY,JSON.stringify(normalizeHighlights(value)));
 return <div className="terminal-highlight-settings"><button onClick={e=>{const rect=e.currentTarget.getBoundingClientRect();setPosition({top:Math.min(rect.bottom+4,window.innerHeight-220),left:Math.max(8,Math.min(rect.left,window.innerWidth-456))});setOpen(!open)}} aria-expanded={open}>{t('关键词高亮','Keyword highlights')}</button>{open&&createPortal(<div className="terminal-highlight-panel" style={position} role="group" aria-label={t('关键词高亮设置','Keyword highlight settings')}>
 <label><input type="checkbox" checked={prefs.enabled} onChange={e=>save({...prefs,enabled:e.target.checked})}/>{t('启用关键词高亮','Enable keyword highlights')}</label>
 <p>{t('按原文区分大小写匹配；仅显示当前普通缓冲区。蓝色 NCCL 和绿色 checkpoint/success 表示信息，不代表错误或已验证成功。','Case-sensitive literal matching in the visible normal buffer. Blue NCCL and green checkpoint/success are informational, not errors or verified success.')}</p>
 {prefs.rules.map((rule,index)=><div className="terminal-highlight-rule" key={index}>
 <input type="checkbox" aria-label={t('启用规则','Enable rule')+' '+rule.text} checked={rule.enabled} onChange={e=>save({...prefs,rules:prefs.rules.map((r,i)=>i===index?{...r,enabled:e.target.checked}:r)})}/>
 <input aria-label={t('关键词','Keyword')+' '+(index+1)} defaultValue={rule.text} key={index+rule.text} maxLength={128} onBlur={e=>{if(e.target.value!==rule.text)save({...prefs,rules:prefs.rules.map((r,i)=>i===index?{...r,text:e.target.value}:r)})}}/>
 <input type="color" aria-label={t('高亮颜色','Highlight color')+' '+(index+1)} value={rule.color} onChange={e=>save({...prefs,rules:prefs.rules.map((r,i)=>i===index?{...r,color:e.target.value}:r)})}/>
 <button aria-label={t('删除规则','Delete rule')+' '+rule.text} onClick={()=>save({...prefs,rules:prefs.rules.filter((_,i)=>i!==index)})}>×</button></div>)}
 <button disabled={prefs.rules.length>=20} onClick={()=>save({...prefs,rules:[...prefs.rules,{text:t('自定义关键词','Custom keyword'),color:'#6b21a8',enabled:true}]})}>{t('添加规则','Add rule')}</button>
 <button onClick={()=>save(DEFAULT_HIGHLIGHTS)}>{t('恢复默认','Restore defaults')}</button>
 <button onClick={()=>setOpen(false)}>{t('关闭','Close')}</button>
 </div>,document.body)}</div>;
}
