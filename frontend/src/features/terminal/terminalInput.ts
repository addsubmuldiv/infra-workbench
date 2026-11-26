export const TERMINAL_INPUT_EVENT='infra-workbench:terminal-input';
export const TERMINAL_TARGETS_EVENT='infra-workbench:terminal-targets';
export const TERMINAL_PICK_EVENT='infra-workbench:terminal-pick';
export type TerminalTarget={terminal_id:string;label:string;number:string;cwd?:string;phase:string};
export function localTerminalTargets(){
 const targets:TerminalTarget[]=[];
 window.dispatchEvent(new CustomEvent(TERMINAL_TARGETS_EVENT,{detail:(items:TerminalTarget[])=>targets.push(...items)}));
 return targets;
}
export function prepareTerminalInput(text:string){
 const value=text.replace(/\r\n?/g,'\n').replace(/[\x00-\x08\x0b-\x1f\x7f-\x9f]/g,'').trimEnd();
 if(!value.trim()||Array.from(value).length>12000)throw Error('请选择 12000 字以内的命令');
 return value;
}
