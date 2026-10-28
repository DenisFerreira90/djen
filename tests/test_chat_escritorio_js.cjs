const assert=require('node:assert/strict');
const {chatRoomCategory:category,chatSessionUpdate:update}=require('../js/chat-escritorio.js');
assert.equal(category({tipo:'geral'}),'avisos');assert.equal(category({tipo:'comunicado'}),'avisos');assert.equal(category({tipo:'grupo'}),'grupos');assert.equal(category({tipo:'direta'}),'pessoas');
let opened=update(new Map(),'open',{id:1,title:'Setor A'});opened=update(opened,'open',{id:2,title:'Setor B'});assert.equal(opened.size,2);
let minimized=update(opened,'minimize',{id:1});assert.equal(minimized.get(1).minimized,true);assert.equal(opened.get(1).minimized,false);
minimized=update(minimized,'minimize_all');assert.equal([...minimized.values()].every(r=>r.minimized),true);
let closed=update(minimized,'close',{id:1});assert.equal(closed.size,1);assert.equal(update(closed,'close_all').size,0);
console.log('10 cenários de categorias e abas aprovados.');
