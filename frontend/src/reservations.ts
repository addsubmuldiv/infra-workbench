import type {MailResult} from './mailSettings';
export type Reservation={id:string;host_id:string;target:string;devices:string[];labels:string[];mode?:'fixed'|'count';required_count?:number;kind?:string;available_count?:number|null;matched_devices?:string[];wait_seconds:number;minimum_gib:number;status:'waiting'|'settling'|'unknown'|'needs_selection'|'ready';idle_seconds:number;remaining_seconds:number;notified_at:number|null;email_notify?:boolean;email?:MailResult|null};
export type ReservationHost={id:string;target:string;snapshot:{fresh:boolean;devices:{id:string;display_id?:string;kind:string;name:string;processes:unknown[];processes_known:boolean}[]}};
const WAIT_KEY='infra-workbench:reservation-wait-minutes';
export function waitSeconds(minutes:number):number{
  if(!Number.isFinite(minutes)||minutes<0||minutes>1440)throw new Error('等待时间请输入 0～1440 分钟');
  return Math.round(minutes*60);
}
export function loadWaitMinutes(storage:Pick<Storage,'getItem'>|null):number{
  try{const raw=storage?.getItem(WAIT_KEY);if(raw==null||raw.trim()==='')return 2;const value=Number(raw);waitSeconds(value);return value}catch{return 2}
}
export function saveWaitMinutes(storage:Pick<Storage,'setItem'>|null,value:number){
  try{waitSeconds(value);storage?.setItem(WAIT_KEY,String(value))}catch{/* The reservation is persisted by the service independently. */}
}
export function countdown(seconds:number):string{
  const value=Math.max(0,Math.ceil(seconds));
  return value<60?`${value} 秒`:`${Math.floor(value/60)} 分 ${value%60} 秒`;
}
