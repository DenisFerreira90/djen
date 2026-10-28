const assert=require('node:assert/strict');
const {chatAlertCandidates}=require('../js/chat-alertas.js');
const list=[{id:1,room_id:2},{id:2,room_id:3}];
assert.deepEqual(chatAlertCandidates(list,2,true),[{id:2,room_id:3}]);
assert.deepEqual(chatAlertCandidates(list,2,false),list);
assert.deepEqual(chatAlertCandidates(list,null,true),list);
console.log('3 cenários de seleção de alertas aprovados.');
