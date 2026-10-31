import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import ts from 'typescript';
const tick=()=>new Promise(resolve=>setImmediate(resolve));
function harness(t,{conflict=false}={}){
  const values=[],effects=[],deps=[],cleanups=[],calls=[];let slot=0,tree,revision=1;
  const metadata={name:'demo',description:'检查任务',source:'user',version:2,enabled:true,warnings:[]};
  const files={'SKILL.md':'---\nname: demo\ndescription: 检查任务\n---\n步骤','references/guide.md':'参考'};
  const detail={...metadata,files,versions:[{version:2},{version:1}],file_manifest:[]};
  const react={createElement:(type,props,...children)=>({type,props:{...props,children}}),
    useState:initial=>{const i=slot++;if(!(i in values))values[i]=typeof initial==='function'?initial():initial;return[values[i],next=>{values[i]=typeof next==='function'?next(values[i]):next}]},
    useRef:initial=>{const i=slot++;if(!(i in values))values[i]={current:initial};return values[i]},
    useEffect:(fn,next)=>{const i=slot++;if(!deps[i]||next.some((v,j)=>v!==deps[i][j])){effects.push(()=>{cleanups[i]?.();cleanups[i]=fn()});deps[i]=next}}};
  const skillRequest=async(path='',method='GET',body)=>{calls.push({path,method,body});
    if(path===''&&method==='GET')return{items:[metadata]};if(path==='/demo'&&method==='GET')return detail;
    if(path==='/drafts'&&method==='GET')return{items:[{id:'saved-draft',revision:4,name:'聊天创建的草稿'}]};
    if(path==='/drafts/saved-draft'&&method==='GET')return{id:'saved-draft',revision:4,files};
    if(path==='/drafts'&&method==='POST')return{id:'draft-1',revision,files:body.files};
    if(path==='/drafts/draft-1'&&method==='PUT')return{id:'draft-1',revision:++revision,files:body.files};
    if(path.endsWith('/validate'))return{valid:true,errors:[],warnings:['脚本不会执行']};
    if(path.endsWith('/install')){if(conflict)throw new Error('草稿已被其他操作修改');return{...metadata,status:'installed'}}
    return{};
  };
  const previous=globalThis.window;globalThis.window=new EventTarget();t.after(()=>{cleanups.forEach(fn=>fn?.());globalThis.window=previous});
  const js=ts.transpileModule(fs.readFileSync(new URL('../src/SkillsSettings.tsx',import.meta.url),'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,jsx:ts.JsxEmit.React,esModuleInterop:true}}).outputText;
  const exports={};new Function('require','exports',js)(name=>name==='react'?react:name==='./skills'?{skillRequest,skillMarkdown:()=>files['SKILL.md']}:name==='./AppConfirm'?{useAppConfirm:()=>({confirm:async()=>true,confirmation:null})}:{},exports);
  const nodes=node=>!node||typeof node!=='object'?[]:[node,...(node.props?.children||[]).flat(Infinity).flatMap(nodes)];
  const find=fn=>nodes(tree).find(fn);
  const render=()=>{slot=0;tree=exports.SkillsSettings();for(const effect of effects.splice(0))effect()};
  const settle=async()=>{await tick();render();await tick();render()};
  const text=node=>(node?.props.children||[]).flat(Infinity).filter(child=>typeof child==='string').join('');
  const click=async(label)=>{const button=find(n=>n.type==='button'&&text(n)===label);assert.ok(button,`button ${label}`);await button.props.onClick();await settle()};
  return{calls,find,render,settle,click,async loaded(){render();await settle()},async open(){const button=find(n=>n.type==='button'&&nodes(n).some(child=>child.type==='strong'&&text(child)==='demo'));await button.props.onClick();await settle()}};
}
test('editing installed skill sends base version, preserves reference files and installs validated revision',async t=>{
  const h=harness(t);await h.loaded();await h.open();await h.click('编辑');
  const editor=h.find(n=>n.props['aria-label']==='技能文件内容');editor.props.onChange({target:{value:'changed instructions'}});h.render();
  await h.click('安装并启用');const create=h.calls.find(call=>call.method==='POST'&&call.path==='/drafts');
  assert.equal(create.body.skill_name,'demo');assert.equal(create.body.base_version,2);assert.equal(create.body.files['references/guide.md'],'参考');assert.equal(create.body.files['SKILL.md'],'changed instructions');
  const validate=h.calls.find(call=>call.path.endsWith('/validate')),install=h.calls.find(call=>call.path.endsWith('/install'));assert.equal(validate.body.revision,install.body.revision);
  assert.ok(h.find(n=>n.props.role==='status'&&n.props.children.flat().some(v=>typeof v==='string'&&v.includes('下一轮对话生效'))));
});
test('install conflict retains editable content and displays backend recovery message',async t=>{
  const h=harness(t,{conflict:true});await h.loaded();await h.open();await h.click('编辑');await h.click('安装并启用');
  assert.ok(h.find(n=>n.props.role==='alert'&&n.props.children.includes('草稿已被其他操作修改')));assert.ok(h.find(n=>n.props['aria-label']==='技能文件内容'));
});
test('toggle and version rollback use current version for optimistic concurrency',async t=>{
  const h=harness(t);await h.loaded();await h.open();await h.click('停用');
  assert.deepEqual(h.calls.find(call=>call.path==='/demo/enabled').body,{enabled:false,expected_version:2});
  await h.click('切换至此版本');assert.deepEqual(h.calls.find(call=>call.path==='/demo/rollback').body,{version:1,expected_version:2});
});
test('persisted chat-created draft can be resumed in management page',async t=>{
  const h=harness(t);await h.loaded();const button=h.find(n=>n.type==='button'&&n.props.children.flat().some(child=>child?.type==='strong'&&child.props.children.includes('聊天创建的草稿')));assert.ok(button);
  await button.props.onClick();await h.settle();assert.ok(h.calls.some(call=>call.path==='/drafts/saved-draft'));assert.equal(h.find(n=>n.props['aria-label']==='技能文件内容').props.value.includes('步骤'),true);
});
