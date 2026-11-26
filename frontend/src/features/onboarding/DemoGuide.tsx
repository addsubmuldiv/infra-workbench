import {demoOnlyBuild} from './demoBootstrap';
import {useEffect, useRef, useState} from 'react';
import {MapPin} from 'lucide-react';
import {t, useLocale} from '../../shared/i18n';
import './demoGuide.css';

const steps = [
  ['overview', '先看资源概览', 'Start with the resource overview', '这里汇总在线机器、设备数量和符合条件的资源。点击统计卡片，可以切换到对应的机器列表；离线或未知状态不会被当作空闲。', 'See online hosts, device counts, and matching resources. Select a summary card to inspect the relevant hosts. Offline or unknown devices are not treated as idle.'],
  ['hosts', '按集群管理机器', 'Organize machines into clusters', '展开 GPU Training、Ascend Lab 或 Inference，按别名搜索机器，或勾选整个集群。试试新建集群和移动机器，重置后会恢复示例分组。', 'Expand GPU Training, Ascend Lab, or Inference. Search by alias or select a whole cluster. Try creating a cluster and moving machines. Reset restores the sample groups.'],
  ['finder', '找到够用的空闲卡', 'Find suitable idle devices', '按 GPU / NPU、设备数量和每卡剩余显存筛选，再点击“查看机器”。默认搜索全部机器，左侧选择不会自动限制搜索范围；空闲结果也不会预留设备。', 'Filter by GPU/NPU, device count, and free memory per device, then select View machines. Searches cover all hosts unless explicitly restricted. Matching devices are not reserved.'],
  ['device', '确认是谁在占卡', 'Inspect device processes', '点击设备，查看占用进程的用户、PID、启动命令和工作目录。不要只凭低利用率判断空闲；这里展示的是模拟进程。', 'Open a device to inspect the user, PID, command, and working directory of its processes. Low utilization alone does not mean idle. These processes are simulated.'],
  ['preflight', '训练前检查与设备监控', 'Run preflight checks and watch devices', '在 GPU Lab 01 勾选设备，设置训练端口，再试试“训练前检查”或“监控所选”。监控规则可在右上角通知中心查看。', 'Select devices on GPU Lab 01 and set a training port. Try the preflight check or watch the selected devices, then find the rule in the notification center.'],
  ['reservation', '设置空闲提醒', 'Set an availability alert', '可以等待任意数量的卡，也可以指定卡号，并设置连续空闲多久后提醒。演示中可把等待设为 0 分钟，再点引导中的“模拟训练结束”观察提醒；预约不会锁卡。', 'Wait for a device count or specific IDs, with a continuous-idle delay. In the demo, use a zero-minute delay and Finish demo training in this guide to try an alert. Alerts do not lock devices.'],
  ['notifications', '查看提醒和监控规则', 'Review alerts and monitoring rules', '打开右上角通知中心。模拟训练结束后的预约提醒显示在“消息记录”，之前添加的监控显示在“监控规则”。', 'Open the notification center at the top right. Messages shows alerts after the simulated run finishes. Monitoring rules shows the rules you added.'],
  ['groups', '预约多台机器或整个集群', 'Create a multi-machine or cluster alert', '要等多台机器一起空闲，可以在这里设一条预约。先展开 GPU Training 的示例，看看哪些机器符合条件，再试试新建多机预约。', 'Set a single alert when you need several machines to be idle at the same time. Expand the GPU Training example to see which hosts qualify, then try creating a multi-machine alert.'],
  ['history', '回看资源空闲时段', 'Review resource history', '想知道机器通常什么时候空闲，可以在这里回看采样。教程已选中两台模拟 GPU 机器。点击图表中的时段，查看空闲、占用和未知状态。', 'Use history to see when machines tend to be idle. The tour selected two simulated GPU machines. Click an interval to inspect idle, busy, and unknown states.'],
  ['files', '打开文件和训练日志', 'Open files and training logs', '浏览这台机器的目录，双击 train.log 查看示例训练日志，也可以编辑示例文本。真实使用时，这里用于管理服务器文件；演示中的修改只保存在当前页面。', 'Browse the host directory and double-click train.log to inspect the sample training log, or edit sample text. In real use this manages server files. Demo edits remain only in this page.'],
  ['terminal', '打开终端并查看训练日志', 'Open a terminal and read a training log', '在演示终端输入 cat train.log，或点“打开当前目录”进入文件浏览器。正式工作台还可通过 tmux 恢复长任务，将终端选区发到助手草稿。', 'Try cat train.log in the demo terminal, or open the current directory in Files. The real app can resume long-running tmux sessions and attach a terminal selection to the assistant draft.'],
  ['tunnels', '管理 SSH 隧道和 VS Code 连接', 'Manage SSH tunnels and VS Code connections', '打开隧道管理，查看已连接的 JupyterLab 和备用的 Remote editor 配置。试试模拟连接或断开。正式工作台可设置自动重连，或在打开 VS Code 前连接指定隧道。', 'Open Tunnel manager to see the connected JupyterLab example and the saved Remote editor rule. Try a simulated connection or disconnection. The real app can reconnect automatically or start selected tunnels before opening VS Code.'],
  ['services', '用端口转发访问远程服务', 'Forward a remote service port', '打开 GPU Training 02 的“服务”，启动模拟 TensorBoard 转发，看看远端端口如何映射到本地。也可以添加 Jupyter 或自定义 HTTP 规则。', 'Open Services on GPU Training 02 and start the simulated TensorBoard forwarding rule to see the local port mapping. You can also add a Jupyter or custom HTTP rule.'],
  ['precision', '按训练步数对比精度', 'Compare metrics by training step', '要核对两次训练的结果，可以在这里按步数对齐日志。点击“载入示例”，查看 loss、grad_norm 和学习率的差异，再打开误差对应的原始日志行。', 'Use this page to align logs from two training runs by step. Load the sample to compare loss, grad_norm, and learning rate, then inspect the source lines for a difference.'],
  ['assistant', '练习向 AI 助手交代任务', 'Practice giving the AI assistant a task', '打开助手，新建一段空白对话，试试“查找空闲资源”或“分析示例日志”。展开模拟工具记录，核对助手看了哪些机器、用了哪些参数。', 'Open the assistant, start a blank conversation, and try Find idle resources or Analyze sample log. Expand the simulated tool record to check which hosts and arguments it used.'],
  ['settings', '找到账号、助手和集成设置', 'Find account, assistant, and integration settings', '这里列出 SSH 账号与 sudo、本地 AI 引擎、Skills、MCP、邮件和桌面更新的实际入口。可以在演示里切换语言，退出后再配置自己的连接。', 'Review where to configure SSH accounts and sudo, local AI engines, Skills, MCP, email, and desktop updates. Try changing language here, then exit to configure your own connections.'],
] as const;
export type DemoStep=typeof steps[number][0];
const destinations:Partial<Record<DemoStep,readonly [string,string]>>={
  groups:['资源预约','Resource alerts'],
  history:['资源历史','Resource history'],
  precision:['精度对比','Precision comparison'],
  settings:['设置','Settings'],
};
function nextLabel(current:DemoStep,next:DemoStep|undefined){
  if(!next)return t('完成','Done');
  const destination=destinations[next];
  if(destination)return t(`前往${destination[0]}`,`Go to ${destination[1]}`);
  if(destinations[current])return t('返回算力总览','Return to overview');
  return t('下一步','Next');
}
const focusable = 'button:not([disabled]), a[href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';
type Rect = {top:number; left:number; right:number; bottom:number};

