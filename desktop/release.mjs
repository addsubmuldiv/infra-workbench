import {syncVersion} from '../scripts/sync-version.mjs';
import {createHash,createPublicKey,verify} from 'node:crypto';
import {readFileSync,readdirSync,writeFileSync,copyFileSync,mkdirSync,existsSync,statSync,mkdtempSync,renameSync,rmSync} from 'node:fs';
import {execFileSync} from 'node:child_process';
import path from 'node:path';
export function verifyVersion(tag, root = path.resolve(import.meta.dirname, '..')) {
  if (!/^v\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?$/.test(tag)) throw new Error('Expected a version tag such as v0.1.0');
  const expected = tag.slice(1);
  if (JSON.parse(readFileSync(path.join(root, 'version.json'), 'utf8')).version !== expected) throw new Error(`version.json version must equal ${expected}`);
  syncVersion(root);
  for (const file of ['frontend/package.json', 'frontend/package-lock.json', 'desktop/package.json', 'desktop/package-lock.json', 'desktop/src-tauri/tauri.conf.json']) {
    if (JSON.parse(readFileSync(path.join(root, file), 'utf8')).version !== expected) throw new Error(`${file} version must equal ${expected}`);
  }
  const cargo = readFileSync(path.join(root, 'desktop/src-tauri/Cargo.toml'), 'utf8');
  const version = cargo.match(/\[package\][\s\S]*?^version\s*=\s*"([^"]+)"/m)?.[1];
  if (version !== expected) throw new Error(`Cargo.toml version must equal ${expected}`);
  for(const file of ['frontend/package-lock.json','desktop/package-lock.json']){
    const lock=JSON.parse(readFileSync(path.join(root,file),'utf8'));
    if(lock.packages[''].version!==expected)throw new Error(`${file} root version must equal ${expected}`);
  }
  const cargoLock = readFileSync(path.join(root, 'desktop/src-tauri/Cargo.lock'), 'utf8');
  const lockedVersion = cargoLock.match(/name = "infra-workbench-desktop"\s+version = "([^"]+)"/)?.[1];
  if (lockedVersion !== expected) throw new Error(`Cargo.lock version must equal ${expected}`);
}

