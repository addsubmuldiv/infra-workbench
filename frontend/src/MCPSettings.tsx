import React,{useEffect,useState} from 'react';
import {Bot,Copy,Check} from 'lucide-react';
import './settings.css';

type MCPInfo={path:string;transport:string;tools:{name:string;title:string;description:string}[]};

export function MCPSettings(){
  const [info,setInfo]=useState<MCPInfo|null>(null),[error,setError]=useState(''),[copied,setCopied]=useState(false);
  useEffect(()=>{let alive=true;fetch('/api/mcp-info',{headers:{'X-IWB':'1'}}).then(async response=>{
    if(!response.ok)throw new Error('无法读取 MCP 能力，请确认已启动新版后台。');
    return response.json() as Promise<MCPInfo>;
  }).then(value=>{if(alive)setInfo(value)}).catch(error=>{if(alive)setError(error.message)});return()=>{alive=false}},[]);
  const endpoint=window.location.origin+(info?.path||'/mcp');
  const copy=async()=>{try{await navigator.clipboard.writeText(endpoint);setCopied(true);setError('')}catch{setError('复制失败，请选中上方地址手动复制。')}};
  return <section className="settings-page mcp-settings" aria-label="外部 Agent（MCP）">
    <div className="settings-section-title"><Bot size={20}/><div><h2>外部 Agent（MCP）</h2><p>把 MCP 地址添加到 agent 客户端，连接后会自动发现工具、参数和使用示例。</p></div></div>
    <div className="settings-card"><label className="form-label">本机 MCP 地址<div className="mcp-endpoint"><input aria-label="MCP 地址" readOnly value={endpoint} onFocus={event=>event.target.select()}/><button className="secondary" onClick={copy}>{copied?<Check size={15}/>:<Copy size={15}/ >}{copied?'已复制':'复制地址'}</button></div></label>
      <p>{info?`${info.transport} · ${info.tools.length} 个工具已就绪`:'正在读取工具…'}</p>
      {error&&<div className="settings-error" role="alert">{error}</div>}
      {info&&<dl className="mcp-tools">{info.tools.map(tool=><div key={tool.name}><dt>{tool.title}<code>{tool.name}</code></dt><dd>{tool.description.split('。')[0]}。</dd></div>)}</dl>}
      <p>支持查询资源、创建和修改预约、设置监控、操作服务器文件和对比训练日志。客户端可读取内置技能组织流程；写入应按你的明确要求执行。普通查询不返回密码。</p>
      <p>此地址供本机客户端使用。远端或容器中的 agent 需让 MCP 客户端通过现有代理或隧道访问这台电脑；远端的 localhost 指向远端自己。</p>
    </div>
  </section>;
}
