import {ui} from './assistantLocale.ts';

/** Resolve presentation dictionaries at access time so changing language stays reactive. */
export function localizedLabels<T extends Record<string,string>>(labels:T):T {
 return new Proxy(labels,{get(target,key,receiver){const value=Reflect.get(target,key,receiver);return typeof value==='string'?ui(value):value;}});
}
