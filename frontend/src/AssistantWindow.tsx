import {ui} from './assistantLocale';
import {useWorkspaceRestore} from './workspaceHooks';
import {workspaceStorage} from './workspaceState';
import React,{useEffect,useRef,useState} from 'react';
import {ChevronDown,GripHorizontal,PanelRightClose,PanelRightOpen,PanelsTopLeft,Sparkles} from 'lucide-react';
import {InfraAssistant} from './InfraAssistantPage';
import {fitFileWindow,moveFileWindow,resizeFileWindow,type WindowFrame} from './fileWindow';
import {fitAssistantDockWidth,loadAssistantLayout,saveAssistantLayout,type AssistantLayout} from './assistantLayout';
import {activateFloatingWindow,registerFloatingWindow} from './windowLayers';
import './assistantWindow.css';

const viewport=()=>({width:window.document?.documentElement.clientWidth||window.innerWidth,height:window.innerHeight});
const fitFrame=(frame:WindowFrame,size:ReturnType<typeof viewport>)=>fitFileWindow({...frame,height:Math.max(520,frame.height)},size);
function storage(){try{return workspaceStorage}catch{return null}}
type Props={open:boolean;onClose:()=>void;onDockWidthChange:(width:number)=>void;selectedHostIds:string[];locate:(hostId:string,devices:string[])=>void;openTerminal:(hostId:string)=>void;openSettings:()=>void};
type Gesture={id:number;kind:string;x:number;y:number;layout:AssistantLayout;frame:WindowFrame;moved:boolean;dock:boolean};

