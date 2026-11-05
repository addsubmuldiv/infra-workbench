import {PROBES} from './internal-defaults-schema.mjs';
import {test} from 'node:test';
import assert from 'node:assert/strict';
import {mkdtempSync,readFileSync,writeFileSync,mkdirSync,rmSync,copyFileSync} from 'node:fs';
import path from 'node:path';
import os from 'node:os';
import {generateInternalDefaults,parseConfig,stripComments,ROOT} from './generate-internal-defaults.mjs';
const source=()=>readFileSync(path.join(ROOT,'config/internal-defaults.jsonc'),'utf8');
function temporary(fn){const root=mkdtempSync(path.join(os.tmpdir(),'iwb-defaults-'));try{mkdirSync(path.join(root,'config'));writeFileSync(path.join(root,'config/internal-defaults.jsonc'),source());for(const file of Object.keys(PROBES)){mkdirSync(path.dirname(path.join(root,file)),{recursive:true});copyFileSync(path.join(ROOT,file),path.join(root,file));}return fn(root)}finally{rmSync(root,{recursive:true,force:true})}}
test('reject invalid, unknown, missing and duplicate keys, even escaped duplicates',()=>{
 const original=source(),value=parseConfig(original);
 assert.throws(()=>parseConfig('{"files":{},"files":{}}'),/Duplicate/);
 assert.throws(()=>parseConfig('{"files":{},"fi\\u006ces":{}}'),/Duplicate/);
 for(const invalid of [true,null,'512',0,-1,0.5,1e99]){const v=structuredClone(value);v.files.upload_max_bytes=invalid;assert.throws(()=>parseConfig(JSON.stringify(v)));}
 const v=structuredClone(value);v.files.surprise=1;assert.throws(()=>parseConfig(JSON.stringify(v)),/Unknown/);
 delete value.files.upload_max_bytes;assert.throws(()=>parseConfig(JSON.stringify(value)),/Missing/);
 assert.equal(parseConfig(original).files.upload_max_bytes,536870912);
});
test('deterministic generation, non-default values, check detects drift, invalid leaves output untouched',()=>temporary(root=>{
 generateInternalDefaults(root);
 const py=path.join(root,'backend/internal_defaults.py'),ts=path.join(root,'frontend/src/internalDefaults.ts');
 const before=readFileSync(py,'utf8');assert.match(before,/FILES_UPLOAD_MAX_BYTES = 536870912/);
 generateInternalDefaults(root,{check:true});generateInternalDefaults(root);assert.equal(readFileSync(py,'utf8'),before);
 const config=parseConfig(source());config.files.upload_max_bytes=2048;writeFileSync(path.join(root,'config/internal-defaults.jsonc'),JSON.stringify(config));
 assert.throws(()=>generateInternalDefaults(root,{check:true}),/out of date/);
 generateInternalDefaults(root);assert.match(readFileSync(py,'utf8'),/FILES_UPLOAD_MAX_BYTES = 2048/);assert.match(readFileSync(ts,'utf8'),/FILES_UPLOAD_MAX_BYTES = 2048/);
 const valid=readFileSync(py,'utf8');writeFileSync(path.join(root,'config/internal-defaults.jsonc'),'{}');assert.throws(()=>generateInternalDefaults(root));assert.equal(readFileSync(py,'utf8'),valid);
}));

test('JSONC comments preserve quoted URLs and comment-like strings',()=>{
 assert.equal(stripComments('{"url":"https://example.test/a/*b*/" /* 中文 */}'),'{"url":"https://example.test/a/*b*/"         }');
 assert.throws(()=>parseConfig(source().replace('"files": {','"files": {"upload_max_bytes": 1,')),/Duplicate/);
});
test('malformed probe marker aborts before any generated file changes',()=>temporary(root=>{
 generateInternalDefaults(root);
 const py=path.join(root,'backend/internal_defaults.py'),before=readFileSync(py,'utf8');
 const config=parseConfig(source());config.files.upload_max_bytes=2048;writeFileSync(path.join(root,'config/internal-defaults.jsonc'),JSON.stringify(config));
 const probe=path.join(root,'backend/file_upload_probe.py');writeFileSync(probe,readFileSync(probe,'utf8').replace('# END GENERATED INTERNAL DEFAULTS',''));
 assert.throws(()=>generateInternalDefaults(root),/markers/);assert.equal(readFileSync(py,'utf8'),before);
}));
