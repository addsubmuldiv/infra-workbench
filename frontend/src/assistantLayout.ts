import type {WindowFrame,Viewport} from './fileWindow';

export const ASSISTANT_WINDOW_KEY='infra-workbench:assistant-window:v1';
export const ASSISTANT_OPEN_KEY='infra-workbench:assistant-open:v1';
export type AssistantLayout={mode:'docked'|'floating';dockWidth:number;frame:WindowFrame};
export function fitAssistantDockWidth(width:number,viewportWidth:number){
  return Math.min(Math.max(1,viewportWidth-16),Math.max(320,Math.min(640,width)));
}
export function loadAssistantLayout(storage:Pick<Storage,'getItem'>|null,viewport:Viewport):AssistantLayout{
  const fallback:AssistantLayout={mode:'docked',dockWidth:420,frame:{x:viewport.width-500,y:40,width:480,height:Math.min(740,viewport.height-80)}};
  try{
    const value=JSON.parse(storage?.getItem(ASSISTANT_WINDOW_KEY)??'null');
    if(value&&['docked','floating'].includes(value.mode)&&typeof value.dockWidth==='number'&&Number.isFinite(value.dockWidth)&&value.frame&&['x','y','width','height'].every(key=>typeof value.frame[key]==='number'&&Number.isFinite(value.frame[key])))return {mode:value.mode,dockWidth:fitAssistantDockWidth(value.dockWidth,viewport.width),frame:{...value.frame}};
  }catch{}
  return fallback;
}
export function saveAssistantLayout(storage:Pick<Storage,'setItem'>|null,layout:AssistantLayout){
  try{storage?.setItem(ASSISTANT_WINDOW_KEY,JSON.stringify(layout))}catch{}
}
export function loadAssistantOpen(storage:Pick<Storage,'getItem'>|null){
  try{return storage?.getItem(ASSISTANT_OPEN_KEY)!=='false'}catch{return true}
}
