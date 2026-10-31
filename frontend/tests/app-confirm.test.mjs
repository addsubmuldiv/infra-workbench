import {test} from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import ts from 'typescript';
function harness(){
  let state=null;const pending={current:null},cleanups=[];
  const react={createElement:(type,props)=>({type,props}),useState:()=>[state,v=>state=v],useRef:()=>pending,useCallback:fn=>fn,useEffect:fn=>cleanups.push(fn())};
  const source=fs.readFileSync(new URL('../src/AppConfirm.tsx',import.meta.url),'utf8');
  const js=ts.transpileModule(source,{compilerOptions:{module:ts.ModuleKind.CommonJS,jsx:ts.JsxEmit.React,esModuleInterop:true}}).outputText;
  const exports={};new Function('require','exports',js)(name=>name==='react'?react:{},exports);
  return {render:()=>exports.useAppConfirm(),unmount:()=>cleanups.forEach(fn=>fn?.())};
}
test('confirmation waits for a choice and cancellation resolves false',async()=>{
  const h=harness();let result='waiting';const answer=h.render().confirm('关闭会话？').then(value=>result=value);
  await Promise.resolve();assert.equal(result,'waiting');h.render().confirmation.props.finish(false);await answer;assert.equal(result,false);
});
test('acceptance resolves once, even with repeated clicks',async()=>{
  const h=harness();const answer=h.render().confirm('关闭会话？');const dialog=h.render().confirmation;
  dialog.props.finish(true);dialog.props.finish(false);assert.equal(await answer,true);
});
test('unmount cancels an outstanding decision',async()=>{
  const h=harness();const answer=h.render().confirm('关闭会话？');h.unmount();assert.equal(await answer,false);
});
test('a replacement cancels the previous decision',async()=>{
  const h=harness(),api=h.render();const first=api.confirm('第一项');const second=api.confirm('第二项');assert.equal(await first,false);h.render().confirmation.props.finish(true);assert.equal(await second,true);
});
