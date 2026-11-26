export type Locale='zh'|'en';
export const LOCALE_KEY='workspace:locale';
type Storage={getItem:(key:string)=>string|null;setItem:(key:string,value:string)=>void;subscribe:(key:string,listener:()=>void)=>()=>void};
export function readLocale(value:string|null):Locale{return value==='en'?'en':'zh'}
export function createLocaleStore(storage:Storage){
  return {
    getSnapshot:()=>readLocale(storage.getItem(LOCALE_KEY)),
    subscribe:(listener:()=>void)=>storage.subscribe(LOCALE_KEY,listener),
    setLocale:(locale:Locale)=>{if(locale!=='zh'&&locale!=='en')throw new Error('Unsupported locale');storage.setItem(LOCALE_KEY,locale)},
  };
}
export function localized(locale:Locale,zh:string,en:string):string{return locale==='en'?en:zh}
