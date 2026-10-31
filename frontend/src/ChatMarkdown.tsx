import React from 'react';
import Markdown,{type Components} from 'react-markdown';
import remarkGfm from 'remark-gfm';

// Keep renderer identities stable so streaming does not remount scrolled tables.
const components:Components={
  a:({node,...props})=><a {...props} target={/^https?:\/\//i.test(props.href||'')?'_blank':undefined} rel="noopener noreferrer"/>,
  table:({node,...props})=><div className="chat-markdown-table" role="region" aria-label="消息表格" tabIndex={0}><table {...props}/></div>,
  img:({node,...props})=><img {...props} loading="lazy"/>,
};
const plugins=[remarkGfm];

// Reparse the current text on each stream update, including unfinished fences.
export function ChatMarkdown({children}:{children:string}){
  return <div className="chat-markdown"><Markdown remarkPlugins={plugins} skipHtml components={components}>{children}</Markdown></div>;
}
