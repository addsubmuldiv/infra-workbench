import {test} from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import ts from 'typescript';
import * as preferences from '../src/preferences.ts';
import * as navigation from '../src/navigation.ts';
import * as notifications from '../src/notifications.ts';
import * as requests from '../src/requests.ts';
import * as usage from '../src/hostUsage.ts';
import * as hostList from '../src/hostList.ts';

const GiB=1024**3;
function host(id,kind,count,fresh=true){return {id,target:id,user:null,auth:'key',snapshot:{status:fresh?'online':'error',fresh,collected_at:1,devices:Array.from({length:count},(_,index)=>({id:String(index),kind,name:'Test device',memory_total:64*GiB,memory_used:8*GiB,memory_free:56*GiB,utilization:0,temperature:35,health:'OK',processes_known:true,processes:[]}))}}}
const hosts=[host('alpha','NPU',8),host('beta','GPU',4),host('offline','GPU',2,false)];
hosts[1].snapshot.devices.slice(1).forEach(d=>d.processes=[{pid:123,user:'test'}]);

function harness(t,hash='#overview'){
  const values=[],storage=new Map();let cursor=0,tree;
  const state={hosts,rules:[],reservations:[],events:[],server_time:100};
  const react={createElement:(type,props,...children)=>({type,props:{...props,children}}),lazy:()=>()=>null,Suspense:'suspense',StrictMode:'strict',
    useState:initial=>{const index=cursor++;if(!(index in values))values[index]=index===0?state:typeof initial==='function'?initial():initial;return [values[index],value=>{values[index]=typeof value==='function'?value(values[index]):value}]},
    useRef:initial=>{const index=cursor++;if(!(index in values))values[index]={current:initial};return values[index]},useEffect(){}};
  for(const [name,value] of Object.entries({window:{localStorage:{getItem:key=>storage.get(key)??null,setItem:(key,value)=>storage.set(key,value)},scrollTo(){}},document:{documentElement:{dataset:{}},getElementById:()=>({})},location:{hash}})){
    const original=Object.getOwnPropertyDescriptor(globalThis,name);Object.defineProperty(globalThis,name,{configurable:true,writable:true,value});t.after(()=>{if(original)Object.defineProperty(globalThis,name,original);else delete globalThis[name]});
  }
  const source=fs.readFileSync(new URL('../src/main.tsx',import.meta.url),'utf8')+'\nexport {App};';
  const js=ts.transpileModule(source,{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022,jsx:ts.JsxEmit.React,esModuleInterop:true}}).outputText;
  const exports={};const mocks={'react':react,'react-dom/client':{createRoot:()=>({render(){}})},'./preferences':preferences,'./navigation':navigation,'./notifications':notifications,'./requests':requests,'./hostUsage':usage,'./hostList':hostList};
  new Function('require','exports',js)(name=>mocks[name]||new Proxy({},{get:(_,key)=>key}),exports);
  const nodes=node=>!node||typeof node!=='object'?[]:[node,...(node.props?.children||[]).flat(Infinity).flatMap(nodes)];
  const find=fn=>nodes(tree).find(fn);
  const text=node=>node==null||node===false?'':typeof node!=='object'?String(node):(node.props?.children||[]).flat(Infinity).map(text).join('');
  const render=()=>{cursor=0;tree=exports.App();return tree};
  const metrics=()=>find(n=>n.props?.['aria-label']==='全部机器资源总览').props.children.map(card=>text(card.props.children.find(n=>n?.type==='strong')));
  const button=label=>find(n=>n.type==='button'&&(n.props['aria-label']===label||n.props.children.includes(label)));
  const finderCount=()=>text(find(n=>n.props?.className==='match-count').props.children.find(n=>n?.type==='strong'));
  return {render,find,text,metrics,button,finderCount};
}

