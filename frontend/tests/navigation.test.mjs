import {test} from 'node:test';
import assert from 'node:assert/strict';
import {pageFromHash,hostLocationFromHash,notificationLocation} from '../src/navigation.ts';

test('every workspace page can be restored from its address',()=>{
  for(const page of ['overview','precision','reservations','history','settings'])assert.equal(pageFromHash('#'+page),page);
  assert.equal(pageFromHash(''),'overview');
  assert.equal(pageFromHash('#unknown'),'overview');
});

test('group reservation notification links stay on the local reservation page',()=>{
  assert.equal(notificationLocation('#reservations?group=abc123'),'#reservations?group=abc123');
  assert.equal(notificationLocation('#reservations?group=../bad'),'#reservations');
});

test('legacy connections addresses open the unified overview',()=>{
  assert.equal(pageFromHash('#connections'),'overview');
  assert.equal(pageFromHash('#connections?host=alpha'),'overview');
});

test('legacy monitoring page falls back to overview',()=>{
  assert.equal(pageFromHash('#watch'),'overview');
});

test('notification links restore a machine and deduplicated device selection',()=>{
  assert.equal(pageFromHash('#overview?host=a&device=0'),'overview');
  assert.deepEqual(hostLocationFromHash('#overview?host=machine+%2F+A&device=0%2F1&device=2&device=2'),{hostId:'machine / A',devices:['0/1','2']});
  assert.equal(hostLocationFromHash('#reservations?host=a'),null);
  assert.equal(hostLocationFromHash('#overview?device=0'),null);
  assert.equal(notificationLocation('javascript:alert(1)'),'#reservations');
  assert.equal(notificationLocation('https://example.org/#overview?host=a'),'#reservations');
  assert.equal(notificationLocation('#overview?host=a&device=0'),'#overview?host=a&device=0');
});
