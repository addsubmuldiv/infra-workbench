import {i18nMock} from './i18n-mock.mjs';
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import ts from 'typescript';
import React from 'react';
import {renderToStaticMarkup} from 'react-dom/server';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import remarkMath from 'remark-math-extended';
import rehypeKatex from 'rehype-katex';
import rehypeHighlight from 'rehype-highlight';
import DOMPurify from 'dompurify';
import * as terminalInput from '../src/terminalInput.ts';

const diagramJs=ts.transpileModule(fs.readFileSync(new URL('../src/MermaidDiagram.tsx',import.meta.url),'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,jsx:ts.JsxEmit.React,esModuleInterop:true}}).outputText;
const diagramExports={};
new Function('require','exports',diagramJs)(name=>{
  const localized=i18nMock(name);if(localized)return localized;
  if(name==='react')return React;
  if(name==='dompurify')return DOMPurify;
  throw new Error('Unexpected diagram import: '+name);
},diagramExports);

const source=fs.readFileSync(new URL('../src/ChatMarkdown.tsx',import.meta.url),'utf8');
const js=ts.transpileModule(source,{compilerOptions:{module:ts.ModuleKind.CommonJS,jsx:ts.JsxEmit.React,esModuleInterop:true}}).outputText;
const exports={};
new Function('require','exports',js)(name=>{
  const localized=i18nMock(name);if(localized)return localized;
  if(name==='react')return React;
  if(name==='react-markdown')return ReactMarkdown;
  if(name==='./terminalInput')return terminalInput;
  if(name==='remark-gfm')return remarkGfm;
  if(name==='remark-math-extended')return remarkMath;
  if(name==='./MermaidDiagram')return diagramExports;
  if(name==='rehype-katex')return rehypeKatex;
  if(name==='rehype-highlight')return rehypeHighlight;
  if(name.endsWith('.css'))return {};
  throw new Error('Unexpected import: '+name);
},exports);
const render=content=>renderToStaticMarkup(React.createElement(exports.ChatMarkdown,{children:content}));

test('LaTeX backslash delimiters render math without interpreting code examples',()=>{
  assert.match(render(String.raw`能量 \(E=mc^2\)。`),/class="katex"/);
  assert.match(render(String.raw`\[\frac{1}{2}\]`),/class="katex-display"/);
  assert.match(render('\\[\n\\begin{aligned}a&=b\\\\c&=d\\end{aligned}\n\\]'),/class="katex-display"/);
  assert.doesNotMatch(render('`\\(x\\)`\n\n```text\n\\[x\\]\n```'),/class="katex"/);
  assert.match(render('未完成 \\(x+'),/未完成/);
});

test('Mermaid fences use a diagram container and retain source for fallback',()=>{
  const html=render('```mermaid\nflowchart LR\n  A[输入] --> B[输出]\n```');
  assert.match(html,/aria-label="Mermaid 图表"/);
  assert.match(html,/<summary>图表源码<\/summary>/);
  assert.match(html,/flowchart LR/);
  assert.doesNotMatch(render('`mermaid`'),/aria-label="Mermaid 图表"/);
});

test('renders inline math and display matrices with accessible MathML',()=>{
  const html=render('能量 $E=mc^2$。\n\n$$\n\\begin{pmatrix}1&2\\\\3&4\\end{pmatrix}\n$$');
  assert.match(html,/class="katex"/);
  assert.match(html,/class="katex-display"/);
  assert.match(html,/<math/);
  assert.match(html,/class="mtable"/);
});

test('math does not interpret code or escaped dollar signs and errors do not crash replies',()=>{
  assert.doesNotMatch(render('`$x^2$`\n\n```text\n$x^2$\n```\n\n价格 \\$20'),/class="katex"/);
  assert.match(render('$\\notARealCommand{x}$ 后续正文'),/后续正文/);
  assert.doesNotThrow(()=>render('未结束 $\\frac{1}{'));
  assert.doesNotMatch(render('$\\href{javascript:alert(1)}{click}$'),/href="javascript:/);
});

test('code blocks highlight known languages and preserve unknown ones',()=>{
  assert.match(render('```python\nprint(1)\n```'),/hljs-built_in/);
  assert.match(render('```unknown-language\nhello\n```'),/hello/);
});

test('renders footnotes, images, automatic links and separators',()=>{
  const html=render('说明[^1]\n\n[^1]: 补充内容\n\n![示意图](https://example.com/plot.png)\n\nhttps://example.com\n\n---');
  for(const fragment of ['data-footnote-ref','补充内容','alt="示意图"','loading="lazy"','href="https://example.com"','<hr/>'])assert.ok(html.includes(fragment),fragment);
});

test('assistant replies render headings, emphasis, nested lists, quotes and GFM tables',()=>{
  const html=render('## 检查结果\n\n**正常**，使用 `nvidia-smi`。\n\n1. 主机 A\n   - GPU 就绪\n\n> 仅供参考\n\n| 主机 | 状态 |\n| --- | --- |\n| A | ~~离线~~ 在线 |\n\n- [x] 已检查\n- [ ] 待确认');
  for(const fragment of ['<h2>检查结果</h2>','<strong>正常</strong>','<code>nvidia-smi</code>','<ol>','<ul>','<blockquote>','<table>','<th>主机</th>','<del>离线</del>','type="checkbox"'])assert.ok(html.includes(fragment),fragment);
});

test('streaming renders unfinished code fences and preserves code indentation',()=>{
  const partial='```python\nif ready:\n    print("ok")';
  const html=render(partial);
  assert.match(html,/<pre><code class="hljs language-python">/);
  const plain=html.replace(/<[^>]*>/g,'');
  assert.ok(plain.includes('if ready:\n    print(&quot;ok&quot;)'));
  assert.equal(render(partial+'\n```'),html);
  assert.match(render('正在输出 **粗体'),/正在输出/);
});

test('model-provided HTML and unsafe links cannot run; external links open safely',()=>{
  const html=render('<script>alert(1)</script>\n\n<img src=x onerror=alert(1)>\n\n[危险](javascript:alert%281%29)\n\n[文档](https://example.com/docs)');
  assert.doesNotMatch(html,/<script|<img|href="javascript:/);
  assert.match(html,/href="https:\/\/example.com\/docs"[^>]*target="_blank"[^>]*rel="noopener noreferrer"/);
});
