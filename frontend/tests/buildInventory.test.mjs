import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtempSync,mkdirSync,readFileSync,writeFileSync,rmSync} from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {currentBuildInventory} from '../vite.config.js';

test('inventory includes final HTML, chunks, CSS, fonts and public assets but excludes retained files',()=>{
  const root=mkdtempSync(path.join(os.tmpdir(),'iwb-inventory-'));
  try{
    const publicDir=path.join(root,'public');
    const dist=path.join(root,'dist');
    mkdirSync(path.join(publicDir,'themes'),{recursive:true});
    mkdirSync(dist);
    writeFileSync(path.join(publicDir,'themes','background.webp'),'image');
    writeFileSync(path.join(dist,'old.js'),'old');
    const plugin=currentBuildInventory();
    plugin.configResolved({publicDir});
    plugin.writeBundle({dir:dist},{'index.html':{},'assets/chunk.js':{},'assets/style.css':{},'assets/font.woff2':{}});
    const inventory=JSON.parse(readFileSync(path.join(dist,'.iwb-build.json'),'utf8'));
    assert.deepEqual(inventory,{version:1,files:['assets/chunk.js','assets/font.woff2','assets/style.css','index.html','themes/background.webp']});
  }finally{rmSync(root,{recursive:true,force:true});}
});
