import React,{useEffect,useRef,useState} from 'react';
import {ModalDialog} from '../../shared/ModalDialog';
import {ArrowRight,BookOpen,Check,Server,X} from 'lucide-react';
import {t,useLocale} from '../../shared/i18n';
import {useWorkspaceValue} from '../../workspace/workspaceHooks';
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
  {title:['管理 SSH 账号、进程和采集','Manage SSH accounts, processes, and collection'],location:['机器卡片 → SSH 账号、设备详情','Host card → SSH accounts, Device details'],items:[
    ['给机器设置默认 SSH 账号，也可在打开文件或终端前选择另一个账号。用 sudo 补齐进程详情时，可看到启动命令、容器内目录，以及能够映射的宿主机目录。','Set a default SSH account, or select a different login for Files and Terminal. Sudo can show the process command, the container working directory, and the host directory when it can be mapped.'],
    ['可暂停单台机器的采集。选择设备后，可以执行训练前检查、监控显存和端口，或设置空闲提醒。','Pause collection for individual machines. Select devices to run a preflight check, watch memory and ports, or set an availability alert.'],
  ]},
  {title:['打开终端、文件和远程开发工具','Use terminals, files, and remote development'],location:['机器卡片 → 终端、文件、SSH 隧道、服务与 VS Code','Host card → Terminal, Files, SSH tunnels, Services, and VS Code'],items:[
    ['长任务可在 tmux 持久会话中运行。从终端打开文件浏览器时，可以直接进入当前目录。文件浏览器支持搜索、编辑与传输。','Use tmux sessions for long-running tasks. Open Files from the terminal to browse its current directory. Search, edit, and transfer files in the file browser.'],
    ['用服务转发访问 TensorBoard 或 Jupyter，或从“隧道管理”查看各台机器的 SSH 隧道。指定隧道可在 VS Code 连接前启动。','Use service forwarding for TensorBoard or Jupyter, or inspect SSH tunnels across hosts in Tunnel manager. Selected tunnels can start before VS Code connects.'],
  ]},
  {title:['让 AI 在明确的机器范围内协助','Give the AI assistant a clear host scope'],location:['右上角 AI 助手；设置 → AI 助手','AI assistant at the top right; Settings → AI assistant'],items:[
    ['可配置模型接口，或选择本机 Codex、Claude Code、OpenCode、Antigravity 或 DeepSeek Harness。使用本机引擎前请安装对应的 CLI 并完成登录。','Configure a model connection or select local Codex, Claude Code, OpenCode, Antigravity, or DeepSeek Harness. Install and sign in to the corresponding CLI first.'],
    ['发送前核对机器范围和权限模式。可把终端选区或当前屏幕附加到草稿，展开执行记录核对工具目标与结果。对话可重命名，重复流程可保存为 Skills。','Check host scope and permissions before sending. Attach a terminal selection or the current screen and inspect tool targets and results. Rename conversations and save repeatable workflows as Skills.'],
  ]},
  {title:['用预约和历史安排资源','Plan with availability alerts and history'],location:['资源预约、资源历史','Availability alerts and Resource history'],items:[
    ['可等待单台指定卡、指定多台机器，或集群中任意几台满足条件；预约只负责空闲提醒，不锁卡，也不自动启动训练。','Wait for selected devices, a fixed set of hosts, or any qualifying hosts in a cluster. Alerts do not lock devices or start training.'],
    ['按指定机器或集群回看资源历史，切换时间范围和时区。图表需要先积累采样，缺失时段会标记为未知。','Review history for selected machines or a cluster, and change the time range and time zone. History needs time to collect samples. Gaps are labelled unknown.'],
  ]},
  {title:['按步数核对训练精度','Compare training metrics by step'],location:['精度对比 → 基准日志、待验证日志','Precision comparison → Baseline and candidate logs'],items:[
    ['选择两份日志，按真实训练步数对齐。可比较 loss、学习率等指标，查看误差和对应的原始日志行。','Choose two logs to align by actual training step. Compare loss, learning rate, and other metrics, then inspect errors and source lines.'],
    ['常用的对比位置可以保存。首次使用可直接载入示例查看图表。','Save frequently used comparison settings. Load the sample to try the charts.'],
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
  const decided=useRef(false);
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
  const finish=()=>{setCompleted(true);setMode(null)};
  if(!mode)return null;
  const current=steps[step],last=step===steps.length-1;
  return <ModalDialog className="modal first-run-guide" labelledBy="first-run-title" describedBy="first-run-description" onDismiss={finish}>
    <header className="modal-header"><div className="first-run-brand"><BookOpen size={23}/><div><small>{t('新手引导','Getting started')}</small><h2 id="first-run-title">{t('欢迎使用 Infra Workbench','Welcome to Infra Workbench')}</h2></div></div><button type="button" className="icon-button" aria-label={t('关闭并跳过引导','Close and skip guide')} onClick={finish}><X size={20}/></button></header>
    <div className="first-run-content"><div className="first-run-step" aria-label={t('引导进度','Guide progress')}>{step+1} / {steps.length}</div><h3>{t(current.title[0],current.title[1])}</h3><p className="first-run-location">{t(current.location[0],current.location[1])}</p><ul id="first-run-description">{current.items.map(([zh,en])=><li key={en}>{t(zh,en)}</li>)}</ul>
      <p className="first-run-demo"><a href="?demo=1" onClick={finish}>{t('没有服务器？先用模拟数据体验演示','No server? Try the demo with simulated data')}</a></p>
    </div>
    <footer className="modal-footer first-run-actions"><button type="button" className="text-button" onClick={finish}>{t('暂时跳过','Skip for now')}</button><span/>{step>0&&<button type="button" className="secondary" onClick={()=>setStep(value=>value-1)}>{t('上一步','Back')}</button>}{step===0&&<button type="button" className="secondary" onClick={()=>{finish();onAddMachine()}}><Server size={15}/>{t('添加机器','Add machine')}</button>}<button data-dialog-focus type="button" className="primary" onClick={()=>last?finish():setStep(value=>value+1)}>{last?<Check size={16}/>:<ArrowRight size={16}/ >}{last?t('完成引导','Finish guide'):t('下一步','Next')}</button></footer>
  </ModalDialog>;
}
