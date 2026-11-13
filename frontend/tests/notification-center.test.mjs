import {workspaceMock} from './workspace-mock.mjs';
import {test} from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import ts from 'typescript';
import * as notifications from '../src/notifications.ts';

function harness(t,storage=new Map()){
  let tree,cursor=0,values=[];
  const actions=[],events=[{id:3,host:'a',message:'a：预约设备可用',created:100,url:'#overview?host=a&device=1'},{id:2,host:'a',message:'a：SSH 连接失败',created:99}];
  const props={events,rules:[{id:'rule-a',host_id:'a',devices:['1'],minimum_gib:16,port:29500,status:'active'}],hosts:[{id:'a',target:'atlas'}],tab:null,notify:false,busy:false,
    setTab:tab=>props.tab=tab,toggleNotifications:async()=>{props.notify=!props.notify;actions.push(props.notify?'enable':'disable')},removeRule:id=>actions.push(['remove',id]),locate:event=>actions.push(['locate',event])};
  const react={createElement:(type,props,...children)=>({type,props:{...props,children}}),useEffect(){},
    useState:initial=>{const i=cursor++;if(!(i in values))values[i]=typeof initial==='function'?initial():initial;return [values[i],value=>values[i]=typeof value==='function'?value(values[i]):value]},
    useRef:initial=>{const i=cursor++;if(!(i in values))values[i]={current:initial};return values[i]}};
  const store={getItem:key=>storage.get(key)??null,setItem:(key,value)=>storage.set(key,value)};
  const source=fs.readFileSync(new URL('../src/NotificationCenter.tsx',import.meta.url),'utf8');
  const js=ts.transpileModule(source,{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022,jsx:ts.JsxEmit.React,esModuleInterop:true}}).outputText;
  const mocks={'react':react,'./preferences':{browserStorage:()=>store},'./notifications':notifications};const exports={};
  new Function('require','exports',js)(name=>workspaceMock(name,react)??(mocks[name]||new Proxy({},{get:(_,key)=>key})),exports);
  const nodes=node=>!node||typeof node!=='object'?[]:[node,...(node.props?.children||[]).flat(Infinity).flatMap(nodes)];
  const render=()=>{cursor=0;tree=exports.NotificationCenter(props)};
  const find=fn=>nodes(tree).find(fn),button=label=>find(n=>n.type==='button'&&(n.props['aria-label']===label||n.props.children.includes(label)));
  return {props,actions,events,render,find,button,remount:()=>{values=[];render()}};
}

test('bell opens messages without requesting permission; closing preserves the current page',t=>{
  const h=harness(t);h.render();h.button('通知中心，1 条未读').props.onClick();h.render();
  assert.ok(h.find(n=>n.props?.role==='dialog'));assert.equal(h.props.tab,'messages');assert.deepEqual(h.actions,[]);
  h.button('关闭通知中心').props.onClick();h.render();assert.equal(h.props.tab,null);assert.equal(h.find(n=>n.props?.role==='dialog'),undefined);
});

test('mark all read persists and later messages get a new badge while silent records remain visible',t=>{
  const h=harness(t);h.props.tab='messages';h.render();h.button('全部已读').props.onClick();h.remount();
  assert.ok(h.button('通知中心'));assert.equal(h.button('全部已读').props.disabled,true);
  assert.ok(h.find(n=>n.type==='p'&&n.props.children.includes('a：SSH 连接失败')));
  h.events.unshift({id:4,host:'a',message:'资源恢复',created:101});h.render();assert.ok(h.button('通知中心，1 条未读'));
});

test('rules, message targets and browser permission each invoke only their own action',async t=>{
  const h=harness(t);h.props.tab='messages';h.render();
  h.button('查看机器和设备').props.onClick();assert.deepEqual(h.actions,[['locate',h.events[0]]]);assert.equal(h.props.tab,null);
  h.props.tab='rules';h.render();h.button('删除监控规则 rule-a').props.onClick();assert.deepEqual(h.actions[1],['remove','rule-a']);
  h.props.busy=true;h.render();assert.equal(h.button('删除监控规则 rule-a').props.disabled,true);
  await h.button('开启浏览器通知').props.onClick();assert.equal(h.actions[2],'enable');h.render();
  await h.button('关闭浏览器通知').props.onClick();assert.equal(h.actions[3],'disable');h.render();
  assert.ok(h.button('开启浏览器通知'));
});

test('notification tabs support arrow keys without leaving focus behind',t=>{
  const h=harness(t);h.props.tab='messages';h.render();let prevented=false,focused=-1;
  const tabs=h.find(n=>n.props?.role==='tablist');
  tabs.props.onKeyDown({key:'ArrowRight',preventDefault:()=>prevented=true,currentTarget:{querySelectorAll:()=>[0,1].map(i=>({focus:()=>focused=i}))}});
  assert.equal(prevented,true);assert.equal(h.props.tab,'rules');assert.equal(focused,1);
});
