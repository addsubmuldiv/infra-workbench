import {demoOnlyBuild} from './demoBootstrap';
import {useEffect, useRef, useState} from 'react';
import {t, useLocale} from './i18n';
import './demoGuide.css';

const steps = [
  ['overview', '先看资源概览', 'Start with the resource overview', '这里汇总在线机器、设备数量和符合条件的资源。点击统计卡片，可以切换到对应的机器列表；离线或未知状态不会被当作空闲。', 'See online hosts, device counts, and matching resources. Select a summary card to inspect the relevant hosts. Offline or unknown devices are not treated as idle.'],
  ['hosts', '选择要查看的机器', 'Choose which machines to inspect', '点击机器名称只看一台，勾选框可以同时查看多台；搜索也支持机器别名。正式工作台还能按集群组织机器并执行批量操作，本演示先练习选择与筛选。', 'Select a host name to inspect one machine, or use checkboxes to show several. Search also matches aliases. The real workbench supports clusters and batch operations; this demo focuses on selection and filtering.'],
  ['finder', '找到够用的空闲卡', 'Find suitable idle devices', '按 GPU / NPU、设备数量和每卡剩余显存筛选，再点击“查看机器”。默认搜索全部机器，左侧选择不会自动限制搜索范围；空闲结果也不会预留设备。', 'Filter by GPU/NPU, device count, and free memory per device, then select View machines. Searches cover all hosts unless explicitly restricted. Matching devices are not reserved.'],
  ['device', '确认是谁在占卡', 'Inspect device processes', '点击设备，查看占用进程的用户、PID、启动命令和工作目录。不要只凭低利用率判断空闲；这里展示的是模拟进程。', 'Open a device to inspect the user, PID, command, and working directory of its processes. Low utilization alone does not mean idle. These processes are simulated.'],
  ['reservation', '设置空闲提醒', 'Set an availability alert', '可以等待任意数量的卡，也可以指定卡号，并设置连续空闲多久后提醒。演示中可把等待设为 0 分钟，再点引导中的“模拟训练结束”观察提醒；预约不会锁卡。', 'Wait for a device count or specific IDs, with a continuous-idle delay. In the demo, use a zero-minute delay and Finish demo training in this guide to try an alert. Alerts do not lock devices.'],
  ['files', '打开文件和训练日志', 'Open files and training logs', '浏览这台机器的目录，双击 train.log 查看示例训练日志，也可以编辑示例文本。真实使用时，这里用于管理服务器文件；演示中的修改只保存在当前页面。', 'Browse the host directory and double-click train.log to inspect the sample training log, or edit sample text. In real use this manages server files. Demo edits remain only in this page.'],
  ['terminal', '在对应机器上打开终端', 'Open a terminal for the host', '演示终端仅支持 help、pwd、ls 等模拟命令。正式工作台可使用 tmux 持久会话运行长任务，也可把终端选区附加到 AI 草稿；真实终端命令可能修改服务器。', 'The demo accepts simulated commands such as help, pwd, and ls. In the real workbench, use persistent tmux sessions for long tasks and attach terminal selections to AI drafts. Real terminal commands may change the server.'],
  ['assistant', '让 AI 协助操作', 'Work with the AI assistant', '打开助手，点击“查找空闲资源”或“分析示例日志”查看预设回答。真实助手可以调用工作台工具，并复用 Skills；请展开工具记录核对目标、参数和结果。', 'Open the assistant and try Find idle resources or Analyze sample log for labelled preset answers. The real assistant can call workbench tools and reuse Skills. Inspect tool records to verify targets, arguments, and results.'],
  ['settings', '了解真实使用前的配置', 'Review setup before real use', '正式设置分为通用、AI 助手、集成服务、关于与帮助；模型接口、Skills、MCP 和邮件各有对应入口。SSH 隧道与 VS Code 位于机器卡片。演示不接收密钥或密码，也不建立真实隧道；请退出演示后配置。', 'Real settings are grouped into General, AI assistant, Integrations, and About and help, with model, Skills, MCP, and email controls. SSH tunnels and VS Code are on host cards. The demo accepts no keys or passwords and creates no real tunnels; exit demo before configuring them.'],
] as const;
const focusable = 'button:not([disabled]), a[href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';
type Rect = {top:number; left:number; right:number; bottom:number};

