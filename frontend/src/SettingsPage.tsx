import {t,useLocale} from './i18n';
import {AutomationSettings} from './AutomationSettings';
import {LaunchSettingsPage} from './LaunchSettingsPage';
import {AgentSettingsPage} from './AgentSettingsPage';
import {MCPSettings} from './MCPSettings';
import {MailSettingsPage} from './MailSettingsPage';
import {SkillsSettings} from './SkillsSettings';
import {LanguageSettings} from './LanguageSettings';
import {DesktopUpdates} from './DesktopUpdatePanel';

export default function SettingsPage(){
  useLocale();
  return <><LanguageSettings/><DesktopUpdates/><LaunchSettingsPage/><AgentSettingsPage/><SkillsSettings/><AutomationSettings/><MCPSettings/><MailSettingsPage/><section className="settings-card"><h2>{t("帮助与演示","Help and demo")}</h2><p className="settings-help"><a href="?demo=1">{t("体验演示与新手引导（无需服务器）","Try the demo and guided tour (no server required)")}</a></p></section></>;
}
