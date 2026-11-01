// Adapter doubles for focused component tests; persistence is tested separately.
export function workspaceMock(name,react){
 const disk=()=>globalThis.window?.localStorage??globalThis.localStorage;
 if(name==='./workspaceState')return {workspaceStorage:{getItem:key=>disk()?.getItem(key)??null,setItem:(key,value)=>disk()?.setItem(key,value),subscribe:()=>()=>{}},initializeWorkspace:()=>new Promise(()=>{})};
 if(name==='./workspaceHooks')return {useWorkspaceRestore(){},useWorkspaceValue:(_key,value)=>react.useState(value)};
}
