import test from 'node:test';
import assert from 'node:assert/strict';
import {fitFileWindow,moveFileWindow} from '../src/fileWindow.ts';

test('resizing a floating file window keeps its title and resize handle in the viewport',()=>{
  const fitted=fitFileWindow({x:800,y:500,width:1200,height:900},{width:1024,height:768});
  assert.deepEqual(fitted,{x:8,y:8,width:1008,height:752});
  const small=fitFileWindow({x:-500,y:-50,width:10,height:10},{width:360,height:240});
  assert.deepEqual(small,{x:8,y:8,width:344,height:224});
});

test('minimized windows can move aside without discarding their restored size',()=>{
  const frame={x:20,y:20,width:880,height:600},viewport={width:1200,height:800};
  const moved=moveFileWindow(frame,2000,2000,viewport,true);
  assert.deepEqual(moved,{x:872,y:736,width:880,height:600});
  const restored=fitFileWindow(moved,viewport);
  assert.deepEqual(restored,{x:312,y:192,width:880,height:600});
  assert.deepEqual(moveFileWindow(frame,-2000,-2000,viewport),{...frame,x:8,y:8});
});
