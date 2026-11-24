import {workspaceStorage} from './workspaceState.ts';
export const THEMES = [
  {id:'daylight',name:'晴空',mode:'light',description:'浅灰与蓝绿'},
  {id:'paper',name:'暖纸',mode:'light',description:'米白与暖棕'},
  {id:'midnight',name:'午夜',mode:'dark',description:'深蓝与薄荷绿'},
  {id:'graphite',name:'石墨',mode:'dark',description:'炭灰与浅紫'},
  {id:'coast-sunset',name:'海岸落日',mode:'dark',description:'GTA VI 风格的紫粉、珊瑚粉与杏金暮光'},
  {id:'frieren',name:'花语旅途',mode:'light',description:'芙莉莲 × 菲伦 · 浅绿与淡紫'},
  {id:'glass-light',name:'玻璃亮色',mode:'light',description:'冷蓝与淡紫光带'},
  {id:'glass-dark',name:'玻璃暗色',mode:'dark',description:'深蓝与烟紫光带'},
  {id:'glass-jade',name:'玻璃青岚',mode:'light',description:'青绿与浅金光带'},
  {id:'glass-dusk',name:'玻璃暮霞',mode:'dark',description:'暮紫与玫瑰光带'},
  {id:'glass-white',name:'玻璃纯白',mode:'light',description:'纯白背景'},
  {id:'glass-black',name:'玻璃纯黑',mode:'dark',description:'纯黑背景'},
] as const;
export type Theme = typeof THEMES[number]['id'];
export type Preferences = {theme:Theme;hostIds:string[]|null};
type StorageReader = Pick<Storage,'getItem'> | null;
type StorageWriter = Pick<Storage,'setItem'> | null;
const KEY='infra-workbench:preferences:v1';
const defaults:Preferences={theme:'daylight',hostIds:null};
export function browserStorage(){try{return workspaceStorage}catch{return null}}
export function loadPreferences(storage:StorageReader):Preferences{
  try{
    const value=JSON.parse(storage?.getItem(KEY)??'null');
    if(!value||!THEMES.some(t=>t.id===value.theme)||!(value.hostIds===null||(Array.isArray(value.hostIds)&&value.hostIds.every((v:unknown)=>typeof v==='string'))))return {...defaults};
    return {theme:value.theme,hostIds:value.hostIds===null?null:[...new Set<string>(value.hostIds)]};
  }catch{return {...defaults}}
}
export function savePreferences(storage:StorageWriter,value:Preferences):boolean{
  try{if(!storage)return false;storage.setItem(KEY,JSON.stringify({theme:value.theme,hostIds:value.hostIds}));return true}catch{return false}
}
export function scopedHosts<T extends {id:string}>(hosts:T[],ids:string[]|null):T[]{return ids===null?hosts:hosts.filter(h=>ids.includes(h.id))}
export function toggleHost(ids:string[]|null,id:string,all:string[]):string[]{
  const current=ids===null?all:ids;
  return current.includes(id)?current.filter(v=>v!==id):[...current,id];
}
