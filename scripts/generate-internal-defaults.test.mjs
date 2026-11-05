import {test} from 'node:test';
import assert from 'node:assert/strict';
import {mkdtempSync,readFileSync,writeFileSync,mkdirSync,rmSync} from 'node:fs';
import path from 'node:path';
import os from 'node:os';
import {generateInternalDefaults,parseConfig,ROOT} from './generate-internal-defaults.mjs';
const source=()=>readFileSync(path.join(ROOT,'config/internal-defaults.json'),'utf8');
function temporary(fn){const root=mkdtempSync(path.join(os.tmpdir(),'iwb-defaults-'));try{mkdirSync(path.join(root,'config'));writeFileSync(path.join(root,'config/internal-defaults.json'),source());return fn(root)}finally{rmSync(root,{recursive:true,force:true})}}
test('reject invalid, unknown, missing and duplicate keys, even escaped duplicates',()=>{
 const original=source(),value=JSON.parse(original);
 assert.throws(()=>parseConfig('{"files":{},"files":{}}'),/Duplicate/);
 assert.throws(()=>parseConfig('{"files":{},"fi\\u006ces":{}}'),/Duplicate/);
 for(const invalid of [true,null,'512',0,-1,0.5,1e99]){const v=structuredClone(value);v.files.upload_max_bytes=invalid;assert.throws(()=>parseConfig(JSON.stringify(v)));}
 const v=structuredClone(value);v.files.surprise=1;assert.throws(()=>parseConfig(JSON.stringify(v)),/Unknown/);
 delete value.files.upload_max_bytes;assert.throws(()=>parseConfig(JSON.stringify(value)),/Missing/);
 assert.deepEqual(parseConfig(original),JSON.parse(original));
});
test('deterministic generation, non-default values, check detects drift, invalid leaves output untouched',()=>temporary(root=>{
 generateInternalDefaults(root);
 const py=path.join(root,'backend/internal_defaults.py'),ts=path.join(root,'frontend/src/internalDefaults.ts');
 const before=readFileSync(py,'utf8');assert.match(before,/FILES_UPLOAD_MAX_BYTES = 536870912/);
 generateInternalDefaults(root,{check:true});generateInternalDefaults(root);assert.equal(readFileSync(py,'utf8'),before);
 const config=JSON.parse(source());config.files.upload_max_bytes=2048;writeFileSync(path.join(root,'config/internal-defaults.json'),JSON.stringify(config));
 assert.throws(()=>generateInternalDefaults(root,{check:true}),/out of date/);
 generateInternalDefaults(root);assert.match(readFileSync(py,'utf8'),/FILES_UPLOAD_MAX_BYTES = 2048/);assert.match(readFileSync(ts,'utf8'),/FILES_UPLOAD_MAX_BYTES = 2048/);
 const valid=readFileSync(py,'utf8');writeFileSync(path.join(root,'config/internal-defaults.json'),'{}');assert.throws(()=>generateInternalDefaults(root));assert.equal(readFileSync(py,'utf8'),valid);
}));
