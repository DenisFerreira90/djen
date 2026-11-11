const assert=require('node:assert/strict');
const {chatAlertCandidates}=require('../js/chat-alertas.js');
const list=[{id:1,room_id:2},{id:2,room_id:3}];
assert.deepEqual(chatAlertCandidates(list,2,true),[{id:2,room_id:3}]);
assert.deepEqual(chatAlertCandidates(list,2,false),list);
assert.deepEqual(chatAlertCandidates(list,null,true),list);
console.log('3 cenários de seleção de alertas aprovados.');

const {chatQuietNow}=require('../js/chat-alertas.js');
const pref={silencio_inicio:'22:00',silencio_fim:'08:00'};
assert.equal(chatQuietNow(pref,new Date(2026,10,4,23,0)),true);
assert.equal(chatQuietNow(pref,new Date(2026,10,5,7,59)),true);
assert.equal(chatQuietNow(pref,new Date(2026,10,5,8,0)),false);
assert.equal(chatQuietNow(pref,new Date(2026,10,5,12,0)),false);
assert.equal(chatQuietNow({silencio_inicio:'12:00',silencio_fim:'13:00'},new Date(2026,10,5,12,30)),true);
assert.equal(chatQuietNow({},new Date()),false);
console.log('6 cenários de horário de silêncio aprovados.');
