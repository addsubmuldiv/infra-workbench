import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import ts from 'typescript';
import * as api from '../src/agentChat.ts';
import * as skills from '../src/skills.ts';
const chat=(id,run='run1')=>({id:id.repeat(32),title:id,created:1,updated:2,active_run:run,turns:[{id:'t-'+id,role:'assistant',content:'开始',created:2,status:run?'running':'completed'}]});
const tick=()=>new Promise(resolve=>setImmediate(resolve));
function harness(t){
  const values=[],deps=[],effects=[],cleanups=[],streams=[],writes=[],requests=[];let slot=0,tree;
  const view={scrollTop:0,scrollHeight:1000,clientHeight:400};
  const useEffect=(fn,next)=>{const i=slot++;if(!deps[i]||next.some((v,j)=>v!==deps[i][j])){effects.push(()=>{cleanups[i]?.();cleanups[i]=fn()});deps[i]=next}};
  const react={createElement:(type,props,...children)=>({type,props:{...props,children}}),useEffect,useLayoutEffect:useEffect,
    useState:initial=>{const i=slot++;if(!(i in values))values[i]=initial;return [values[i],value=>{values[i]=typeof value==='function'?value(values[i]):value}]},
    useRef:initial=>{const i=slot++;if(!(i in values))values[i]={current:initial};return values[i]}};
  const previous={fetch:globalThis.fetch,window:globalThis.window,storage:Object.getOwnPropertyDescriptor(globalThis,'localStorage')};
  globalThis.window=new EventTarget();
  Object.defineProperty(globalThis,'localStorage',{configurable:true,value:{getItem:()=>null,setItem:(key,value)=>writes.push([key,value])}});
  globalThis.fetch=async(url,options)=>{
    requests.push({url,method:options?.method});
    if(url==='/api/skills')return Response.json({items:[]});
    if(url.endsWith('/events')){let source;const body=new ReadableStream({start(controller){source=controller}});streams.push({id:url.split('/').at(-2),source,signal:options.signal});return new Response(body,{headers:{'Content-Type':'text/event-stream'}})}
    if(url==='/api/assistant/chats')return Response.json({items:[chat('a'),chat('b',null)]});
    return Response.json(chat(url.endsWith('b'.repeat(32))?'b':'a',url.endsWith('b'.repeat(32))?null:'run1'));
  };
  const js=ts.transpileModule(fs.readFileSync(new URL('../src/AssistantChat.tsx',import.meta.url),'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,jsx:ts.JsxEmit.React,esModuleInterop:true}}).outputText;
  const exports={};new Function('require','exports',js)(name=>name==='react'?react:name==='./workspaceState'?{workspaceStorage:{subscribe:()=>()=>{}}}:name==='./workspaceHooks'?{useWorkspaceValue:(_key,value)=>react.useState(value)}:name==='./agentChat'?{...api,loadChatId:()=>null,saveChatId:id=>writes.push(['iwb-assistant-chat',id])}:name==='./skills'?skills:name==='./AppConfirm'?{useAppConfirm:()=>({confirm:async()=>true,confirmation:null})}:{},exports);
  const nodes=node=>!node||typeof node!=='object'?[]:[node,...(node.props?.children||[]).flat(Infinity).flatMap(nodes)];
  const find=predicate=>nodes(tree).find(predicate);
  const render=()=>{slot=0;tree=exports.AssistantChat({configured:true,selectedHostIds:[]});const node=find(n=>n.props.className==='chat-transcript');node.props.ref.current=view;for(const effect of effects.splice(0))effect();return tree};
  const unmount=()=>cleanups.splice(0).forEach(fn=>fn?.());
  t.after(()=>{unmount();globalThis.fetch=previous.fetch;globalThis.window=previous.window;if(previous.storage)Object.defineProperty(globalThis,'localStorage',previous.storage);else delete globalThis.localStorage});
  const publish=async(content,updated)=>{const data={chat_id:'a'.repeat(32),title:'a',updated,active_run:'run1',turn:{id:'t-a',role:'assistant',content,created:2,status:'running'}};streams[0].source.enqueue(new TextEncoder().encode(`event: turn\ndata: ${JSON.stringify(data)}\n\n`));await tick();render()};
  return {render,find,view,streams,writes,requests,publish,unmount,async loaded(){render();await tick();render();await tick();render()},text:()=>nodes(tree).filter(n=>n.props.className?.startsWith('chat-message-text')).flatMap(n=>nodes(n).flatMap(child=>child.props?.children||[])).filter(value=>typeof value==='string').join('')};
}

test('streamed content remains visible, persists only ID changes and follows only a near-bottom transcript',async t=>{
  const h=harness(t);await h.loaded();assert.equal(h.streams.length,1);assert.equal(h.writes.length,1);
  h.view.scrollHeight=1200;await h.publish('真实的第一段',3);assert.equal(h.text(),'真实的第一段');assert.equal(h.view.scrollTop,1200);assert.equal(h.writes.length,1);
  h.view.scrollTop=100;h.find(n=>n.props.className==='chat-transcript').props.onScroll();h.view.scrollHeight=1500;
  await h.publish('真实的第一段，继续输出',4);assert.equal(h.text(),'真实的第一段，继续输出');assert.equal(h.view.scrollTop,100);assert.equal(h.writes.length,1);
  h.view.scrollTop=1100;h.find(n=>n.props.className==='chat-transcript').props.onScroll();h.view.scrollHeight=1600;await h.publish('又一段',5);assert.equal(h.view.scrollTop,1600);
});

test('switching chats aborts its subscription without cancelling server work and unmount aborts the active read',async t=>{
  const h=harness(t);await h.loaded();const old=h.streams[0];
  await h.find(n=>Array.isArray(n.props.items)&&typeof n.props.onChange==='function').props.onChange('b'.repeat(32));h.render();await tick();h.render();
  assert.equal(old.signal.aborted,true);assert.equal(h.text(),'开始');assert.equal(h.streams.length,1);assert.equal(h.writes.at(-1)[1],'b'.repeat(32));
  await h.find(n=>Array.isArray(n.props.items)&&typeof n.props.onChange==='function').props.onChange('a'.repeat(32));h.render();await tick();h.render();assert.equal(h.streams.length,2);
  h.unmount();assert.equal(h.streams[1].signal.aborted,true);assert.equal(h.requests.some(request=>request.url.endsWith('/cancel')),false);
});
