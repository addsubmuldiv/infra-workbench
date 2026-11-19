import {test} from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import ts from 'typescript';

const nodes=n=>!n||typeof n!=='object'?[]:[n,...(n.props?.children??[]).flat(Infinity).flatMap(nodes)];
const flush=()=>new Promise(resolve=>setImmediate(resolve));

test('tunnel manager keeps disconnected machines and connects a saved rule directly',async()=>{
 const proxy={name:'Proxy',direction:'remote',local_port:7890,remote_port:18899,connected_at:null};
 const hosts=[
  {id:'new',target:'New',snapshot:{fresh:true}},
  {id:'never',target:'Never connected',snapshot:{fresh:true}},
  {id:'offline',target:'Offline',snapshot:{fresh:false}},
  {id:'history',target:'Previously connected',snapshot:{fresh:false}},
  {id:'active',target:'Connected',snapshot:{fresh:false}},
  {id:'legacy',target:'Legacy',snapshot:{fresh:false}},
 ];
 const stored={
  new:[],
  never:[{...proxy,id:'saved',status:'error',has_connected:false}],
  legacy:[{...proxy,id:'old',status:'stopped'}],
  offline:[],
  history:[{...proxy,id:'forward/1',status:'error',has_connected:true}],
  active:[{...proxy,id:'live',status:'connected',connected_at:1,has_connected:true},
          {...proxy,id:'backoff',status:'reconnecting',has_connected:true}],
 };
 const states=[Object.fromEntries(Object.entries(stored).map(([id,rules])=>[id,{rules}])),[],false,true];
 let cursor=0;
 const calls=[];
 const react={
  createElement:(type,props,...children)=>({type,props:{...props,children}}),
  useEffect(){},useId:()=> 'title',useCallback:fn=>fn,useRef:value=>({current:value}),
  useState:initial=>{
   const i=cursor++;
   if(!(i in states))states[i]=initial;
   return [states[i],value=>{states[i]=typeof value==='function'?value(states[i]):value}];
  },
 };
 const tunnelRequest=async(host,path='',method='GET')=>{
  calls.push({host,path,method});
  if(!path)return stored[host];
  const [,encodedId,action]=path.split('/');
  const id=decodeURIComponent(encodedId);
  const rule=stored[host].find(item=>item.id===id);
  Object.assign(rule,action==='start'?{status:'connected',connected_at:1,has_connected:true}:{status:'stopped',connected_at:null});
  return {...rule};
 };
 const SSHTunnelPanel=()=>{};
 const source=fs.readFileSync(new URL('../src/TunnelManager.tsx',import.meta.url),'utf8');
 const js=ts.transpileModule(source,{compilerOptions:{module:ts.ModuleKind.CommonJS,jsx:ts.JsxEmit.React,esModuleInterop:true}}).outputText;
 const exports={};
 new Function('require','exports','document',js)(name=>({
  react,'react-dom':{createPortal:n=>n},'./i18n':{t:zh=>zh,useLocale(){}},
  './SSHTunnelPanel':{SSHTunnelPanel,tunnelRequest,tunnelStatusText:status=>status},
 }[name]??{}),exports,{body:{}});
 const render=()=>{cursor=0;return exports.TunnelManager({hosts,close(){}})};
 const machine=(tree,name)=>nodes(tree).find(n=>n.type==='article'&&nodes(n).some(h=>h.type==='h3'&&h.props.children.includes(name)));
 const button=(tree,label)=>nodes(tree).find(n=>n.type==='button'&&n.props.children.includes(label));
 const order=tree=>nodes(tree).filter(n=>n.type==='h3').map(n=>n.props.children[0]);

 let tree=render();
 assert.deepEqual(order(tree),['Connected','Previously connected','Legacy','New','Never connected']);
 assert.ok(button(machine(tree,'New'),'配置隧道'));
 assert.ok(button(machine(tree,'Never connected'),'连接'));
 button(machine(tree,'Previously connected'),'重连').props.onClick();
 await flush();
 assert.deepEqual(calls.filter(c=>c.method==='POST'),[{host:'history',path:'/forward%2F1/start',method:'POST'}]);

 tree=render();
 assert.deepEqual(order(tree),['Previously connected','Connected','Legacy','New','Never connected']);
 button(tree,'断开全部运行中隧道').props.onClick();
 await flush();
 assert.deepEqual(calls.filter(c=>c.method==='POST').slice(1),[
  {host:'history',path:'/forward%2F1/stop',method:'POST'},
  {host:'active',path:'/live/stop',method:'POST'},
  {host:'active',path:'/backoff/stop',method:'POST'},
 ]);
 tree=render();
 assert.deepEqual(order(tree),['Previously connected','Connected','Legacy','New','Never connected']);
 const manageButtons=nodes(machine(tree,'Connected')).filter(n=>n.type==='button'&&n.props.children.includes('管理'));
 manageButtons[1].props.onClick();
 const detail=render();
 assert.equal(detail.type,SSHTunnelPanel);
 assert.equal(detail.props.initialRuleId,'backoff');
});
