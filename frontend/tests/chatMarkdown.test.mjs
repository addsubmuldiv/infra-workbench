import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import ts from 'typescript';
import React from 'react';
import {renderToStaticMarkup} from 'react-dom/server';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

const source=fs.readFileSync(new URL('../src/ChatMarkdown.tsx',import.meta.url),'utf8');
const js=ts.transpileModule(source,{compilerOptions:{module:ts.ModuleKind.CommonJS,jsx:ts.JsxEmit.React,esModuleInterop:true}}).outputText;
const exports={};
new Function('require','exports',js)(name=>{
  if(name==='react')return React;
  if(name==='react-markdown')return ReactMarkdown;
  if(name==='remark-gfm')return remarkGfm;
  throw new Error('Unexpected import: '+name);
},exports);
const render=content=>renderToStaticMarkup(React.createElement(exports.ChatMarkdown,{children:content}));

test('assistant replies render headings, emphasis, nested lists, quotes and GFM tables',()=>{
  const html=render('## 检查结果\n\n**正常**，使用 `nvidia-smi`。\n\n1. 主机 A\n   - GPU 就绪\n\n> 仅供参考\n\n| 主机 | 状态 |\n| --- | --- |\n| A | ~~离线~~ 在线 |\n\n- [x] 已检查\n- [ ] 待确认');
  for(const fragment of ['<h2>检查结果</h2>','<strong>正常</strong>','<code>nvidia-smi</code>','<ol>','<ul>','<blockquote>','<table>','<th>主机</th>','<del>离线</del>','type="checkbox"'])assert.ok(html.includes(fragment),fragment);
});

test('streaming renders unfinished code fences and preserves code indentation',()=>{
  const partial='```python\nif ready:\n    print("ok")';
  const html=render(partial);
  assert.match(html,/<pre><code class="language-python">/);
  assert.ok(html.includes('if ready:\n    print(&quot;ok&quot;)'));
  assert.equal(render(partial+'\n```'),html);
  assert.match(render('正在输出 **粗体'),/正在输出/);
});

test('model-provided HTML and unsafe links cannot run; external links open safely',()=>{
  const html=render('<script>alert(1)</script>\n\n<img src=x onerror=alert(1)>\n\n[危险](javascript:alert%281%29)\n\n[文档](https://example.com/docs)');
  assert.doesNotMatch(html,/<script|<img|href="javascript:/);
  assert.match(html,/href="https:\/\/example.com\/docs"[^>]*target="_blank"[^>]*rel="noopener noreferrer"/);
});
