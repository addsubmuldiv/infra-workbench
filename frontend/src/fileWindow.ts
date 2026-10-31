export type WindowFrame={x:number;y:number;width:number;height:number};
export type Viewport={width:number;height:number};
export function fitFileWindow(frame:WindowFrame,viewport:Viewport):WindowFrame{
  const margin=8,availableWidth=Math.max(1,viewport.width-margin*2),availableHeight=Math.max(1,viewport.height-margin*2);
  const width=Math.min(availableWidth,Math.max(400,frame.width)),height=Math.min(availableHeight,Math.max(260,frame.height));
  return {width,height,x:Math.max(margin,Math.min(frame.x,viewport.width-width-margin)),y:Math.max(margin,Math.min(frame.y,viewport.height-height-margin))};
}
export function moveFileWindow(frame:WindowFrame,dx:number,dy:number,viewport:Viewport,minimized=false):WindowFrame{
  const width=minimized?Math.min(320,viewport.width-16):frame.width,height=minimized?56:frame.height;
  return {...frame,x:Math.max(8,Math.min(frame.x+dx,viewport.width-width-8)),y:Math.max(8,Math.min(frame.y+dy,viewport.height-height-8))};
}
export function resizeFileWindow(frame:WindowFrame,edge:string,dx:number,dy:number,viewport:Viewport):WindowFrame{
  const next={...frame},minWidth=Math.min(400,viewport.width-16),minHeight=Math.min(260,viewport.height-16);
  const clamp=(n:number,min:number,max:number)=>Math.max(min,Math.min(max,n));
  if(edge.includes('e'))next.width=clamp(frame.width+dx,minWidth,viewport.width-frame.x-8);
  if(edge.includes('s'))next.height=clamp(frame.height+dy,minHeight,viewport.height-frame.y-8);
  if(edge.includes('w')){next.x=clamp(frame.x+dx,8,frame.x+frame.width-minWidth);next.width=frame.x+frame.width-next.x}
  if(edge.includes('n')){next.y=clamp(frame.y+dy,8,frame.y+frame.height-minHeight);next.height=frame.y+frame.height-next.y}
  return fitFileWindow(next,viewport);
}
