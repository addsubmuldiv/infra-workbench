import {LaunchSettingsPage} from './LaunchSettingsPage';
import {AgentSettingsPage} from './AgentSettingsPage';
import {MCPSettings} from './MCPSettings';
import {MailSettingsPage} from './MailSettingsPage';
import {SkillsSettings} from './SkillsSettings';

export default function SettingsPage(){
  return <><LaunchSettingsPage/><AgentSettingsPage/><SkillsSettings/><MCPSettings/><MailSettingsPage/></>;
}
