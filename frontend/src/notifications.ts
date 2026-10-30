type NotificationEvent={message:string;created:number;notify?:boolean};
const quietSuffixes=['：SSH 连接失败','：采集已恢复','：已连接，远端采集失败','：已连接，设备解析失败'];

export function shouldNotify(event:NotificationEvent,now=Date.now()/1000):boolean{
  const age=now-event.created;
  return event.notify!==false&&!!event.message&&Number.isFinite(age)&&age>=-30&&age<=120
    &&!quietSuffixes.some(suffix=>event.message.endsWith(suffix));
}
