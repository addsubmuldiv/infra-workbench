import type {AssistantEngine} from './AssistantEnginePicker';
import type {TerminalAttachment} from './terminalContext';
import {t} from './i18n.ts';
import {localizedLabels} from './localizedLabels.ts';
import {ui} from './assistantLocale.ts';
import {workspaceStorage} from './workspaceState.ts';
import {assistantRequest} from './infraAssistant.ts';
export type ChatTool={id:string;name:string;target?:string;status:string;arguments:string;output:string;started:number;finished?:number};
export type ContextUsage={used_tokens:number;total_tokens:number;trigger_tokens:number;source:'provider'|'manual'|'fallback';model:string;estimated:boolean;phase:'request'|'response';updated:number};
export type ChatTurn={supplemental_instructions?:{content:string;created:number}[];terminal_attachments?:TerminalAttachment[];provider_status?:string;model?:string;profile_name?:string;context_usage?:ContextUsage;context_compaction?:{status:'running'|'completed'|'failed';started:number;finished?:number};id:string;role:'user'|'assistant';content:string;created:number;status?:string;elapsed_ms?:number;tools?:ChatTool[];selected_skill_names?:string[];skills_read?:{name:string;version:number|string;source:string}[]};
export type Chat={id:string;title:string;created:number;updated:number;turns:ChatTurn[];active_run:string|null;engine?:AssistantEngine};
export type ChatItem=Pick<Chat,'id'|'title'|'created'|'updated'|'active_run'>;
export function chatReplyTime(created:number,now=new Date()):{label:string;full:string;iso:string}|null{
  const date=new Date(created*1000);
  if(!Number.isFinite(created)||created<=0||!Number.isFinite(date.getTime()))return null;
  const parts=(value:Date)=>Object.fromEntries(new Intl.DateTimeFormat('en-GB',{timeZone:'Asia/Hong_Kong',year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',second:'2-digit',hourCycle:'h23'}).formatToParts(value).map(part=>[part.type,part.value]));
  const value=parts(date),today=parts(now);
  const time=`${value.hour}:${value.minute}:${value.second}`;
  const day=`${value.month}/${value.day}`;
  const sameYear=value.year===today.year;
  const sameDay=sameYear&&value.month===today.month&&value.day===today.day;
  return {label:sameDay?time:sameYear?`${day} ${time}`:`${value.year}/${day} ${time}`,full:t(`回复开始于 ${value.year}/${day} ${time}（UTC+8）；机器状态以回复中的采样时间为准`,`Reply started at ${value.year}/${day} ${time} (UTC+8); machine state refers to the sampling time in the reply`),iso:date.toISOString()};
}
export const toolNames:Record<string,string>=localizedLabels({create_reservation:'创建预约',update_reservation:'修改预约',cancel_reservation:'取消预约',create_rule:'创建监控',delete_rule:'删除监控',get_workbench_state:'查看机器与预约',preflight:'训练前检查',file_operation:'操作服务器文件',read_training_log:'解析训练日志',compare_training_logs:'对比训练日志',get_log_record:'核对日志记录',save_log_comparison:'保存对比配置',search_hosts:'筛选机器',refresh_host:'刷新采样',search_server_files:'搜索服务器文件',create_upload:'准备上传',get_upload:'查询上传进度',download_server_file:'准备文件下载',download_server_folder:'准备目录下载',list_hosts:'列出机器',search_fleet:'查找资源与进程',get_resources:'查看设备资源',read_directory:'浏览目录',read_file:'读取技能与上下文',read_server_directory:'浏览服务器目录',read_server_file:'读取服务器文件',ls:'浏览技能与上下文',glob:'查找技能文件',grep:'搜索技能内容',compact_conversation:'整理对话上下文',ssh_check:'SSH 只读检查',read_changes:'读取资源变化'});
export const toolStatus:Record<string,string>=localizedLabels({running:'正在执行',succeeded:'已返回结果',failed:'未完成',cancelled:'已取消',interrupted:'已中断'});
Object.assign(toolNames,{list_skills:'查询技能',read_skill:'读取技能说明',create_skill_draft:'创建技能草稿',update_skill_draft:'修改技能草稿',validate_skill_draft:'校验技能草稿',install_skill_draft:'安装技能',set_skill_enabled:'启停技能',rollback_skill:'回退技能版本'});
export function loadChatId(storage:Pick<Storage,'getItem'>=workspaceStorage):string|null{try{const id=storage.getItem('iwb-assistant-chat');return id&&/^[a-f0-9]{32}$/.test(id)?id:null}catch{return null}}
export function saveChatId(id:string,storage:Pick<Storage,'setItem'>=workspaceStorage){try{storage.setItem('iwb-assistant-chat',id)}catch{}}
export function chatRequest<T>(path='',method='GET',body?:unknown,signal?:AbortSignal):Promise<T>{return assistantRequest<T>('/chats'+path,method,body,signal)}

export type ChatEvent=
  |{type:'snapshot';data:Chat}
  |{type:'turn';data:{chat_id:string;title:string;updated:number;active_run:string|null;turn:ChatTurn}}
  |{type:'patch';data:{chat_id:string;title:string;updated:number;base_updated:number;active_run:string|null;turn_id:string;changes:Partial<ChatTurn>&{content_append?:string}}}
  |{type:'deleted';data:{chat_id:string}};

export function applyChatEvent(chat:Chat,event:ChatEvent):Chat|null{
  if(event.type==='snapshot')return event.data.id===chat.id&&event.data.updated>=chat.updated?event.data:chat;
  const value=event.data;
  if(value.chat_id!==chat.id)return chat;
  if(event.type==='deleted')return null;
  if(event.type==='patch'){
    const patch=event.data,latest=chat.turns[chat.turns.length-1];
    if(patch.updated<=chat.updated||latest?.role!=='assistant'||latest.id!==patch.turn_id||chat.active_run!==patch.active_run)return chat;
    if(patch.base_updated!==chat.updated)throw new Error(ui("对话更新格式不正确，正在重新连接。"));
    const {content_append,...changes}=patch.changes;
    const turn={...latest,...changes};
    if(content_append!==undefined)turn.content=latest.content+content_append;
    return {...chat,title:patch.title,updated:patch.updated,active_run:patch.active_run,turns:[...chat.turns.slice(0,-1),turn]};
  }
  const update=event.data;
  if(update.updated<chat.updated||chat.active_run&&update.active_run&&chat.active_run!==update.active_run)return chat;
  const latest=chat.turns[chat.turns.length-1];
  // A final event from an older run must not replace a newer assistant turn.
  if(latest?.role!=='assistant'||latest.id!==update.turn.id)return chat;
  return {...chat,title:update.title,updated:update.updated,active_run:update.active_run,turns:[...chat.turns.slice(0,-1),update.turn]};
}

export function shouldFollowChat(view:Pick<HTMLElement,'scrollHeight'|'clientHeight'|'scrollTop'>):boolean{
  return view.scrollHeight-view.clientHeight-view.scrollTop<=64;
}

function retryChatStream(delay:number,signal:AbortSignal):Promise<void>{
  return new Promise(resolve=>{
    if(signal.aborted){resolve();return}
    const finish=()=>{clearTimeout(timer);signal.removeEventListener('abort',finish);resolve()};
    const timer=setTimeout(finish,delay);signal.addEventListener('abort',finish,{once:true});
  });
}

/** Fetch SSE rather than EventSource so the local API's request header is preserved. */
export async function watchChat(id:string,{signal,onEvent,onError,request=fetch,retryMs=1000}:{signal:AbortSignal;onEvent:(event:ChatEvent)=>void;onError?:(error:Error)=>void;request?:typeof fetch;retryMs?:number}):Promise<void>{
  while(!signal.aborted){
    let reader:ReadableStreamDefaultReader<Uint8Array>|undefined;
    const cancel=()=>{void reader?.cancel().catch(()=>{})};
    try{
      const response=await request('/api/assistant/chats/'+encodeURIComponent(id)+'/events',{method:'GET',cache:'no-store',credentials:'same-origin',signal,headers:{'Accept':'text/event-stream','X-IWB':'1','X-IWB-Stream':'delta-v1'}});
      if(signal.aborted){void response.body?.cancel().catch(()=>{});return}
      if(!response.ok){
        if(response.status===404){
          // Older backends have chat snapshots but no events route. Confirm deletion separately.
          const snapshot=await request('/api/assistant/chats/'+encodeURIComponent(id),{method:'GET',cache:'no-store',credentials:'same-origin',signal,headers:{'Accept':'application/json','X-IWB':'1'}});
          if(signal.aborted)return;
          if(snapshot.status===404){onEvent({type:'deleted',data:{chat_id:id}});return}
          if(!snapshot.ok)throw new Error(ui("无法读取对话，正在重试。"));
          const value=await snapshot.json() as Chat;
          if(signal.aborted)return;
          if(value?.id!==id||!Array.isArray(value.turns))throw new Error(ui("对话更新格式不正确，正在重新连接。"));
          onEvent({type:'snapshot',data:value});
          if(value.active_run&&!signal.aborted)onError?.(new Error(ui("当前后台尚不支持实时回复，请从托盘正常退出后重新打开软件，以加载新版后台。")));
          return;
        }
        throw new Error(ui("无法连接对话更新，正在重试。"));
      }
      if(!response.headers.get('content-type')?.includes('text/event-stream')||!response.body)throw new Error(ui("后台未返回对话数据流，请确认已启动新版后台。"));
      reader=response.body.getReader();signal.addEventListener('abort',cancel,{once:true});
      const decoder=new TextDecoder();let buffer='',type='',data:string[]=[];let finished=false;
      const line=(value:string)=>{
        if(!value){
          if(data.length){
            if(type==='snapshot'||type==='turn'||type==='patch'||type==='deleted'){
              const payload=JSON.parse(data.join('\n'));
              if(!payload||typeof payload!=='object'||(type==='snapshot'?payload.id:payload.chat_id)!==id)throw new Error(ui("对话更新格式不正确，正在重新连接。"));
              if(type==='snapshot'&&!Array.isArray(payload.turns)||type==='turn'&&(!payload.turn||typeof payload.turn.content!=='string'))throw new Error(ui("对话更新格式不正确，正在重新连接。"));
              if(type==='patch'&&(!payload.changes||typeof payload.changes!=='object'||Array.isArray(payload.changes)||typeof payload.turn_id!=='string'||!Number.isFinite(payload.base_updated)||!Number.isFinite(payload.updated)||
                payload.changes.content_append!==undefined&&typeof payload.changes.content_append!=='string'||payload.changes.content!==undefined&&typeof payload.changes.content!=='string'))throw new Error(ui("对话更新格式不正确，正在重新连接。"));
              if(!signal.aborted)onEvent({type,data:payload} as ChatEvent);
              if(type==='deleted'||(type==='snapshot'||type==='turn')&&payload.active_run===null)finished=true;
            }
          }
          type='';data=[];return;
        }
        if(value[0]===':')return;
        const colon=value.indexOf(':');const field=colon<0?value:value.slice(0,colon);let content=colon<0?'':value.slice(colon+1);if(content.startsWith(' '))content=content.slice(1);
        if(field==='event')type=content;else if(field==='data')data.push(content);
      };
      while(!signal.aborted&&!finished){
        const chunk=await reader.read();if(chunk.done){if(buffer.endsWith('\r'))line(buffer.slice(0,-1));break;}
        buffer+=decoder.decode(chunk.value,{stream:true});
        // Delay a trailing CR until its possible LF arrives in the next byte chunk.
        let offset=0;
        for(let index=0;index<buffer.length;index++){
          const char=buffer[index];if(char!=='\r'&&char!=='\n')continue;
          if(char==='\r'&&index===buffer.length-1)break;
          line(buffer.slice(offset,index));if(char==='\r'&&buffer[index+1]==='\n')index++;offset=index+1;
          if(signal.aborted||finished)break;
        }
        buffer=buffer.slice(offset);
      }
      if(finished)return;
      // Incomplete frames at EOF are discarded. The next connection begins with a snapshot.
    }catch(error){if(!signal.aborted)onError?.(error instanceof Error?error:new Error(ui("无法读取对话更新，正在重试。")))}
    finally{signal.removeEventListener('abort',cancel);await reader?.cancel().catch(()=>{});reader?.releaseLock()}
    if(!signal.aborted)await retryChatStream(retryMs,signal);
  }
}

export function toolPresentation(tool:ChatTool){
  if(tool.status==='failed'||tool.status==='succeeded'){
    try{
      const result=JSON.parse(tool.output);
      if(result?.error?.code==='STALE_SNAPSHOT')return {status:'warning',label:ui("未取得有效采样")};
      if(result?.partial===true)return {status:'warning',label:ui("已返回部分结果")};
    }catch{}
  }
  return {status:tool.status,label:tool.status==='failed'?ui("调用失败"):toolStatus[tool.status]||tool.status};
}
