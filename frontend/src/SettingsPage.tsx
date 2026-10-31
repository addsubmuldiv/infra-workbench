import {AgentSettingsPage} from './AgentSettingsPage';
import {MCPSettings} from './MCPSettings';
import {MailSettingsPage} from './MailSettingsPage';
import {SkillsSettings} from './SkillsSettings';

export default function SettingsPage(){
  return <><AgentSettingsPage/><SkillsSettings/><MCPSettings/><MailSettingsPage/></>;
}