export function AssistantWindow({open,onClose,onDockWidthChange,...assistantProps}:Props){
  const [size,setSize]=useState(viewport);
  const [layout,setLayout]=useState(()=>{const value=loadAssistantLayout(storage(),viewport());return {...value,frame:fitFrame(value.frame,viewport())}});
  useWorkspaceRestore('infra-workbench:assistant-window:v1',()=>loadAssistantLayout(storage(),viewport()),setLayout);
  const [preview,setPreview]=useState(false),[dragging,setDragging]=useState(false);
  const current=useRef(layout),gesture=useRef<Gesture|null>(null),element=useRef<HTMLElement>(null);
  current.current=layout;
  const update=(next:AssistantLayout)=>{current.current=next;setLayout(next)};
  const persist=(next:AssistantLayout)=>{update(next);saveAssistantLayout(storage(),next)};
  const dockWidth=fitAssistantDockWidth(layout.dockWidth,size.width),floating=layout.mode==='floating';
  useEffect(()=>{
    const resize=()=>{setSize(viewport());gesture.current=null;setPreview(false);setDragging(false);update({...current.current,frame:fitFrame(current.current.frame,viewport())})};
    window.addEventListener('resize',resize);return()=>window.removeEventListener('resize',resize);
  },[]);
  useEffect(()=>{onDockWidthChange(open&&!floating&&size.width>=1100?dockWidth:0)},[open,floating,dockWidth,size.width,onDockWidthChange]);
  useEffect(()=>()=>onDockWidthChange(0),[onDockWidthChange]);
  useEffect(()=>{if(open&&floating)registerFloatingWindow(element.current);else element.current?.style.removeProperty('z-index')},[open,floating]);
  const detach=()=>persist({...current.current,mode:'floating',frame:fitFrame(current.current.frame,viewport())});
  const dock=()=>{setPreview(false);persist({...current.current,mode:'docked'})};
  const start=(event:React.PointerEvent,kind:string)=>{
    if(event.button!==0||gesture.current)return;
    if(kind==='move'&&(event.target as HTMLElement).closest('button,input,select,a'))return;
    event.preventDefault();event.currentTarget.setPointerCapture(event.pointerId);
    let frame=current.current.frame;
    if(kind==='move'&&current.current.mode==='docked'){
      const width=Math.max(440,dockWidth),left=element.current?.getBoundingClientRect().left??size.width-dockWidth;
      frame=fitFrame({x:event.clientX-Math.min(event.clientX-left,width-60),y:event.clientY-24,width,height:Math.min(740,size.height-32)},viewport());
    }
    gesture.current={id:event.pointerId,kind,x:event.clientX,y:event.clientY,layout:current.current,frame,moved:false,dock:false};
  };
  const move=(event:React.PointerEvent)=>{
    const g=gesture.current;if(!g||g.id!==event.pointerId)return;
    const dx=event.clientX-g.x,dy=event.clientY-g.y;
    if(!g.moved&&Math.hypot(dx,dy)<6)return;
    g.moved=true;setDragging(true);
    if(g.kind==='dock-width')update({...g.layout,dockWidth:fitAssistantDockWidth(g.layout.dockWidth-dx,size.width)});
    else if(g.kind==='move'){
      g.dock=event.clientX>=size.width-36;setPreview(g.dock);
      update({...current.current,mode:'floating',frame:moveFileWindow(g.frame,dx,dy,viewport())});
    }else update({...current.current,frame:fitFrame(resizeFileWindow(g.frame,g.kind,dx,dy,viewport()),viewport())});
  };
  const finish=(event:React.PointerEvent,cancelled=false)=>{
    const g=gesture.current;if(!g||g.id!==event.pointerId)return;
    if(!cancelled)move(event);
    gesture.current=null;setDragging(false);setPreview(false);
    if(g.moved)persist({...current.current,mode:!cancelled&&g.kind==='move'&&g.dock?'docked':current.current.mode});
    if(event.currentTarget.hasPointerCapture(event.pointerId))event.currentTarget.releasePointerCapture(event.pointerId);
  };
  const frame=fitFrame(layout.frame,size);
  const dimensions=floating?{left:frame.x,top:frame.y,width:frame.width,height:frame.height}:{right:0,top:0,width:dockWidth,height:'100dvh'};
  return <section id="infra-assistant-panel" ref={element} hidden={!open} className={'assistant-window '+layout.mode+(preview?' dock-preview':'')+(dragging?' dragging':'')} style={dimensions}
    role={floating?'dialog':'complementary'} aria-label={ui("AI 助手窗口")} aria-modal={floating?false:undefined} data-floating-window={open&&floating?'assistant':undefined}
    onPointerDownCapture={floating?activateFloatingWindow:undefined} onFocusCapture={floating?activateFloatingWindow:undefined}
    onPointerMove={move} onPointerUp={event=>finish(event)} onPointerCancel={event=>finish(event,true)} onLostPointerCapture={event=>finish(event,true)}>
    <header className="assistant-window-header" onPointerDown={event=>start(event,'move')}>
      <div className="assistant-window-title" tabIndex={0} aria-label={ui("移动 AI 助手窗口，拖动标题栏或使用方向键")} onKeyDown={event=>{
        if(event.target!==event.currentTarget)return;
        const offset:Record<string,[number,number]>={ArrowLeft:[-20,0],ArrowRight:[20,0],ArrowUp:[0,-20],ArrowDown:[0,20]};
        if(offset[event.key]){event.preventDefault();persist({...current.current,mode:'floating',frame:moveFileWindow(current.current.frame,...offset[event.key],viewport())})}
      }}><span className="assistant-window-icon"><Sparkles size={17}/></span><div><strong>{ui("AI 助手")}</strong><small>{floating?ui("悬浮窗口"):ui("右侧停靠")}</small></div><GripHorizontal size={15} className="assistant-window-grip"/></div>
      <div className="assistant-window-actions"><button className="icon-button" aria-label={floating?ui("停靠到右侧"):ui("悬浮 AI 助手")} title={floating?ui("停靠到右侧"):ui("切换为悬浮窗口，也可以拖动标题栏")} onClick={floating?dock:detach}>{floating?<PanelRightClose size={16}/>:<PanelsTopLeft size={16}/>}</button><button className="icon-button" aria-label={ui("收起 AI 助手")} title={ui("收起助手，保留对话和输入")} onClick={onClose}><ChevronDown size={17}/></button></div>
    </header>
    <div className="assistant-window-content"><InfraAssistant {...assistantProps} compact/></div>
    {floating?['n','s','e','w','ne','nw','se','sw'].map(edge=><div key={edge} className={'file-edge-resize edge-'+edge} role={edge==='se'?'separator':undefined} aria-label={edge==='se'?ui("调整助手窗口大小"):undefined} tabIndex={edge==='se'?0:undefined} onPointerDown={event=>start(event,edge)} onKeyDown={event=>{
      const offset:Record<string,[number,number]>={ArrowLeft:[-20,0],ArrowRight:[20,0],ArrowUp:[0,-20],ArrowDown:[0,20]};
      if(offset[event.key]){event.preventDefault();persist({...current.current,frame:fitFrame(resizeFileWindow(current.current.frame,'se',...offset[event.key],viewport()),viewport())})}
    }}/>):<div className="assistant-dock-resizer" role="separator" aria-label={ui("调整助手侧栏宽度")} aria-orientation="vertical" aria-valuemin={Math.min(320,size.width-16)} aria-valuemax={Math.min(640,size.width-16)} aria-valuenow={dockWidth} tabIndex={0} onPointerDown={event=>start(event,'dock-width')} onDoubleClick={()=>persist({...current.current,dockWidth:420})} onKeyDown={event=>{
      if(event.key==='ArrowLeft'||event.key==='ArrowRight'){event.preventDefault();persist({...current.current,dockWidth:fitAssistantDockWidth(dockWidth+(event.key==='ArrowLeft'?20:-20),size.width)})}
    }}/>}
    {preview&&<div className="assistant-dock-hint"><PanelRightOpen size={16}/>{ui("松开后停靠到右侧")}</div>}
  </section>;
}
