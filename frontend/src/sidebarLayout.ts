export const SIDEBAR_KEY='infra-workbench:sidebar-width:v1';
export const DEFAULT_SIDEBAR_WIDTH=258;
export const MIN_SIDEBAR_WIDTH=220;
export const MOBILE_BREAKPOINT=800;
export function sidebarMaximum(viewport:number){return Math.max(MIN_SIDEBAR_WIDTH,Math.min(720,viewport-480))}
export function fitSidebarWidth(width:number,viewport:number){
  if(viewport<=MOBILE_BREAKPOINT)return 65;
  return Math.round(Math.max(MIN_SIDEBAR_WIDTH,Math.min(sidebarMaximum(viewport),width)));
}
export function loadSidebarWidth(storage:Pick<Storage,'getItem'>|null):number{
  try{
    const value=JSON.parse(storage?.getItem(SIDEBAR_KEY)??'null');
    return typeof value==='number'&&Number.isFinite(value)&&value>=MIN_SIDEBAR_WIDTH&&value<=720?value:DEFAULT_SIDEBAR_WIDTH;
  }catch{return DEFAULT_SIDEBAR_WIDTH}
}
export function saveSidebarWidth(storage:Pick<Storage,'setItem'>|null,width:number){
  try{storage?.setItem(SIDEBAR_KEY,JSON.stringify(width))}catch{/* Resizing remains usable when browser storage is unavailable. */}
}
