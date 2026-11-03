import test from 'node:test';
import assert from 'node:assert/strict';
import {archiveCommand,canFillArchive} from '../src/terminalArchives.ts';
import {IMAGE_OPTIONS,createTerminalImages,readImagesEnabled,createImageDecodeGuard} from '../src/terminalImages.ts';
test('archive commands quote exact Unicode and shell punctuation without execution',()=>{
 assert.equal(archiveCommand("/tmp/训练 a'$(touch x);.zip"),"unzip -n '/tmp/训练 a'\\''$(touch x);.zip' -d '/tmp'");
 for(const ext of ['tar','tar.gz','tgz','tar.bz2','tbz2','tar.xz'])assert.equal(archiveCommand('/tmp/a.'+ext),"tar -xf '/tmp/a."+ext+"' -C '/tmp' --keep-old-files");
 assert.equal(archiveCommand('a.zip','/data/work'),"unzip -n '/data/work/a.zip' -d '/data/work'");
 assert.equal(archiveCommand('./a.zip','/'),"unzip -n '/a.zip' -d '/'");
 for(const path of ['a.zip','../a.zip','/tmp/../a.zip','https://a.zip','C:\\a.zip','/tmp/a.zip\n','/tmp/a.exe'])assert.equal(archiveCommand(path),undefined);
 assert.ok(!archiveCommand('/tmp/a.zip').includes('\n'));
});
test('archive fill requires known empty prompt and preserves user edits',()=>{
 assert.equal(canFillArchive(true,{valid:true,text:'',cursor:0}),true);
 for(const [prompt,line] of [[false,{valid:true,text:'',cursor:0}],[true,{valid:false,text:'',cursor:0}],[true,{valid:true,text:'ls',cursor:2}]])assert.equal(canFillArchive(prompt,line),false);
});
test('images are opt-in and limits bound decoding and each terminal cache',()=>{
 assert.equal(readImagesEnabled({getItem:()=>null}),false);assert.equal(readImagesEnabled({getItem:()=> 'true'}),true);
 assert.equal(IMAGE_OPTIONS.pixelLimit,2097152);assert.equal(IMAGE_OPTIONS.storageLimit,16);assert.equal(IMAGE_OPTIONS.iipSizeLimit,8388608);assert.equal(IMAGE_OPTIONS.sixelSizeLimit,8388608);assert.equal(IMAGE_OPTIONS.enableSizeReports,false);
});
test('image lifecycle disposes on disable, errors and final teardown',()=>{
 let created=0,disposed=0,failed=0;
 const term={write:(_,done)=>done(),loadAddon:()=>{}};
 const images=createTerminalImages(term,()=>{created++;return {dispose(){disposed++}}},()=>failed++);
 images.setEnabled(true);images.setEnabled(true);assert.equal(created,1);images.setEnabled(false);assert.equal(disposed,1);images.setEnabled(true);images.dispose();images.setEnabled(true);assert.equal(created,2);assert.equal(disposed,2);
 const broken=createTerminalImages({...term,loadAddon(){throw Error('unsupported')}},()=>({dispose(){disposed++}}),()=>failed++);broken.setEnabled(true);assert.equal(failed,1);assert.equal(disposed,3);broken.dispose();
});
test('failed image finalization and late decode never mutate resumed/disposed storage',async()=>{
 let inserted=0,closed=0,late;
 const guard=createImageDecodeGuard(()=>inserted++,10);
 assert.equal(await guard.run(()=>Promise.reject(Error('corrupt'))),true);
 assert.equal(guard.run(()=>{throw Error('canvas unsupported')}),true);
 await guard.run(accept=>new Promise(resolve=>{late=()=>{accept({close(){closed++}});resolve(true)}}));
 late();assert.equal(inserted,0);assert.equal(closed,1);
 let afterDispose;const pending=guard.run(accept=>new Promise(resolve=>{afterDispose=()=>{accept({close(){closed++}});resolve(true)}}));
 guard.dispose();await pending;afterDispose();assert.equal(inserted,0);assert.equal(closed,2);
});
