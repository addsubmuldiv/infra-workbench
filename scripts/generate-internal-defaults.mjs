import {readFileSync,writeFileSync,existsSync,mkdirSync,renameSync,rmSync} from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {SCHEMA,PROBES} from './internal-defaults-schema.mjs';
export const ROOT=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');

// Walk JSON tokens before JSON.parse so duplicate (including escaped) object keys cannot disappear.
function rejectDuplicates(text){
 const tokens=text.match(/"(?:[^"\\]|\\.)*"|[{}\[\]:,]|-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?|true|false|null/g)||[];
 let index=0;
 function value(){
  const token=tokens[index++];
  if(token==='{'){
   const keys=new Set();
   while(tokens[index]!=='}'){
    const key=JSON.parse(tokens[index++]);
    if(keys.has(key))throw new Error(`Duplicate key: ${key}`);keys.add(key);
    if(tokens[index++]!==':')throw new Error('Invalid JSON');value();
    if(tokens[index]!==',')break;index++;
   }
   if(tokens[index++]!=='}')throw new Error('Invalid JSON');
  }else if(token==='['){
   while(tokens[index]!==']'){value();if(tokens[index]!==',')break;index++;}
   if(tokens[index++]!==']')throw new Error('Invalid JSON');
  }
 }
 value();
}
export function stripComments(text){return text.replace(/("(?:[^"\\]|\\.)*")|\/\*[\s\S]*?\*\/|\/\/[^\r\n]*/g,(match,string)=>string??match.replace(/[^\r\n]/g,' '));}
export function parseConfig(text){
 text=stripComments(text);const config=JSON.parse(text);rejectDuplicates(text);
 function validate(value,schema,prefix=''){
  if(!value||Array.isArray(value)||typeof value!=='object')throw new Error(`Expected object: ${prefix}`);
  for(const key of Object.keys(value))if(!Object.hasOwn(schema,key))throw new Error(`Unknown key: ${prefix}${key}`);
  for(const [key,rule] of Object.entries(schema)){
   if(!Object.hasOwn(value,key))throw new Error(`Missing key: ${prefix}${key}`);
   if(!Object.hasOwn(rule,'min'))validate(value[key],rule,`${prefix}${key}.`);
   else if(!Number.isSafeInteger(value[key])||value[key]<rule.min||value[key]>rule.max)throw new Error(`Invalid ${prefix}${key}: expected integer ${rule.min}..${rule.max}`);
  }
 }
 validate(config,SCHEMA);
 if(config.skills.file_max_bytes>config.skills.total_max_bytes)throw new Error('skills.file_max_bytes exceeds total_max_bytes');
 return config;
}
export function generateInternalDefaults(root=ROOT,{check=false}={}){
 const config=parseConfig(readFileSync(path.join(root,'config/internal-defaults.jsonc'),'utf8'));
 const entries=Object.entries(config).sort().flatMap(([group,fields])=>Object.entries(fields).sort().map(([key,value])=>({name:`${group}_${key}`.toUpperCase(),value,frontend:SCHEMA[group][key].frontend,description:SCHEMA[group][key].description})));
 const heading='Generated from config/internal-defaults.jsonc. DO NOT EDIT. Run node scripts/generate-internal-defaults.mjs';
 const formatter='\ndef format_bytes(value):\n    for unit, size in (("GiB", 1024**3), ("MiB", 1024**2), ("KiB", 1024)):\n        if value >= size and value % size == 0: return str(value // size) + " " + unit\n    return str(value) + " B"\n';
 const outputs=[['backend/internal_defaults.py',`# ${heading}\n`+entries.map(e=>`# ${e.description}\n${e.name} = ${e.value}\n`).join('')+formatter],['frontend/src/internalDefaults.ts',`// ${heading}\n`+entries.filter(e=>e.frontend).map(e=>`// ${e.description}\nexport const ${e.name} = ${e.value};\n`).join('')]];
 for(const [file,aliases] of Object.entries(PROBES)){
  const source=readFileSync(path.join(root,file),'utf8').replace(/\r\n/g,'\n');
  const begin='# BEGIN GENERATED INTERNAL DEFAULTS',end='# END GENERATED INTERNAL DEFAULTS';
  if(source.split(begin).length!==2||source.split(end).length!==2||source.indexOf(end)<source.indexOf(begin))throw new Error(`Missing or duplicate generated markers: ${file}`);
  const block=begin+'\n# '+heading+'\n'+Object.entries(aliases).map(([name,target])=>{
   const entry=entries.find(e=>e.name===target);if(!entry)throw new Error(`Unknown probe constant ${target}`);return `# ${entry.description}\n${name} = ${entry.value}\n`;
  }).join('')+formatter+'\n'+end;
  outputs.push([file,source.slice(0,source.indexOf(begin))+block+source.slice(source.indexOf(end)+end.length)]);
 }
 const changed=outputs.filter(([file,content])=>!existsSync(path.join(root,file))||readFileSync(path.join(root,file),'utf8').replace(/\r\n/g,'\n')!==content);
 if(check&&changed.length)throw new Error('Generated defaults out of date: '+changed.map(([file])=>file).join(', '));
 if(!check)for(const [file,content] of changed){const target=path.join(root,file),temp=target+'.tmp';mkdirSync(path.dirname(target),{recursive:true});try{writeFileSync(temp,content);renameSync(temp,target)}finally{rmSync(temp,{force:true})}}
 return outputs.map(([file])=>file);
}
if(process.argv[1]&&path.resolve(process.argv[1])===fileURLToPath(import.meta.url)){
 if(process.argv.slice(2).some(arg=>arg!=='--check'))throw new Error('Use generate-internal-defaults.mjs [--check]');
 generateInternalDefaults(ROOT,{check:process.argv.includes('--check')});
}
