export type MailResult={status:'pending'|'sending'|'sent'|'failed'|'skipped';error:string;updated:number};
export type MailConfig={enabled:boolean;host:string;port:number;security:'ssl'|'starttls';username:string;sender:string;recipients:string[]};
export type MailView=MailConfig&{password_saved:boolean;has_password:boolean;reservation_available:boolean;can_remember:boolean;credential_error:string;last_test:MailResult|null;last_delivery:MailResult|null};
export const defaultMailConfig:MailConfig={enabled:false,host:'',port:465,security:'ssl',username:'',sender:'',recipients:[]};
export function recipientList(value:string):string[]{return [...new Set(value.split(/[,;，；\s]+/).map(value=>value.trim()).filter(Boolean))]}
export async function mailRequest<T>(path='',method='GET',body?:unknown,request:typeof fetch=fetch):Promise<T>{
  const response=await request('/api/settings/mail'+path,{method,headers:{'Content-Type':'application/json','X-IWB':'1'},body:body===undefined?undefined:JSON.stringify(body)});
  const value=await response.json();
  if(!response.ok)throw new Error(typeof value.detail==='string'?value.detail:'邮件设置操作失败，请检查输入');
  return value as T;
}
export const mailStatusText={pending:'邮件排队中',sending:'正在发送邮件',sent:'邮件已提交',failed:'邮件发送失败',skipped:'未发送邮件'};
