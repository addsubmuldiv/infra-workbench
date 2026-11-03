import test from 'node:test';
import assert from 'node:assert/strict';
import {createContextSender,receiveTerminalContext} from '../src/terminalAssistantBridge.ts';

function channels(){
 const peers=[];
 return ()=>{const port={onmessage:null,closed:false,postMessage(data){for(const peer of peers)if(peer!==port&&!peer.closed)peer.onmessage?.({data:structuredClone(data)})},close(){port.closed=true}};peers.push(port);return port};
}
const attachment=n=>({host_id:'host-'+n,label:'test',terminal_id:'tab',source:'screen',content:'line '+n,captured_at:'now',truncated:false});
test('late companion receives pending attachments once, including subsequent captures',()=>{
 const connect=channels(),sender=createContextSender(connect()),received=[];
 sender.add([attachment(1)]);
 const receiver=receiveTerminalContext(connect(),value=>received.push(...value));
 receiver.ready();receiver.ready();assert.deepEqual(received,[attachment(1)]);
 sender.add([attachment(2)]);receiver.ready();assert.deepEqual(received,[attachment(1),attachment(2)]);
 receiver.close();sender.close();
});
test('handoff is bounded and acknowledged captures are not replayed into a reopened window',()=>{
 const connect=channels(),sender=createContextSender(connect()),received=[];
 sender.add([attachment(1),attachment(2),attachment(3),attachment(4)]);
 const receiver=receiveTerminalContext(connect(),v=>received.push(...v));receiver.ready();receiver.close();
 assert.deepEqual(received.map(v=>v.content),['line 2','line 3','line 4']);
 const reopened=[];const next=receiveTerminalContext(connect(),v=>reopened.push(...v));next.ready();assert.deepEqual(reopened,[]);
 sender.add([attachment(5)]);assert.deepEqual(reopened,[attachment(5)]);next.close();sender.close();
});
