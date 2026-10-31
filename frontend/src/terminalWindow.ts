export type TerminalFrame={x:number;y:number;width:number;height:number};
export type TerminalViewport={width:number;height:number};
export const TERMINAL_FRAME_KEY='infra-workbench:terminal-frame:v1';
const clamp=(n:number,min:number,max:number)=>Math.max(min,Math.min(max,n));
export function fitTerminalFrame(frame:TerminalFrame,viewport:TerminalViewport):TerminalFrame{
  const availableWidth=Math.max(1,viewport.width-24),availableHeight=Math.max(1,viewport.height-24);
  const width=clamp(frame.width,Math.min(520,availableWidth),availableWidth),height=clamp(frame.height,Math.min(280,availableHeight),availableHeight);
  return {width,height,x:clamp(frame.x,12,viewport.width-width-12),y:clamp(frame.y,12,viewport.height-height-12)};
}
export function moveTerminalFrame(frame:TerminalFrame,dx:number,dy:number,viewport:TerminalViewport){return fitTerminalFrame({...frame,x:frame.x+dx,y:frame.y+dy},viewport)}
export function resizeTerminalFrame(frame:TerminalFrame,edge:string,dx:number,dy:number,viewport:TerminalViewport):TerminalFrame{
  const next={...frame},minWidth=Math.min(520,viewport.width-24),minHeight=Math.min(280,viewport.height-24);
  if(edge.includes('e'))next.width=clamp(frame.width+dx,minWidth,viewport.width-frame.x-12);
  if(edge.includes('s'))next.height=clamp(frame.height+dy,minHeight,viewport.height-frame.y-12);
  if(edge.includes('w')){next.x=clamp(frame.x+dx,12,frame.x+frame.width-minWidth);next.width=frame.x+frame.width-next.x}
  if(edge.includes('n')){next.y=clamp(frame.y+dy,12,frame.y+frame.height-minHeight);next.height=frame.y+frame.height-next.y}
  return fitTerminalFrame(next,viewport);
}
export function loadTerminalFrame(storage:Pick<Storage,'getItem'>|null,viewport:TerminalViewport):TerminalFrame{
  const width=Math.min(1100,viewport.width-290),height=Math.min(480,viewport.height-100);
  const fallback={x:viewport.width-width-16,y:viewport.height-height-16,width,height};
  try{
    const value=JSON.parse(storage?.getItem(TERMINAL_FRAME_KEY)??'null');
    if(value&&['x','y','width','height'].every(key=>typeof value[key]==='number'&&Number.isFinite(value[key])))return fitTerminalFrame(value,viewport);
  }catch{}
  return fitTerminalFrame(fallback,viewport);
}
export function terminalFrameStyle(frame:TerminalFrame,viewport:TerminalViewport,collapsed:boolean,maximized:boolean){
  if(collapsed)return {left:'auto',top:'auto',right:16,bottom:16,width:Math.min(264,viewport.width-32),height:62};
  const visible=maximized?{x:12,y:12,width:viewport.width-24,height:viewport.height-24}:fitTerminalFrame(frame,viewport);
  return {left:visible.x,top:visible.y,width:visible.width,height:visible.height,right:'auto',bottom:'auto'};
}
