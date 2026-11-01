import {workspaceStorage} from './workspaceState.ts';
export const THEMES = [
  {id:'daylight',name:'晴空',mode:'light',description:'浅灰与蓝绿',swatches:['#f3f6fa','#ffffff','#177b70']},
  {id:'paper',name:'暖纸',mode:'light',description:'米白与暖棕',swatches:['#f5f1e9','#fffdf7','#8d6840']},
  {id:'midnight',name:'午夜',mode:'dark',description:'深蓝与薄荷绿',swatches:['#111b28','#1c2939','#78ddbd']},
  {id:'graphite',name:'石墨',mode:'dark',description:'炭灰与浅紫',swatches:['#202024','#2b2b31','#c1afff']},
  {id:'frieren',name:'花语旅途',mode:'light',description:'芙莉莲 × 菲伦 · 浅绿与淡紫',swatches:['#f3f5ee','#faf8ff','#758669']},
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
