import {assistantRequest} from './infraAssistant.ts';
export type ChatTool={id:string;name:string;target?:string;status:string;arguments:string;output:string;started:number;finished?:number};
export type ChatTurn={id:string;role:'user'|'assistant';content:string;created:number;status?:string;elapsed_ms?:number;tools?:ChatTool[]};
export type Chat={id:string;title:string;created:number;updated:number;turns:ChatTurn[];active_run:string|null};
export type ChatItem=Pick<Chat,'id'|'title'|'created'|'updated'|'active_run'>;
export const toolNames:Record<string,string>={create_reservation:'创建预约',update_reservation:'修改预约',cancel_reservation:'取消预约',create_rule:'创建监控',delete_rule:'删除监控',get_workbench_state:'查看机器与预约',preflight:'训练前检查',file_operation:'操作服务器文件',read_training_log:'解析训练日志',compare_training_logs:'对比训练日志',get_log_record:'核对日志记录',save_log_comparison:'保存对比配置',search_hosts:'筛选机器',refresh_host:'刷新采样',search_server_files:'搜索服务器文件',create_upload:'准备上传',get_upload:'查询上传进度',download_server_file:'准备文件下载',download_server_folder:'准备目录下载',list_hosts:'列出机器',search_fleet:'查找资源与进程',get_resources:'查看设备资源',read_directory:'浏览目录',read_file:'读取技能与上下文',read_server_directory:'浏览服务器目录',read_server_file:'读取服务器文件',ls:'浏览技能与上下文',glob:'查找技能文件',grep:'搜索技能内容',compact_conversation:'整理对话上下文',ssh_check:'SSH 只读检查',read_changes:'读取资源变化'};
export const toolStatus:Record<string,string>={running:'正在执行',succeeded:'已返回结果',failed:'未完成',cancelled:'已取消',interrupted:'已中断'};
export function loadChatId():string|null{try{const id=localStorage.getItem('iwb-assistant-chat');return id&&/^[a-f0-9]{32}$/.test(id)?id:null}catch{return null}}
export function saveChatId(id:string){try{localStorage.setItem('iwb-assistant-chat',id)}catch{}}
export function chatRequest<T>(path='',method='GET',body?:unknown,signal?:AbortSignal):Promise<T>{return assistantRequest<T>('/chats'+path,method,body,signal)}

export type ChatEvent=
  |{type:'snapshot';data:Chat}
  |{type:'turn';data:{chat_id:string;title:string;updated:number;active_run:string|null;turn:ChatTurn}}
  |{type:'deleted';data:{chat_id:string}};

export function applyChatEvent(chat:Chat,event:ChatEvent):Chat|null{
  if(event.type==='snapshot')return event.data.id===chat.id&&event.data.updated>=chat.updated?event.data:chat;
  const value=event.data;
  if(value.chat_id!==chat.id)return chat;
  if(event.type==='deleted')return null;
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
      const response=await request('/api/assistant/chats/'+encodeURIComponent(id)+'/events',{method:'GET',cache:'no-store',credentials:'same-origin',signal,headers:{'Accept':'text/event-stream','X-IWB':'1'}});
      if(signal.aborted){void response.body?.cancel().catch(()=>{});return}
      if(!response.ok){
        if(response.status===404){
          // Older backends have chat snapshots but no events route. Confirm deletion separately.
          const snapshot=await request('/api/assistant/chats/'+encodeURIComponent(id),{method:'GET',cache:'no-store',credentials:'same-origin',signal,headers:{'Accept':'application/json','X-IWB':'1'}});
          if(signal.aborted)return;
          if(snapshot.status===404){onEvent({type:'deleted',data:{chat_id:id}});return}
          if(!snapshot.ok)throw new Error('无法读取对话，正在重试。');
          const value=await snapshot.json() as Chat;
          if(signal.aborted)return;
          if(value?.id!==id||!Array.isArray(value.turns))throw new Error('对话更新格式不正确，正在重新连接。');
          onEvent({type:'snapshot',data:value});
          if(value.active_run&&!signal.aborted)onError?.(new Error('当前后台尚不支持实时回复，请从托盘正常退出后重新打开软件，以加载新版后台。'));
          return;
        }
        throw new Error('无法连接对话更新，正在重试。');
      }
      if(!response.headers.get('content-type')?.includes('text/event-stream')||!response.body)throw new Error('后台未返回对话数据流，请确认已启动新版后台。');
      reader=response.body.getReader();signal.addEventListener('abort',cancel,{once:true});
      const decoder=new TextDecoder();let buffer='',type='',data:string[]=[];let finished=false;
      const line=(value:string)=>{
        if(!value){
          if(data.length){
            if(type==='snapshot'||type==='turn'||type==='deleted'){
              const payload=JSON.parse(data.join('\n'));
              if(!payload||typeof payload!=='object'||(type==='snapshot'?payload.id:payload.chat_id)!==id)throw new Error('对话更新格式不正确，正在重新连接。');
              if(type==='snapshot'&&!Array.isArray(payload.turns)||type==='turn'&&(!payload.turn||typeof payload.turn.content!=='string'))throw new Error('对话更新格式不正确，正在重新连接。');
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
    }catch(error){if(!signal.aborted)onError?.(error instanceof Error?error:new Error('无法读取对话更新，正在重试。'))}
    finally{signal.removeEventListener('abort',cancel);await reader?.cancel().catch(()=>{});reader?.releaseLock()}
    if(!signal.aborted)await retryChatStream(retryMs,signal);
  }
}
