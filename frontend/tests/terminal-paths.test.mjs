import test from 'node:test';
import assert from 'node:assert/strict';
import {directoryPathLink,directoryLinkProvider} from '../src/terminalPaths.ts';

function term(text,cols=40){
  const rows=[];let cells=[],wrapped=false;
  const finish=()=>{const data=[...cells];while(data.length<cols)data.push({chars:'',width:1});rows.push({isWrapped:wrapped,length:cols,getCell:x=>data[x]&&{getChars:()=>data[x].chars,getWidth:()=>data[x].width},translateToString:()=>data.filter(c=>c.width!==0).map(c=>c.chars||' ').join('').trimEnd()});cells=[];wrapped=true};
  for(const char of text){
    const width=char.codePointAt(0)>255?2:1;
    if(cells.length+width>cols)finish();
    cells.push({chars:char,width});if(width===2)cells.push({chars:'',width:0});
  }
  finish();
  return {cols,buffer:{active:{type:'normal',getLine:index=>rows[index]}},rows};
}

test('pwd paths support spaces, shell punctuation and Unicode without constructing commands',()=>{
  for(const path of ['/','/home/test','/data/训练 目录/😀','/tmp/a;$(echo-not-executed)']){
    const terminal=term(path);
    for(let row=1;row<=terminal.rows.length;row++)assert.equal(directoryPathLink(terminal,row).path,path);
  }
});
test('wrapped paths map wide CJK glyphs to real terminal cells',()=>{
  const terminal=term('/abcd中文/目录',6);
  const link=directoryPathLink(terminal,2);
  assert.equal(link.path,'/abcd中文/目录');
  assert.deepEqual(link.range.start,{x:1,y:1});
  assert.deepEqual(link.range.end,{x:4,y:3});
});
test('only Ctrl+left click opens directories, plain click and URLs do nothing',()=>{
  const opened=[],provider=directoryLinkProvider(term('/data/project'),path=>opened.push(path));
  let links;provider.provideLinks(1,value=>links=value);
  let prevented=0;
  const event=(ctrlKey,button)=>({ctrlKey,button,preventDefault:()=>prevented++});
  links[0].activate(event(false,0));links[0].activate(event(true,2));
  assert.deepEqual(opened,[]);
  links[0].activate(event(true,0));assert.deepEqual(opened,['/data/project']);assert.equal(prevented,1);
  for(const text of ['user@host:~$ pwd','https://example.com','relative/path'])assert.equal(directoryPathLink(term(text),1),undefined);
  const alternate=term('/data');alternate.buffer.active.type='alternate';assert.equal(directoryPathLink(alternate,1),undefined);
});
