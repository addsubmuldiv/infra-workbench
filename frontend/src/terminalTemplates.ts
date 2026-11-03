import {toolText as tt} from './toolI18n.ts';
export type Snippet={id?:string;name:string;command:string};
export const examples:Snippet[]=[
  {name:'训练任务',command:'CUDA_VISIBLE_DEVICES={{cards}} torchrun --nproc_per_node={{count}} --master_port={{port}} {{script}}'},
  {name:'查看日志',command:'tail -n 100 -f -- {{log}}'},
  {name:'切换 Conda 环境',command:'conda activate {{environment}}'},
];
export const variables=(text:string)=>[...new Set([...text.matchAll(/\{\{([a-zA-Z_][\w]*)\}\}/g)].map(match=>match[1]))];
export function renderTemplate(text:string,values:Record<string,string>){
  const missing=variables(text).filter(key=>!values[key]?.trim());
  if(missing.length)return {command:'',error:tt("请填写：")+missing.join('、')};
  if(Object.values(values).some(value=>/[\x00-\x1f\x7f]/.test(value)||value.length>4096))return {command:'',error:tt("参数只能包含单行文本")};
  const command=text.replace(/\{\{([a-zA-Z_][\w]*)\}\}/g,(_,key)=>"'"+values[key].replace(/'/g,"'\\''")+"'");
  return {command,error:command.length>8192?tt("命令过长"):''};
}
