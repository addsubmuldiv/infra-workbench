import {test} from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import ts from 'typescript';
import {clusterGroups,selectionState} from '../../src/features/hosts/clusterApi.ts';
import {HOST_CATEGORIES,filterHosts} from '../../src/features/hosts/hostList.ts';
function harness(category='全部',alias,ssh_hostname,showHostAddresses=true,target='machine'){
 const values=[];let cursor=0;
 const react={createElement:(type,props,...children)=>({type,props:{...props,children}}),useEffect(){},useRef:current=>({current}),useState:initial=>{const i=cursor++;if(!(i in values))values[i]=typeof initial==='function'?initial():initial;return [values[i],next=>{values[i]=typeof next==='function'?next(values[i]):next}]}};
 const source=fs.readFileSync(new URL('../../src/features/hosts/ClusterSidebar.tsx',import.meta.url),'utf8');
 const js=ts.transpileModule(source,{compilerOptions:{module:ts.ModuleKind.CommonJS,jsx:ts.JsxEmit.React,esModuleInterop:true}}).outputText;
 const exports={};
 new Function('require','exports',js)(name=>({'react':react,'react-dom':{},'../../shared/i18n':{t:zh=>zh,useLocale(){}},'../../shared/OverlayScrollbar':{OverlayScrollbar:'OverlayScrollbar'},'./hostList':{HOST_CATEGORIES,filterHosts},'./clusterApi':{clusterGroups,selectionState},'../monitoring/hostUsage':{deviceUsage:()=>({occupied:0,idle:0,unknown:0,abnormal:0})},'../onboarding/demoBootstrap':{isDemo:true},'../../workspace/workspaceState':{workspaceStorage:{getItem:()=>null,setItem(){}}}}[name]??{}),exports);
 let selectionCalls=0;const copied=[];
 const props={hosts:[{id:'a',target,alias,ssh_hostname,snapshot:{fresh:false,status:'offline',devices:[]}}],selected:null,category,search:'',showHostAddresses,select(){selectionCalls++},copyName:name=>copied.push(name),setSearch:s=>{props.search=s},setCategory:c=>{props.category=c}};
 const render=()=>{cursor=0;return exports.ClusterSidebar(props)};
 return {render,copied,get selectionCalls(){return selectionCalls}};
}
const nodes=n=>!n||typeof n!=='object'?[]:[n,...(n.props?.children??[]).flat(Infinity).flatMap(nodes)];
test('the overlay scrollbar follows the machine list scroller',()=>{
 const list=nodes(harness().render()).find(n=>n.props.className==='cluster-list-scroll');
 const [scroller,scrollbar]=list.props.children;
 assert.equal(scroller.props.className,'host-picker-items');
 assert.equal(scrollbar.type,'OverlayScrollbar');
 assert.ok(scroller.props.ref);
 assert.equal(scrollbar.props.scrollRef,scroller.props.ref);
});
test('copy button uses the full displayed name without selecting a machine',()=>{
 for(const [alias,expected] of [[undefined,'machine'],['训练机器 A','训练机器 A']]){
  const h=harness('全部',alias);
  const button=nodes(h.render()).find(n=>n.type==='button'&&n.props['aria-label']===`复制机器名称 ${expected}`);
  assert.equal(button.props.type,'button');
  button.props.onClick();
  assert.deepEqual(h.copied,[expected]);
  assert.equal(h.selectionCalls,0);
 }
});
test('machine details stay available when the compact layout truncates the name',()=>{
 const alias='训练机器 A / Long display name';
 const h=harness('全部',alias);
 const machine=nodes(h.render()).find(n=>n.type==='button'&&n.props['aria-label']==='只看机器 machine');
 assert.equal(machine.props.title,`${alias}\nmachine\n离线`);
 assert.ok(nodes(machine).some(n=>n.props.className==='host-row-address'&&n.props.children.includes('machine')));
 assert.ok(nodes(machine).some(n=>n.props.className==='host-row-status'&&n.props.children.includes('离线')));
 assert.ok(!nodes(machine).some(n=>n.props.className==='host-usage'));
 machine.props.onClick();
 assert.equal(h.selectionCalls,1);
});
test('the list shows the configured SSH address for an imported alias and honors the display preference',()=>{
 const address='192.0.2.17';
 for(const [alias,visible] of [[undefined,true],['Training host',true],[undefined,false]]){
  const machine=nodes(harness('全部',alias,address,visible).render()).find(n=>n.props.className==='host-row-main');
  assert.equal(nodes(machine).find(n=>n.props.className==='host-row-address')?.props.children[0],visible?address:undefined);
  assert.equal(machine.props.title.includes(address),visible);
 }
 const direct=nodes(harness('全部',undefined,address,true,address).render());
 assert.ok(!direct.some(n=>n.props.className==='host-row-address'));
});
test('group name toggles members without changing machine selection',()=>{
 const h=harness();let tree=h.render();
 assert.equal(nodes(tree).filter(n=>n.props?.className?.startsWith('host-picker-row')).length,1);
 nodes(tree).find(n=>n.props?.className==='cluster-name').props.onClick();tree=h.render();
 assert.equal(nodes(tree).filter(n=>n.props?.className?.startsWith('host-picker-row')).length,0);
 assert.equal(h.selectionCalls,0);
 nodes(tree).find(n=>n.props?.className==='cluster-name').props.onClick();tree=h.render();
 assert.equal(nodes(tree).filter(n=>n.props?.className?.startsWith('host-picker-row')).length,1);
});
test('expanded filtered group explains empty results and category exposes pressed state',()=>{
 const h=harness('NPU');let tree=h.render();
 assert.ok(nodes(tree).some(n=>n.props?.className==='cluster-empty'));
 const filters=()=>nodes(tree).filter(n=>n.type==='button'&&n.props['aria-pressed']!==undefined);
 assert.equal(filters().find(n=>n.props['aria-pressed']).props.children[0],'NPU');
 nodes(tree).find(n=>n.type==='button'&&n.props.children.includes('显示全部成员')).props.onClick();tree=h.render();
 assert.equal(filters().find(n=>n.props['aria-pressed']).props.children[0],'全部');
 assert.ok(nodes(tree).some(n=>n.props?.className?.startsWith('host-picker-row')));
});

