import {test} from 'node:test';
import assert from 'node:assert/strict';
import {mkdtempSync, writeFileSync, readFileSync, rmSync} from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {checksums, verifyVersion} from './release.mjs';

test('release tag must match all desktop versions', () => {
  const current = JSON.parse(readFileSync(new URL('./package.json', import.meta.url), 'utf8')).version;
  verifyVersion('v' + current);
  assert.throws(() => verifyVersion('v9.9.9'), /version must equal/);
  assert.throws(() => verifyVersion('../main'), /Expected a version tag/);
});
test('checksum inventory requires all three platform installers', () => {
  const dir = mkdtempSync(path.join(os.tmpdir(), 'iwb-release-'));
  try {
    writeFileSync(path.join(dir, 'windows.exe'), 'abc');
    assert.throws(() => checksums(dir), /Expected one Windows/);
    writeFileSync(path.join(dir, 'arm64.dmg'), 'abc');
    writeFileSync(path.join(dir, 'x64.dmg'), 'abc');
    checksums(dir);
    const manifest = readFileSync(path.join(dir, 'SHA256SUMS.txt'), 'utf8');
    assert.equal(manifest.split('\n').filter(Boolean).length, 3);
    assert.match(manifest, /ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad/);
    assert.doesNotThrow(() => checksums(dir));
  } finally { rmSync(dir, {recursive: true}); }
});

test('signed update feed uses distinct platform assets and embedded signatures',async()=>{
  const {createUpdateManifest}=await import('./release.mjs');
  const dir=mkdtempSync(path.join(os.tmpdir(),'iwb-feed-'));
  try{
    const names=['Infra-Workbench-0.1.1-windows-x86_64-setup.exe','Infra-Workbench-0.1.1-darwin-aarch64.app.tar.gz','Infra-Workbench-0.1.1-darwin-x86_64.app.tar.gz'];
    for(const name of names){writeFileSync(path.join(dir,name),'package');writeFileSync(path.join(dir,name+'.sig'),'c2lnbmF0dXJl');}
    const value=createUpdateManifest(dir,{version:'0.1.1',notes:'Changes',publishedAt:'2026-11-03T08:00:00Z'});
    assert.deepEqual(Object.keys(value.platforms).sort(),['darwin-aarch64','darwin-x86_64','windows-x86_64']);
    assert.equal(value.platforms['windows-x86_64'].signature,'c2lnbmF0dXJl');
    assert.match(value.platforms['windows-x86_64'].url,/releases\/download\/v0\.1\.1\/Infra-Workbench-0\.1\.1-windows-x86_64-setup\.exe$/);
    assert.equal(JSON.parse(readFileSync(path.join(dir,'latest.json'),'utf8')).version,'0.1.1');
    writeFileSync(path.join(dir,names[0]+'.sig'),'');
    assert.throws(()=>createUpdateManifest(dir,{version:'0.1.1'}),/signature/i);
  }finally{rmSync(dir,{recursive:true});}
});

test('Windows-only bootstrap feed is explicit and never invents unbuilt platforms',async()=>{
 const {createUpdateManifest}=await import('./release.mjs');const dir=mkdtempSync(path.join(os.tmpdir(),'iwb-bootstrap-'));
 try{
  const name='Infra-Workbench-0.1.1-windows-x86_64-setup.exe';writeFileSync(path.join(dir,name),'pkg');writeFileSync(path.join(dir,name+'.sig'),'c2ln');
  assert.throws(()=>createUpdateManifest(dir,{version:'0.1.1'}),/Missing/);
  const result=createUpdateManifest(dir,{version:'0.1.1',requireAllPlatforms:false});assert.deepEqual(Object.keys(result.platforms),['windows-x86_64']);
  assert.throws(()=>createUpdateManifest(dir,{version:'../evil',requireAllPlatforms:false}),/version/i);
 }finally{rmSync(dir,{recursive:true});}
});

test('artifact collection selects current version and preserves signatures under unique names',async()=>{
 const {collectArtifacts}=await import('./release.mjs');const root=mkdtempSync(path.join(os.tmpdir(),'iwb-collect-'));
 try{
  const bundle=path.join(root,'bundle'),folder=path.join(bundle,'nsis'),out=path.join(root,'out');
  const {mkdirSync}=await import('node:fs');mkdirSync(folder,{recursive:true});
  for(const version of ['0.1.0','0.1.1']){const file=path.join(folder,`Workbench_${version}_x64-setup.exe`);writeFileSync(file,version);writeFileSync(file+'.sig',version+'-signature');}
  collectArtifacts(bundle,out,{version:'0.1.1',platform:'win32',arch:'x64'});
  assert.equal(readFileSync(path.join(out,'Infra-Workbench-0.1.1-windows-x86_64-setup.exe'),'utf8'),'0.1.1');
  assert.equal(readFileSync(path.join(out,'Infra-Workbench-0.1.1-windows-x86_64-setup.exe.sig'),'utf8'),'0.1.1-signature');
 }finally{rmSync(root,{recursive:true});}
});