const targets=['windows-x86_64','darwin-aarch64','darwin-x86_64'];
function safeVersion(version){if(!/^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?$/.test(version))throw new Error('Invalid update version');return version}
function assetName(version,target){return `Infra-Workbench-${safeVersion(version)}-${target}${target.startsWith('windows')?'-setup.exe':'.app.tar.gz'}`}
function configuredKey(){return JSON.parse(readFileSync(new URL('./src-tauri/tauri.conf.json',import.meta.url),'utf8')).plugins.updater.pubkey}
function decode(value){if(typeof value!=='string'||!value.trim()||! /^[A-Za-z0-9+/=\r\n]+$/.test(value.trim()))throw new Error('Invalid signature encoding');return Buffer.from(value.trim(),'base64')}
export function verifySignature(payload,signature,version,publicKey=configuredKey()){
  safeVersion(version);
  const lines=decode(signature).toString('utf8').trim().split(/\r?\n/),keyLines=decode(publicKey).toString('utf8').trim().split(/\r?\n/);
  if(lines.length!==4||!lines[2].startsWith('trusted comment: '))throw new Error('Invalid signature structure');
  const packet=decode(lines[1]),key=decode(keyLines[1]),global=decode(lines[3]),comment=lines[2].slice('trusted comment: '.length);
  if(packet.length!==74||key.length!==42||packet.subarray(0,2).toString()!=='ED'||!packet.subarray(2,10).equals(key.subarray(2,10)))throw new Error('Invalid signature algorithm or publisher key');
  const publicObject=createPublicKey({key:Buffer.concat([Buffer.from('302a300506032b6570032100','hex'),key.subarray(10)]),format:'der',type:'spki'});
  if(!verify(null,createHash('blake2b512').update(payload).digest(),publicObject,packet.subarray(10))||!verify(null,Buffer.concat([packet.subarray(10),Buffer.from(comment)]),publicObject,global))throw new Error('Invalid cryptographic signature');
  const versions=comment.split('\t').filter(part=>part.startsWith('version:'));
  if(versions.length!==1||versions[0]!==`version:${version}`)throw new Error('Signed version mismatch');
}
const digest=file=>createHash('sha256').update(readFileSync(file)).digest('hex');
function identity(){const commit=execFileSync('git',['rev-parse','HEAD'],{cwd:import.meta.dirname,encoding:'utf8'}).trim();return {commit,build:process.env.GITHUB_RUN_ID?`${process.env.GITHUB_RUN_ID}:${process.env.GITHUB_RUN_ATTEMPT||'1'}`:commit}}
function inventory(directory,{version,publicKey,requireAllPlatforms=true}={}){
  const provenance=readdirSync(directory).filter(n=>/^provenance-.+\.json$/.test(n));
  if(!provenance.length)throw new Error('Missing collection provenance');
  const expected=new Set(['SHA256SUMS.txt','latest.json',...provenance]),platforms={},seen=new Set();let source;
  for(const name of provenance){const record=JSON.parse(readFileSync(path.join(directory,name),'utf8'));
    if(!targets.includes(record.target)||name!==`provenance-${record.target}.json`||seen.has(record.target))throw new Error('Invalid provenance target');seen.add(record.target);
    version??=record.version;safeVersion(version);if(record.version!==version)throw new Error('Mixed release versions');
    const current=identity();if(record.commit!==current.commit||record.build!==current.build)throw new Error('Collection provenance differs from current commit/build');
    const sourceId=JSON.stringify([record.commit,record.build]);if(source&&source!==sourceId)throw new Error('Mixed build provenance');source=sourceId;
    const asset=assetName(version,record.target),required=[asset,asset+'.sig',...(record.target.startsWith('darwin')?[`Infra-Workbench-${version}-${record.target}.dmg`]:[])];
    if(JSON.stringify(Object.keys(record.files).sort())!==JSON.stringify(required.sort()))throw new Error('Invalid provenance inventory');
    for(const file of required){expected.add(file);if(!existsSync(path.join(directory,file))||!statSync(path.join(directory,file)).isFile()||!statSync(path.join(directory,file)).size||digest(path.join(directory,file))!==record.files[file])throw new Error(`Artifact integrity mismatch: ${file}`)}
    const signature=readFileSync(path.join(directory,asset+'.sig'),'utf8').trim();verifySignature(readFileSync(path.join(directory,asset)),signature,version,publicKey);platforms[record.target]={url:`https://github.com/addsubmuldiv/infra-workbench/releases/download/v${version}/${encodeURIComponent(asset)}`,signature};
  }
  for(const file of readdirSync(directory))if(!expected.has(file))throw new Error(`Unexpected release asset: ${file}`);
  if(requireAllPlatforms&&targets.some(target=>!seen.has(target)))throw new Error('Missing platform artifacts');
  return {version,platforms,files:[...expected].filter(n=>n!=='SHA256SUMS.txt'&&existsSync(path.join(directory,n))).sort()};
}
export function checksums(directory,options={}){const {files,version,platforms}=inventory(directory,options);if(existsSync(path.join(directory,'latest.json'))){const feed=JSON.parse(readFileSync(path.join(directory,'latest.json'),'utf8'));if(feed.version!==version||JSON.stringify(feed.platforms)!==JSON.stringify(platforms))throw new Error('Update manifest differs from verified artifacts')}writeFileSync(path.join(directory,'SHA256SUMS.txt'),files.map(name=>`${digest(path.join(directory,name))}  ${name}`).join('\n')+'\n');return files}
export function createUpdateManifest(directory,{notes='',publishedAt=new Date().toISOString(),...options}={}){const {version,platforms}=inventory(directory,options);const result={version,notes,pub_date:publishedAt,platforms};writeFileSync(path.join(directory,'latest.json'),JSON.stringify(result,null,2)+'\n');return result}
export function collectArtifacts(bundle,destination,{version,platform=process.platform,arch=process.arch,publicKey}={}){
  safeVersion(version);platform=platform==='win32'?'windows':platform;arch=arch==='x64'?'x86_64':arch==='arm64'?'aarch64':arch;const target=`${platform}-${arch}`;
  if(!targets.includes(target))throw new Error('Unsupported update target');
  if(existsSync(destination))throw new Error('Collection destination must not exist; use a fresh build directory');
  const one=(folder,predicate)=>{const directory=path.join(bundle,folder),files=readdirSync(directory).filter(predicate);if(files.length!==1)throw new Error(`Expected one matching current version/platform artifact in ${directory}`);return path.join(directory,files[0])};
  const nativeArch=arch==='x86_64'?'x64':'aarch64';
  const updater=platform==='windows'?one('nsis',n=>n.endsWith(`_${version}_${nativeArch}-setup.exe`)):one('macos',n=>n==='Infra Workbench.app.tar.gz');
  const signature=updater+'.sig';if(!existsSync(signature))throw new Error(`Missing signed updater artifact for ${target}`);
  verifySignature(readFileSync(updater),readFileSync(signature,'utf8'),version,publicKey);
  const name=assetName(version,target),copies=[[updater,name],[signature,name+'.sig']];
  if(platform==='darwin')copies.push([one('dmg',n=>n.endsWith(`_${version}_${nativeArch}.dmg`)),`Infra-Workbench-${version}-${target}.dmg`]);
  mkdirSync(path.dirname(path.resolve(destination)),{recursive:true});const stage=mkdtempSync(path.resolve(destination)+'.staging-');
  try{const files={};for(const [source,name] of copies){copyFileSync(source,path.join(stage,name));files[name]=digest(path.join(stage,name))}verifySignature(readFileSync(path.join(stage,name)),readFileSync(path.join(stage,name+'.sig'),'utf8'),version,publicKey);writeFileSync(path.join(stage,`provenance-${target}.json`),JSON.stringify({version,target,...identity(),files},null,2)+'\n');renameSync(stage,destination)}finally{rmSync(stage,{recursive:true,force:true})}
  return {target,name};
}
if(process.argv[1]&&path.resolve(process.argv[1])===import.meta.filename){const partial={requireAllPlatforms:!process.argv.includes('--partial')};if(process.argv[2]==='version')verifyVersion(process.argv[3]);else if(process.argv[2]==='collect')collectArtifacts(path.resolve(process.argv[3]),path.resolve(process.argv[4]),{version:JSON.parse(readFileSync(new URL('./package.json',import.meta.url),'utf8')).version});else if(process.argv[2]==='manifest')createUpdateManifest(path.resolve(process.argv[3]),{version:process.argv[4],notes:process.argv[5]&&!process.argv[5].startsWith('--')?readFileSync(path.resolve(process.argv[5]),'utf8'):'',...partial});else if(process.argv[2]==='checksums')checksums(path.resolve(process.argv[3]),partial);else throw new Error('Use release.mjs version, collect, manifest or checksums')}
