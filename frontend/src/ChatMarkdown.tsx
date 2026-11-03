import {ui} from './assistantLocale';
import React from 'react';
import Markdown,{type Components} from 'react-markdown';
import remarkGfm from 'remark-gfm';
import remarkMath from 'remark-math-extended';
import rehypeKatex from 'rehype-katex';
import rehypeHighlight from 'rehype-highlight';
import 'katex/dist/katex.min.css';
import {MermaidDiagram} from './MermaidDiagram';
import {TERMINAL_PICK_EVENT} from './terminalInput';

// Keep renderer identities stable so streaming does not remount scrolled tables.
const components:Components={
  pre:({node,children,...props})=>{
    const code=node?.children[0];
    if(code?.type==='element'&&code.tagName==='code'&&
      Array.isArray(code.properties.className)&&code.properties.className.includes('language-mermaid')){
      const source=code.children.filter(child=>child.type==='text').map(child=>child.value).join('');
      return <MermaidDiagram source={source}/>;
    }
    return <div className="chat-code-container"><pre {...props}>{children}</pre><button className="chat-code-insert" onClick={event=>{const element=event.currentTarget;window.dispatchEvent(new CustomEvent(TERMINAL_PICK_EVENT,{detail:{text:element.previousElementSibling?.textContent||'',element}}))}}>{ui('填入终端…')}</button></div>;
  },
  a:({node,...props})=><a {...props} target={/^https?:\/\//i.test(props.href||'')?'_blank':undefined} rel="noopener noreferrer"/>,
  table:({node,...props})=><div className="chat-markdown-table" role="region" aria-label={ui("消息表格")} tabIndex={0}><table {...props}/></div>,
  img:({node,...props})=><img {...props} loading="lazy"/>,
};
const plugins=[remarkGfm,remarkMath];
const rehypePlugins:React.ComponentProps<typeof Markdown>['rehypePlugins']=[rehypeKatex,[rehypeHighlight,{plainText:['mermaid']}]];

// Reparse the current text on each stream update, including unfinished fences.
export function ChatMarkdown({children}:{children:string}){
  return <div className="chat-markdown"><Markdown remarkPlugins={plugins} rehypePlugins={rehypePlugins} skipHtml components={components}>{children}</Markdown></div>;
}
