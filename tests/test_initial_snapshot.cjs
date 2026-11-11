const fs = require('fs');
const path = require('path');
const vm = require('vm');
const assert = require('assert/strict');
const source = fs.readFileSync(path.join(__dirname, '../motor/eproc.py'), 'utf8');
const js = source.match(/SNAPSHOT = r'''([\s\S]*?)'''/)[1];
const origin = 'https://eproc1g.tjrs.jus.br';
const draft = id => origin+'/eproc/controlador.php?acao=peticao_inicial_preparada_carregar&id_peticao_pendente='+id+'&hash=TEST_ONLY';
const visible = {getClientRects: () => [1]};
function row(hrefs) {
  return {...visible, id: '', cells: [{innerText: ''}, {innerText: 'Autor de teste'}],
    querySelectorAll: sel => sel === 'a[href]' ? hrefs.map(href => ({...visible, href})) : []};
}
const rows = [row([]), row([draft('1001')]), row([draft('1001').replace('tjrs', 'tjsc')]),
  row([draft('001')]), row([draft('1001'), draft('1002')]),
  row([draft('1001').replace('peticao_inicial_preparada_carregar', 'peticao_inicial_preparada_excluir')])];
const table = {...visible, id: '', caption: {innerText: 'Lista de Petições Iniciais preparadas (5 registros):'},
  rows, getAttribute: () => ''};
const document = {body: {innerText: ''}, querySelectorAll: sel => sel === 'table' ? [table] : []};
const capture = vm.runInNewContext('('+js+')', {URL, document, location: {origin, href: origin+'/eproc/'}});
const result = JSON.parse(JSON.stringify(capture()));
assert.deepEqual(result.tabelas[0].identificadores_peticoes_linhas, [null, '1001', null, null, null, null]);
assert(!JSON.stringify(result).includes('TEST_ONLY'));
console.log('Identificadores das petições: extração restrita, sem hashes ou navegação. OK');