test('overview remains global when selecting a different machine or clearing the detail selection',t=>{
  const h=harness(t);h.render();assert.deepEqual(h.metrics(),['2/ 3','14个设备','2台机器','0条']);
  h.button('只看机器 alpha').props.onClick();h.render();assert.deepEqual(h.metrics(),['2/ 3','14个设备','2台机器','0条']);assert.ok(h.find(n=>n.props?.['aria-label']==='机器详情 alpha'));assert.equal(h.find(n=>n.props?.['aria-label']==='机器详情 beta'),undefined);
  h.button('只看机器 beta').props.onClick();h.render();assert.deepEqual(h.metrics(),['2/ 3','14个设备','2台机器','0条']);assert.equal(h.find(n=>n.props?.['aria-label']==='机器详情 alpha'),undefined);assert.ok(h.find(n=>n.props?.['aria-label']==='机器详情 beta'));
  h.button('清空').props.onClick();h.render();assert.deepEqual(h.metrics(),['2/ 3','14个设备','2台机器','0条']);assert.equal(h.finderCount(),'0');
});

test('legacy connections page displays overview without a duplicate navigation entry',t=>{
  const h=harness(t,'#connections');h.render();
  assert.ok(h.button('算力总览'));assert.equal(h.button('机器连接'),undefined);
  assert.deepEqual(h.metrics(),['2/ 3','14个设备','2台机器','0条']);
});

test('machine names and checkboxes open overview from other workspace pages',t=>{
  const h=harness(t);h.render();
  for(const label of ['卡预约','精度对比','设置']){
    h.button(label).props.onClick();h.render();
    h.button('只看机器 beta').props.onClick();h.render();
    assert.equal(h.button('算力总览').props['aria-current'],'page');
    assert.ok(h.find(n=>n.props?.['aria-label']==='机器详情 beta'));
    h.button(label).props.onClick();h.render();
    h.find(n=>n.props?.['aria-label']==='显示机器 alpha').props.onChange();h.render();
    assert.equal(h.button('算力总览').props['aria-current'],'page');
    assert.ok(h.find(n=>n.props?.['aria-label']==='机器详情 alpha'));
  }
});

test('monitoring moves into the notification center without a separate navigation page',t=>{
  const h=harness(t);h.render();
  assert.equal(h.button('资源监控'),undefined);
  const center=h.find(n=>n.type==='NotificationCenter');assert.ok(center);
  center.props.setTab('messages');h.render();assert.equal(h.find(n=>n.type==='NotificationCenter').props.tab,'messages');
  assert.equal(h.button('算力总览').props['aria-current'],'page');
});

test('legacy monitoring links open the notification center on overview',t=>{
  const h=harness(t,'#watch');h.render();
  assert.equal(h.button('算力总览').props['aria-current'],'page');
  assert.equal(h.find(n=>n.type==='NotificationCenter').props.tab,'messages');
});

test('global condition matching and the selected-machine finder use their own scopes',t=>{
  const h=harness(t);h.render();h.find(n=>n.props?.['aria-label']==='需要设备数').props.onChange({target:{value:'2'}});h.render();
  h.button('只看机器 beta').props.onClick();h.render();assert.equal(h.metrics()[2],'1台机器');assert.equal(h.finderCount(),'0');
  h.button('只看机器 alpha').props.onClick();h.render();assert.equal(h.metrics()[2],'1台机器');assert.equal(h.finderCount(),'1');
});

test('machine categories filter the sidebar without clearing selected machines and combine with search',t=>{
  const h=harness(t);h.render();h.button('只看机器 alpha').props.onClick();h.render();
  h.button('只显示GPU机器').props.onClick();h.render();
  assert.equal(h.button('只看机器 alpha'),undefined);assert.ok(h.button('只看机器 beta'));assert.ok(h.button('只看机器 offline'));
  assert.ok(h.find(n=>n.props?.['aria-label']==='机器详情 alpha'),'detail selection survives switching list category');
  h.find(n=>n.props?.['aria-label']==='搜索机器列表').props.onChange({target:{value:'ALPHA'}});h.render();
  assert.equal(h.button('只看机器 beta'),undefined);
  h.button('只显示NPU机器').props.onClick();h.render();
  assert.ok(h.button('只看机器 alpha'));assert.equal(h.find(n=>n.props?.['aria-label']==='显示机器 alpha').props.checked,true);
  assert.equal(h.button('只看机器 beta'),undefined);
});
