import {test} from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import ts from 'typescript';
import * as api from '../src/serverImportApi.ts';

const preview={id:'test-job',status:'preview',total:1,processed:0,success:0,failed:0,skipped:0,valid:1,key_total:0,key_done:0,key_failed:0,rows:[{row:2,target:'192.0.2.10',user:'u',port:22,status:'ready',reason:'',host_id:null,key_status:'not_requested',key_reason:''}]};
function harness(t,initial,request){
  const values=[],effects=[],cleanups=[];let cursor=0,tree;
  const react={createElement:(type,props,...children)=>({type,props:{...props,children}}),
    useState:initialValue=>{const index=cursor++;if(!(index in values))values[index]=index===0?initial:initialValue;return [values[index],value=>{values[index]=typeof value==='function'?value(values[index]):value}]},
    useRef:current=>{const index=cursor++;if(!(index in values))values[index]={current};return values[index]},
    useEffect:fn=>effects.push(fn)};
  const source=fs.readFileSync(new URL('../src/ServerImport.tsx',import.meta.url),'utf8');
  const js=ts.transpileModule(source,{compilerOptions:{module:ts.ModuleKind.CommonJS,jsx:ts.JsxEmit.React,esModuleInterop:true}}).outputText;
  const exports={};new Function('require','exports',js)(name=>name==='react'?react:name==='./serverImportApi'?{...api,importRequest:request}:{},exports);
  const render=()=>{cursor=0;tree=exports.default({onChanged(){}});return tree};
  const nodes=n=>!n||typeof n!=='object'?[]:[n,...(n.props?.children||[]).flat(Infinity).flatMap(nodes)];
  const text=n=>n==null||n===false?'':typeof n!=='object'?String(n):(n.props?.children||[]).flat(Infinity).map(text).join('');
  const find=predicate=>nodes(tree).find(predicate);
  const mount=()=>effects.splice(0).forEach(fn=>cleanups.push(fn()));
  const unmount=()=>cleanups.splice(0).reverse().forEach(fn=>fn?.());
  t.after(unmount);return {render,find,text,mount,unmount};
}

test('closing immediately after start never deletes the job whose start request is in flight',async t=>{
  let finish;const calls=[];
  const h=harness(t,preview,(path,options={})=>{
    calls.push({path,method:options.method||'GET'});
    if(path.endsWith('/start'))return new Promise(resolve=>finish=resolve);
    return Promise.resolve(null);
  });
  h.render();h.mount();
  h.find(n=>n.type==='button'&&h.text(n).includes('开始处理')).props.onClick();
  h.unmount();
  assert.ok(calls.some(call=>call.path.endsWith('/start')));
  assert.ok(!calls.some(call=>call.method==='DELETE'),'a start racing the close must be allowed to finish');
  finish({...preview,status:'running'});await new Promise(resolve=>setImmediate(resolve));
});

test('a disappeared running job stops polling and allows a fresh file selection',async t=>{
  const running={...preview,status:'running'};
  const h=harness(t,running,path=>path==='/latest'?Promise.resolve(null):Promise.reject(Object.assign(new Error('job expired'),{status:404})));
  h.render();h.mount();await new Promise(resolve=>setImmediate(resolve));h.render();
  assert.equal(h.find(n=>n.type==='input'&&n.props.type==='file').props.disabled,false);
});

test('discarding a preview without starting releases its temporary credentials',t=>{
  const calls=[];const h=harness(t,preview,(path,options={})=>{calls.push({path,method:options.method});return Promise.resolve(null)});
  h.render();h.mount();h.unmount();
  assert.ok(calls.some(call=>call.path==='/test-job'&&call.method==='DELETE'));
});


test('password storage results are visible and failures can be filtered independently',t=>{
  const complete={...preview,status:'complete',total:2,processed:2,success:2,password_saved:1,password_failed:1,rows:[
    {...preview.rows[0],status:'imported',target:'192.0.2.10',password_status:'saved',password_reason:'已存入系统凭据管理器'},
    {...preview.rows[0],row:3,status:'imported',target:'192.0.2.11',password_status:'failed',password_reason:'请重试保存'}]};
  const h=harness(t,complete,()=>Promise.resolve(null));
  h.render();
  assert.match(h.text(h.render()),/SSH 密码：已保存/);
  assert.match(h.text(h.render()),/SSH 密码：保存失败/);
  h.find(n=>n.type==='input'&&n.props.type==='checkbox').props.onChange({target:{checked:true}});
  const filtered=h.text(h.render());
  assert.ok(!filtered.includes('192.0.2.10'));
  assert.ok(filtered.includes('192.0.2.11'));
});

test('an existing host password update is shown as an update rather than an unexplained skip',t=>{
  const complete={...preview,status:'complete',processed:1,success:0,skipped:1,password_saved:1,rows:[
    {...preview.rows[0],status:'skipped',host_id:'existing-alias',password_status:'saved',reason:'机器已存在，SSH 密码已保存，原配置保持不变'}]};
  const h=harness(t,complete,()=>Promise.resolve(null));h.render();
  const row=h.find(n=>n.type==='tr'&&h.text(n).includes('192.0.2.10'));
  assert.ok(h.text(row).includes('密码已保存'));
  assert.ok(!h.text(row).includes('已跳过'));
});
