import {AutomationSettings} from './AutomationSettings';
import {LaunchSettingsPage} from './LaunchSettingsPage';
import {AgentSettingsPage} from './AgentSettingsPage';
import {MCPSettings} from './MCPSettings';
import {MailSettingsPage} from './MailSettingsPage';
import {SkillsSettings} from './SkillsSettings';
import {LanguageSettings} from './LanguageSettings';
import {DesktopUpdates} from './DesktopUpdatePanel';

export default function SettingsPage(){
  return <><LanguageSettings/><DesktopUpdates/><LaunchSettingsPage/><AgentSettingsPage/><SkillsSettings/><AutomationSettings/><MCPSettings/><MailSettingsPage/></>;
}
