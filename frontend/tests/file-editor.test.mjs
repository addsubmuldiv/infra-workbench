import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import ts from 'typescript';

function editorHarness(t,{failSave=false}={}){
  const values=[],effects=[],deps=[],calls=[];
  let slot=0,tree,closed=0;
  const ref={current:null};
  const react={createElement:(type,props,...children)=>({type,props:{...props,children}}),
    useState:initial=>{const index=slot++;if(!(index in values))values[index]=initial;return [values[index],value=>{values[index]=typeof value==='function'?value(values[index]):value}]},
    useRef:initial=>{const index=slot++;if(!(index in values))values[index]={current:initial};return values[index]},
    useEffect:(fn,next)=>{const index=slot++;if(!next||!deps[index]||next.some((v,i)=>v!==deps[index][i])){effects.push(fn);deps[index]=next}}};
  const original=globalThis.window;
  globalThis.window={addEventListener(){},removeEventListener(){}};
  t.after(()=>{globalThis.window=original});
  const exports={};
  const source=ts.transpileModule(fs.readFileSync(new URL('../src/FileEditor.tsx',import.meta.url),'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,jsx:ts.JsxEmit.React,esModuleInterop:true}}).outputText;
  const operation=async(host,command)=>{calls.push(command);if(command.op==='save'&&failSave)throw new Error('文件已被其他人修改');return {path:'/test.txt',content:command.op==='save'?command.content:'original',revision:'revision',newline:'LF',bytes:8}};
  new Function('require','exports',source)(name=>name==='react'?react:name==='./files'?{fileOperation:operation}:new Proxy({},{get:(_,key)=>key}),exports);
  const render=()=>{slot=0;tree=exports.FileEditor({host:'test',path:'/test.txt',close:()=>closed++,saved(){},changed(){},busyChanged(){},closeRequest:ref});for(const effect of effects.splice(0))effect();return tree};
  const nodes=(node=tree)=>!node||typeof node!=='object'?[]:[node,...(node.props?.children||[]).flat(Infinity).flatMap(child=>nodes(child))];
  const find=predicate=>nodes().find(predicate);
  const button=label=>find(n=>n.type==='button'&&(n.props.children.includes(label)||n.props['aria-label']===label));
  return {render,find,button,calls,ref,get closed(){return closed},async loaded(){render();await new Promise(resolve=>setImmediate(resolve));render()},edit(text){find(n=>n.type==='textarea').props.onChange({target:{value:text}});render()}};
}

test('Ctrl+S saves directly through the remote-file endpoint',async t=>{
  const h=editorHarness(t);await h.loaded();h.edit('edited directly');
  const root=h.render();let prevented=false;
  root.props.onKeyDown({ctrlKey:true,key:'s',preventDefault(){prevented=true}});
  await new Promise(resolve=>setImmediate(resolve));h.render();
  assert.ok(prevented);
  assert.deepEqual(h.calls.map(call=>call.op),['read','save']);
  assert.equal(h.calls[1].content,'edited directly');
  assert.equal(h.calls[1].revision,'revision');
});

test('close offers save, discard and cancel; failed save keeps edited text',async t=>{
  const h=editorHarness(t,{failSave:true});await h.loaded();h.edit('keep my edits');
  h.ref.current();h.render();
  assert.ok(h.button('保存并关闭'));assert.ok(h.button('不保存'));assert.ok(h.button('取消'));
  h.button('取消').props.onClick();h.render();assert.equal(h.closed,0);
  h.ref.current();h.render();await h.button('保存并关闭').props.onClick();h.render();
  assert.equal(h.closed,0);
  assert.equal(h.find(n=>n.type==='textarea').props.value,'keep my edits');
  h.ref.current();h.render();h.button('不保存').props.onClick();assert.equal(h.closed,1);
});

test('save-and-close also guards closing the whole file browser or changing machines',async t=>{
  const h=editorHarness(t);await h.loaded();h.edit('saved before leaving');let left=0;
  h.ref.current(()=>left++);h.render();assert.equal(left,0);
  await h.button('保存并关闭').props.onClick();h.render();
  assert.equal(left,1);assert.equal(h.calls.at(-1).content,'saved before leaving');
});
