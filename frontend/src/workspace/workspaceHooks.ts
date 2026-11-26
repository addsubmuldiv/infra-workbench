import {useEffect,useRef,useState,type Dispatch,type SetStateAction} from 'react';
import {workspaceStorage} from './workspaceState.ts';
export function useWorkspaceRestore<T>(key:string,read:()=>T,set:Dispatch<SetStateAction<T>>){
 const remote=useRef(false);
 const latest=useRef({read,set});latest.current={read,set};
 useEffect(()=>workspaceStorage.subscribe(key,()=>{remote.current=true;latest.current.set(latest.current.read())}),[key]);
 return remote;
}
export function useWorkspaceValue<T>(key:string,fallback:T):[T,Dispatch<SetStateAction<T>>]{
 const read=()=>{try{const raw=workspaceStorage.getItem(key);if(raw===null)return fallback;const parsed=JSON.parse(raw);return parsed!==null&&typeof parsed===typeof fallback&&Array.isArray(parsed)===Array.isArray(fallback)?parsed as T:fallback}catch{return fallback}};
 const [value,setValue]=useState<T>(read);
 useEffect(()=>{if(workspaceStorage.getItem(key)===null)workspaceStorage.setItem(key,JSON.stringify(value))},[key]);
 useWorkspaceRestore(key,read,setValue);
 const current=useRef(value);current.current=value;
 const update:Dispatch<SetStateAction<T>>=next=>{
  const result=typeof next==='function'?(next as (value:T)=>T)(current.current):next;
  current.current=result;setValue(result);workspaceStorage.setItem(key,JSON.stringify(result));
 };
 return [value,update];
}
