import {useEffect,useState} from 'react';
import {A2uiSurface,createComponentImplementation,type ReactCatalogComponent} from '@a2ui/react';
import {AgentToRendererMessageSchema,Catalog,MessageProcessor,childList,type SurfaceModel} from '@a2ui/web_core/v1_0';
import {z} from 'zod';
import {t} from '../../shared/i18n';
import './assistantA2ui.css';

export type AssistantSurface={
  version:'1.0';
  createSurface:{surfaceId:string;catalogId:string;components:unknown[]};
};

type Cell=string|number|null;
type Sort={index:number;direction:1|-1};
const unknownValue=()=>t('未知','Unknown');
const comparison=new Intl.Collator(undefined,{numeric:true});

function DataTable({title,columns,rows}:{title:string;columns:string[];rows:Cell[][]}){
  const [sort,setSort]=useState<Sort|null>(null);
  const visible=sort?[...rows].sort((left,right)=>{
    const a=left[sort.index],b=right[sort.index];
    if(a===b)return 0;
    if(a===null)return 1;
    if(b===null)return -1;
    return sort.direction*(typeof a==='number'&&typeof b==='number'?a-b:comparison.compare(String(a),String(b)));
  }):rows;
  return <div className="a2ui-widget a2ui-table" data-a2ui-component="DataTable">
    <table>
      <caption>{title}</caption>
      <thead><tr>{columns.map((column,index)=><th scope="col" key={index} aria-sort={sort?.index===index?(sort.direction===1?'ascending':'descending'):undefined}>
        <button type="button" onClick={()=>setSort({index,direction:sort?.index===index&&sort.direction===1?-1:1})}>
          {column}<span aria-hidden="true">{sort?.index===index?(sort.direction===1?' ↑':' ↓'):' ↕'}</span>
        </button>
      </th>)}</tr></thead>
      <tbody>{visible.map((row,index)=><tr key={index}>{row.map((cell,column)=><td key={column}>{cell??unknownValue()}</td>)}</tr>)}</tbody>
    </table>
  </div>;
}

function BarChart({title,labels,values,unit}:{title:string;labels:string[];values:(number|null)[];unit:string}){
  const max=Math.max(1,...values.map(value=>value??0));
  return <figure className="a2ui-widget a2ui-chart" data-a2ui-component="BarChart">
    <figcaption>{title}</figcaption>
    <ul>{labels.map((label,index)=>{
      const value=values[index]??null;
      return <li key={index}>
        <span>{label}</span>
        <span className="a2ui-bar-track" aria-hidden="true"><i style={{width:`${100*(value??0)/max}%`}}/></span>
        <strong>{value===null?unknownValue():[value,unit].filter(item=>item!=='').join(' ')}</strong>
      </li>;
    })}</ul>
  </figure>;
}

const layoutSchema=z.object({children:childList()});
// The pinned SDK predates the final v1.0 wire version spelling.
const sdkVersion='v1.0';
const catalog=new Catalog<ReactCatalogComponent>('urn:infra-workbench:a2ui-prototype',sdkVersion,[
  createComponentImplementation({name:'Column',schema:layoutSchema},({props,buildChild})=>
    <div className="a2ui-column" data-a2ui-component="Column">{props.children.map(child=>typeof child==='string'?buildChild(child):buildChild(child.id,child.basePath))}</div>),
  createComponentImplementation({name:'Row',schema:layoutSchema},({props,buildChild})=>
    <div className="a2ui-row" data-a2ui-component="Row">{props.children.map(child=>typeof child==='string'?buildChild(child):buildChild(child.id,child.basePath))}</div>),
  createComponentImplementation({name:'Text',schema:z.object({text:z.string(),variant:z.enum(['heading','body'])})},({props})=>
    props.variant==='heading'?<h3 className="a2ui-heading">{props.text}</h3>:<p className="a2ui-note">{props.text}</p>),
  createComponentImplementation({name:'DataTable',schema:z.object({
    title:z.string(),columns:z.array(z.string()),rows:z.array(z.array(z.union([z.string(),z.number(),z.null()]))),
  })},({props})=><DataTable {...props} columns={props.columns.filter(column=>typeof column==='string')}/>),
  createComponentImplementation({name:'BarChart',schema:z.object({
    title:z.string(),labels:z.array(z.string()),values:z.array(z.number().nullable()),unit:z.string(),
  })},({props})=><BarChart {...props} labels={props.labels.filter(label=>typeof label==='string')}/>),
]);

export default function AssistantA2ui({message}:{message:AssistantSurface}){
  const [surface,setSurface]=useState<SurfaceModel<ReactCatalogComponent>|null|undefined>(undefined);
  useEffect(()=>{
    const processor=new MessageProcessor<ReactCatalogComponent>([catalog],undefined,{version:sdkVersion});
    try{
      processor.processMessages(AgentToRendererMessageSchema.parse({...message,version:sdkVersion}));
      setSurface(processor.model.getSurface(message.createSurface.surfaceId)??null);
    }catch{
      setSurface(null);
    }
    return ()=>processor.dispose();
  },[message]);
  if(surface===undefined)return null;
  if(surface===null)return <small className="a2ui-unavailable">{t('此回复的界面无法显示。','The interface for this reply could not be displayed.')}</small>;
  return <section className="assistant-a2ui" aria-label={t('助手生成的界面','Assistant-generated interface')}><A2uiSurface surface={surface}/></section>;
}
