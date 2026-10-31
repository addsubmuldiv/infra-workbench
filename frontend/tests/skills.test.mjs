import test from 'node:test';
import assert from 'node:assert/strict';
import {skillRequest,importSkill,exportSkill,installedSkill,skillMarkdown,copySkillFiles} from '../src/skills.ts';
test('skill API preserves revisions and displays conflicts without losing drafts',async()=>{
  const calls=[];const request=async(url,options)=>{calls.push([url,options]);return new Response(JSON.stringify({detail:'草稿版本已更新'}),{status:409})};
  await assert.rejects(skillRequest('/drafts/a/install','POST',{revision:3},undefined,request),/草稿版本已更新/);
  assert.equal(calls[0][1].headers['X-IWB'],'1');assert.equal(calls[0][1].body,'{"revision":3}');
});
test('import sends raw file bytes and rejects oversized files before transfer',async()=>{
  let calls=0;const request=async(url,options)=>{calls++;assert.equal(url,'/api/skills/import?filename=a%20b.zip');assert.equal(options.body,file);return new Response('{"id":"draft"}')};
  const file=new File(['zip'],'a b.zip');assert.equal((await importSkill(file,undefined,request)).id,'draft');
  await assert.rejects(importSkill(new File([new Uint8Array(2*1024*1024+1)],'big.zip'),undefined,request),/2 MiB/);assert.equal(calls,1);
});
test('export preserves binary response',async()=>{
  const bytes=new Uint8Array([0,255,32,128]);const blob=await exportSkill('a',2,async(url)=>{assert.equal(url,'/api/skills/a/export?version=2');return new Response(bytes)});
  assert.deepEqual(new Uint8Array(await blob.arrayBuffer()),bytes);
});
test('install cards require actual successful installed result',()=>{
  const output=JSON.stringify({ok:true,data:{name:'my-skill',version:2,status:'installed'}});
  assert.deepEqual(installedSkill(output,'succeeded'),{name:'my-skill',version:2});assert.equal(installedSkill(output,'failed'),null);
  assert.equal(installedSkill('{"ok":false,"data":{"status":"installed"}}','succeeded'),null);assert.equal(installedSkill('truncated','succeeded'),null);
});
test('generated metadata quotes user input and builtin copy changes only metadata',()=>{
  const md=skillMarkdown('new-skill','hello: "world"','body');assert.match(md,/description: "hello: \\"world\\""/);
  const files={'SKILL.md':md,'references/a.md':'name: original'};const copy=copySkillFiles(files,'copied');assert.match(copy['SKILL.md'],/name: "copied"/);assert.equal(files['SKILL.md'],md);assert.equal(copy['references/a.md'],'name: original');
});
