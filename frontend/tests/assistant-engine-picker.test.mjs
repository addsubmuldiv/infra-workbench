import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import ts from 'typescript';
import {i18nMock} from './i18n-mock.mjs';
function harness(result){
  const values=[],effects=[];let slot=0,tree,props={value:'claude',onChange(){},disabled:false};
  const react={createElement:(type,props,...children)=>({type,props:{...props,children}}),useState:initial=>{const i=slot++;if(!(i in values))values[i]=initial;return [values[i],value=>values[i]=value]},useEffect:fn=>{if(!effects.length)effects.push(fn)}};
  const js=ts.transpileModule(fs.readFileSync(new URL('../src/AssistantEnginePicker.tsx',import.meta.url),'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,jsx:ts.JsxEmit.React,esModuleInterop:true}}).outputText;
  const exports={};new Function('require','exports',js)(name=>i18nMock(name)??(name==='react'?react:{assistantRequest:()=>result}),exports);
  const nodes=node=>!node||typeof node!=='object'?[]:[node,...(node.props?.children||[]).flat(Infinity).flatMap(nodes)];
  const render=value=>{if(value)props={...props,value};slot=0;tree=exports.AssistantEnginePicker(props);return tree};
  return {render,nodes:()=>nodes(tree),async load(){render();effects[0]();await new Promise(resolve=>setImmediate(resolve));render()}};
}
test('CLI picker offers each engine and displays only its own setup status',async()=>{
  const h=harness(Promise.resolve({codex:{available:true,message:'Codex ready'},claude:{available:false,message:'Claude login required'},opencode:{available:false,message:'OpenCode not installed'}}));
  await h.load();assert.deepEqual(h.nodes().filter(n=>n.type==='option').map(n=>n.props.value),['deepagents','codex','claude','opencode']);
  const status=()=>h.nodes().find(n=>n.type==='small').props.children.join('');
  assert.equal(status(),'Claude login required');h.render('opencode');assert.equal(status(),'OpenCode not installed');h.render('codex');assert.equal(status(),'Codex ready');
  h.render('deepagents');assert.equal(h.nodes().find(n=>n.props.role==='status'),undefined);
});
test('older backend does not leave a missing engine at detecting forever',async()=>{
  const h=harness(Promise.resolve({codex:{available:true,message:'Codex ready'}}));await h.load();
  assert.match(h.nodes().find(n=>n.type==='small').props.children.join(''),/后台/);
});
