import {test} from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import ts from 'typescript';
import {clusterGroups,selectionState} from '../src/clusterApi.ts';
import {HOST_CATEGORIES,filterHosts} from '../src/hostList.ts';
function harness(category='全部'){
 const values=[];let cursor=0;
 const react={createElement:(type,props,...children)=>({type,props:{...props,children}}),useEffect(){},useState:initial=>{const i=cursor++;if(!(i in values))values[i]=typeof initial==='function'?initial():initial;return [values[i],next=>{values[i]=typeof next==='function'?next(values[i]):next}]}};
 const source=fs.readFileSync(new URL('../src/ClusterSidebar.tsx',import.meta.url),'utf8');
 const js=ts.transpileModule(source,{compilerOptions:{module:ts.ModuleKind.CommonJS,jsx:ts.JsxEmit.React,esModuleInterop:true}}).outputText;
 const exports={};
 new Function('require','exports',js)(name=>({'react':react,'react-dom':{},'./i18n':{t:zh=>zh,useLocale(){}},'./hostList':{HOST_CATEGORIES,filterHosts},'./clusterApi':{clusterGroups,selectionState},'./hostUsage':{deviceUsage:()=>({occupied:0,idle:0,unknown:0,abnormal:0})},'./demoBootstrap':{isDemo:true},'./workspaceState':{workspaceStorage:{getItem:()=>null,setItem(){}}}}[name]??{}),exports);
 let selectionCalls=0;
 const props={hosts:[{id:'a',target:'machine',snapshot:{fresh:false,status:'offline',devices:[]}}],selected:null,category,search:'',select(){selectionCalls++},setSearch:s=>{props.search=s},setCategory:c=>{props.category=c}};
 const render=()=>{cursor=0;return exports.ClusterSidebar(props)};
 return {render,get selectionCalls(){return selectionCalls}};
}
const nodes=n=>!n||typeof n!=='object'?[]:[n,...(n.props?.children??[]).flat(Infinity).flatMap(nodes)];
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
 const source=fs.readFileSync(new URL('../src/ClusterSidebar.tsx',import.meta.url),'utf8');
 const js=ts.transpileModule(source,{compilerOptions:{module:ts.ModuleKind.CommonJS,jsx:ts.JsxEmit.React,esModuleInterop:true}}).outputText;
 const exports={};
 new Function('require','exports',js+';exports.Menu=ClusterMenu;')(name=>({'react':react,'./i18n':{t:zh=>zh}}[name]??{}),exports);
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
