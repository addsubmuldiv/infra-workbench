import {i18nMock} from './i18n-mock.mjs';
import * as toolTranslations from '../src/toolI18n.ts';
import {workspaceMock} from './workspace-mock.mjs';
import {test} from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import ts from 'typescript';
import * as frames from '../src/fileWindow.ts';
import * as templates from '../src/terminalTemplates.ts';

function harness(t,snippets=[]){
  const slots=[],dependencies=[],effects=[],cleanups=[],actions=[],inserted=[];let index=0,tree,closed=0;
  let workspace={snippets,history:[],settings:{}};
  const savedGlobals={};
  for(const [key,value] of Object.entries({window:{innerWidth:1200,innerHeight:900,addEventListener(){},removeEventListener(){}},document:{body:{}},localStorage:{getItem(){return null},setItem(){}}})){
    savedGlobals[key]=Object.getOwnPropertyDescriptor(globalThis,key);Object.defineProperty(globalThis,key,{configurable:true,writable:true,value});
  }
  t.after(()=>{cleanups.forEach(fn=>fn?.());for(const [key,value] of Object.entries(savedGlobals)){if(value)Object.defineProperty(globalThis,key,value);else delete globalThis[key]}});
  const react={createElement:(type,props,...children)=>({type,props:{...props,children}}),
    useState:initial=>{const key=index++;if(!(key in slots))slots[key]=typeof initial==='function'?initial():initial;return [slots[key],value=>slots[key]=typeof value==='function'?value(slots[key]):value]},
    useRef:initial=>{const key=index++;if(!(key in slots))slots[key]={current:initial};return slots[key]},
    useEffect:(fn,deps)=>{const key=index++;if(!dependencies[key]||!deps||deps.some((v,i)=>v!==dependencies[key][i])){effects.push(()=>{cleanups[key]?.();cleanups[key]=fn()});dependencies[key]=deps}}};
  const compiled=ts.transpileModule(fs.readFileSync(new URL('../src/TerminalCommands.tsx',import.meta.url),'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022,jsx:ts.JsxEmit.React,esModuleInterop:true}}).outputText;
  const exports={};new Function('require','exports',compiled)(name=>i18nMock(name)??((name==='./toolI18n'||name==='./toolI18n.ts')?toolTranslations:undefined)??workspaceMock(name,react)??(name==='react'?react:name==='react-dom'?{createPortal:node=>node}:name==='./fileWindow'?frames:name==='./terminalTemplates'?templates:{}),exports);
  const render=()=>{index=0;tree=exports.default({host:'test',workspace,action:value=>actions.push(value),insert:value=>{inserted.push(value);return true},close:()=>closed++});for(const effect of effects.splice(0))effect();return tree};
  const nodes=node=>!node||typeof node!=='object'?[]:[node,...(node.props?.children||[]).flat(Infinity).flatMap(child=>nodes(child))];
  const find=predicate=>nodes(tree).find(predicate);
  const button=name=>find(node=>node.type==='button'&&(node.props['aria-label']===name||node.props.children.includes(name)));
  return {render,find,button,actions,inserted,get closed(){return closed},receive(snippets){workspace={...workspace,snippets};render();render()}};
}

test('favorites are distinct from built-in templates and saving returns to the confirmed list',t=>{
  const h=harness(t);h.render();
  assert.ok(h.find(n=>n.type==='strong'&&n.props.children.includes('这台机器还没有收藏命令')));
  assert.equal(h.button('使用模板 训练任务'),undefined);
  h.button('内置模板').props.onClick();h.render();h.button('使用模板 训练任务').props.onClick();h.render();
  h.button('收藏此模板').props.onClick();h.render();
  assert.equal(h.actions[0].action,'save_snippet');assert.equal(h.inserted.length,0);
  assert.equal(h.button('正在保存…').props.disabled,true);
  h.receive([{...h.actions[0].snippet,id:'saved-training'}]);
  assert.ok(h.button('我的收藏 (1)'));assert.ok(h.button('编辑收藏 训练任务'));assert.ok(h.button('填入收藏 训练任务'));
  assert.ok(h.find(n=>n.type==='code'&&n.props.children.includes(templates.examples[0].command)));
  assert.equal(h.button('收藏此模板'),undefined);
});

test('saved command content is visible and filling does not add a newline',t=>{
  const snippet={id:'test',name:'GPU 占用',command:'watch -n 1 nvidia-smi'};const h=harness(t,[snippet]);h.render();
  assert.ok(h.find(n=>n.type==='code'&&n.props.children.includes(snippet.command)));
  h.button('填入收藏 GPU 占用').props.onClick();assert.deepEqual(h.inserted,[snippet.command]);assert.equal(h.closed,1);
});

test('command window moves, resizes and maximizes while retaining a minimized draft',t=>{
  const h=harness(t);let root=h.render();h.button('＋ 新建收藏').props.onClick();h.render();
  const nameInput=h.find(n=>n.type==='input'&&n.props.placeholder==='例如：查看 GPU 占用');nameInput.props.onChange({target:{value:'草稿'}});root=h.render();
  const old={...root.props.style};const event={button:0,pointerId:7,clientX:100,clientY:100,target:{closest:()=>false},currentTarget:{setPointerCapture(){}},preventDefault(){}};
  h.find(n=>n.type==='header').props.onPointerDown(event);root.props.onPointerMove({...event,clientX:160,clientY:140});root=h.render();assert.equal(root.props.style.left,old.left+60);assert.equal(root.props.style.top,old.top+40);root.props.onPointerUp(event);
  h.find(n=>n.props?.['aria-label']==='调整命令窗口大小').props.onPointerDown(event);root.props.onPointerMove({...event,clientX:180,clientY:160});root=h.render();assert.equal(root.props.style.width,old.width+80);assert.equal(root.props.style.height,old.height+60);root.props.onPointerUp(event);
  h.button('最大化命令窗口').props.onClick();root=h.render();assert.equal(root.props.style.width,1176);
  h.button('最小化命令窗口').props.onClick();root=h.render();assert.equal(root.props.style.height,56);
  h.button('恢复命令窗口').props.onClick();h.render();assert.equal(h.find(n=>n.type==='input'&&n.props.placeholder==='例如：查看 GPU 占用').props.value,'草稿');
});
