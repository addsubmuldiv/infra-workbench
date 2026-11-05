import {getLocale} from './i18n';
import {t} from './i18n';
import {ui} from './assistantLocale';
import React,{useEffect,useState} from 'react';
import {agentRequest,type ContextCapacity} from './agentSettings';
import type {Chat} from './agentChat';

export function ContextUsageMeter({chat,model}:{chat:Chat|null;model?:string}){
  const [capacity,setCapacity]=useState<ContextCapacity|null>(null);
  const [version,setVersion]=useState(0);
  useEffect(()=>{const refresh=()=>setVersion(v=>v+1);window.addEventListener('infra-workbench:agent-settings-changed',refresh);return()=>window.removeEventListener('infra-workbench:agent-settings-changed',refresh)},[]);
  useEffect(()=>{
    let disposed=false;
    setCapacity(null);
    if(model)void agentRequest<ContextCapacity>('/context','POST').then(value=>{if(!disposed)setCapacity(value)}).catch(()=>{});
    return()=>{disposed=true};
  },[model,version]);
  const latest=[...(chat?.turns||[])].reverse().find(turn=>turn.role==='assistant');
  const usage=latest?.context_usage;
  const valid=usage&&usage.model===model&&(!capacity||usage.total_tokens===capacity.tokens);
  const total=capacity?.tokens||(valid?usage.total_tokens:0);
  const trigger=capacity?.trigger_tokens||(valid?usage.trigger_tokens:0);
  const used=valid?usage.used_tokens:null;
  const percent=used!==null&&total?used/total*100:0;
  const remaining=used===null?null:Math.max(0,trigger-used);
  const compacting=latest?.context_compaction?.status==='running';
  const source=capacity?.source||(valid?usage.source:null);
  const format=(value:number)=>value.toLocaleString(getLocale()==='en'?'en-US':'zh-CN');
  const detail=used===null?ui("发送消息后显示实际上下文的估算用量；旧记录没有计数时不显示为零。"):ui("按最近一次模型调用的有效上下文估算，包含系统提示、工具定义、摘要和近期消息；回复结束后计入本次回复。不是服务商计费 token 数。");
  return <div className="chat-context-meter" title={detail}>
    <div className="chat-context-meter-heading"><span>{ui("上下文")}{used!==null?ui("（估算）"):''}</span><span>{used===null?ui("待统计"):format(used)} / {total?format(total):ui("读取中")} token{used!==null&&` · ${percent.toFixed(1)}%`}</span></div>
    <div className="chat-context-meter-track" role="progressbar" aria-label={ui("上下文容量使用情况")} aria-valuemin={0} aria-valuemax={total||100} aria-valuenow={used===null?undefined:Math.min(total,used)} aria-valuetext={used===null?ui("尚未统计上下文用量"):t(`估算已用 ${format(used)}，总容量 ${format(total)}，压缩触发点 ${format(trigger)} token`,`Estimated usage ${format(used)} of ${format(total)} tokens; compaction threshold ${format(trigger)}`)}>
      <span className={'chat-context-meter-fill'+(percent>=85?' near-limit':'')} style={{width:`${Math.min(100,percent)}%`}}/>
      <i style={{left:`${total?trigger/total*100:85}%`}}/>
    </div>
    <div className="chat-context-meter-caption"><span>{compacting?ui("正在压缩上下文…"):remaining===null?ui("发送消息后更新用量"):remaining===0?ui("已达到触发线，下次调用前由框架判断压缩"):t(`距压缩约 ${format(remaining)} token`,`About ${format(remaining)} tokens until compaction`)}</span><span>{source==='fallback'?ui("容量未识别 · 默认值"):t(`压缩线 ${total?Math.round(trigger/total*100):85}%`,`Compaction at ${total?Math.round(trigger/total*100):85}%`)}</span></div>
  </div>;
}
