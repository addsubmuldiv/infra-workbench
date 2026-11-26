import {ui} from './assistantLocale';
import {ChevronDown,History} from 'lucide-react';
import {ChatMenuButton} from './ChatMenuButton';
import type {ChatItem} from './agentChat';
import {getLocale,t} from '../../shared/i18n';

const updatedTime={
  zh:new Intl.DateTimeFormat('zh-CN',{dateStyle:'short',timeStyle:'short',timeZone:'Asia/Hong_Kong'}),
  en:new Intl.DateTimeFormat('en-GB',{dateStyle:'short',timeStyle:'short',timeZone:'Asia/Hong_Kong'}),
};

export function ChatSessionPicker({items,value,disabled,onChange}:{items:ChatItem[];value:string;disabled:boolean;onChange:(id:string)=>void}){
  const current=items.find(item=>item.id===value);
  const title=current?.title==='新对话'&&!current.custom_title?undefined:current?.title;
  const historyLabel=t('对话历史','Conversation history');
  return <ChatMenuButton label={historyLabel} triggerLabel={title?`${historyLabel} · ${title}`:historyLabel} triggerClassName="chat-session-picker" value={value} disabled={disabled}
    options={items.map(item=>({id:item.id,label:item.title==='新对话'&&!item.custom_title?ui('新对话'):item.title,title:item.title,
      description:[item.active_run?t('处理中','Running'):'',item.updated>0&&Number.isFinite(item.updated)?updatedTime[getLocale()].format(item.updated*1000):''].filter(Boolean).join(' · ')}))}
    onChange={onChange} emptyLabel={ui("暂无历史对话")}>
    <History size={16} aria-hidden="true"/><span title={title}>{title||historyLabel}</span><ChevronDown size={13} aria-hidden="true"/>
  </ChatMenuButton>;
}
