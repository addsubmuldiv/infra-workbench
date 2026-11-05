import {test} from 'node:test';
import assert from 'node:assert/strict';
import {mkdtempSync, mkdirSync, copyFileSync, writeFileSync, readFileSync, rmSync} from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {syncVersion, ROOT} from './sync-version.mjs';
const files = ['version.json','frontend/package.json','frontend/package-lock.json','desktop/package.json','desktop/package-lock.json','desktop/src-tauri/tauri.conf.json','desktop/src-tauri/Cargo.toml','desktop/src-tauri/Cargo.lock','backend/app.py'];
test('single source synchronizes every consumer without changing dependency versions', () => {
  const root = mkdtempSync(path.join(os.tmpdir(), 'iwb-version-'));
  try {
    for (const file of files) {mkdirSync(path.dirname(path.join(root,file)),{recursive:true});copyFileSync(path.join(ROOT,file),path.join(root,file));}
    const cargoBefore=readFileSync(path.join(root,'desktop/src-tauri/Cargo.lock'),'utf8');
    const npmBefore=JSON.parse(readFileSync(path.join(root,'frontend/package-lock.json')));
    writeFileSync(path.join(root,'version.json'),JSON.stringify({version:'1.2.3-rc.1'}));
    assert.throws(()=>syncVersion(root,{check:true}),/out of sync/);
    assert.equal(syncVersion(root),'1.2.3-rc.1');
    syncVersion(root,{check:true});
    for (const file of files.filter(file=>file.endsWith('.json') && file!=='version.json')) {
      const value=JSON.parse(readFileSync(path.join(root,file)));
      assert.equal(value.version,'1.2.3-rc.1',file);
      if(file.endsWith('package-lock.json')) assert.equal(value.packages[''].version,'1.2.3-rc.1');
    }
    assert.match(readFileSync(path.join(root,'desktop/src-tauri/Cargo.toml'),'utf8'),/version = "1.2.3-rc.1"/);
    const cargoAfter=readFileSync(path.join(root,'desktop/src-tauri/Cargo.lock'),'utf8');
    assert.equal(cargoAfter,cargoBefore.replace(/(name = "infra-workbench-desktop"\r?\nversion = ")[^"]+/, '$11.2.3-rc.1'));
    const npmAfter=JSON.parse(readFileSync(path.join(root,'frontend/package-lock.json')));
    delete npmBefore.version;delete npmBefore.packages[''].version;delete npmAfter.version;delete npmAfter.packages[''].version;
    assert.deepEqual(npmAfter,npmBefore);
    assert.match(readFileSync(path.join(root,'backend/app.py'),'utf8'),/'version': '1.2.3-rc.1'/);
    const before=files.map(file=>readFileSync(path.join(root,file),'utf8'));
    syncVersion(root);assert.deepEqual(files.map(file=>readFileSync(path.join(root,file),'utf8')),before);
    writeFileSync(path.join(root,'version.json'),JSON.stringify({version:'bad'}));
    assert.throws(()=>syncVersion(root),/Invalid/);
    assert.equal(readFileSync(path.join(root,'desktop/package.json'),'utf8'),before[3]);
  } finally {rmSync(root,{recursive:true,force:true});}
});
