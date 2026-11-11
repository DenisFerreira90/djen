const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

function element(tag, css, text) {
    return {tag, css, text, children: [], attributes: {}, append(...children) {
        this.children.push(...children);
    }, setAttribute(name, value) {
        this.attributes[name] = value;
    }};
}

const content = element('main');
const S = {view: 'planilhas', user: {role: 'administrador'}};
const calls = [];
let owner = true;
const J = {
    S, el: element, head() {}, card() {const c=element('section');content.append(c);return c;},
    button(label, click, css) {return {...element('button', css, label), click};},
    isOwner: () => owner,
    api: async (route, body) => {
        calls.push({route, body});
        return {criados: 1, existentes: 0};
    },
    async go(view) {S.view = view;await this.render();},
    async render() {content.children = [];await ctx.window.Dados.render();}
};
const ctx = vm.createContext({
    window: {Juridico: J, Org: {render: async () => {content.append(element('p', '', 'Formulário de planilha'));}}},
    document: {getElementById: () => content},
    btoa
});
vm.runInContext(fs.readFileSync(require.resolve('../js/dados.js'), 'utf8'), ctx);
const find = (predicate, node = content) => {
    if (predicate(node)) return node;
    for (const child of node.children) {
        const found = find(predicate, child);
        if (found) return found;
    }
};

(async () => {
    for (const [tab, expected] of [
        ['Recuperar coleta', 'Importar uma coleta já realizada'],
        ['Exportar dados', 'Planilha para consulta'],
        ['Backup e restauração', 'Criar cópia restaurável']
    ]) {
        await J.go('planilhas');
        assert(find(node => node.text === 'Formulário de planilha'));
        await find(node => node.tag === 'button' && node.text === tab).click();
        assert.equal(S.view, 'dados');
        assert(find(node => node.text === expected), expected);
        assert.equal(find(node => node.tag === 'button' && node.text === tab).attributes['aria-pressed'], 'true');
        if (tab === 'Recuperar coleta') {
            find(node => node.tag === 'input').files = [{size: 2, arrayBuffer: async () => new Uint8Array([123,125]).buffer}];
            await find(node => node.text === 'Importar coleta').click();
            assert.equal(calls.at(-1).route, 'importar');
            assert.equal(calls.at(-1).body.arquivo_base64, 'e30=');
        }
    }
    owner = false;
    await J.go('planilhas');
    assert(find(node => node.text === 'Formulário de planilha'));
    assert(!find(node => node.text === 'Recuperar coleta'));
    await assert.rejects(J.go('dados'), /exclusiva/);
    console.log('Abas da Central de dados, importação JSON e restrição por conta verificadas.');
})().catch(error => {console.error(error);process.exitCode=1;});
