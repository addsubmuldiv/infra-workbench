import {createHash} from 'node:crypto';
import {readFileSync, readdirSync, writeFileSync, copyFileSync, mkdirSync, existsSync, statSync} from 'node:fs';
import path from 'node:path';

export function verifyVersion(tag, root = path.resolve(import.meta.dirname, '..')) {
  if (!/^v\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?$/.test(tag)) throw new Error('Expected a version tag such as v0.1.0');
  const expected = tag.slice(1);
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

export function checksums(directory,{requireAllPlatforms=true}={}) {
  const files = readdirSync(directory).filter(name => /\.(exe|dmg|gz|sig|json)$/.test(name)).sort();
  if (requireAllPlatforms && (files.filter(n => n.endsWith('.exe')).length !== 1 || files.filter(n => n.endsWith('.dmg')).length !== 2)) {
    throw new Error('Expected one Windows installer and two macOS disk images');
  }
  const lines = files.map(name => `${createHash('sha256').update(readFileSync(path.join(directory, name))).digest('hex')}  ${name}`);
  writeFileSync(path.join(directory, 'SHA256SUMS.txt'), lines.join('\n') + '\n');
  return files;
}

const targets=['windows-x86_64','darwin-aarch64','darwin-x86_64'];
function safeVersion(version){if(!/^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?$/.test(version))throw new Error('Invalid update version');return version}
function assetName(version,target){return `Infra-Workbench-${safeVersion(version)}-${target}${target.startsWith('windows')?'-setup.exe':'.app.tar.gz'}`}
export function createUpdateManifest(directory,{version,notes='',publishedAt=new Date().toISOString(),requireAllPlatforms=true}={}){
  safeVersion(version);const platforms={};
  for(const target of targets){
    const name=assetName(version,target),file=path.join(directory,name);
    if(!existsSync(file)){if(requireAllPlatforms)throw new Error(`Missing updater artifact: ${name}`);continue}
    if(!statSync(file).size)throw new Error(`Empty updater artifact: ${name}`);
    const signatureFile=file+'.sig';
    if(!existsSync(signatureFile))throw new Error(`Missing signature: ${name}`);
    const signature=readFileSync(signatureFile,'utf8').trim();
    if(!signature||!/^[A-Za-z0-9+/=\r\n]+$/.test(signature))throw new Error(`Invalid signature: ${name}`);
    platforms[target]={url:`https://github.com/addsubmuldiv/infra-workbench/releases/download/v${version}/${encodeURIComponent(name)}`,signature};
  }
  if(!Object.keys(platforms).length)throw new Error('Missing updater artifacts');
  const result={version,notes,pub_date:publishedAt,platforms};
  writeFileSync(path.join(directory,'latest.json'),JSON.stringify(result,null,2)+'\n');return result;
}
export function collectArtifacts(bundle,destination,{version,platform=process.platform,arch=process.arch}={}){
  safeVersion(version);platform=platform==='win32'?'windows':platform;arch=arch==='x64'?'x86_64':arch==='arm64'?'aarch64':arch;
  const target=`${platform}-${arch}`;if(!targets.includes(target))throw new Error('Unsupported update target');
  mkdirSync(destination,{recursive:true});
  const one=(folder,suffix)=>{const directory=path.join(bundle,folder);const candidates=readdirSync(directory).filter(name=>name.endsWith(suffix));const versioned=candidates.filter(name=>name.includes('_'+version+'_')||name.includes('-'+version+'-'));const files=versioned.length?versioned:candidates;if(files.length!==1)throw new Error(`Expected one ${suffix} in ${directory}`);return path.join(directory,files[0])};
  const updater=platform==='windows'?one('nsis','.exe'):one('macos','.app.tar.gz');
  const signature=updater+'.sig';if(!existsSync(signature))throw new Error(`Missing signed updater artifact for ${target}`);
  const name=assetName(version,target);copyFileSync(updater,path.join(destination,name));copyFileSync(signature,path.join(destination,name+'.sig'));
  if(platform==='darwin')copyFileSync(one('dmg','.dmg'),path.join(destination,`Infra-Workbench-${version}-${target}.dmg`));
  return {target,name};
}

if (process.argv[1] && path.resolve(process.argv[1]) === import.meta.filename) {
  if (process.argv[2] === 'version') verifyVersion(process.argv[3]);
  else if (process.argv[2] === 'checksums') checksums(path.resolve(process.argv[3]),{requireAllPlatforms:!process.argv.includes('--partial')});
  else if (process.argv[2] === 'collect') collectArtifacts(path.resolve(process.argv[3]),path.resolve(process.argv[4]),{version:JSON.parse(readFileSync(new URL('./package.json',import.meta.url),'utf8')).version});
  else if (process.argv[2] === 'manifest') createUpdateManifest(path.resolve(process.argv[3]),{version:process.argv[4],notes:process.argv[5]&&!process.argv[5].startsWith('--')?readFileSync(path.resolve(process.argv[5]),'utf8'):'',requireAllPlatforms:!process.argv.includes('--partial')});
  else throw new Error('Use release.mjs version, collect, manifest or checksums');
}
