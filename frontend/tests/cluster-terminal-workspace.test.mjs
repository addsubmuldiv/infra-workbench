import {test} from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import ts from 'typescript';
test('dedicated workspace never attaches a terminal until explicit interaction and then excludes it from broadcast',t=>{
 const values=[{id:'batch',items:[{id:'item',host_id:'host',target:'machine',session_id:'session',status:'created'}]},'item',[],['item']];let cursor=0;
 const react={createElement:(type,props,...children)=>({type,props:{...props,children}}),useEffect(){},useRef:value=>({current:value}),useState:initial=>{const index=cursor++;if(!(index in values))values[index]=initial;return [values[index],value=>{values[index]=typeof value==='function'?value(values[index]):value}]}};
 const original=Object.getOwnPropertyDescriptor(globalThis,'document');Object.defineProperty(globalThis,'document',{configurable:true,value:{body:{}}});t.after(()=>{if(original)Object.defineProperty(globalThis,'document',original);else delete globalThis.document});
 const source=fs.readFileSync(new URL('../src/ClusterTerminalWorkspace.tsx',import.meta.url),'utf8');const js=ts.transpileModule(source,{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022,jsx:ts.JsxEmit.React,esModuleInterop:true}}).outputText;
 const exports={};new Function('require','exports',js)(name=>({'react':react,'react-dom':{createPortal:node=>node,flushSync:fn=>fn()},'./i18n':{t:zh=>zh,useLocale(){}},'./TerminalDock':{TerminalView:'TerminalView'},'./clusterApi':{},'./AppConfirm':{useAppConfirm:()=>({confirmation:null,confirm:async()=>true})}}[name]??{}),exports);
 const render=()=>{cursor=0;return exports.ClusterTerminalWorkspace({cluster:null,hosts:[{id:'host',target:'machine',user:null}],close(){}})};
 const nodes=node=>!node||typeof node!=='object'?[]:[node,...(node.props?.children??[]).flat(Infinity).flatMap(nodes)];
 let tree=render();assert.equal(nodes(tree).some(n=>n.type==='TerminalView'),false);
 const target=()=>nodes(tree).find(n=>n.props?.['aria-label']==='广播目标 machine');assert.equal(target().props.checked,true);assert.equal(target().props.disabled,false);
 nodes(tree).find(n=>n.type==='button'&&n.props.children.includes('接入交互终端')).props.onClick();tree=render();
 assert.equal(nodes(tree).filter(n=>n.type==='TerminalView').length,1);assert.equal(target().props.checked,false);assert.equal(target().props.disabled,true);
});
