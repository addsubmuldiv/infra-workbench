import React,{useState} from 'react';
import {t,useLocale} from '../../shared/i18n';
import {demoRuntime} from './demoBootstrap';
import './demoPanels.css';
export function DemoAssistant({selectedHostIds=[]}:{selectedHostIds?:string[]}){
 useLocale();
 const [example,setExample]=useState<'resources'|'logs'|null>(null);
 const scoped=demoRuntime!.getHosts().filter(h=>!selectedHostIds.length||selectedHostIds.includes(h.id));
 const available=scoped.filter(h=>h.snapshot.fresh&&h.snapshot.devices.some(d=>d.processes_known&&d.utilization===0&&!d.processes.length));
 const heading=example==='resources'?t('查找空闲资源','Find idle resources'):t('分析示例日志','Analyze sample log');
 return <section className="demo-assistant"><h2>{t('AI 助手演示','AI assistant demo')}</h2><p>{t('以下为预设回答示例，用于展示操作方式，不调用模型。真实使用时可在设置中配置自己的模型接口。','These preset examples show the workflow without calling a model. Configure your own model in Settings for real use.')}</p>
 <button className="secondary" onClick={()=>setExample(null)}>{t('新建对话','New conversation')}</button>
 <button className="secondary" onClick={()=>setExample('resources')}>{t('查找空闲资源','Find idle resources')}</button>
 <button className="secondary" onClick={()=>setExample('logs')}>{t('分析示例日志','Analyze sample log')}</button>
 {example&&<div className="demo-answer"><strong>{heading}</strong>
 <p role="status">{example==='resources'
  ?t(`有空闲设备的模拟机器：${available.map(h=>h.alias).join('、')||'暂无'}。请核对设备数量和剩余显存。`,`Simulated machines with idle devices: ${available.map(h=>h.alias).join(', ')||'none'}. Check device counts and free memory.`)
  :t('示例 train.log 的 loss 从 step 1 的 2.2000 降至 step 20 的 0.4583。可以用精度对比查看两次训练的差异。','Loss in the sample train.log falls from 2.2000 at step 1 to 0.4583 at step 20. Use Precision comparison to compare two runs.')}</p>
 <details><summary>{t('模拟工具调用','Simulated tool call')}</summary><pre>{JSON.stringify(example==='resources'
  ?{operation:'resource lookup',host_ids:scoped.map(h=>h.id)}
  :{operation:'read sample file',host_id:'demo-gpu-busy',path:'/demo/train.log'},null,2)}</pre></details></div>}</section>
}

const settingsTopics=[
 ['机器卡片 → SSH 账号、sudo、暂停采集','Host card → SSH accounts, sudo, and collection pause',
  '设置默认 SSH 账号后，可分别选择终端和文件使用的登录账号。sudo 用于补齐进程详情，采集也可按机器暂停。',
  'Set the default SSH account and choose which login to use for terminals and files. Sudo adds process details. Collection can be paused per machine.'],
 ['设置 → AI 助手','Settings → AI assistant',
  '配置模型接口或本地 Codex、Claude Code、OpenCode、Antigravity、DeepSeek Harness。常用流程可保存为 Skills。助手里可管理、重命名和检索对话。',
  'Configure a model provider or local Codex, Claude Code, OpenCode, Antigravity, or DeepSeek Harness. Save recurring workflows as Skills. Manage, rename, and search conversations in the assistant.'],
 ['设置 → 集成服务','Settings → Integrations',
  '复制 MCP 接入地址给外部助手。设置邮件后，资源预约可同时发送邮件提醒。',
  'Copy the MCP endpoint for external assistants. Configure email to receive availability alerts by email.'],
 ['设置 → 通用、关于与帮助','Settings → General, About and help',
  '设置语言、桌面启动方式和资源浮窗。可在关于与帮助中查看更新或重新打开教程。',
  'Set language, desktop launch mode, and the floating resource monitor. Check updates or replay the guide in About and help.'],
] as const;
export function DemoSettings(){
 useLocale();
 return <section className="settings-card"><h2>{t('正式工作台的设置入口','Settings in the workbench')}</h2>
 {settingsTopics.map(([zh,en,detailZh,detailEn])=><details key={en}><summary>{t(zh,en)}</summary><p>{t(detailZh,detailEn)}</p></details>)}
 </section>
}
export function DemoTerminal({hostId,close,openFiles}:{hostId:string;close:()=>void;openFiles:()=>void}){
 useLocale();
 const [input,setInput]=useState(''),[lines,setLines]=useState<string[]>([]);
 const run=async(event:React.FormEvent)=>{
  event.preventDefault();
  const command=input.trim();
  if(!command)return;
  setInput('');
  if(command==='clear'){setLines([]);return}
  let result=t('演示终端支持 help、pwd、ls、cat 和 clear。','The demo terminal supports help, pwd, ls, cat, and clear.');
  const file=/^cat ([\w.-]+)$/.exec(command)?.[1];
  if(command==='pwd')result='/demo';
  if(command==='ls'||file){
   const response=await demoRuntime!.fetch('/api/files/'+(file?'operation':'browse'),{method:'POST',
    body:JSON.stringify({host_id:hostId,path:file?'/demo/'+file:'/demo',...(file?{op:'read'}:{})})});
   if(response.ok){
    const data=await response.json();
    result=file?data.content:data.entries.map((entry:{name:string})=>entry.name).join('  ');
   }else result=t('找不到这个示例文件。','Sample file not found.');
  }
  setLines(old=>[...old,'demo$ '+command,result.trimEnd()]);
 };
 return <section className="demo-terminal" role="dialog" aria-label={t('演示终端','Demo terminal')}>
 <div><strong>{t('演示终端 · 仅模拟命令','Demo terminal · simulated commands only')}</strong>
 <button className="secondary" onClick={openFiles}>{t('打开当前目录','Open current directory')}</button>
 <button className="secondary" onClick={close}>{t('关闭终端','Close terminal')}</button></div>
 <pre aria-live="polite">{lines.length?lines.join('\n'):t('试试 help、pwd、ls 或 cat train.log。','Try help, pwd, ls, or cat train.log.')}</pre>
 <form onSubmit={event=>void run(event)}><label>demo$ <input aria-label={t('演示命令','Demo command')} value={input} onChange={e=>setInput(e.target.value)} autoComplete="off"/></label><button className="secondary">{t('执行模拟命令','Run simulated command')}</button></form></section>
}
