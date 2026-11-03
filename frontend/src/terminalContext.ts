export type TerminalAttachment={host_id:string;label:string;terminal_id:string;session_id?:string;cwd?:string;captured_at:string;source:'selection'|'screen';content:string;truncated:boolean};
export const TERMINAL_CONTEXT_EVENT='infra-workbench:terminal-context';
// Pending data stays in this window's memory; opening the assistant never sends it.
let pending:TerminalAttachment[]=[];
export function takeTerminalContext(){const value=pending;pending=[];return value}
export function handoffTerminalContext(value:TerminalAttachment){pending=[...pending,value].slice(-3);window.dispatchEvent(new Event(TERMINAL_CONTEXT_EVENT))}
type TerminalBuffer={getSelection:()=>string;rows:number;buffer:{active:{viewportY:number;getLine:(index:number)=>{translateToString:(trim:boolean)=>string}|undefined}}};
export function captureTerminal(terminal:TerminalBuffer,origin:Pick<TerminalAttachment,'host_id'|'label'|'terminal_id'|'session_id'|'cwd'>,source:TerminalAttachment['source']):TerminalAttachment{
 let raw=source==='selection'?terminal.getSelection():Array.from({length:Math.min(terminal.rows,150)},(_,i)=>terminal.buffer.active.getLine(terminal.buffer.active.viewportY+i)?.translateToString(true)||'').join('\n');
 raw=raw.replace(/\r\n?/g,'\n').replace(/[\x00-\x08\x0b-\x1f\x7f-\x9f]/g,'');
 const lines=raw.split('\n'),bounded=lines.slice(0,150).join('\n'),chars=Array.from(bounded),content=chars.slice(0,12000).join('');
 return {...origin,source,captured_at:new Date().toISOString(),content,truncated:lines.length>150||chars.length>12000||(source==='screen'&&terminal.rows>150)};
}
