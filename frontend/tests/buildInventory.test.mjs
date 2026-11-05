import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtempSync,mkdirSync,readFileSync,writeFileSync,rmSync} from 'node:fs';
import os from 'node:os';
import {createHash} from 'node:crypto';
import path from 'node:path';
import config,{currentBuildInventory} from '../vite.config.js';

test('inventory includes final HTML, chunks, CSS, fonts and public assets but excludes retained files',()=>{
  const root=mkdtempSync(path.join(os.tmpdir(),'iwb-inventory-'));
  try{
    const publicDir=path.join(root,'public');
    const dist=path.join(root,'dist');
    mkdirSync(path.join(publicDir,'themes'),{recursive:true});
    mkdirSync(dist);
    writeFileSync(path.join(publicDir,'themes','background.webp'),'image');
    writeFileSync(path.join(dist,'old.js'),'old');
    const names=['assets/chunk.js','assets/font.woff2','assets/style.css','index.html','themes/background.webp'];
    for(const name of names){mkdirSync(path.dirname(path.join(dist,name)),{recursive:true});writeFileSync(path.join(dist,name),'bytes:'+name);}
    const plugin=currentBuildInventory();
    plugin.configResolved({publicDir});
    plugin.writeBundle({dir:dist},{'index.html':{},'assets/chunk.js':{},'assets/style.css':{},'assets/font.woff2':{}});
    const inventory=JSON.parse(readFileSync(path.join(dist,'.iwb-build.json'),'utf8'));
    assert.equal(inventory.version,2);
    assert.equal(inventory.appVersion,JSON.parse(readFileSync(new URL('../package.json',import.meta.url))).version);
    assert.deepEqual(Object.keys(inventory.files),names);
    for(const name of names){const bytes=readFileSync(path.join(dist,name));assert.deepEqual(inventory.files[name],{size:bytes.length,sha256:createHash('sha256').update(bytes).digest('hex')});}
  }finally{rmSync(root,{recursive:true,force:true});}
});

test('build clears old assets by default and retention requires explicit local opt-in',()=>{
  const previous=process.env.IWB_RETAIN_OLD_CHUNKS;
  try{
    delete process.env.IWB_RETAIN_OLD_CHUNKS;
    assert.equal(config({mode:'production',command:'build'}).build.emptyOutDir,true);
    process.env.IWB_RETAIN_OLD_CHUNKS='1';
    assert.equal(config({mode:'production',command:'build'}).build.emptyOutDir,false);
    assert.equal(config({mode:'demo',command:'build'}).build.emptyOutDir,true);
  }finally{
    if(previous===undefined)delete process.env.IWB_RETAIN_OLD_CHUNKS;
    else process.env.IWB_RETAIN_OLD_CHUNKS=previous;
  }
});
