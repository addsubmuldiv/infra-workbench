import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import ts from 'typescript';
import * as input from '../src/terminalInput.ts';

function harness(t,standalone,items){
 const state=[],refs=[],effects=[],restores=[],events=new Map(),sent=[];let slot=0,refSlot=0;
 const assistant={contains:()=>true};
 const react={createElement:(type,props,...children)=>({type,props:{...props,children}}),useState:initial=>{const i=slot++;if(!(i in state))state[i]=initial;return [state[i],v=>{state[i]=v}]},useRef:value=>{const i=refSlot++;return refs[i]??(refs[i]={current:value})},useEffect:fn=>{if(!effects.length)effects.push(fn)}};
 const doc={addEventListener:(name,fn)=>events.set(name,fn),removeEventListener:()=>{}};
 const win={getSelection:()=>({anchorNode:{},focusNode:{},toString:()=> 'echo hello\n',rangeCount:1,getRangeAt:()=>({getBoundingClientRect:()=>({left:20,bottom:30})})}),addEventListener:(name,fn)=>events.set(name,fn),removeEventListener:()=>{},dispatchEvent:event=>{if(event.type===input.TERMINAL_TARGETS_EVENT)event.detail(items);if(event.type===input.TERMINAL_INPUT_EVENT){sent.push(event.detail);event.detail.reply('')}},__TAURI_INTERNALS__:standalone?{invoke:async(action,args)=>{if(args.action==='list-terminal-targets')return items;if(args.action==='send-terminal-input')sent.push(args.input)}}:undefined};
 for(const [key,value] of Object.entries({window:win,document:doc,location:{search:standalone?'?tool=assistant&channel=fixture':''},innerWidth:1200,innerHeight:800,CustomEvent:class{constructor(type,options){this.type=type;this.detail=options.detail}}})){const prior=Object.getOwnPropertyDescriptor(globalThis,key);Object.defineProperty(globalThis,key,{configurable:true,value});restores.push(()=>{if(prior)Object.defineProperty(globalThis,key,prior);else delete globalThis[key]})}
 const js=ts.transpileModule(fs.readFileSync(new URL('../src/TerminalInsert.tsx',import.meta.url),'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,jsx:ts.JsxEmit.React,esModuleInterop:true}}).outputText;
 const exports={};new Function('require','exports',js)(name=>name==='react'?react:name==='./terminalInput'?input:name==='./i18n'?{t:zh=>zh}:{},exports);
 const render=()=>{slot=0;refSlot=0;const tree=exports.TerminalInsert();refs[0].current={closest:()=>assistant,contains:()=>false};return tree};
 const nodes=tree=>!tree||typeof tree!=='object'?[]:[tree,...(tree.props?.children||[]).flat(Infinity).flatMap(nodes)];
 render();const cleanup=effects[0]();t.after(()=>{cleanup();restores.forEach(fn=>fn())});
 events.get('mouseup')();
 const click=async predicate=>{const node=nodes(render()).find(predicate);assert.ok(node);node.props.onClick();await new Promise(resolve=>setImmediate(resolve));};
 return {sent,render,nodes,click};
}
const target=(id,phase='running')=>({terminal_id:id,label:'machine-'+id,number:'01',cwd:'/home/test',phase});
test('workbench requires a target choice even with one terminal and inserts without Enter',async t=>{
 const h=harness(t,false,[target('a')]);
 await h.click(n=>n.props?.className==='terminal-insert-trigger');assert.equal(h.sent.length,0);
 await h.click(n=>n.type==='button'&&n.props.children?.[0]?.type==='strong');
 assert.equal(h.sent[0].terminal_id,'a');assert.equal(h.sent[0].text,'echo hello');
});
test('standalone inserts directly only when its paired terminal has one connected tab',async t=>{
 const h=harness(t,true,[target('solo')]);await h.click(n=>n.props?.className==='terminal-insert-trigger');
 assert.equal(h.sent.length,1);assert.equal(h.sent[0].terminal_id,'solo');assert.equal(h.sent[0].text,'echo hello');
});
test('multiple paired tabs require a choice and disconnected tabs are disabled',async t=>{
 const h=harness(t,true,[target('a'),target('b','closed')]);await h.click(n=>n.props?.className==='terminal-insert-trigger');
 assert.equal(h.sent.length,0);const buttons=h.nodes(h.render()).filter(n=>n.type==='button');assert.ok(buttons.some(n=>n.props.disabled===true));
});
test('choosing a different tab routes text to that exact tab',async t=>{
 const h=harness(t,true,[target('a'),target('b')]);await h.click(n=>n.props?.className==='terminal-insert-trigger');
 await h.click(n=>n.type==='button'&&n.props.children?.[0]?.props?.children?.includes('machine-b'));
 assert.equal(h.sent.length,1);assert.equal(h.sent[0].terminal_id,'b');assert.equal(h.sent[0].text,'echo hello');
});
