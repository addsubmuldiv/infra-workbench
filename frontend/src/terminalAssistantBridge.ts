import type {TerminalAttachment} from './terminalContext';

type Port=Pick<BroadcastChannel,'onmessage'|'postMessage'|'close'>;
type Envelope={id:number;attachment:TerminalAttachment};
// Only this source window and its companion know the random channel name.
// Text stays in memory and never enters a URL, workspace storage or an AI request.
export function createContextSender(port:Port){
 let sequence=0,queue:Envelope[]=[],connected=false;
 const flush=()=>{if(connected&&queue.length)port.postMessage({type:'attachments',items:queue})};
 port.onmessage=({data})=>{
  if(data?.type==='ready'){connected=true;flush()}
  if(data?.type==='ack'&&Array.isArray(data.ids)){const ids=new Set(data.ids);queue=queue.filter(item=>!ids.has(item.id))}
 };
 return {add(items:TerminalAttachment[]){queue=[...queue,...items.map(attachment=>({id:++sequence,attachment}))].slice(-3);flush()},close(){port.onmessage=null;queue=[];port.close()}};
}
export function receiveTerminalContext(port:Port,receive:(items:TerminalAttachment[])=>void){
 const seen=new Set<number>();
 port.onmessage=({data})=>{
  if(data?.type!=='attachments'||!Array.isArray(data.items))return;
  const items=(data.items as Envelope[]).slice(-3).filter(item=>Number.isSafeInteger(item?.id)&&item.attachment&&typeof item.attachment.content==='string');
  const fresh=items.filter(item=>!seen.has(item.id));
  if(fresh.length){receive(fresh.map(item=>item.attachment));fresh.forEach(item=>seen.add(item.id))}
  port.postMessage({type:'ack',ids:items.map(item=>item.id)});
 };
 return {ready(){port.postMessage({type:'ready'})},close(){port.onmessage=null;port.close()}};
}
