import React,{useEffect,useId,useState} from 'react';
import DOMPurify from 'dompurify';

// One shared import; Mermaid serializes render calls internally.
let engine:Promise<typeof import('mermaid')['default']>|undefined;
function loadMermaid(){
  return engine??=(import('mermaid').then(({default:mermaid})=>{
    mermaid.initialize({startOnLoad:false,securityLevel:'strict',theme:'neutral',
      htmlLabels:false,suppressErrorRendering:true,maxTextSize:50000,
      secure:['securityLevel','startOnLoad','maxTextSize','suppressErrorRendering','htmlLabels']});
    return mermaid;
  }).catch(error=>{engine=undefined;throw error}));
}

export function MermaidDiagram({source}:{source:string}){
  const id='chat-mermaid-'+useId().replace(/[^a-zA-Z0-9_-]/g,'');
  const [result,setResult]=useState<{source:string;svg?:string;failed?:boolean}>();
  useEffect(()=>{
    let cancelled=false;
    // Coalesce stream updates rather than running layout for every token.
    const timer=setTimeout(async()=>{
      let container:HTMLDivElement|undefined;
      try{
        if(source.length>50000)throw new Error('Diagram exceeds render limit');
        const mermaid=await loadMermaid();
        if(cancelled)return;
        container=document.createElement('div');
        container.setAttribute('aria-hidden','true');
        container.style.cssText='position:fixed;left:-100000px;top:0;width:1200px;pointer-events:none';
        document.body.appendChild(container);
        const {svg}=await mermaid.render(id,source,container);
        // Only library-generated, sanitized SVG reaches the message DOM.
        const safe=DOMPurify.sanitize(svg,{USE_PROFILES:{svg:true,svgFilters:true},FORBID_TAGS:['foreignObject']});
        if(!cancelled)setResult({source,svg:safe});
      }catch{
        if(!cancelled)setResult({source,failed:true});
      }finally{container?.remove()}
    },250);
    return ()=>{cancelled=true;clearTimeout(timer)};
  },[source,id]);
  const current=result?.source===source?result:undefined;
  return <figure className="chat-mermaid" aria-label="Mermaid 图表">
    {current?.svg?<div className="chat-mermaid-canvas" role="region" aria-label="Mermaid 图表，可横向滚动" tabIndex={0}
      ref={node=>{
        const svg=node?.querySelector('svg');
        if(svg?.viewBox.baseVal.width)svg.style.width=svg.viewBox.baseVal.width+'px';
      }} dangerouslySetInnerHTML={{__html:current.svg}}/>:
      <p className="chat-mermaid-status" role="status">{current?.failed?'图表暂未完成或语法有误，可查看源码。':'正在绘制图表…'}</p>}
    <details><summary>图表源码</summary><pre><code>{source}</code></pre></details>
  </figure>;
}