test('cluster menu uses the top layer and stays inside a short viewport',()=>{
 let opened=false;
 const panel={style:{},matches:()=>opened,showPopover(){opened=true},hidePopover(){opened=false},getBoundingClientRect:()=>({width:180,height:260})};
 const handlers={},effects=[];let refIndex=0;const triggerNode={contains:target=>target==='trigger',focus(){}};panel.contains=target=>target==='menu';
 const react={createElement:(type,props,...children)=>({type,props:{...props,children}}),useRef:()=>({current:refIndex++===0?panel:triggerNode}),useEffect:fn=>effects.push(fn)};
 const source=fs.readFileSync(new URL('../../src/features/hosts/ClusterSidebar.tsx',import.meta.url),'utf8');
 const js=ts.transpileModule(source,{compilerOptions:{module:ts.ModuleKind.CommonJS,jsx:ts.JsxEmit.React,esModuleInterop:true}}).outputText;
 const exports={};
 new Function('require','exports',js+';exports.Menu=ClusterMenu;')(name=>({'react':react,'../../shared/i18n':{t:zh=>zh}}[name]??{}),exports);
 const previous=globalThis.window,previousDocument=globalThis.document;globalThis.window={innerWidth:375,innerHeight:320,addEventListener(){},removeEventListener(){}};globalThis.document={addEventListener:(name,fn)=>{handlers[name]=fn},removeEventListener(){}};
 try{
  const tree=exports.Menu({children:[]}),items=nodes(tree);
  assert.equal(items.find(n=>n.props.popover).props.popover,'manual');
  effects.forEach(fn=>fn());
  const trigger=items.find(n=>n.type==='button');
  trigger.props.onClick({currentTarget:{getBoundingClientRect:()=>({right:360,bottom:290})}});
  assert.equal(opened,true);assert.equal(panel.style.left,'180px');assert.equal(panel.style.top,'52px');assert.equal(panel.style.maxHeight,'304px');
  handlers.pointerdown({target:'trigger'});assert.equal(opened,true);
  trigger.props.onClick({});assert.equal(opened,false);
  const reopen=()=>trigger.props.onClick({currentTarget:{getBoundingClientRect:()=>({right:360,bottom:290})}});
  reopen();handlers.pointerdown({target:'menu'});assert.equal(opened,true);
  handlers.pointerdown({target:'outside'});assert.equal(opened,false);
  reopen();handlers.click({target:'outside'});assert.equal(opened,false);
  reopen();handlers.keydown({key:'Escape'});assert.equal(opened,false);
  reopen();
  items.find(n=>n.props.popover).props.onClick({target:{closest:()=>({})}});
  assert.equal(opened,false);
 }finally{globalThis.window=previous;globalThis.document=previousDocument}
});
