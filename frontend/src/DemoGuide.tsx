import {demoOnlyBuild} from './demoBootstrap';
import {useEffect, useRef, useState} from 'react';
import {t, useLocale} from './i18n';
import './demoGuide.css';

const steps = [
  ['hosts', '选择机器', 'Choose a machine', '机器列表提供了几台演示机器，点击名称可以查看资源。', 'Select a machine in the demo list to inspect its resources.'],
  ['finder', '筛选资源', 'Filter resources', '使用筛选条件，找到符合显存、状态等要求的设备。', 'Filter devices by memory, status, and other requirements.'],
  ['device', '查看进程', 'Inspect processes', '点击高亮按钮，查看这台设备上的模拟进程。关闭详情后可继续引导。', 'Open the highlighted button to inspect simulated processes. Close the details to continue the tour.'],
  ['reservation', '创建预约', 'Create a reservation', '使用预约按钮体验资源预约流程。这里的预约只用于演示。', 'Use the reservation button to try the booking flow. These bookings are for demonstration only.'],
  ['assistant', '询问 AI 助手', 'Ask the AI assistant', '打开助手，体验基于演示数据的回答，不会调用真实模型。', 'Open the assistant to try answers based on demo data, without calling a real model.'],
] as const;
const focusable = 'button:not([disabled]), a[href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';
type Rect = {top:number; left:number; right:number; bottom:number};

export function DemoGuide({onReset, onFinishTraining,onStart}: {onReset:()=>void; onFinishTraining:()=>void;onStart?:()=>void}) {
  useLocale();
  const [step, setStep] = useState<number|null>(0);
  const [rect, setRect] = useState<Rect|null>(null);
  const card = useRef<HTMLDivElement>(null);
  const target = useRef<HTMLElement|null>(null);
  const replay = useRef<HTMLButtonElement>(null);
  const active = step !== null;
  useEffect(()=>{onStart?.()},[]);
  useEffect(() => {
    if (step === null) {setRect(null); return;}
    let frame = 0;
    const measure = () => {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(() => {
        // Keep a detail/booking dialog operable when the highlighted control opens it.
        const dialogs = [...document.querySelectorAll<HTMLElement>('[role="dialog"], dialog[open]')].filter(el => !el.classList.contains('demo-tour-card') && el.getClientRects().length);
        const assistant=step===4?document.querySelector<HTMLElement>('#infra-assistant-panel:not([hidden])'):null;
        const el = dialogs[dialogs.length-1] ?? assistant ?? [...document.querySelectorAll<HTMLElement>(`[data-tour="${steps[step][0]}"]`)].find(el=>el.getClientRects().length) ?? null;
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
    observer.observe(document.body, {childList:true, subtree:true,attributes:true,attributeFilter:['hidden','open']});
    const resize = new ResizeObserver(measure);
    resize.observe(document.body);
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
  const cardTop=rect ? side ? Math.min(Math.max(12,rect.top),innerHeight-320) : rect.bottom+250<innerHeight ? rect.bottom+14 : Math.max(12,rect.top-250) : 90;
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
      <div className="demo-tour-card" ref={card} tabIndex={-1} role="dialog" aria-labelledby="demo-tour-title" aria-describedby="demo-tour-description" style={{top:Math.min(cardTop,Math.max(8,innerHeight-320)),left:cardLeft}}>
        <small>{t('新手引导','Getting started')} · {step+1} / {steps.length}</small>
        <h2 id="demo-tour-title">{t(steps[step][1],steps[step][2])}</h2>
        <p id="demo-tour-description">{t(steps[step][3],steps[step][4])}</p>
        {!rect && <p role="status">{t('当前控件暂不可见，你可以继续下一步。','This control is currently unavailable. You can continue to the next step.')}</p>}
        <div className="demo-tour-actions"><button onClick={stop}>{t('跳过','Skip')}</button><span /><button disabled={step===0} onClick={()=>setStep(step-1)}>{t('上一步','Back')}</button><button className="demo-tour-next" onClick={()=>step===steps.length-1 ? stop() : setStep(step+1)}>{step===steps.length-1 ? t('完成','Done') : t('下一步','Next')}</button></div>
      </div>
    </div>}
  </>;
}
