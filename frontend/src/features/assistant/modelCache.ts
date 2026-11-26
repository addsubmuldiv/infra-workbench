export const MODEL_CACHE_TTL=14*24*60*60*1000;
type ModelList={models:string[];truncated:boolean};
type CacheStorage=Pick<Storage,'getItem'|'setItem'>;
export function modelCacheKey(config:{active_id:string;base_url:string;protocol:string}){
  return 'infra-workbench:model-list:v1:'+JSON.stringify([config.active_id,config.base_url.trim(),config.protocol]);
}
export function readModelCache(key:string,storage?:CacheStorage,now=Date.now()):(ModelList&{stale:boolean})|null{
  try{
    const value=JSON.parse((storage??localStorage).getItem(key)||'null');
    if(!value||!Array.isArray(value.models)||!value.models.every((item:unknown)=>typeof item==='string')||typeof value.truncated!=='boolean'||!Number.isFinite(value.updated))return null;
    return {models:value.models,truncated:value.truncated,stale:now-value.updated>=MODEL_CACHE_TTL||now<value.updated};
  }catch{return null}
}
export function writeModelCache(key:string,list:ModelList,storage?:CacheStorage,now=Date.now()){
  try{(storage??localStorage).setItem(key,JSON.stringify({models:list.models,truncated:list.truncated,updated:now}))}catch{/* Storage may be unavailable or full. */}
}
