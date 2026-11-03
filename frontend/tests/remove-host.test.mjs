import {i18nMock} from './i18n-mock.mjs';
import {test} from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import ts from 'typescript';

function harness(remove,hosts){
  const values=[];let slot=0,tree,closed=0;
  const react={createElement:(type,props,...children)=>({type,props:{...props,children}}),
    useState:initial=>{const i=slot++;if(!(i in values))values[i]=initial;return [values[i],v=>{values[i]=v}]},
    useRef:initial=>{const i=slot++;if(!(i in values))values[i]={current:initial};return values[i]}};
  const source=fs.readFileSync(new URL('../src/RemoveHostDialog.tsx',import.meta.url),'utf8');
  const js=ts.transpileModule(source,{compilerOptions:{module:ts.ModuleKind.CommonJS,jsx:ts.JsxEmit.React,esModuleInterop:true}}).outputText;
  const exports={};new Function('require','exports',js)(name=>i18nMock(name)??(name==='react'?react:new Proxy({},{get:(_,key)=>key})),exports);
  const render=()=>{slot=0;tree=exports.RemoveHostDialog({host:{id:'fake',target:'example-server'},hosts,remove,close:()=>closed++});return tree};
  const nodes=n=>!n||typeof n!=='object'?[]:[n,...(n.props?.children||[]).flat(Infinity).flatMap(nodes)];
  const find=fn=>nodes(tree).find(fn);
  return {render,find,get closed(){return closed}};
}

test('opening or cancelling the removal confirmation does not remove a machine',()=>{
  let removed=0;const h=harness(async()=>removed++);h.render();
  assert.equal(removed,0);
  h.find(n=>n.type==='button'&&n.props['aria-label']==='取消移除机器').props.onClick();
  assert.equal(removed,0);assert.equal(h.closed,1);
});

test('batch removal continues after a failure and retries only failed machines',async()=>{
  const removed=[],calls=[];let fail=true;
  const h=harness(async host=>{calls.push(host.id);if(host.id==='beta'&&fail)throw new Error('连接失败');removed.push(host.id)},[{id:'alpha',target:'Alpha'},{id:'beta',target:'Beta'},{id:'gamma',target:'Gamma'}]);
  h.render();
  await h.find(n=>n.props?.['aria-label']==='确认移除机器').props.onClick();h.render();
  assert.deepEqual(removed,['alpha','gamma']);assert.equal(h.closed,0);
  assert.ok(h.find(n=>n.props?.role==='alert'));
  fail=false;
  await h.find(n=>n.props?.['aria-label']==='确认移除机器').props.onClick();
  assert.deepEqual(calls,['alpha','beta','gamma','beta']);assert.equal(h.closed,1);
});

test('removing waits for success and ignores repeated confirmation clicks',async()=>{
  let complete,calls=0;const h=harness(()=>{calls++;return new Promise(resolve=>complete=resolve)});h.render();
  const button=h.find(n=>n.type==='button'&&n.props['aria-label']==='确认移除机器');
  const pending=button.props.onClick();button.props.onClick();h.render();
  assert.equal(calls,1);assert.equal(h.closed,0);
  assert.equal(h.find(n=>n.props?.['aria-label']==='取消移除机器').props.disabled,true);
  complete();await pending;assert.equal(h.closed,1);
});

test('a failed removal keeps the dialog open and allows a retry',async()=>{
  let calls=0;const h=harness(async()=>{if(++calls===1)throw new Error('凭据删除失败')});h.render();
  await h.find(n=>n.props?.['aria-label']==='确认移除机器').props.onClick();h.render();
  assert.equal(h.closed,0);assert.ok(h.find(n=>n.props?.role==='alert'));
  await h.find(n=>n.props?.['aria-label']==='确认移除机器').props.onClick();
  assert.equal(calls,2);assert.equal(h.closed,1);
});
