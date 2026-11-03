import {i18nMock} from './i18n-mock.mjs';
import {test} from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import ts from 'typescript';
import * as reservations from '../src/reservations.ts';
const hosts=[{id:'alpha',target:'alpha',snapshot:{fresh:true,devices:[0,1,2,3].map(i=>({id:String(i),kind:'GPU',name:'Test',processes:[],processes_known:true}))}}];
function harness(t,draft,save,configured=true){
  const values=[],effects=[],cleanups=[];let cursor=0,tree;
  const react={createElement:(type,props,...children)=>({type,props:{...props,children}}),useState:initial=>{const i=cursor++;if(!(i in values))values[i]=typeof initial==='function'?initial():initial;return [values[i],v=>{values[i]=typeof v==='function'?v(values[i]):v}]},useEffect:fn=>effects.push(fn)};
  const js=ts.transpileModule(fs.readFileSync(new URL('../src/ReservationPanel.tsx',import.meta.url),'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,jsx:ts.JsxEmit.React,esModuleInterop:true}}).outputText;
  const exports={};new Function('require','exports',js)(name=>i18nMock(name)??(name==='react'?react:name==='./reservations'?reservations:name==='./preferences'?{browserStorage:()=>null}:name==='./mailSettings'?{mailRequest:async()=>({reservation_available:configured})}:{}),exports);
  let closed=0;const props={hosts,draft,countEnabled:true,save,close:()=>closed++,openSettings(){}};
  const nodes=n=>!n||typeof n!=='object'?[]:[n,...(n.props?.children||[]).flat(Infinity).flatMap(nodes)];
  const text=n=>n==null||n===false?'':typeof n!=='object'?String(n):(n.props?.children||[]).flat(Infinity).map(text).join('');
  const render=()=>{cursor=0;tree=exports.ReservationDialog(props);return tree};
  const find=fn=>nodes(tree).find(fn),field=label=>find(n=>n.props?.['aria-label']===label);
  const mount=async()=>{effects.splice(0).forEach(fn=>cleanups.push(fn()));await new Promise(resolve=>setImmediate(resolve));render()};
  t.after(()=>cleanups.forEach(fn=>fn?.()));
  return {render,mount,field,find,text,closed:()=>closed,submit:()=>find(n=>n.type==='form').props.onSubmit({preventDefault(){}})};
}
test('full editor restores count, memory, delay and email then saves all new conditions',async t=>{
  let saved;const h=harness(t,{editingId:'old',hostId:'alpha',mode:'count',requiredCount:3,kind:'GPU',devices:[],minimum:24,waitSeconds:180,emailNotify:true},async body=>saved=body);
  h.render();await h.mount();
  assert.equal(h.field('预约需要设备数').props.value,'3');assert.equal(h.field('预约等待分钟').props.value,'3');assert.equal(h.field('预约每设备剩余显存').props.value,'24');assert.equal(h.field('使用邮箱通知').props.checked,true);
  h.field('预约需要设备数').props.onChange({target:{value:'2'}});h.field('预约每设备剩余显存').props.onChange({target:{value:'32'}});h.render();await h.submit();
  assert.deepEqual(saved,{host_id:'alpha',mode:'count',devices:[],required_count:2,kind:'GPU',wait_seconds:180,minimum_gib:32,email_notify:true});assert.equal(h.closed(),1);
});
test('an unavailable email configuration cannot silently erase the old opt-in',async t=>{
  let saved;const h=harness(t,{hostId:'alpha',devices:['1'],emailNotify:true},async body=>saved=body,false);
  h.render();await h.mount();assert.equal(h.field('使用邮箱通知').props.checked,true);assert.equal(h.field('使用邮箱通知').props.disabled,false);
  await h.submit();h.render();assert.equal(saved,undefined);assert.match(h.text(h.render()),/邮箱配置不可用/);assert.equal(h.closed(),0);
  h.field('使用邮箱通知').props.onChange({target:{checked:false}});h.render();await h.submit();assert.equal(saved.email_notify,false);assert.equal(h.closed(),1);
});
test('a replaced device and a failed save both preserve the editor for correction',async t=>{
  const h=harness(t,{editingId:'old',hostId:'alpha',devices:['missing']},async()=>{throw new Error('存储失败')});h.render();await h.mount();
  await h.submit();h.render();assert.match(h.text(h.render()),/部分设备已不存在/);assert.equal(h.closed(),0);
  h.find(n=>n.type==='button'&&h.text(n)==='全选').props.onClick();h.render();await h.submit();h.render();assert.match(h.text(h.render()),/存储失败/);assert.equal(h.closed(),0);
});
