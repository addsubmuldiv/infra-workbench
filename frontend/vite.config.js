import { defineConfig } from 'vite';
import {readFileSync} from 'node:fs';
const version=JSON.parse(readFileSync(new URL('./package.json',import.meta.url),'utf8')).version;
export default defineConfig(({mode,command})=>({
  define:{__IWB_VERSION__:JSON.stringify(version),__IWB_DEMO__:JSON.stringify(mode==='demo')},
  base:mode==='demo'?'./':'/',
  plugins:mode==='demo'&&command==='build'?[{name:'demo-network-policy',transformIndexHtml(){return [{tag:'meta',attrs:{'http-equiv':'Content-Security-Policy',content:"connect-src 'none'; form-action 'none'; object-src 'none'; base-uri 'self'"},injectTo:'head-prepend'}]}}]:[],
  // Open pages may still request older lazy chunks after an in-place update.
  build:{target:['es2020','safari15'],emptyOutDir:mode==='demo',outDir:mode==='demo'?'demo-dist':'dist'},
  server:{proxy:{'/api':{target:'http://127.0.0.1:8765',ws:true}}},
}));
