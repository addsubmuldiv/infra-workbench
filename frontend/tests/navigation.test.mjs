import {test} from 'node:test';
import assert from 'node:assert/strict';
import {pageFromHash,hostSelectionPage,hostLocationFromHash,notificationLocation} from '../src/navigation.ts';

test('every workspace page can be restored from its address',()=>{
  for(const page of ['overview','connections','watch','precision','reservations','settings'])assert.equal(pageFromHash('#'+page),page);
  assert.equal(pageFromHash(''),'overview');
  assert.equal(pageFromHash('#unknown'),'overview');
});

test('machine names always open device overview, including precision and watch pages',()=>{
  for(const page of ['overview','connections','watch','precision','reservations','settings'])assert.equal(hostSelectionPage(page,true),'overview');
});

test('machine filter controls leave non-device pages and preserve the connections view',()=>{
  assert.equal(hostSelectionPage('precision'),'overview');
  assert.equal(hostSelectionPage('watch'),'overview');
  assert.equal(hostSelectionPage('overview'),'overview');
  assert.equal(hostSelectionPage('connections'),'connections');
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
