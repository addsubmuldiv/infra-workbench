import {ui} from './assistantLocale';
import React,{useEffect,useRef,useState} from 'react';
import {useLocale} from './i18n';
import {latestUpdate} from './latestUpdate';
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

const streamingPlugins=[remarkGfm];
const streamingComponents:Components={...components,pre:({node,children,...props})=>
  <div className="chat-code-container"><pre {...props}>{children}</pre><button className="chat-code-insert" onClick={event=>{
    const element=event.currentTarget;window.dispatchEvent(new CustomEvent(TERMINAL_PICK_EVENT,{detail:{text:element.previousElementSibling?.textContent||'',element}}));
  }}>{ui('填入终端…')}</button></div>};

// Completed replies reuse their parsed tree. Streaming text is parsed at most
// every 100ms; syntax highlighting, math and diagram layout wait for completion.
const MarkdownBody=React.memo(function MarkdownBody({children,streaming}:{children:string;streaming:boolean}){
  useLocale();
  return <Markdown remarkPlugins={streaming?streamingPlugins:plugins} rehypePlugins={streaming?[]:rehypePlugins} skipHtml components={streaming?streamingComponents:components}>{children}</Markdown>;
});
export const ChatMarkdown=React.memo(function ChatMarkdown({children,streaming=false}:{children:string;streaming?:boolean}){
  const [visible,setVisible]=useState(children);
  const buffer=useRef<ReturnType<typeof latestUpdate<string>>|null>(null);
  useEffect(()=>{
    const pending=latestUpdate(setVisible);buffer.current=pending;
    return()=>{pending.dispose();buffer.current=null};
  },[]);
  useEffect(()=>{buffer.current?.push(children,!streaming)},[children,streaming]);
  return <div className="chat-markdown"><MarkdownBody streaming={streaming}>{streaming?visible:children}</MarkdownBody></div>;
});
