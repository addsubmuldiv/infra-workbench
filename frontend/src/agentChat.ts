import {assistantRequest} from './infraAssistant.ts';
export type ChatTool={id:string;name:string;target?:string;status:string;arguments:string;output:string;started:number;finished?:number};
export type ChatTurn={id:string;role:'user'|'assistant';content:string;created:number;status?:string;elapsed_ms?:number;tools?:ChatTool[]};
export type Chat={id:string;title:string;created:number;updated:number;turns:ChatTurn[];active_run:string|null};
export type ChatItem=Pick<Chat,'id'|'title'|'created'|'updated'|'active_run'>;
export const toolNames:Record<string,string>={list_hosts:'列出机器',search_fleet:'查找资源与进程',get_resources:'查看设备资源',read_directory:'浏览目录',read_file:'读取文件',ssh_check:'SSH 只读检查',read_changes:'读取资源变化'};
export const toolStatus:Record<string,string>={running:'正在执行',succeeded:'已返回结果',failed:'未完成',cancelled:'已取消',interrupted:'已中断'};
export function loadChatId():string|null{try{const id=localStorage.getItem('iwb-assistant-chat');return id&&/^[a-f0-9]{32}$/.test(id)?id:null}catch{return null}}
export function saveChatId(id:string){try{localStorage.setItem('iwb-assistant-chat',id)}catch{}}
export function chatRequest<T>(path='',method='GET',body?:unknown,signal?:AbortSignal):Promise<T>{return assistantRequest<T>('/chats'+path,method,body,signal)}
