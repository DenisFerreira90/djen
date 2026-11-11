const vm=require('node:vm'),fs=require('node:fs'),assert=require('node:assert/strict');
const run=(role,owner)=>{const content={nodes:[],prepend(n){this.nodes.unshift(n);}},central={dataset:{view:'proprietario'},classList:{toggle(c,v){this.active=v;}}},agenda={dataset:{view:'agenda'},classList:{toggle(c,v){this.active=v;}}};
const document={getElementById:id=>id==='content'?content:null,querySelectorAll:q=>q.includes('details')?[]:[central,agenda]};
const window={Juridico:{S:{user:{id:1,role},view:'jusdown'},isOwner:()=>owner,el(t,c){return {children:[],setAttribute(){},append(x){this.children.push(x);}};},button(text,fn){return {text,fn,setAttribute(){}};},go(){}}};const c={window,document};vm.createContext(c);vm.runInContext(fs.readFileSync(require.resolve('../js/navegacao.js'),'utf8'),c);
if(owner){assert(central.classList.active);const titles=content.nodes[0].children.map(x=>x.text);assert(titles.includes('Portais'));assert(titles.includes('Coleta'));assert(titles.includes('Dados e backup'));assert(!titles.includes('Notificações'));}else assert.equal(content.nodes.length,0);
window.Juridico.S.view='prazos';window.WorkspaceNav.apply();assert(agenda.classList.active);
};run('administrador',true);run('administrador',false);run('equipe',false);console.log('Abas técnicas exclusivas do dono; agenda preservada para administradores e equipe.');