export function DemoGuide({onReset,onFinishTraining,onStepChange}: {onReset:()=>void;onFinishTraining:()=>void;onStepChange:(target:DemoStep)=>void}) {
  useLocale();
  const [step, setStep] = useState<number|null>(0);
  const [spotlight,setSpotlight]=useState<{step:number;rect:Rect|null}|null>(null);
  const [cardHeight,setCardHeight]=useState(280);
  const card = useRef<HTMLDivElement>(null);
  const target = useRef<HTMLElement|null>(null);
  const replay = useRef<HTMLButtonElement>(null);
  const active = step !== null;
  const section=step===null?null:steps[step][0];
  const rect=spotlight?.step===step?spotlight.rect:null;
  useEffect(()=>{if(step!==null)onStepChange(steps[step][0])},[step]);
  useEffect(() => {
    if (step === null) {setSpotlight(null);return;}
    let frame = 0;
    let scrollTarget:HTMLElement|null=null;
    const measure = () => {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(() => {
        const height=card.current?.getBoundingClientRect().height;
        if(height)setCardHeight(previous=>Math.abs(previous-height)<1?previous:height);
        // Keep a detail/booking dialog operable when the highlighted control opens it.
        const dialogs = [...document.querySelectorAll<HTMLElement>('[role="dialog"], dialog[open]')].filter(el => !el.classList.contains('demo-tour-card') && el.getClientRects().length);
        const assistant=steps[step][0]==='assistant'?document.querySelector<HTMLElement>('#infra-assistant-panel:not([hidden])'):null;
        const panel=document.querySelector<HTMLElement>(`[data-tour-panel="${steps[step][0]}"]`);
        const control=[...document.querySelectorAll<HTMLElement>(`[data-tour="${steps[step][0]}"]`)].find(el=>el.getClientRects().length);
        const el = dialogs[dialogs.length-1] ?? assistant ?? panel ?? control ?? null;
        if(el&&(el===panel||el===control)&&el!==scrollTarget){scrollTarget=el;el.scrollIntoView({block:'nearest',behavior:'auto'});}
        target.current = el;
        const r = el?.getBoundingClientRect();
        const next = r && r.width > 0 && r.height > 0 && r.bottom > 0 && r.top < innerHeight && r.right > 0 && r.left < innerWidth
          ? {top:Math.max(0,r.top-5), left:Math.max(0,r.left-5), right:Math.min(innerWidth,r.right+5), bottom:Math.min(innerHeight,r.bottom+5)} : null;
        setSpotlight(previous=>previous?.step===step&&JSON.stringify(previous.rect)===JSON.stringify(next)?previous:{step,rect:next});
      });
    };
    measure();
    card.current?.focus({preventScroll:true});
    window.addEventListener('resize', measure);
    document.addEventListener('scroll', measure, true);
    const observer = new MutationObserver(measure);
    observer.observe(document.body, {childList:true, subtree:true,attributes:true,attributeFilter:['hidden','open','data-tour-panel']});
    const resize = new ResizeObserver(measure);
    resize.observe(document.body);
    if(card.current)resize.observe(card.current);
    return () => {cancelAnimationFrame(frame); observer.disconnect(); resize.disconnect(); window.removeEventListener('resize',measure); document.removeEventListener('scroll',measure,true);};
  }, [step]);
  useEffect(() => {
    if (!active) return;
    const allowed = (el:Element|null) => !!el && (!!card.current?.contains(el) || !!target.current?.contains(el));
    const keydown = (event:KeyboardEvent) => {
      if(target.current?.closest('dialog[open],[aria-modal="true"]'))return;
      if (event.key === 'Escape') {event.preventDefault(); setStep(null); return;}
      if (event.key !== 'Tab') return;
      const candidates = [...(target.current?.querySelectorAll<HTMLElement>(focusable) ?? []), ...(card.current?.querySelectorAll<HTMLElement>(focusable) ?? [])];
      if (target.current?.matches(focusable)) candidates.unshift(target.current);
      const items = candidates.filter(el => el.getClientRects().length && getComputedStyle(el).visibility !== 'hidden');
      if (!items.length) {event.preventDefault(); card.current?.focus(); return;}
      const index = items.indexOf(document.activeElement as HTMLElement);
      event.preventDefault();
      items[(index + (event.shiftKey ? -1 : 1) + items.length) % items.length].focus();
    };
    const focus = (event:FocusEvent) => {
      if((event.target as Element)?.closest('dialog[open],[aria-modal="true"]'))return;
      if (!allowed(event.target as Element)) card.current?.focus();
    };
    document.addEventListener('keydown',keydown,true);
    document.addEventListener('focusin',focus,true);
    return () => {document.removeEventListener('keydown',keydown,true); document.removeEventListener('focusin',focus,true);};
  },[active,section]);
  useEffect(()=>{if(!active)replay.current?.focus()},[active]);
  const stop = () => {setStep(null);};
  const exit = () => {if(demoOnlyBuild){location.assign('https://github.com/addsubmuldiv/infra-workbench');return;}const url = new URL(location.href); url.searchParams.delete('demo');url.hash='';location.assign(url.href);};
  const fullWidth=Math.min(360,innerWidth-24);
  const cardWidth=rect&&rect.left>=252&&rect.right+fullWidth+24>innerWidth
    ? Math.min(fullWidth,rect.left-24) : fullWidth;
  const left=rect&&rect.left>=cardWidth+24;
  const right=rect&&rect.right+cardWidth+24<=innerWidth;
  const cardLeft=rect ? right?rect.right+12:left?rect.left-cardWidth-12:Math.max(12,Math.min(rect.left,innerWidth-cardWidth-12)) : Math.max(12,(innerWidth-cardWidth)/2);
  const maxCardTop=Math.max(12,innerHeight-cardHeight-12);
  const preferredTop=rect ? left||right?rect.top
    :rect.top>=cardHeight+24?rect.top-cardHeight-12
    :rect.bottom+cardHeight+24<=innerHeight?rect.bottom+12
    :innerHeight-rect.bottom>rect.top?maxCardTop:12 : 90;
  const cardTop=Math.max(12,Math.min(preferredTop,maxCardTop));
  const destination=section?destinations[section]:undefined;
  return <>
    <aside className="demo-bar" aria-label={t('演示模式','Demo mode')}>
      <span><strong>{t('演示模式','Demo mode')}</strong> · {t('所有数据均为模拟，不连接 SSH 或真实模型。','All data is simulated. No SSH or real model connections.')}</span>
      <div><button ref={replay} onClick={()=>setStep(0)}>{t('重播引导','Replay tour')}</button><button onClick={onFinishTraining}>{t('模拟训练结束','Finish demo training')}</button><button onClick={onReset}>{t('重置','Reset')}</button><button onClick={exit}>{t('退出演示','Exit demo')}</button></div>
    </aside>
    {step !== null && <div className="demo-tour">
      {rect ? <>
        <div className="demo-shade" style={{top:0,left:0,right:0,height:rect.top}} />
        <div className="demo-shade" style={{top:rect.top,left:0,width:rect.left,height:rect.bottom-rect.top}} />
        <div className="demo-shade" style={{top:rect.top,left:rect.right,right:0,height:rect.bottom-rect.top}} />
        <div className="demo-shade" style={{top:rect.bottom,left:0,right:0,bottom:0}} />
        <div className="demo-highlight" style={{top:rect.top,left:rect.left,width:rect.right-rect.left,height:rect.bottom-rect.top}} />
      </> : <div className="demo-shade" style={{inset:0}} />}
      <div className="demo-tour-card" ref={card} tabIndex={-1} role="dialog" aria-labelledby="demo-tour-title" aria-describedby={destination?"demo-tour-location demo-tour-description":"demo-tour-description"} style={{top:cardTop,left:cardLeft,width:cardWidth}}>
        <label className="demo-tour-picker"><small>{step+1} / {steps.length}</small><select aria-label={t('跳转到教程步骤','Jump to tutorial step')} value={step} onChange={event=>setStep(Number(event.target.value))}>{steps.map(([key,zh,en],index)=><option key={key} value={index}>{index+1}. {t(zh,en)}</option>)}</select></label>
        {destination&&<p className="demo-tour-location" id="demo-tour-location"><MapPin size={14} aria-hidden="true"/>{t(`当前位置 · ${destination[0]}`,`You’re here · ${destination[1]}`)}</p>}
        <h2 id="demo-tour-title">{t(steps[step][1],steps[step][2])}</h2>
        <p id="demo-tour-description">{t(steps[step][3],steps[step][4])}</p>
        {(section==='reservation'||section==='groups')&&<button className="demo-tour-next" onClick={onFinishTraining}>{t('模拟训练结束','Finish demo training')}</button>}
        <div className="demo-tour-actions"><button onClick={stop}>{t('跳过','Skip')}</button><span /><button disabled={step===0} onClick={()=>setStep(step-1)}>{t('上一步','Back')}</button><button className="demo-tour-next" onClick={()=>step===steps.length-1 ? stop() : setStep(step+1)}>{nextLabel(steps[step][0],steps[step+1]?.[0])}</button></div>
      </div>
    </div>}
  </>;
}
