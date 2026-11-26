import Markdown, {type Components} from 'react-markdown';
import remarkGfm from 'remark-gfm';
import {RELEASES_URL} from './desktopUpdates';

const plugins=[remarkGfm];
const components:Components={
  a:({node,...props})=><a {...props} target="_blank" rel="noreferrer"/>,
  img:({node,...props})=><img {...props} loading="lazy" referrerPolicy="no-referrer"/>,
};

function releaseUrl(value:string){
  try{
    const url=new URL(value,`${RELEASES_URL}/`);
    if(url.protocol==='https:'||url.protocol==='http:')return url.href;
  }catch{/* Malformed URLs are omitted. */}
  return undefined;
}

export default function ReleaseNotes({children}:{children:string}){
  return <div className="desktop-update-notes"><Markdown remarkPlugins={plugins} components={components} urlTransform={releaseUrl} skipHtml>{children}</Markdown></div>;
}
