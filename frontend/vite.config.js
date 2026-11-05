import { defineConfig } from 'vite';
import {readFileSync,writeFileSync,readdirSync} from 'node:fs';
import path from 'node:path';
import {createHash} from 'node:crypto';
const version=JSON.parse(readFileSync(new URL('./package.json',import.meta.url),'utf8')).version;
// writeBundle runs after Vite has emitted HTML and its final chunk/CSS/assets.
// dist deliberately retains old lazy chunks; packaging consumes only this list.
export function currentBuildInventory(){
  let publicDir;
  function publicFiles(directory,prefix=''){
    return readdirSync(directory,{withFileTypes:true}).flatMap(entry=>{
      const name=prefix+entry.name;
      if(entry.isDirectory())return publicFiles(path.join(directory,entry.name),name+'/');
      if(!entry.isFile())throw new Error('Unsupported public asset: '+name);
      return [name];
    });
  }
  return {name:'current-build-inventory',enforce:'post',configResolved(config){publicDir=config.publicDir;},writeBundle(options,bundle){
    const files=[...new Set([...Object.keys(bundle),...(publicDir?publicFiles(publicDir):[])])].sort();
    writeFileSync(path.join(options.dir,'.iwb-build.json'),JSON.stringify({version:2,appVersion:version,internalPolicySha256:createHash('sha256').update(readFileSync(new URL('./src/internalDefaults.ts',import.meta.url),'utf8').replace(/\r\n/g,'\n')).digest('hex'),files:Object.fromEntries(files.map(name=>{const bytes=readFileSync(path.join(options.dir,name));return [name,{size:bytes.length,sha256:createHash('sha256').update(bytes).digest('hex')}];}))},null,2)+'\n');
  }};
}
export default defineConfig(({mode,command})=>({
  define:{__IWB_VERSION__:JSON.stringify(version),__IWB_DEMO__:JSON.stringify(mode==='demo')},
  base:mode==='demo'?'./':'/',
  plugins:[...(mode!=='demo'&&command==='build'?[currentBuildInventory()]:[]),...(mode==='demo'&&command==='build'?[{name:'demo-network-policy',transformIndexHtml(){return [{tag:'meta',attrs:{'http-equiv':'Content-Security-Policy',content:"connect-src 'none'; form-action 'none'; object-src 'none'; base-uri 'self'"},injectTo:'head-prepend'}]}}]:[])],
  // Open pages may still request older lazy chunks after an in-place update.
  build:{target:['es2020','safari15'],emptyOutDir:mode==='demo',outDir:mode==='demo'?'demo-dist':'dist'},
  server:{proxy:{'/api':{target:'http://127.0.0.1:8765',ws:true}}},
}));
