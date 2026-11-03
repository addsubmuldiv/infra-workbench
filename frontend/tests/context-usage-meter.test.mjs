import {i18nMock} from './i18n-mock.mjs';
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import ts from 'typescript';

function render(usage,extra={}){
  const react={createElement:(type,props,...children)=>({type,props:{...props,children}}),useEffect:()=>{},useState:()=>[null,()=>{}]};
  const exports={};
  const code=ts.transpileModule(fs.readFileSync(new URL('../src/ContextUsageMeter.tsx',import.meta.url),'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,jsx:ts.JsxEmit.React,esModuleInterop:true}}).outputText;
  new Function('require','exports',code)(name=>i18nMock(name)??(name==='react'?react:{}),exports);
  const turn={role:'assistant',context_usage:usage,...extra};
  const tree=exports.ContextUsageMeter({chat:{turns:[turn]},model:'test-model'});
  const nodes=node=>!node||typeof node!=='object'?[]:[node,...node.props.children.flat(Infinity).flatMap(nodes)];
  const list=nodes(tree);
  return {find:fn=>list.find(fn),text:list.flatMap(node=>node.props.children.flat(Infinity)).filter(value=>typeof value==='string').join(' ')};
}
const usage={used_tokens:100000,total_tokens:1048576,trigger_tokens:891289,source:'provider',model:'test-model',estimated:true,phase:'response'};
test('meter exposes estimate, capacity and distance to compression',()=>{
  const view=render(usage);
  const bar=view.find(node=>node.props.role==='progressbar');
  assert.equal(bar.props['aria-valuenow'],100000);
  assert.equal(bar.props['aria-valuemax'],1048576);
  assert.match(view.text,/估算/);
  assert.match(view.text,/791,289/);
  assert.match(view.text,/1,048,576/);
  assert.match(view.text,/85%/);
});
test('old records and records from another model never pretend to have zero usage',()=>{
  for(const value of [undefined,{...usage,model:'previous-model'}]){
    const view=render(value);
    assert.match(view.text,/待统计/);
    assert.equal(view.find(node=>node.props.role==='progressbar').props['aria-valuenow'],undefined);
  }
});
test('overflow is visible while progress fill remains bounded',()=>{
  const view=render({...usage,used_tokens:2000000});
  assert.equal(view.find(node=>node.props.className?.includes('chat-context-meter-fill')).props.style.width,'100%');
  assert.match(view.text,/已达到触发线/);
});
test('active compaction and unrecognized capacity are stated explicitly',()=>{
  const view=render({...usage,source:'fallback'},{context_compaction:{status:'running'}});
  assert.match(view.text,/正在压缩/);
  assert.match(view.text,/容量未识别/);
});
