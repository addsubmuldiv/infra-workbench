import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import ts from 'typescript';
import {i18nMock} from './i18n-mock.mjs';

function harness(t,saved){
  let slot=0,tree;const values=[];let stored=saved;
  const previous=globalThis.localStorage;
  globalThis.localStorage={getItem:()=>stored,setItem:(_key,value)=>stored=value};
  t.after(()=>{if(previous===undefined)delete globalThis.localStorage;else globalThis.localStorage=previous});
  const react={useEffect(){},createElement:(type,props,...children)=>({type,props:{...props,children}}),
    useState:initial=>{const index=slot++;if(!(index in values))values[index]=typeof initial==='function'?initial():initial;return[values[index],next=>{values[index]=typeof next==='function'?next(values[index]):next}]}};
  const js=ts.transpileModule(fs.readFileSync(new URL('../src/SettingsPage.tsx',import.meta.url),'utf8'),{compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.CommonJS,jsx:ts.JsxEmit.ReactJSX}}).outputText;
  const exports={};const components={};
  new Function('require','exports',js)(name=>i18nMock(name)??(name==='react'?react:name==='react/jsx-runtime'?{jsx:(type,props,key)=>({type,key,props}),jsxs:(type,props,key)=>({type,key,props})}:name==='lucide-react'?{}:components[name]??={}),exports);
  const nodes=node=>!node||typeof node!=='object'?[]:[node,...[node.props?.children].flat(Infinity).flatMap(nodes)];
  const render=()=>{slot=0;tree=exports.default()};
  const all=()=>nodes(tree);
  const click=label=>{const button=all().find(n=>n.type==='button'&&nodes(n).some(child=>child.props?.children===label)||n.type==='button'&&n.props.children===label);assert.ok(button,label);button.props.onClick();render()};
  render();
  return{all,click,stored:()=>JSON.parse(stored),panels:()=>all().filter(n=>n.props?.className==='settings-category-panel')};
}

test('categories and inner tabs retain visited forms and remember navigation',t=>{
  const h=harness(t,null);
  assert.equal(h.panels().length,1);
  h.click('AI 助手');h.click('Skills');
  assert.equal(h.stored().ai,'skills');
  assert.equal(h.panels().length,3);
  assert.equal(h.panels().filter(p=>!p.props.hidden).length,1);
  h.click('集成服务');h.click('邮件');h.click('AI 助手');
  assert.equal(h.all().find(n=>n.type==='button'&&n.props.children==='Skills').props['aria-pressed'],true);
  assert.equal(h.stored().category,'ai');
  assert.equal(h.panels().length,5);
});

test('invalid saved navigation falls back to general',t=>{
  const h=harness(t,'{"category":"unknown","ai":"invalid"}');
  assert.equal(h.all().find(n=>n.props?.['aria-current']==='page').props.children[1].props.children,'通用');
});

test('saved integration tab is restored on opening settings',t=>{
  const h=harness(t,'{"category":"integrations","integrations":"mail"}');
  assert.equal(h.all().find(n=>n.type==='button'&&n.props.children==='邮件').props['aria-pressed'],true);
  assert.equal(h.panels().length,1);
});

