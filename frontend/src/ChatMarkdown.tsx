import {ui} from './assistantLocale';
import React,{useEffect,useRef,useState} from 'react';
import {t,useLocale} from './i18n';
import {Check,Copy,Terminal} from 'lucide-react';
import {latestUpdate} from './latestUpdate';
import Markdown,{type Components} from 'react-markdown';
import remarkGfm from 'remark-gfm';
import remarkMath from 'remark-math-extended';
import rehypeKatex from 'rehype-katex';
import rehypeHighlight from 'rehype-highlight';
import 'katex/dist/katex.min.css';
import {MermaidDiagram} from './MermaidDiagram';
import {TERMINAL_PICK_EVENT} from './terminalInput';

function CodeBlock(props:React.ComponentPropsWithoutRef<'pre'>){
  const code=useRef<HTMLPreElement>(null);
  const reset=useRef<ReturnType<typeof setTimeout>>(undefined);
  const [status,setStatus]=useState<'copied'|'failed'>();
  useEffect(()=>()=>clearTimeout(reset.current),[]);
  const copy=async()=>{
    if(!code.current)return;
    try{
      await navigator.clipboard.writeText(code.current.textContent||'');
      setStatus('copied');
    }catch{
      setStatus('failed');
    }
    clearTimeout(reset.current);
    reset.current=setTimeout(()=>setStatus(undefined),2500);
  };
  const feedback=status==='copied'?ui('已复制'):status==='failed'?t('复制失败','Copy failed'):'';
  const copyLabel=t('复制代码','Copy code');
  const insertLabel=t('填入终端…','Insert into terminal…');
  return <div className="chat-code-container">
    <pre {...props} ref={code}/>
    <div className="chat-code-actions">
      <button type="button" aria-label={copyLabel} title={feedback||copyLabel} onClick={copy}>
        {status==='copied'?<Check size={14}/>:<Copy size={14}/>}
      </button>
      <button type="button" aria-label={insertLabel} title={insertLabel} onClick={event=>{
        window.dispatchEvent(new CustomEvent(TERMINAL_PICK_EVENT,{detail:{text:code.current?.textContent||'',element:event.currentTarget}}));
      }}><Terminal size={14}/></button>
      <span className="chat-code-feedback" role="status">{feedback}</span>
    </div>
  </div>;
}

// Keep renderer identities stable so streaming does not remount scrolled tables.
const components:Components={
  pre:({node,children,...props})=>{
    const code=node?.children[0];
    if(code?.type==='element'&&code.tagName==='code'&&
      Array.isArray(code.properties.className)&&code.properties.className.includes('language-mermaid')){
      const source=code.children.filter(child=>child.type==='text').map(child=>child.value).join('');
      return <MermaidDiagram source={source}/>;
    }
    return <CodeBlock {...props}>{children}</CodeBlock>;
  },
  a:({node,...props})=><a {...props} target={/^https?:\/\//i.test(props.href||'')?'_blank':undefined} rel="noopener noreferrer"/>,
  table:({node,...props})=><div className="chat-markdown-table" role="region" aria-label={ui("消息表格")} tabIndex={0}><table {...props}/></div>,
  img:({node,...props})=><img {...props} loading="lazy"/>,
};
const plugins=[remarkGfm,remarkMath];
const rehypePlugins:React.ComponentProps<typeof Markdown>['rehypePlugins']=[rehypeKatex,[rehypeHighlight,{plainText:['mermaid']}]];

const streamingPlugins=[remarkGfm];
const streamingComponents:Components={...components,pre:({node,...props})=><CodeBlock {...props}/>};

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
