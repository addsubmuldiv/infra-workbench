import type {MailResult} from './mailSettings';
export type DesktopStatus='pending'|'sending'|'submitted'|'failed'|'disabled'|'unknown'|'skipped';
export type Reservation={id:string;host_id:string;target:string;devices:string[];labels:string[];mode?:'fixed'|'count';required_count?:number;kind?:string;available_count?:number|null;matched_devices?:string[];wait_seconds:number;minimum_gib:number;status:'waiting'|'settling'|'unknown'|'needs_selection'|'ready';idle_seconds:number;remaining_seconds:number;notified_at:number|null;email_notify?:boolean;email?:MailResult|null;desktop?:{status:DesktopStatus;error?:string;updated:number}|null;url?:string};
export type ReservationHost={id:string;target:string;snapshot:{fresh:boolean;devices:{id:string;display_id?:string;kind:string;name:string;processes:unknown[];processes_known:boolean}[]}};
export type ReservationDraft={hostId?:string;devices?:string[];minimum?:number;mode?:'fixed'|'count';requiredCount?:number;kind?:string;waitSeconds?:number;emailNotify?:boolean;editingId?:string};
export function reservationDraft(item:Reservation,editing:boolean):ReservationDraft{
  return {hostId:item.host_id,devices:[...item.devices],minimum:item.minimum_gib,mode:item.mode??'fixed',requiredCount:item.required_count,kind:item.kind,waitSeconds:item.wait_seconds,emailNotify:item.email_notify===true,...(editing?{editingId:item.id}:{})};
}
export function reservationLocation(item:Pick<Reservation,'host_id'|'mode'|'devices'|'matched_devices'>):string{
  const query=new URLSearchParams({host:item.host_id});
  for(const id of item.mode==='count'?item.matched_devices??[]:item.devices)query.append('device',id);
  return '#overview?'+query.toString();
}
export const desktopStatusText:Record<DesktopStatus,string>={pending:'系统通知等待托盘处理',sending:'正在提交 系统通知',submitted:'已提交 系统通知',failed:'系统通知提交失败',disabled:'托盘桌面通知已关闭',unknown:'系统通知结果待确认',skipped:'未提交 系统通知'};
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
