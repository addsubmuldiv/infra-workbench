import {t,useLocale} from './i18n';
import {useWorkspaceRestore} from './workspaceHooks';
import {workspaceStorage} from './workspaceState';
import React,{useEffect,useRef,useState} from 'react';
import {DEFAULT_SIDEBAR_WIDTH,MIN_SIDEBAR_WIDTH,MOBILE_BREAKPOINT,fitSidebarWidth,loadSidebarWidth,saveSidebarWidth,sidebarMaximum} from './sidebarLayout';

function storage(){try{return workspaceStorage}catch{return null}}

export function WorkspaceLayout({children,onClickCapture,assistantWidth=0}:{children:React.ReactNode;onClickCapture?:React.MouseEventHandler<HTMLDivElement>;assistantWidth?:number}){
  useLocale();
  const [preferred,setPreferred]=useState(()=>loadSidebarWidth(storage()));
  useWorkspaceRestore('infra-workbench:sidebar-width:v1',()=>loadSidebarWidth(storage()),setPreferred);
  const [viewport,setViewport]=useState(()=>window.innerWidth),[dragging,setDragging]=useState(false);
  const gesture=useRef<{id:number;x:number;width:number}|null>(null),lastWidth=useRef(preferred);
  const maximum=Math.min(sidebarMaximum(viewport),Math.max(MIN_SIDEBAR_WIDTH,viewport-assistantWidth-420));
  const fit=(value:number)=>Math.min(fitSidebarWidth(value,window.innerWidth),maximum);
  const width=fit(preferred);
  useEffect(()=>{
    const resize=()=>{setViewport(window.innerWidth);gesture.current=null;setDragging(false)};
    window.addEventListener('resize',resize);return()=>window.removeEventListener('resize',resize);
  },[]);
  const commit=(value:number)=>{setPreferred(value);lastWidth.current=value;saveSidebarWidth(storage(),value)};
  const move=(event:React.PointerEvent)=>{
    const start=gesture.current;if(!start||event.pointerId!==start.id)return;
    const value=fit(start.width+event.clientX-start.x);
    lastWidth.current=value;setPreferred(value);
  };
  const finish=(event:React.PointerEvent)=>{
    if(!gesture.current||event.pointerId!==gesture.current.id)return;
    commit(lastWidth.current);gesture.current=null;setDragging(false);
    if(event.currentTarget.hasPointerCapture(event.pointerId))event.currentTarget.releasePointerCapture(event.pointerId);
  };
  return <div onClickCapture={onClickCapture} className={'shell'+(dragging?' resizing-sidebar':'')+(assistantWidth?' assistant-docked':'')} style={{'--sidebar-width':`${width}px`,'--assistant-width':`${assistantWidth}px`} as React.CSSProperties} data-sidebar-wide={width>=480}>
    {children}
    <div className="sidebar-resizer" role="separator" aria-label={t("调整左侧栏宽度","Resize sidebar")} aria-orientation="vertical" aria-valuemin={viewport<=MOBILE_BREAKPOINT?65:MIN_SIDEBAR_WIDTH} aria-valuemax={viewport<=MOBILE_BREAKPOINT?65:maximum} aria-valuenow={width} tabIndex={0}
      title={t("拖动调整左栏宽度；双击恢复默认；方向键微调","Drag to resize; double-click to reset; use arrow keys to adjust")}
      onPointerDown={event=>{
        if(event.button!==0)return;event.preventDefault();
        event.currentTarget.setPointerCapture(event.pointerId);
        gesture.current={id:event.pointerId,x:event.clientX,width};lastWidth.current=width;setDragging(true);
      }} onPointerMove={move} onPointerUp={event=>{move(event);finish(event)}} onPointerCancel={finish} onLostPointerCapture={finish}
      onDoubleClick={()=>commit(fit(DEFAULT_SIDEBAR_WIDTH))}
      onKeyDown={event=>{
        const step=event.shiftKey?50:20;
        const value=event.key==='ArrowLeft'?width-step:event.key==='ArrowRight'?width+step:event.key==='Home'?MIN_SIDEBAR_WIDTH:event.key==='End'?maximum:null;
        if(value!==null){event.preventDefault();commit(fit(value))}
      }}><span/></div>
  </div>;
}
