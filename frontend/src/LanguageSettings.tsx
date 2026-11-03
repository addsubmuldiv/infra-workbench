import {Languages} from 'lucide-react';
import {setLocale,t,useLocale,type Locale} from './i18n';
export function LanguageSettings(){
 const locale=useLocale();
 return <section className="settings-page" aria-labelledby="language-heading">
  <div className="settings-section-title"><Languages size={20}/><div><h2 id="language-heading">{t('界面语言','Interface language')}</h2><p>{t('切换后立即生效，并同步到使用同一后台的工作台窗口。','Applies immediately and syncs across workbench windows using this backend.')}</p></div></div>
  <div className="settings-card"><label className="form-label" htmlFor="interface-language">{t('语言','Language')}<select id="interface-language" value={locale} onChange={event=>setLocale(event.target.value as Locale)}><option value="zh">简体中文</option><option value="en">English</option></select></label><p className="settings-help">{t('只切换界面文案；机器名称、文件内容、终端输出和模型回复保留原文。','Changes interface text. Machine names, file contents, terminal output, and model responses retain their original language.')}</p></div>
 </section>;
}
