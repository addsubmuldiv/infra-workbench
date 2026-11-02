import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import ts from 'typescript';

test('opening the model picker again fetches the current provider and binds its list request to that provider',async()=>{
  let slot=0,tree;const values=[],calls=[];
  const react={createElement:(type,props,...children)=>({type,props:{...props,children}}),useState:initial=>{const i=slot++;if(!(i in values))values[i]=initial;return [values[i],v=>values[i]=v]},useRef:initial=>{const i=slot++;return values[i]??=( {current:initial})},useEffect(){},useLayoutEffect(){}};
  let profile='a';const exports={};
  const request=async(path='',method,body)=>{calls.push({path,body});if(!path)return {active_id:profile,model:profile+'-model',base_url:'https://example.test',protocol:'auto',timeout_seconds:45};return {models:[profile+'-model'],truncated:false}};
  const js=ts.transpileModule(fs.readFileSync(new URL('../src/ChatModelPicker.tsx',import.meta.url),'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,jsx:ts.JsxEmit.React,esModuleInterop:true}}).outputText;
  new Function('require','exports',js)(name=>name==='react'?react:name==='react-dom'?{createPortal:node=>node}:name==='./agentSettings'?{agentRequest:request}:{},exports);
  const old=globalThis.document;globalThis.document={body:{}};
  try{
    const render=()=>{slot=0;return tree=exports.ChatModelPicker({model:'a-model'})};
    const flush=async()=>{await new Promise(resolve=>setImmediate(resolve));render()};
    render();tree.props.children[0].props.onClick();await flush();
    assert.equal(calls[1].body.profile_id,'a');
    tree.props.children[0].props.onClick();render();profile='b';
    tree.props.children[0].props.onClick();await flush();
    assert.equal(calls[3].body.profile_id,'b');
    assert.equal(tree.props.children[0].props['aria-expanded'],true);
  }finally{if(old===undefined)delete globalThis.document;else globalThis.document=old}
});
