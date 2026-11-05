import {t} from './i18n.ts';
export function formatBytes(value:number):string{
  for(const [unit,size] of [['GiB',1024**3],['MiB',1024**2],['KiB',1024]] as const)if(value>=size&&value%size===0)return `${value/size} ${unit}`;
  return `${value} B`;
}
export function capacityError(zh:string,en:string){return t(zh,en)}
