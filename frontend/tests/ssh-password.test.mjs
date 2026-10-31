import {test} from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import ts from 'typescript';

function harness(t,{fail=false}={}){
  const values=[],effects=[],deps=[],calls=[];let slot=0,tree,closed=0,updated=0;
  const react={createElement:(type,props,...children)=>({type,props:{...props,children}}),
    useState:initial=>{const i=slot++;if(!(i in values))values[i]=typeof initial==='function'?initial():initial;return [values[i],v=>{values[i]=typeof v==='function'?v(values[i]):v}]},
    useEffect:(fn,next)=>{const i=slot++;if(!deps[i]||next.some((v,j)=>v!==deps[i][j])){effects.push(fn);deps[i]=next}}};
  const original=globalThis.fetch;
  globalThis.fetch=async(url,options={})=>{calls.push({url,...options});return {ok:!(fail&&options.method==='POST'),json:async()=>fail&&options.method==='POST'?{detail:'验证失败'}:{password_saved:options.method!=='DELETE',can_remember:true,error:null}}};
  t.after(()=>{globalThis.fetch=original});
  const js=ts.transpileModule(fs.readFileSync(new URL('../src/SSHPasswordDialog.tsx',import.meta.url),'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,jsx:ts.JsxEmit.React,esModuleInterop:true}}).outputText;
  const exports={};new Function('require','exports',js)(name=>name==='react'?react:new Proxy({},{get:(_,key)=>key}),exports);
  const host={id:'example',target:'example'};
  const render=()=>{slot=0;tree=exports.SSHPasswordDialog({host,close:()=>closed++,updated:async()=>updated++});for(const effect of effects.splice(0))effect();return tree};
  const nodes=(node=tree)=>!node||typeof node!=='object'?[]:[node,...(node.props?.children||[]).flat(Infinity).flatMap(n=>nodes(n))];
  const find=fn=>nodes().find(fn);const settle=()=>new Promise(r=>setImmediate(r));
  return {render,find,calls,settle,get closed(){return closed},get updated(){return updated},async ready(){render();await settle();render()},edit(value){find(n=>n.type==='input').props.onChange({target:{value}});render()}};
}

test('SSH password save validates, clears secret and closes automatically',async t=>{
  const h=harness(t);await h.ready();h.edit('fake-only-password');
  await h.find(n=>n.type==='form').props.onSubmit({preventDefault(){}});h.render();
  const post=h.calls.find(c=>c.method==='POST');assert.equal(JSON.parse(post.body).password,'fake-only-password');
  assert.equal(h.find(n=>n.type==='input').props.value,'');assert.equal(h.closed,1);assert.equal(h.updated,1);
  assert.equal(post.headers['X-IWB'],'1');
});

test('failed verification preserves the dialog for correction',async t=>{
  const h=harness(t,{fail:true});await h.ready();h.edit('fake-wrong');
  await h.find(n=>n.type==='form').props.onSubmit({preventDefault(){}});h.render();
  assert.equal(h.closed,0);assert.equal(h.find(n=>n.type==='input').props.value,'fake-wrong');
  assert.ok(h.find(n=>n.props?.role==='alert'));
});

test('deleting a saved SSH password updates the state without returning a secret',async t=>{
  const h=harness(t);await h.ready();
  await h.find(n=>n.type==='button'&&n.props['aria-label']==='删除已保存的 SSH 密码').props.onClick();h.render();
  assert.ok(h.calls.some(c=>c.method==='DELETE'));assert.equal(h.updated,1);
  assert.equal(h.find(n=>n.type==='input').props.value,'');
});
