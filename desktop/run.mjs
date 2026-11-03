import {spawnSync} from 'node:child_process';
import {existsSync} from 'node:fs';
import path from 'node:path';
import os from 'node:os';
import {fileURLToPath} from 'node:url';

const directory=path.dirname(fileURLToPath(import.meta.url));
const root=path.dirname(directory);
const mode=process.argv[2];
if(!['dev','build'].includes(mode))throw new Error('Use npm run dev or npm run build');
if(!['win32','darwin'].includes(process.platform))throw new Error('Desktop builds currently support Windows and macOS');
process.env.PATH=path.join(os.homedir(),'.cargo','bin')+path.delimiter+process.env.PATH;
function run(command,args,cwd=root){
  const result=spawnSync(command,args,{cwd,stdio:'inherit',env:process.env});
  if(result.error)throw result.error;
  if(result.status!==0)process.exit(result.status??1);
}
const python=path.join(root,process.platform==='win32'?'.venv/Scripts/python.exe':'.venv/bin/python');
if(!existsSync(python))throw new Error('Run the existing project installer first to create .venv');
const npmCli=process.env.npm_execpath;
if(!npmCli||!existsSync(npmCli))throw new Error('Start this script with npm run dev or npm run build');
if(mode==='build'&&!process.env.TAURI_SIGNING_PRIVATE_KEY&&process.env.IWB_UNSIGNED_BUILD!=='1')throw new Error('Signed updater builds require TAURI_SIGNING_PRIVATE_KEY. For an unsigned development installer only, explicitly set IWB_UNSIGNED_BUILD=1.');
if(mode==='build'){
  const check=spawnSync(python,['-c','import PyInstaller'],{cwd:root,stdio:'ignore'});
  if(check.status!==0)throw new Error(`Desktop build dependencies are missing. Run: "${python}" -m pip install -r desktop/requirements-build.txt`);
}
run(process.execPath,[npmCli,'run','build'],path.join(root,'frontend'));
if(mode==='build')run(python,[path.join(directory,'build_runtime.py')]);
const args=[path.join(directory,'node_modules/@tauri-apps/cli/tauri.js'),mode];
if(mode==='build')args.push('--config','src-tauri/tauri.bundle.conf.json','--bundles',process.platform==='win32'?'nsis':'app,dmg');
if(mode==='build'&&process.env.IWB_UNSIGNED_BUILD==='1')args.push('--config',JSON.stringify({bundle:{createUpdaterArtifacts:false}}));
run(process.execPath,[...args,...process.argv.slice(3)],directory);
