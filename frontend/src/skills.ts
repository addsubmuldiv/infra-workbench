import {SKILLS_UPLOAD_MAX_BYTES} from './internalDefaults.ts';
import {formatBytes} from './internalPolicy.ts';
import {t} from './i18n.ts';
export type SkillReceipt={name:string;version:number|string;source:string};
export type SkillMeta=SkillReceipt&{description:string;enabled:boolean;warnings:string[]};
export type SkillVersion={version:number;created?:number;content_hash?:string};
export type SkillFile={path:string;size:number;text:boolean};
export type SkillDetail=SkillMeta&{files:Record<string,string>;versions:SkillVersion[];file_manifest?:SkillFile[]};
export type SkillDraft={id:string;revision:number;files:Record<string,string>;skill_name?:string|null;base_version?:number|null;file_manifest?:SkillFile[]};
export type SkillValidation={valid:boolean;errors:string[];warnings:string[];missing_tools?:string[]};
async function checked(response:Response){
  if(!response.ok){let value;try{value=await response.json()}catch{}throw new Error(typeof value?.detail==='string'?value.detail:t('技能操作失败，请检查后台版本和输入。','Skill operation failed. Check the backend version and input.'))}
  return response;
}
export async function skillRequest<T>(path='',method='GET',body?:unknown,signal?:AbortSignal,request:typeof fetch=fetch):Promise<T>{
  const response=await checked(await request('/api/skills'+path,{method,cache:'no-store',signal,headers:{'Content-Type':'application/json','X-IWB':'1'},body:body===undefined?undefined:JSON.stringify(body)}));
  if(response.status===204)return undefined as T;
  return response.json() as Promise<T>;
}
export async function importSkill(file:File,signal?:AbortSignal,request:typeof fetch=fetch):Promise<SkillDraft>{
  if(file.size>SKILLS_UPLOAD_MAX_BYTES)throw new Error(t(`导入文件不能超过 ${formatBytes(SKILLS_UPLOAD_MAX_BYTES)}。`,`Imported files must not exceed ${formatBytes(SKILLS_UPLOAD_MAX_BYTES)}.`));
  if(!/\.(md|zip)$/i.test(file.name))throw new Error(t('请选择 Markdown 或 ZIP 文件。','Select a Markdown or ZIP file.'));
  const response=await checked(await request('/api/skills/import?filename='+encodeURIComponent(file.name),{method:'POST',signal,headers:{'Content-Type':'application/octet-stream','X-IWB':'1'},body:file}));
  return response.json() as Promise<SkillDraft>;
}
export async function exportSkill(name:string,version?:number|string,request:typeof fetch=fetch):Promise<Blob>{
  const response=await checked(await request('/api/skills/'+encodeURIComponent(name)+'/export'+(version===undefined?'':'?version='+encodeURIComponent(version)),{headers:{'X-IWB':'1'},cache:'no-store'}));
  return response.blob();
}
export function skillMarkdown(name:string,description:string,body:string):string{
  return `---\nname: ${JSON.stringify(name.trim())}\ndescription: ${JSON.stringify(description.trim())}\n---\n\n${body}\n`;
}
export function copySkillFiles(files:Record<string,string>,name:string):Record<string,string>{
  return {...files,'SKILL.md':files['SKILL.md'].replace(/^(---\r?\n)([\s\S]*?)(?=\r?\n---(?:\r?\n|$))/,(_all,opening,metadata)=>opening+metadata.replace(/^name:[^\n]*/m,'name: '+JSON.stringify(name.trim())))};
}
export function installedSkill(output:string,status:string):{name:string;version:number|string}|null{
  if(status!=='succeeded')return null;
  try{const envelope=JSON.parse(output);if(envelope.ok===false)return null;const value=envelope.data??envelope.result??envelope;
    const name=value.name??value.skill_name??value.skill_id?.replace(/^user:/,'');
    return typeof name==='string'&&['installed','updated'].includes(value.status)&&['number','string'].includes(typeof value.version)?{name,version:value.version}:null;
  }catch{return null}
}
