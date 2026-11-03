// Adapter doubles for focused component tests; persistence is tested separately.
import {i18nMock} from './i18n-mock.mjs';
export function workspaceMock(name,react){
 const localized=i18nMock(name);if(localized)return localized;
 const disk=()=>globalThis.window?.localStorage??globalThis.localStorage;
 if(name==='./workspaceState')return {workspaceStorage:{getItem:key=>disk()?.getItem(key)??null,setItem:(key,value)=>disk()?.setItem(key,value),subscribe:()=>()=>{}},initializeWorkspace:()=>new Promise(()=>{})};
 if(name==='./workspaceHooks')return {useWorkspaceRestore(){},useWorkspaceValue:(_key,value)=>react.useState(value)};
}
