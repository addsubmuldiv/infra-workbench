import {i18nMock} from './i18n-mock.mjs';
import {workspaceMock} from './workspace-mock.mjs';
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
import * as clusterApi from '../src/clusterApi.ts';
import * as ids from '../src/browserId.ts';
import * as assistantLayout from '../src/assistantLayout.ts';

const GiB=1024**3;
function host(id,kind,count,fresh=true){return {id,target:id,user:null,auth:'key',snapshot:{status:fresh?'online':'error',fresh,collected_at:1,devices:Array.from({length:count},(_,index)=>({id:String(index),kind,name:'Test device',memory_total:64*GiB,memory_used:8*GiB,memory_free:56*GiB,utilization:0,temperature:35,health:'OK',processes_known:true,processes:[]}))}}}
const hosts=[host('alpha','NPU',8),host('beta','GPU',4),host('offline','GPU',2,false)];
hosts[1].snapshot.devices.slice(1).forEach(d=>d.processes=[{pid:123,user:'test'}]);

function harness(t,hash='#overview',reservations=[],hostItems=hosts,demo=false){
  const values=[],storage=new Map(),cardRenders=new Map();let cursor=0,tree;
  const state={hosts:hostItems,rules:[],reservations,events:[],server_time:100};
  const react={memo:(fn,compare)=>{fn.testCompare=compare;return fn},createElement:(type,props,...children)=>{
    if(type?.name==='MachineView'){
      const previous=cardRenders.get(props.key);
      if(previous&&type.testCompare(previous.props,props))return previous.tree;
      const tree=type({...props,children});cardRenders.set(props.key,{props,tree,count:(previous?.count??0)+1});return tree;
    }
    return typeof type==='function'&&['ClusterSidebar','Check'].includes(type.name)?type({...props,children}):({type,props:{...props,children}})
  },lazy:()=>()=>null,Suspense:'suspense',StrictMode:'strict',
    useState:initial=>{const index=cursor++;if(!(index in values))values[index]=initial&&typeof initial==='object'&&Array.isArray(initial.hosts)&&'server_time' in initial?state:typeof initial==='function'?initial():initial;return [values[index],value=>{values[index]=typeof value==='function'?value(values[index]):value}]},
    useRef:initial=>{const index=cursor++;if(!(index in values))values[index]={current:initial};return values[index]},useMemo:fn=>fn(),useEffect(){}};
  for(const [name,value] of Object.entries({window:{localStorage:{getItem:key=>storage.get(key)??null,setItem:(key,value)=>storage.set(key,value)},scrollTo(){}},document:{documentElement:{dataset:{}},getElementById:()=>({})},location:{hash}})){
    const original=Object.getOwnPropertyDescriptor(globalThis,name);Object.defineProperty(globalThis,name,{configurable:true,writable:true,value});t.after(()=>{if(original)Object.defineProperty(globalThis,name,original);else delete globalThis[name]});
  }
  const source=fs.readFileSync(new URL('../src/main.tsx',import.meta.url),'utf8')+'\nexport {App};';
  const js=ts.transpileModule(source,{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022,jsx:ts.JsxEmit.React,esModuleInterop:true}}).outputText;
  const exports={};const mocks={'./clusterApi':clusterApi,'./i18n':{t:(zh)=>zh,useLocale(){}},'./demoBootstrap':{isDemo:demo},'react':react,'react-dom/client':{createRoot:()=>({render(){}})},'./preferences':{...preferences,browserStorage:()=>window.localStorage},'./navigation':navigation,'./notifications':notifications,'./requests':requests,'./hostUsage':usage,'./hostList':hostList,'./browserId':ids,'./assistantLayout':assistantLayout};
  const sidebarJs=ts.transpileModule(fs.readFileSync(new URL('../src/ClusterSidebar.tsx',import.meta.url),'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022,jsx:ts.JsxEmit.React,esModuleInterop:true}}).outputText;
  const sidebarExports={};new Function('require','exports',sidebarJs)(name=>workspaceMock(name,react)??(mocks[name]||new Proxy({},{get:(_,key)=>key})),sidebarExports);mocks['./ClusterSidebar']=sidebarExports;
  new Function('require','exports',js)(name=>workspaceMock(name,react)??(mocks[name]||new Proxy({},{get:(_,key)=>key})),exports);
  const nodes=node=>!node||typeof node!=='object'?[]:[node,...(node.props?.children||[]).flat(Infinity).flatMap(nodes)];
  const find=fn=>nodes(tree).find(fn);
  const text=node=>node==null||node===false?'':typeof node!=='object'?String(node):(node.props?.children||[]).flat(Infinity).map(text).join('');
  const render=()=>{cursor=0;tree=exports.App();return tree};
  const metrics=()=>find(n=>n.props?.['aria-label']==='全部机器资源总览').props.children.map(card=>text(card.props.children.find(n=>n?.type==='strong')));
  const button=label=>find(n=>n.type==='button'&&(n.props['aria-label']===label||n.props.children.includes(label)));
  const finderCount=()=>text(find(n=>n.props?.className==='match-count').props.children.find(n=>n?.type==='strong'));
  return {render,find,text,metrics,button,finderCount,cardRenders};
}

test('reservation summary excludes ready reservations and their machines but opens all reservations',t=>{
  const items=[{id:'a',host_id:'alpha',status:'waiting'},{id:'b',host_id:'alpha',status:'settling'},{id:'c',host_id:'beta',status:'ready'}];
  const h=harness(t,'#overview',items);h.render();
  const summary=()=>h.find(n=>n.props?.className==='reservation-stat');
  assert.ok(h.text(summary()).includes('2条'));
  assert.ok(h.text(summary()).includes('1 台机器 · 2 条等待中'));
  h.button('只看机器 alpha').props.onClick();h.render();
  assert.ok(h.text(summary()).includes('1 台机器 · 2 条等待中'));
  h.button('查看卡预约，2 条等待中').props.onClick();h.render();
  assert.equal(h.button('资源预约').props['aria-current'],'page');
  assert.deepEqual(h.find(n=>n.type==='Reservations').props.items,items);
});

test('overview remains global when selecting a different machine or clearing the detail selection',t=>{
  const h=harness(t);h.render();assert.deepEqual(h.metrics(),['2/ 3','14个设备','2台机器','0条']);
  h.button('只看机器 alpha').props.onClick();h.render();assert.deepEqual(h.metrics(),['2/ 3','14个设备','2台机器','0条']);assert.ok(h.find(n=>n.props?.['aria-label']==='机器详情 alpha'));assert.equal(h.find(n=>n.props?.['aria-label']==='机器详情 beta'),undefined);
  h.button('只看机器 beta').props.onClick();h.render();assert.deepEqual(h.metrics(),['2/ 3','14个设备','2台机器','0条']);assert.equal(h.find(n=>n.props?.['aria-label']==='机器详情 alpha'),undefined);assert.ok(h.find(n=>n.props?.['aria-label']==='机器详情 beta'));
  h.button('清空').props.onClick();h.render();assert.deepEqual(h.metrics(),['2/ 3','14个设备','2台机器','0条']);assert.equal(h.finderCount(),'2');
});

test('bulk deletion uses checked machines even when the sidebar category hides them',t=>{
  const h=harness(t);h.render();
  h.button('清空').props.onClick();h.render();
  assert.equal(h.button('删除机器').props.disabled,true);
  for(const name of ['alpha','beta']){h.find(n=>n.props?.['aria-label']==='显示机器 '+name).props.onChange();h.render()}
  h.button('只显示NPU机器').props.onClick();h.render();
  assert.equal(h.button('删除机器').props.disabled,false);
  h.button('删除机器').props.onClick();h.render();
  const dialog=h.find(n=>n.type==='RemoveHostDialog');
  assert.deepEqual(dialog.props.hosts.map(host=>host.id),['alpha','beta']);
  dialog.props.close();h.render();assert.equal(h.find(n=>n.type==='RemoveHostDialog'),undefined);
  assert.ok(h.find(n=>n.props?.['aria-label']==='机器详情 alpha'));
});

test('bulk collection changes only checked machines that need the requested state',async t=>{
  const items=[{...hosts[0]},{...hosts[1],collection:{paused:true}},{...hosts[2]}];
  const calls=[];
  t.mock.method(globalThis,'fetch',async (url,options)=>{
    if(url==='/api/state')return Response.json({hosts:items,rules:[],reservations:[],events:[],server_time:100});
    const id=url.split('/')[3];
    const {paused}=JSON.parse(options.body);
    calls.push([id,paused]);
    const index=items.findIndex(item=>item.id===id);
    items[index]={...items[index],collection:{paused}};
    return Response.json({host_id:id,paused});
  });
  const h=harness(t,'#overview',[],items);h.render();
  h.button('清空').props.onClick();h.render();
  assert.equal(h.button('批量暂停采集'),undefined);
  for(const name of ['alpha','beta']){h.find(n=>n.props?.['aria-label']==='显示机器 '+name).props.onChange();h.render()}

  await h.button('批量暂停采集').props.onClick();h.render();
  assert.deepEqual(calls,[['alpha',true]]);
  assert.equal(h.button('批量暂停采集').props.disabled,true);

  await h.button('批量恢复采集').props.onClick();h.render();
  assert.deepEqual(calls,[['alpha',true],['alpha',false],['beta',false]]);
  assert.equal(h.button('批量恢复采集').props.disabled,true);
});

test('bulk collection reports partial failures and keeps the successful changes visible',async t=>{
  const items=hosts.map(host=>({...host}));
  t.mock.method(globalThis,'fetch',async url=>{
    if(url==='/api/state')return Response.json({hosts:items,rules:[],reservations:[],events:[],server_time:100});
    if(url==='/api/hosts/beta/collection')return Response.json({detail:'Unavailable'},{status:503});
    const index=url==='/api/hosts/alpha/collection'?0:2;
    items[index]={...items[index],collection:{paused:true}};
    return Response.json({host_id:items[index].id,paused:true});
  });
  const h=harness(t,'#overview',[],items);h.render();
  await h.button('批量暂停采集').props.onClick();h.render();
  assert.match(h.text(h.find(n=>n.props?.className==='toast')),/已暂停 2 台机器.*失败 1 台.*beta/);
  assert.equal(h.text(h.button('批量暂停采集')),'批量暂停采集1');
  assert.equal(h.text(h.button('批量恢复采集')),'批量恢复采集2');
});

test('legacy connections page displays overview without a duplicate navigation entry',t=>{
  const h=harness(t,'#connections');h.render();
  assert.ok(h.button('算力总览'));assert.equal(h.button('机器连接'),undefined);
  assert.deepEqual(h.metrics(),['2/ 3','14个设备','2台机器','0条']);
});

test('header AI toggle sits beside notifications and never selects a second navigation page',t=>{
  const h=harness(t);h.render();
  for(const label of ['精度对比','资源预约','设置','算力总览']){
    h.button(label).props.onClick();h.render();
    const nav=h.find(n=>n.type==='nav');
    assert.ok(!h.text(nav).includes('AI 助手'));
    assert.equal(nav.props.children.flat(Infinity).filter(n=>n.props.className==='active').length,1);
    assert.equal(h.button(label).props['aria-current'],'page');
    assert.ok(h.find(n=>n.props.className==='header-panel-tools').props.children.includes(h.button('AI 助手')));
    assert.equal(h.button('AI 助手').props['aria-controls'],'infra-assistant-panel');
    assert.equal(h.button('AI 助手').props['aria-expanded'],true);
    h.button('AI 助手').props.onClick();h.render();
    assert.equal(h.button('AI 助手').props['aria-expanded'],false);
    assert.equal(h.button(label).props['aria-current'],'page');
    h.button('AI 助手').props.onClick();h.render();
    assert.equal(h.button('AI 助手').props['aria-expanded'],true);
    assert.equal(h.button(label).props['aria-current'],'page');
  }
});

test('machine names and checkboxes open overview from other workspace pages',t=>{
  const h=harness(t);h.render();
  for(const label of ['资源预约','精度对比','设置']){
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

test('finder defaults to all hosts independently of detail selection and supports selected scope',t=>{
  const h=harness(t);h.render();h.find(n=>n.props?.['aria-label']==='需要设备数').props.onChange({target:{value:'2'}});h.render();
  h.button('只看机器 beta').props.onClick();h.render();assert.equal(h.metrics()[2],'1台机器');assert.equal(h.finderCount(),'1');
  h.find(n=>n.props?.['aria-label']==='仅在所选机器中寻找').props.onChange({target:{checked:true}});h.render();assert.equal(h.finderCount(),'0');
  h.find(n=>n.props?.['aria-label']==='仅在所选机器中寻找').props.onChange({target:{checked:false}});h.render();
  h.button('查看匹配机器').props.onClick();h.render();
  assert.ok(h.find(n=>n.props?.['aria-label']==='机器详情 alpha'));assert.equal(h.find(n=>n.props?.['aria-label']==='机器详情 beta'),undefined);
});

test('overview shortcuts reset hidden sidebar filters and expose device groups',t=>{
  const h=harness(t);h.render();h.button('清空').props.onClick();h.render();
  h.find(n=>n.props?.['aria-label']==='搜索机器列表').props.onChange({target:{value:'missing'}});h.render();
  h.button('查看全部机器').props.onClick();h.render();
  assert.ok(h.button('只看机器 alpha'));assert.ok(h.find(n=>n.props?.['aria-label']==='机器详情 offline'));
  h.button('展开加速设备概览').props.onClick();h.render();
  assert.ok(h.find(n=>n.props?.['aria-label']==='加速设备分类概览'));
  h.button('查看 GPU Test device 对应机器').props.onClick();h.render();
  assert.ok(h.find(n=>n.props?.['aria-label']==='机器详情 beta'));assert.equal(h.find(n=>n.props?.['aria-label']==='机器详情 alpha'),undefined);
  h.button('查看全局符合条件的机器').props.onClick();h.render();
  assert.ok(h.find(n=>n.props?.['aria-label']==='机器详情 alpha'));assert.equal(h.find(n=>n.props?.['aria-label']==='机器详情 offline'),undefined);
});

test('resource type is independent of the device detail filter and empty results cannot clear selection',t=>{
  const h=harness(t);h.render();
  h.find(n=>n.props?.['aria-label']==='寻找设备类型').props.onChange({target:{value:'GPU'}});h.render();assert.equal(h.metrics()[2],'1台机器');
  h.find(n=>n.type==='button'&&n.props.children.includes('NPU')).props.onClick();h.render();assert.equal(h.metrics()[2],'1台机器');
  h.find(n=>n.props?.['aria-label']==='需要设备数').props.onChange({target:{value:'8'}});h.render();assert.equal(h.finderCount(),'0');assert.equal(h.button('查看匹配机器').props.disabled,true);
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


test('all-machines card toggles actual selection, including manually checked all hosts',t=>{
  const h=harness(t);h.render();h.button('清空').props.onClick();h.render();
  h.button('查看全部机器').props.onClick();h.render();
  assert.ok(h.find(n=>n.props?.['aria-label']==='机器详情 offline'));
  assert.equal(h.button('清空机器选择').props['aria-pressed'],true);
  h.button('清空机器选择').props.onClick();h.render();
  assert.equal(h.find(n=>n.props?.['aria-label']==='机器详情 alpha'),undefined);
  assert.equal(h.finderCount(),'2');
  for(const id of ['alpha','beta','offline']){h.find(n=>n.props?.['aria-label']==='显示机器 '+id).props.onChange();h.render()}
  assert.ok(h.button('清空机器选择'));
  h.button('清空机器选择').props.onClick();h.render();assert.equal(h.button('删除机器').props.disabled,true);
});

test('device overview closes on outside clicks and navigation but preserves clicks inside it and its toggle',t=>{
  const h=harness(t);h.render();
  const overview=()=>h.find(n=>n.props?.['aria-label']==='加速设备分类概览');
  const original=Object.getOwnPropertyDescriptor(globalThis,'Element');
  class Target{constructor(inside){this.inside=inside}closest(){return this.inside?{}:null}}
  Object.defineProperty(globalThis,'Element',{configurable:true,value:Target});
  t.after(()=>{if(original)Object.defineProperty(globalThis,'Element',original);else delete globalThis.Element});
  h.button('展开加速设备概览').props.onClick();h.render();assert.ok(overview());
  h.find(n=>n.type==='WorkspaceLayout').props.onClickCapture({target:new Target(true)});h.render();assert.ok(overview());
  h.find(n=>n.type==='WorkspaceLayout').props.onClickCapture({target:new Target(false)});h.render();assert.equal(overview(),undefined);
  h.button('展开加速设备概览').props.onClick();h.render();
  h.button('查看 GPU Test device 对应机器').props.onClick();h.render();assert.equal(overview(),undefined);
  h.button('展开加速设备概览').props.onClick();h.render();
  h.button('查看全局符合条件的机器').props.onClick();h.render();assert.equal(overview(),undefined);
});


test('SSH password button highlights only confirmed saved credentials and updates when removed',t=>{
  const items=hosts.map((host,index)=>({...host,ssh_password:{password_saved:[true,false,null][index],can_remember:true}}));
  const h=harness(t,'#overview',[],items);h.render();
  assert.ok(h.button('alpha SSH 密码设置').props.className.includes('enabled'));
  assert.equal(h.button('alpha SSH 密码设置').props.title,'SSH 密码已保存，点击管理');
  assert.ok(!h.button('beta SSH 密码设置').props.className.includes('enabled'));
  assert.ok(!h.button('offline SSH 密码设置').props.className.includes('enabled'));
  items[0]={...items[0],ssh_password:{...items[0].ssh_password,password_saved:false}};h.render();
  assert.ok(!h.button('alpha SSH 密码设置').props.className.includes('enabled'));
  h.button('alpha SSH 密码设置').props.onClick();h.render();
  assert.ok(h.find(n=>n.type==='SSHPasswordDialog'));
});


test('demo prevents entering real SSH credentials while leaving resource browsing usable',t=>{
 const h=harness(t,'#overview',[],hosts,true);h.render();
 h.button('alpha SSH 密码设置').props.onClick();h.render();
 assert.equal(h.find(n=>n.type==='SSHPasswordDialog'),undefined);
 h.button('alpha sudo 设置').props.onClick();h.render();
 assert.equal(h.find(n=>n.type==='SudoModal'),undefined);
 h.button('添加机器').props.onClick();h.render();
 assert.equal(h.find(n=>n.type==='AddMachine'),undefined);
 h.button('只看机器 beta').props.onClick();h.render();
 assert.ok(h.find(n=>n.props?.['aria-label']==='机器详情 beta'));
});


test('manual refresh reports progress, shares repeated clicks and reports collection failure',async t=>{
  const original=globalThis.fetch;let finish,calls=0;
  globalThis.fetch=async url=>{
    if(url.includes('/hosts/')){calls++;return new Promise(resolve=>{finish=()=>resolve({ok:true,json:async()=>({status:'error',error:'Synthetic probe failure'})})})}
    return {ok:true,json:async()=>({hosts,rules:[],reservations:[],events:[],server_time:100})};
  };
  t.after(()=>{globalThis.fetch=original});
  const h=harness(t);h.render();
  const first=h.button('刷新 alpha').props.onClick();
  h.button('刷新 alpha').props.onClick();h.render();
  assert.equal(calls,1);assert.equal(h.button('刷新 alpha').props.disabled,true);
  assert.ok(h.text(h.find(n=>n.props?.className==='collection-summary')).includes('正在刷新'));
  finish();await first;h.render();
  assert.equal(h.button('刷新 alpha').props.disabled,false);
  assert.ok(h.text(h.find(n=>n.props?.className==='collection-summary')).includes('手动刷新失败'));
});


test('machine selection rerenders only its own card and unrelated notice does not redraw cards',t=>{
  const h=harness(t);h.render();
  assert.equal(h.cardRenders.get('alpha').count,1);assert.equal(h.cardRenders.get('beta').count,1);
  h.find(n=>n.type==='input'&&n.props['aria-label']==='选择 alpha 设备 0').props.onChange();h.render();
  assert.equal(h.cardRenders.get('alpha').count,2);assert.equal(h.cardRenders.get('beta').count,1);
  h.render();assert.equal(h.cardRenders.get('alpha').count,2);assert.equal(h.cardRenders.get('beta').count,1);
});

test('manual completion expires and an old timer cannot clear a new refresh',async t=>{
  const originalFetch=globalThis.fetch,originalTimer=globalThis.setTimeout,originalClear=globalThis.clearTimeout;
  let timerId=0,finish;const timers=new Map();
  globalThis.setTimeout=(callback,delay)=>{const id=++timerId;timers.set(id,{callback,delay});return id};
  globalThis.clearTimeout=id=>timers.delete(id);
  globalThis.fetch=async url=>url.includes('/hosts/')?new Promise(resolve=>{finish=()=>resolve({ok:true,json:async()=>({status:'online'})})}):({ok:true,json:async()=>({hosts,rules:[],reservations:[],events:[],server_time:100})});
  t.after(()=>{globalThis.fetch=originalFetch;globalThis.setTimeout=originalTimer;globalThis.clearTimeout=originalClear});
  const h=harness(t);h.render();
  let request=h.button('刷新 alpha').props.onClick();finish();await request;h.render();
  const summary=()=>h.text(h.find(n=>n.props?.className==='collection-summary'));
  assert.ok(summary().includes('手动刷新已完成'));
  let timer=[...timers.values()].find(timer=>timer.delay===3000);assert.ok(timer);
  timer.callback();h.render();assert.ok(!summary().includes('手动刷新已完成'));
  request=h.button('刷新 alpha').props.onClick();finish();await request;h.render();
  const oldId=timerId;
  request=h.button('刷新 alpha').props.onClick();h.render();
  assert.ok(!timers.has(oldId));assert.ok(summary().includes('正在刷新'));
  finish();await request;
});

test('automatic collection timings stay inside a closed statistics disclosure',t=>{
  const items=[{...hosts[0],collection:{status:'collecting',duration_seconds:5.23,queue_seconds:0,response_bytes:5120,samples:2}}];
  const h=harness(t,'#overview',[],items);h.render();
  const panel=h.find(n=>n.props?.className==='collection-summary');
  const children=panel.props.children.flat(Infinity).filter(Boolean);
  const disclosures=children.filter(child=>child.type==='details');
  assert.equal(disclosures.length,1);
  assert.ok(!disclosures[0].props.open);
  assert.ok(h.text(disclosures[0]).includes('上次耗时'));
  assert.ok(!children.filter(child=>child.type!=='details').some(child=>h.text(child).includes('上次耗时')));
});
