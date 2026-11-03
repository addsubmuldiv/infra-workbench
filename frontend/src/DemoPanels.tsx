import React,{useState} from 'react';
import {t,useLocale} from './i18n';
import {demoRuntime} from './demoBootstrap';
import './demoPanels.css';
export function DemoAssistant(){
 useLocale();const [answer,setAnswer]=useState('');
 return <section className="demo-assistant"><h2>{t('AI 助手演示','AI assistant demo')}</h2><p>{t('以下为预设回答示例，用于展示操作方式，不调用模型。真实使用时可在设置中配置自己的模型接口。','These preset examples show the workflow without calling a model. Configure your own model in Settings for real use.')}</p>
 <button className="secondary" onClick={()=>{const hosts=demoRuntime!.getHosts();const available=hosts.filter(h=>h.snapshot.fresh&&h.snapshot.devices.some(d=>!d.processes.length));setAnswer(t(`【预设回答】当前模拟数据中，${available.map(h=>h.target).join('、')||'暂无机器'} 有空闲设备。请在资源筛选中核对设备数量和显存；预约只负责提醒，不预留设备。`,`[Preset response] Hosts with idle devices in the current simulated data: ${available.map(h=>h.target).join(', ')||'none'}. Check device count and memory in the resource finder. Alerts do not reserve devices.`))}}>{t('查找空闲资源','Find idle resources')}</button>
 <button className="secondary" onClick={()=>setAnswer(t('【预设回答】示例 train.log 中 loss 随步数下降。真实助手可读取指定日志，再引用原始行说明结果；此处没有读取真实文件。','[Preset response] Loss decreases across steps in the sample train.log. The real assistant can read a selected log and cite original lines. No real file was read here.'))}>{t('分析示例日志','Analyze sample log')}</button>
 {answer&&<p className="demo-answer" role="status">{answer}</p>}</section>
}
export function DemoTerminal({close}:{close:()=>void}){
 const [input,setInput]=useState(''),[lines,setLines]=useState(['Demo terminal — no shell or SSH. Try: help, pwd, ls, cat train.log']);
 const run=(event:React.FormEvent)=>{event.preventDefault();const command=input.trim();const result:Record<string,string>={help:'help · pwd · ls · cat train.log · clear',pwd:'/demo',ls:'README.md  demo.yaml  train.log','cat train.log':'step=1 loss=2.2000\nstep=2 loss=1.8333\nstep=3 loss=1.5714'};setLines(old=>command==='clear'?[]:[...old,'demo$ '+command,result[command]??'Unsupported demo command. No command was executed.']);setInput('')};
 return <section className="demo-terminal" role="dialog" aria-label={t('演示终端','Demo terminal')}><div><strong>{t('演示终端 · 仅模拟命令','Demo terminal · simulated commands only')}</strong><button className="secondary" onClick={close}>{t('关闭终端','Close terminal')}</button></div><pre aria-live="polite">{lines.join('\n')}</pre><form onSubmit={run}><label>demo$ <input aria-label={t('演示命令','Demo command')} value={input} onChange={e=>setInput(e.target.value)} autoComplete="off"/></label><button className="secondary">{t('执行模拟命令','Run simulated command')}</button></form></section>
}
