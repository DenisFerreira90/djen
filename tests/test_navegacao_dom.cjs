const vm=require('node:vm'),fs=require('node:fs'),assert=require('node:assert/strict');
const run=role=>{const content={nodes:[],prepend(n){this.nodes.unshift(n);}},central={dataset:{view:'centralconsultas'},classList:{toggle(c,v){this.active=v;}}},agenda={dataset:{view:'agenda'},classList:{toggle(c,v){this.active=v;}}};
const document={getElementById:id=>id==='content'?content:null,querySelectorAll:q=>q.includes('details')?[]:[central,agenda]};
const window={Juridico:{S:{user:{id:1,role},view:'jusdown'},el(t,c){return {children:[],setAttribute(){},append(x){this.children.push(x);}};},button(text,fn){return {text,fn,setAttribute(){}};},go(){}}};const c={window,document};vm.createContext(c);vm.runInContext(fs.readFileSync(require.resolve('../js/navegacao.js'),'utf8'),c);
assert(central.classList.active);const titles=content.nodes[0].children.map(x=>x.text);assert(titles.includes('JUSDOWN'));assert(titles.includes('Coletas e processos'));assert.equal(titles.includes('Rotinas automáticas'),role==='administrador');
window.Juridico.S.view='prazos';window.WorkspaceNav.apply();assert(agenda.classList.active);
};run('administrador');run('equipe');console.log('Central única, abas relacionadas e rotinas restritas aprovadas.');
