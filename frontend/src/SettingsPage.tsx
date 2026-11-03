import {LaunchSettingsPage} from './LaunchSettingsPage';
import {AgentSettingsPage} from './AgentSettingsPage';
import {MCPSettings} from './MCPSettings';
import {MailSettingsPage} from './MailSettingsPage';
import {SkillsSettings} from './SkillsSettings';
import {LanguageSettings} from './LanguageSettings';

export default function SettingsPage(){
  return <><LanguageSettings/><LaunchSettingsPage/><AgentSettingsPage/><SkillsSettings/><MCPSettings/><MailSettingsPage/></>;
}
