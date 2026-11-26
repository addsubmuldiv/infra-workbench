type NotificationEvent={message:string;created:number;notify?:boolean};
export type NotificationRecord=NotificationEvent&{id:number;host:string;url?:string};
const quietSuffixes=['：SSH 连接失败','：采集已恢复','：已连接，远端采集失败','：已连接，设备解析失败'];
const readKey='infra-workbench:notifications:read:v1';
const actionable=(event:NotificationEvent)=>!!event.message&&!quietSuffixes.some(suffix=>event.message.endsWith(suffix));

export function shouldNotify(event:NotificationEvent,now=Date.now()/1000):boolean{
  const age=now-event.created;
  return event.notify!==false&&actionable(event)&&Number.isFinite(age)&&age>=-30&&age<=120;
}
export function loadReadEvent(storage:Pick<Storage,'getItem'>|null):number{
  try{const value=Number(storage?.getItem(readKey)??0);return Number.isSafeInteger(value)&&value>=0?value:0}catch{return 0}
}
export function saveReadEvent(storage:Pick<Storage,'setItem'>|null,id:number):boolean{
  try{if(!storage)return false;storage.setItem(readKey,String(id));return true}catch{return false}
}
export function unreadEvents(events:(NotificationEvent&{id:number})[],read:number):number{
  return events.filter(event=>event.id>read&&actionable(event)).length;
}