export function DemoGuide({onReset, onFinishTraining,onStart,onStepChange}: {onReset:()=>void; onFinishTraining:()=>void;onStart?:()=>void;onStepChange?:(target:string)=>void}) {
  useLocale();
  const [step, setStep] = useState<number|null>(0);
  const [rect, setRect] = useState<Rect|null>(null);
  const [cardHeight,setCardHeight]=useState(280);
  const card = useRef<HTMLDivElement>(null);
  const target = useRef<HTMLElement|null>(null);
  const replay = useRef<HTMLButtonElement>(null);
  const active = step !== null;
  useEffect(()=>{onStart?.()},[]);
  useEffect(()=>{if(step!==null)onStepChange?.(steps[step][0])},[step]);
  useEffect(() => {
    if (step === null) {setRect(null); return;}
    let frame = 0;
    const measure = () => {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(() => {
        const height=card.current?.getBoundingClientRect().height;
        if(height)setCardHeight(previous=>Math.abs(previous-height)<1?previous:height);
        // Keep a detail/booking dialog operable when the highlighted control opens it.
        const dialogs = [...document.querySelectorAll<HTMLElement>('[role="dialog"], dialog[open]')].filter(el => !el.classList.contains('demo-tour-card') && el.getClientRects().length);
        const assistant=steps[step][0]==='assistant'?document.querySelector<HTMLElement>('#infra-assistant-panel:not([hidden])'):null;
        const panel=document.querySelector<HTMLElement>(`[data-tour-panel="${steps[step][0]}"]`);
        const el = dialogs[dialogs.length-1] ?? assistant ?? panel ?? [...document.querySelectorAll<HTMLElement>(`[data-tour="${steps[step][0]}"]`)].find(el=>el.getClientRects().length) ?? null;
        target.current = el;
        const r = el?.getBoundingClientRect();
        const next = r && r.width > 0 && r.height > 0 && r.bottom > 0 && r.top < innerHeight && r.right > 0 && r.left < innerWidth
          ? {top:Math.max(0,r.top-5), left:Math.max(0,r.left-5), right:Math.min(innerWidth,r.right+5), bottom:Math.min(innerHeight,r.bottom+5)} : null;
        setRect(previous => JSON.stringify(previous) === JSON.stringify(next) ? previous : next);
      });
    };
    const initialTarget=[...document.querySelectorAll<HTMLElement>(`[data-tour="${steps[step][0]}"]`)].find(el=>el.getClientRects().length) ?? null;
    initialTarget?.scrollIntoView({block:'center',behavior:'auto'});
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
    const focus = (event:FocusEvent) => {if (!allowed(event.target as Element)) card.current?.focus();};
    document.addEventListener('keydown',keydown,true);
    document.addEventListener('focusin',focus,true);
    return () => {document.removeEventListener('keydown',keydown,true); document.removeEventListener('focusin',focus,true);};
  },[active]);
  useEffect(()=>{if(!active)replay.current?.focus()},[active]);
  const stop = () => {setStep(null);};
  const exit = () => {if(demoOnlyBuild){location.assign('https://github.com/addsubmuldiv/infra-workbench');return;}const url = new URL(location.href); url.searchParams.delete('demo'); location.assign(url.href);};
  const cardWidth=Math.min(360,innerWidth-24);
  const side=rect&&(rect.right+cardWidth+24<innerWidth||rect.left>cardWidth+24);
  const cardLeft=rect ? rect.right+cardWidth+24<innerWidth ? rect.right+14 : rect.left>cardWidth+24 ? rect.left-cardWidth-14 : Math.max(12,Math.min(rect.left,innerWidth-cardWidth-12)) : Math.max(12,(innerWidth-cardWidth)/2);
  const maxCardTop=Math.max(12,innerHeight-cardHeight-12);
  const preferredTop=rect ? side ? rect.top : rect.bottom+cardHeight+24<innerHeight ? rect.bottom+14 : rect.top-cardHeight-14 : 90;
  const cardTop=Math.max(12,Math.min(preferredTop,maxCardTop));
  return <>
    <aside className="demo-bar" aria-label={t('演示模式','Demo mode')}>
      <span><strong>{t('演示模式','Demo mode')}</strong> · {t('所有数据均为模拟，不连接 SSH 或真实模型。','All data is simulated. No SSH or real model connections.')}</span>
      <div><button ref={replay} onClick={()=>{onStart?.();setStep(0)}}>{t('重播引导','Replay tour')}</button><button onClick={onFinishTraining}>{t('模拟训练结束','Finish demo training')}</button><button onClick={onReset}>{t('重置','Reset')}</button><button onClick={exit}>{t('退出演示','Exit demo')}</button></div>
    </aside>
    {step !== null && <div className="demo-tour">
      {rect ? <>
        <div className="demo-shade" style={{top:0,left:0,right:0,height:rect.top}} />
        <div className="demo-shade" style={{top:rect.top,left:0,width:rect.left,height:rect.bottom-rect.top}} />
        <div className="demo-shade" style={{top:rect.top,left:rect.right,right:0,height:rect.bottom-rect.top}} />
        <div className="demo-shade" style={{top:rect.bottom,left:0,right:0,bottom:0}} />
        <div className="demo-highlight" style={{top:rect.top,left:rect.left,width:rect.right-rect.left,height:rect.bottom-rect.top}} />
      </> : <div className="demo-shade" style={{inset:0}} />}
      <div className="demo-tour-card" ref={card} tabIndex={-1} role="dialog" aria-labelledby="demo-tour-title" aria-describedby="demo-tour-description" style={{top:cardTop,left:cardLeft}}>
        <small>{t('新手引导','Getting started')} · {step+1} / {steps.length}</small>
        <h2 id="demo-tour-title">{t(steps[step][1],steps[step][2])}</h2>
        <p id="demo-tour-description">{t(steps[step][3],steps[step][4])}</p>
        {steps[step][0]==='reservation'&&<button className="demo-tour-next" onClick={onFinishTraining}>{t('模拟训练结束','Finish demo training')}</button>}
        <p className="demo-tour-hint">{t('可先操作高亮区域，再继续。切换步骤会收起当前演示窗口，请先保存编辑内容。','Try the highlighted controls before continuing. Moving between steps closes demo windows; save edits first.')}</p>
        {!rect && <p role="status">{t('当前控件暂不可见，你可以继续下一步。','This control is currently unavailable. You can continue to the next step.')}</p>}
        <div className="demo-tour-actions"><button onClick={stop}>{t('跳过','Skip')}</button><span /><button disabled={step===0} onClick={()=>setStep(step-1)}>{t('上一步','Back')}</button><button className="demo-tour-next" onClick={()=>step===steps.length-1 ? stop() : setStep(step+1)}>{step===steps.length-1 ? t('完成','Done') : t('下一步','Next')}</button></div>
      </div>
    </div>}
  </>;
}
