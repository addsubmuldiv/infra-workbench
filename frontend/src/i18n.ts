import {useSyncExternalStore} from 'react';
import {workspaceStorage} from './workspaceState.ts';
import {createLocaleStore,localized,type Locale} from './localeStore.ts';
export type {Locale} from './localeStore.ts';
const store=createLocaleStore(workspaceStorage);
export const getLocale=store.getSnapshot;
export const setLocale=store.setLocale;
export function useLocale():Locale{return useSyncExternalStore(store.subscribe,store.getSnapshot,()=> 'zh')}
export function t(zh:string,en:string):string{return localized(getLocale(),zh,en)}
export function dateLocale():string{return getLocale()==='en'?'en-US':'zh-CN'}
export function initializeLocale(){
  const apply=()=>{document.documentElement.lang=getLocale()==='en'?'en':'zh-CN'};
  apply();return store.subscribe(apply);
}
