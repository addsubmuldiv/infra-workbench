import {ui} from './assistantLocale';
import {ChevronDown,MessageSquare} from 'lucide-react';
import {ChatMenuButton} from './ChatMenuButton';
import type {ChatItem} from './agentChat';

export function ChatSessionPicker({items,value,disabled,onChange}:{items:ChatItem[];value:string;disabled:boolean;onChange:(id:string)=>void}){
  return <ChatMenuButton label={ui("选择对话")} triggerClassName="chat-session-picker" value={value} disabled={disabled}
    options={items.map(item=>({id:item.id,label:(item.active_run?ui("处理中 · "):'')+item.title,title:item.title}))}
    onChange={onChange} emptyLabel={ui("暂无历史对话")}>
    <MessageSquare size={16}/><span>{items.find(item=>item.id===value)?.title||ui("新对话")}</span><ChevronDown size={13}/>
  </ChatMenuButton>;
}
