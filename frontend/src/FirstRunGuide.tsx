import React,{useEffect,useRef,useState} from 'react';
import {createPortal} from 'react-dom';
import {ArrowRight,BookOpen,Check,Server,X} from 'lucide-react';
import {t,useLocale} from './i18n';
import {useWorkspaceValue} from './workspaceHooks';
import './firstRunGuide.css';

const steps=[
  {title:['连接第一台机器','Connect your first machine'],location:['算力总览 → 添加机器','Resource overview → Add machine'],items:[
    ['可选择本机 SSH 配置、手动输入主机，或从 Excel 批量导入。首次连接前请核对机器身份。','Choose a local SSH configuration, enter a host manually, or import an Excel sheet. Verify the machine identity before connecting.'],
    ['已有密钥可直接使用；密码仅在你选择记住并验证成功后保存到系统凭据管理器。SSH 登录密码与 sudo 密码分别管理。','Use an existing key, or explicitly remember a verified password in the system credential store. SSH and sudo passwords are managed separately.'],
  ]},
  {title:['看懂资源与机器列表','Understand resources and the host list'],location:['算力总览 → 左侧机器列表与资源筛选','Resource overview → Host list and filters'],items:[
    ['给机器设置别名，按集群组织；点击名称查看单台，勾选多台进行批量操作。','Assign aliases and organize hosts into clusters. Select a name to inspect one host, or select several for batch operations.'],
    ['按 GPU / NPU、设备数量和剩余显存寻找资源。低利用率不等于空闲；采集失败、过期和未知数据会单独标记。','Find resources by GPU/NPU type, device count, and free memory. Low utilization does not mean idle; failed, stale, and unknown samples are labelled separately.'],
  ]},
  {title:['打开终端、文件和远程开发工具','Use terminals, files, and remote development'],location:['机器卡片 → 终端、文件、SSH 隧道与 VS Code','Host card → Terminal, Files, SSH tunnels, and VS Code'],items:[
    ['在对应机器上打开终端或管理文件；长任务可使用 tmux 持久会话，普通终端断开可能影响前台任务。','Open a terminal or manage files on the selected host. Use persistent tmux sessions for long tasks; disconnecting an ordinary terminal may interrupt foreground work.'],
    ['需要端口转发时配置 SSH 隧道，也可勾选在打开 VS Code 前连接指定隧道。本机需安装 VS Code 和 Remote - SSH 扩展。','Configure SSH tunnels for port forwarding, and optionally connect selected tunnels before opening VS Code. Install VS Code and its Remote - SSH extension locally.'],
  ]},
  {title:['让 AI 在明确的机器范围内协助','Give the AI assistant a clear host scope'],location:['右上角 AI 助手；设置 → AI 助手','AI assistant at the top right; Settings → AI assistant'],items:[
    ['可配置模型接口，或选择本机 Codex、Claude Code、OpenCode；使用本机引擎前需自行安装并完成登录。','Configure a model connection or select local Codex, Claude Code, or OpenCode. Install and sign in to a local engine before using it.'],
    ['发送前核对机器范围。终端选区或当前屏幕可先附加到草稿；展开执行记录核对工具目标与结果，重复流程可保存为 Skills。','Check the host scope before sending. Attach terminal selections or the current screen to a draft, inspect tool targets and results, and save repeatable workflows as Skills.'],
  ]},
  {title:['用预约和历史安排资源','Plan with availability alerts and history'],location:['资源预约、资源历史与精度对比','Availability alerts, Resource history, and Precision comparison'],items:[
    ['可等待单台指定卡、指定多台机器，或集群中任意几台满足条件；预约只负责空闲提醒，不锁卡，也不自动启动训练。','Wait for selected devices, a fixed set of hosts, or any qualifying hosts in a cluster. Alerts do not lock devices or start training.'],
    ['历史图表需要先积累采样，缺失时段保留为未知。精度对比用于读取日志并按训练步数核对指标。','History needs time to collect samples; gaps remain unknown. Precision comparison reads logs and aligns metrics by training step.'],
  ]},
  {title:['按需配置，随时回来','Configure what you need and return anytime'],location:['设置 → 通用、AI 助手、集成服务、关于与帮助','Settings → General, AI assistant, Integrations, About and help'],items:[
    ['通用设置管理语言、启动方式和桌面浮窗；AI 助手管理模型与 Skills；集成服务管理 MCP 和邮件通知。','General contains language, launch preferences, and the desktop monitor; AI assistant contains models and Skills; Integrations contains MCP and email.'],
    ['完成或跳过引导后不会反复弹出；可在“关于与帮助”中重播，也可进入隔离演示试用。','This guide stays dismissed after completion or skipping; replay it in About and help, or try the isolated demo.'],
  ]},
] as const;

