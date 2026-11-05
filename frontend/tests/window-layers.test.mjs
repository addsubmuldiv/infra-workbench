import {test} from 'node:test';
import assert from 'node:assert/strict';
import {activateFloatingWindow,registerFloatingWindow} from '../src/windowLayers.ts';
import {resizeFileWindow} from '../src/fileWindow.ts';
import {scheduleDrawerEntrance} from '../src/drawerMotion.ts';

test('drawer entrance waits for an initial paint and cancels pending frames on close',()=>{
  const pending=new Map();let next=0,started=0;
  const request=callback=>{pending.set(++next,callback);return next};
  const cancel=id=>pending.delete(id);
  const frame=()=>{const callbacks=[...pending.values()];pending.clear();callbacks.forEach(fn=>fn())};
  const cleanup=scheduleDrawerEntrance(()=>started++,request,cancel);
  assert.equal(started,0);
  frame();assert.equal(started,0);
  frame();assert.equal(started,1);
  cleanup();assert.equal(pending.size,0);
  const closeImmediately=scheduleDrawerEntrance(()=>started++,request,cancel);
  closeImmediately();frame();assert.equal(started,1);
  const closeAfterPaint=scheduleDrawerEntrance(()=>started++,request,cancel);
  frame();closeAfterPaint();frame();assert.equal(started,1);
});

function workspace(){
  const windows=[];
  const doc={querySelectorAll:()=>windows};
  const create=name=>{const element={name,style:{},ownerDocument:doc};windows.push(element);return element};
  return {windows,create,click(element){activateFloatingWindow({currentTarget:element,target:{closest:()=>element}})}};
}

test('clicking terminal, files or editor brings exactly that window to the top',()=>{
  const desk=workspace(),terminal=desk.create('terminal'),files=desk.create('files'),editor=desk.create('editor');
  [terminal,files,editor].forEach(registerFloatingWindow);
  assert.ok(+editor.style.zIndex>+files.style.zIndex);
  desk.click(terminal);assert.ok(+terminal.style.zIndex>+files.style.zIndex&&+terminal.style.zIndex>+editor.style.zIndex);
  desk.click(files);assert.ok(+files.style.zIndex>+terminal.style.zIndex&&+files.style.zIndex>+editor.style.zIndex);
  desk.click(editor);assert.ok(+editor.style.zIndex>+files.style.zIndex);
});

test('portal events do not raise a parent above the clicked editor and focus does not steal input',()=>{
  const desk=workspace(),files=desk.create('files'),editor=desk.create('editor');
  registerFloatingWindow(editor);const old=files.style.zIndex;
  activateFloatingWindow({currentTarget:files,target:{closest:()=>editor},preventDefault(){throw Error('must not prevent selection')}});
  assert.equal(files.style.zIndex,old);
  desk.click(files);assert.ok(+files.style.zIndex>+editor.style.zIndex);
});

test('repeated activations keep z-order bounded and forget closed windows',()=>{
  const desk=workspace(),files=desk.create('files'),terminal=desk.create('terminal');
  for(let i=0;i<1000;i++)desk.click(i%2?files:terminal);
  assert.ok(+terminal.style.zIndex<100&&+files.style.zIndex<100);
  desk.windows.splice(desk.windows.indexOf(files),1);desk.click(terminal);
  assert.equal(+terminal.style.zIndex,70);
});

test('file window resizing works from every edge and keeps the opposite edge anchored',()=>{
  const frame={x:200,y:100,width:800,height:500},viewport={width:1400,height:900};
  assert.deepEqual(resizeFileWindow(frame,'se',100,80,viewport),{x:200,y:100,width:900,height:580});
  assert.deepEqual(resizeFileWindow(frame,'nw',-100,-40,viewport),{x:100,y:60,width:900,height:540});
  const east=resizeFileWindow(frame,'e',2000,0,viewport);assert.equal(east.x,200);assert.equal(east.x+east.width,1392);
  for(const edge of ['n','s','e','w','ne','nw','se','sw']){
    const next=resizeFileWindow(frame,edge,-4000,4000,viewport);
    assert.ok(next.x>=8&&next.y>=8&&next.width>=400&&next.height>=260);
    assert.ok(next.x+next.width<=1392&&next.y+next.height<=892);
  }
});
