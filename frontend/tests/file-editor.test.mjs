import {i18nMock} from './i18n-mock.mjs';
import * as toolTranslations from '../src/toolI18n.ts';
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import ts from 'typescript';
import {fitFileWindow,moveFileWindow,resizeFileWindow} from '../src/fileWindow.ts';

function editorHarness(t,{failSave=false}={}){
  const values=[],effects=[],deps=[],calls=[];
  let slot=0,tree,closed=0;
  const ref={current:null};
  const react={createElement:(type,props,...children)=>({type,props:{...props,children}}),lazy:()=>TextEditor,Suspense:'suspense',
    useState:initial=>{const index=slot++;if(!(index in values))values[index]=typeof initial==='function'?initial():initial;return [values[index],value=>{values[index]=typeof value==='function'?value(values[index]):value}]},
    useRef:initial=>{const index=slot++;if(!(index in values))values[index]={current:initial};return values[index]},
    useEffect:(fn,next)=>{const index=slot++;if(!next||!deps[index]||next.some((v,i)=>v!==deps[index][i])){effects.push(fn);deps[index]=next}}};
  const original=globalThis.window,originalDocument=globalThis.document;
  globalThis.window={innerWidth:1200,innerHeight:800,addEventListener(){},removeEventListener(){}};
  globalThis.document={body:{}};
  t.after(()=>{globalThis.window=original;globalThis.document=originalDocument});
  const exports={};
  const source=ts.transpileModule(fs.readFileSync(new URL('../src/FileEditor.tsx',import.meta.url),'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,jsx:ts.JsxEmit.React,esModuleInterop:true}}).outputText;
  const operation=async(host,command)=>{calls.push(command);if(command.op==='save'&&failSave)throw new Error('文件已被其他人修改');return {path:'/test.txt',content:command.op==='save'?command.content:'original',revision:'revision',newline:'LF',bytes:8}};
  function TextEditor(){}
  new Function('require','exports',source)(name=>i18nMock(name)??((name==='./toolI18n'||name==='./toolI18n.ts')?toolTranslations:undefined)??(name==='react'?react:name==='react-dom'?{createPortal:node=>node}:name==='./TextEditor'?{TextEditor}:name==='./fileWindow'?{fitFileWindow,moveFileWindow,resizeFileWindow}:name==='./files'?{fileOperation:operation}:new Proxy({},{get:(_,key)=>key})),exports);
  const render=()=>{slot=0;tree=exports.FileEditor({host:'test',path:'/test.txt',close:()=>closed++,saved(){},changed(){},busyChanged(){},closeRequest:ref});for(const effect of effects.splice(0))effect();return tree};
  const nodes=(node=tree)=>!node||typeof node!=='object'?[]:[node,...(node.props?.children||[]).flat(Infinity).flatMap(child=>nodes(child))];
  const find=predicate=>nodes().find(predicate);
  const button=label=>find(n=>n.type==='button'&&(n.props.children.includes(label)||n.props['aria-label']===label));
  return {render,find,button,calls,ref,content:()=>find(n=>n.type===TextEditor),get closed(){return closed},async loaded(){render();await new Promise(resolve=>setImmediate(resolve));render()},edit(text){find(n=>n.type===TextEditor).props.onChange(text);render()}};
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
  assert.equal(h.content().props.value,'keep my edits');
  h.ref.current();h.render();h.button('不保存').props.onClick();assert.equal(h.closed,1);
});

test('save-and-close also guards closing the whole file browser or changing machines',async t=>{
  const h=editorHarness(t);await h.loaded();h.edit('saved before leaving');let left=0;
  h.ref.current(()=>left++);h.render();assert.equal(left,0);
  await h.button('保存并关闭').props.onClick();h.render();
  assert.equal(left,1);assert.equal(h.calls.at(-1).content,'saved before leaving');
});

test('floating editor does not steal focus and preserves unsaved text when minimized and restored',async t=>{
  const h=editorHarness(t);await h.loaded();h.edit('unsaved draft');
  assert.equal(h.render().props['aria-modal'],'false');
  assert.notEqual(h.content().props.autoFocus,true);
  h.button('最小化文本编辑器').props.onClick();let root=h.render();
  assert.equal(root.props.style.height,56);assert.equal(h.closed,0);
  h.button('恢复文本编辑器').props.onClick();root=h.render();
  assert.equal(h.content().props.value,'unsaved draft');
  assert.ok(root.props.style.height>56);
  h.button('最小化文本编辑器').props.onClick();h.render();h.ref.current();root=h.render();
  assert.ok(h.button('保存并关闭'));assert.ok(root.props.style.height>56);
});

test('floating editor can move and resize without discarding text',async t=>{
  const h=editorHarness(t);await h.loaded();h.edit('draft');const initial=h.render().props.style;
  const header=h.find(n=>n.props?.className==='file-editor-heading');
  header.props.onPointerDown({button:0,pointerId:1,clientX:100,clientY:100,target:{closest:()=>null},currentTarget:{setPointerCapture(){}},preventDefault(){}});
  h.render().props.onPointerMove({pointerId:1,clientX:60,clientY:130});let root=h.render();
  assert.equal(root.props.style.left,initial.left-40);assert.equal(root.props.style.top,initial.top+30);
  root.props.onPointerUp({pointerId:1});
  const handle=h.find(n=>n.props?.['aria-label']==='调整文本编辑器大小');
  handle.props.onPointerDown({button:0,pointerId:2,clientX:100,clientY:100,currentTarget:{setPointerCapture(){}},preventDefault(){}});
  root.props.onPointerMove({pointerId:2,clientX:40,clientY:80});root=h.render();
  assert.equal(root.props.style.width,initial.width-60);assert.equal(root.props.style.height,initial.height-20);
  assert.equal(h.content().props.value,'draft');
});