export function FirstRunGuide({ready,hasHosts,onAddMachine}:{ready:boolean;hasHosts:boolean;onAddMachine:()=>void}){
  useLocale();
  const [completed,setCompleted]=useWorkspaceValue('workspace:onboarding-completed:v1',false);
  const [mode,setMode]=useState<'automatic'|'manual'|null>(null),[step,setStep]=useState(0);
  const decided=useRef(false),dialog=useRef<HTMLDialogElement>(null),next=useRef<HTMLButtonElement>(null);
  useEffect(()=>{
    if(!ready||decided.current||completed)return;
    decided.current=true;
    // Existing workspaces should not be interrupted when upgrading.
    if(hasHosts)setCompleted(true);else setMode('automatic');
  },[ready,hasHosts,completed]);
  useEffect(()=>{if(completed&&mode==='automatic')setMode(null)},[completed,mode]);
  useEffect(()=>{
    const replay=()=>{setStep(0);setMode('manual')};
    window.addEventListener('iwb:replay-getting-started',replay);
    return()=>window.removeEventListener('iwb:replay-getting-started',replay);
  },[]);
  useEffect(()=>{
    if(!mode)return;
    const previous=document.activeElement,element=dialog.current;
    element?.showModal();next.current?.focus();
    return()=>{element?.close();if(previous instanceof HTMLElement&&previous.isConnected)previous.focus()};
  },[mode]);
  const finish=()=>{setCompleted(true);setMode(null)};
  if(!mode)return null;
  const current=steps[step],last=step===steps.length-1;
  return createPortal(<dialog ref={dialog} className="modal first-run-guide" aria-modal={true} aria-labelledby="first-run-title" aria-describedby="first-run-description" onCancel={event=>{event.preventDefault();finish()}}>
    <header className="modal-header"><div className="first-run-brand"><BookOpen size={23}/><div><small>{t('新手引导','Getting started')}</small><h2 id="first-run-title">{t('欢迎使用 Infra Workbench','Welcome to Infra Workbench')}</h2></div></div><button type="button" className="icon-button" aria-label={t('关闭并跳过引导','Close and skip guide')} onClick={finish}><X size={20}/></button></header>
    <div className="first-run-content"><div className="first-run-step" aria-label={t('引导进度','Guide progress')}>{step+1} / {steps.length}</div><h3>{t(current.title[0],current.title[1])}</h3><p className="first-run-location">{t(current.location[0],current.location[1])}</p><ul id="first-run-description">{current.items.map(([zh,en])=><li key={en}>{t(zh,en)}</li>)}</ul>
      <p className="first-run-demo"><a href="?demo=1" onClick={finish}>{t('没有服务器？先用模拟数据体验演示','No server? Try the demo with simulated data')}</a></p>
    </div>
    <footer className="modal-footer first-run-actions"><button type="button" className="text-button" onClick={finish}>{t('暂时跳过','Skip for now')}</button><span/>{step>0&&<button type="button" className="secondary" onClick={()=>setStep(value=>value-1)}>{t('上一步','Back')}</button>}{step===0&&<button type="button" className="secondary" onClick={()=>{finish();onAddMachine()}}><Server size={15}/>{t('添加机器','Add machine')}</button>}<button ref={next} type="button" className="primary" onClick={()=>last?finish():setStep(value=>value+1)}>{last?<Check size={16}/>:<ArrowRight size={16}/ >}{last?t('完成引导','Finish guide'):t('下一步','Next')}</button></footer>
  </dialog>,document.body);
}
