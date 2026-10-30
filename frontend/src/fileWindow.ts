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
