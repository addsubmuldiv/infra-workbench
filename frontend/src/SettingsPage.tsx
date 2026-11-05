import {useEffect,useState,type ReactNode} from 'react';
import {SlidersHorizontal,Sparkles,Plug,Info} from 'lucide-react';
import {t,useLocale} from './i18n';
import './settingsNavigation.css';
import {LaunchSettingsPage} from './LaunchSettingsPage';
import {AgentSettingsPage} from './AgentSettingsPage';
import {MCPSettings} from './MCPSettings';
import {MailSettingsPage} from './MailSettingsPage';
import {SkillsSettings} from './SkillsSettings';
import {LanguageSettings} from './LanguageSettings';
import {DesktopUpdates} from './DesktopUpdatePanel';

const storageKey='iwb.settings.navigation';
const categoryIds=['general','ai','integrations','about'] as const;
type Category=typeof categoryIds[number];
type Navigation={category:Category;ai:'models'|'skills';integrations:'mcp'|'mail'};
function readNavigation():Navigation{
  const defaults:Navigation={category:'general',ai:'models',integrations:'mcp'};
  try{const saved=JSON.parse(localStorage.getItem(storageKey)||'null');
    if(saved&&typeof saved==='object')return {
      category:categoryIds.includes(saved.category)?saved.category:defaults.category,
      ai:saved.ai==='skills'?'skills':'models',integrations:saved.integrations==='mail'?'mail':'mcp',
    };
  }catch{/* Navigation remains usable when browser storage is unavailable. */}
  return defaults;
}

export default function SettingsPage(){
  useLocale();
  const [navigation,setNavigation]=useState(readNavigation);
  const activePanel=navigation.category==='ai'?navigation.ai:navigation.category==='integrations'?navigation.integrations:navigation.category;
  // Keep visited forms mounted so switching categories preserves unsaved edits.
  const [visited,setVisited]=useState(()=>new Set<string>([activePanel]));
  const categories=[
    {id:'general',Icon:SlidersHorizontal,label:t('通用','General'),description:t('语言、启动方式与桌面浮窗。','Language, launch preferences and desktop monitor.')},
    {id:'ai',Icon:Sparkles,label:t('AI 助手','AI assistant'),description:t('配置模型连接与助手技能。','Configure model connections and assistant skills.')},
    {id:'integrations',Icon:Plug,label:t('集成服务','Integrations'),description:t('连接 MCP 服务与邮件通知。','Connect MCP services and email notifications.')},
    {id:'about',Icon:Info,label:t('关于与帮助','About and help'),description:t('软件更新与使用指引。','Software updates and getting started.')},
  ] as const;
  const current=categories.find(category=>category.id===navigation.category)!;
  function navigate(next:Navigation){
    setNavigation(next);
    const panel=next.category==='ai'?next.ai:next.category==='integrations'?next.integrations:next.category;
    setVisited(previous=>new Set([...previous,panel]));
    try{localStorage.setItem(storageKey,JSON.stringify(next))}catch{/* Optional preference. */}
  }
  useEffect(()=>{
    const showUpdates=()=>navigate({...readNavigation(),category:'about'});
    window.addEventListener('iwb:show-update-settings',showUpdates);
    return()=>window.removeEventListener('iwb:show-update-settings',showUpdates);
  },[]);
  const panels:Record<string,()=>ReactNode>={
    general:()=> <><LanguageSettings/><LaunchSettingsPage/></>,
    models:()=> <AgentSettingsPage/>,skills:()=> <SkillsSettings/>,
    mcp:()=> <MCPSettings/>,mail:()=> <MailSettingsPage/>,
    about:()=> <><DesktopUpdates/><section className="settings-card settings-help-card"><h2>{t('帮助与演示','Help and demo')}</h2><p className="settings-help"><button type="button" className="secondary" onClick={()=>window.dispatchEvent(new Event('iwb:replay-getting-started'))}>{t('重播新手引导','Replay getting-started guide')}</button></p><p className="settings-help"><a href="?demo=1">{t('体验演示与新手引导（无需服务器）','Try the demo and guided tour (no server required)')}</a></p></section></>,
  };
  const tabs=navigation.category==='ai'?
    [{id:'models',label:t('模型配置','Model configuration')},{id:'skills',label:'Skills'}]:
    navigation.category==='integrations'?[{id:'mcp',label:'MCP'},{id:'mail',label:t('邮件','Email')}]:[];
  return <div className="settings-navigation-layout">
    <nav className="settings-category-nav" aria-label={t('设置分类','Settings categories')}>
      {categories.map(({id,Icon,label})=><button key={id} type="button" aria-current={navigation.category===id?'page':undefined} onClick={()=>navigate({...navigation,category:id})}><Icon size={18}/><span>{label}</span></button>)}
    </nav>
    <div className="settings-category-content">
      <div className="settings-category-heading"><h2>{current.label}</h2><p>{current.description}</p></div>
      {tabs.length>0&&<div className="settings-category-tabs" role="group" aria-label={current.label}>{tabs.map(tab=><button key={tab.id} type="button" aria-pressed={activePanel===tab.id} onClick={()=>navigate(navigation.category==='ai'?{...navigation,ai:tab.id as Navigation['ai']}:{...navigation,integrations:tab.id as Navigation['integrations']})}>{tab.label}</button>)}</div>}
      {Object.entries(panels).map(([id,render])=>visited.has(id)&&<div key={id} className="settings-category-panel" hidden={activePanel!==id}>{render()}</div>)}
    </div>
  </div>;
}
