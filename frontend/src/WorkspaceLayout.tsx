import React,{useEffect,useRef,useState} from 'react';
import {DEFAULT_SIDEBAR_WIDTH,MIN_SIDEBAR_WIDTH,MOBILE_BREAKPOINT,fitSidebarWidth,loadSidebarWidth,saveSidebarWidth,sidebarMaximum} from './sidebarLayout';

function storage(){try{return window.localStorage}catch{return null}}

export function WorkspaceLayout({children}:{children:React.ReactNode}){
  const [preferred,setPreferred]=useState(()=>loadSidebarWidth(storage()));
  const [viewport,setViewport]=useState(()=>window.innerWidth),[dragging,setDragging]=useState(false);
  const gesture=useRef<{id:number;x:number;width:number}|null>(null),lastWidth=useRef(preferred);
  const width=fitSidebarWidth(preferred,viewport),maximum=sidebarMaximum(viewport);
  useEffect(()=>{
    const resize=()=>{setViewport(window.innerWidth);gesture.current=null;setDragging(false)};
    window.addEventListener('resize',resize);return()=>window.removeEventListener('resize',resize);
  },[]);
  const commit=(value:number)=>{setPreferred(value);lastWidth.current=value;saveSidebarWidth(storage(),value)};
  const move=(event:React.PointerEvent)=>{
    const start=gesture.current;if(!start||event.pointerId!==start.id)return;
    const value=fitSidebarWidth(start.width+event.clientX-start.x,window.innerWidth);
    lastWidth.current=value;setPreferred(value);
  };
  const finish=(event:React.PointerEvent)=>{
    if(!gesture.current||event.pointerId!==gesture.current.id)return;
    commit(lastWidth.current);gesture.current=null;setDragging(false);
    if(event.currentTarget.hasPointerCapture(event.pointerId))event.currentTarget.releasePointerCapture(event.pointerId);
  };
  return <div className={'shell'+(dragging?' resizing-sidebar':'')} style={{'--sidebar-width':`${width}px`} as React.CSSProperties} data-sidebar-wide={width>=480}>
    {children}
    <div className="sidebar-resizer" role="separator" aria-label="调整左侧栏宽度" aria-orientation="vertical" aria-valuemin={viewport<=MOBILE_BREAKPOINT?65:MIN_SIDEBAR_WIDTH} aria-valuemax={viewport<=MOBILE_BREAKPOINT?65:maximum} aria-valuenow={width} tabIndex={0}
      title="拖动调整左栏宽度；双击恢复默认；方向键微调"
      onPointerDown={event=>{
        if(event.button!==0)return;event.preventDefault();
        event.currentTarget.setPointerCapture(event.pointerId);
        gesture.current={id:event.pointerId,x:event.clientX,width};lastWidth.current=width;setDragging(true);
      }} onPointerMove={move} onPointerUp={event=>{move(event);finish(event)}} onPointerCancel={finish} onLostPointerCapture={finish}
      onDoubleClick={()=>commit(fitSidebarWidth(DEFAULT_SIDEBAR_WIDTH,window.innerWidth))}
      onKeyDown={event=>{
        const step=event.shiftKey?50:20;
        const value=event.key==='ArrowLeft'?width-step:event.key==='ArrowRight'?width+step:event.key==='Home'?MIN_SIDEBAR_WIDTH:event.key==='End'?maximum:null;
        if(value!==null){event.preventDefault();commit(fitSidebarWidth(value,window.innerWidth))}
      }}><span/></div>
  </div>;
}
