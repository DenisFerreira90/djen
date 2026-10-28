'use strict';
const $ = id => document.getElementById(id);
const form = $('searchForm');
const BATCH_SIZE = 100;
const STORAGE_KEY = 'djen-consulta-simples-filtros-v1';
const API_URL = fetch('./api/health').then(async r => r.ok && (await r.json()).servidor === 'Python' ? './api/buscar?' : './api/buscar.php?').catch(() => './api/buscar.php?');

const state = {filters:null, page:1, perPage:20, total:null, cache:new Map(), controller:null, currentItem:null, running:false, serial:0, processList:[]};
const searchable = ['numeroOab','nomeAdvogado','numeroProcesso','nomeParte','siglaTribunal','texto'];
const dateStart = $('dataDisponibilizacaoInicio');
const dateEnd = $('dataDisponibilizacaoFim');

let monitorInterval = null;
let isMonitoring = false;
let lastKnownTotal = 0;

function dateIso(d) { return [d.getFullYear(),String(d.getMonth()+1).padStart(2,'0'),String(d.getDate()).padStart(2,'0')].join('-'); }
function dateForDisplay(value) { return /^\d{4}-\d\d-\d\d/.test(value || '') ? value.slice(8,10)+'/'+value.slice(5,7)+'/'+value.slice(0,4) : (value || 'Não informada'); }
function quickDate(days) { const end=new Date(); const start=new Date(end.getFullYear(),end.getMonth(),end.getDate()); start.setDate(start.getDate()-Math.max(0,days-1)); dateStart.value=dateIso(start); dateEnd.value=dateIso(end); }
function toast(msg){ const e=$('toast');e.textContent=msg;e.hidden=false;window.clearTimeout(toast.timer);toast.timer=window.setTimeout(()=>e.hidden=true,3300); }
function notice(message,kind=''){const n=$('notice');n.hidden=!message;n.className='notice'+(kind?' '+kind:'');n.textContent=message||'';}
function node(tag, className, value) {const x=document.createElement(tag);if(className)x.className=className;if(value!==undefined)x.textContent=String(value);return x;}
function empty(title,content){const div=node('div','empty-state');div.append(node('div','empty-icon','⌕'),node('h3','',title),node('p','',content));$('results').replaceChildren(div);}

function formFilters(){
    const data=new FormData(form);
    const obj={};
    for(const [name,value] of data){if(String(value).trim())obj[name]=String(value).trim();}
    if(obj.numeroProcesso)obj.numeroProcesso=obj.numeroProcesso.replace(/\D/g,'');
    if(obj.siglaTribunal)obj.siglaTribunal=obj.siglaTribunal.toUpperCase();
    return obj;
}

function verify(f){
    if(!searchable.some(k=>f[k])) return 'Informe tribunal, processo, nome, OAB ou teor.';
    if(f.ufOab&&!f.numeroOab) return 'Informe o número da OAB com a UF.';
    if(Boolean(f.dataDisponibilizacaoInicio)!==Boolean(f.dataDisponibilizacaoFim)) return 'Informe as duas datas ou nenhuma.';
    if(f.dataDisponibilizacaoInicio&&f.dataDisponibilizacaoInicio>f.dataDisponibilizacaoFim) return 'Data inicial maior que a final.';
    return '';
}
function setLoading(value){state.running=value;$('searchButton').disabled=value;$('searchButton').textContent=value?'Consultando CNJ…':'⌕ Buscar publicações';}

// Classificação e Cores baseadas no Teor
function classificarTeor(texto) {
    const txt = (texto || '').toLowerCase();
    if (txt.includes('mandado') || txt.includes('expedido')) return { badge: 'Mandado / Expedição', color: '#dc2626', bg: '#fee2e2' };
    if (txt.includes('agravo')) return { badge: 'Agravo', color: '#ea580c', bg: '#ffedd5' };
    if (txt.includes('cumprimento de sentença')) return { badge: 'Cump. Sentença', color: '#c026d3', bg: '#fdf4ff' };
    if (txt.includes('sentença') || txt.includes('decisão')) return { badge: 'Sentença/Decisão', color: '#7c3aed', bg: '#ede9fe' };
    if (txt.includes('audiência')) return { badge: 'Audiência', color: '#059669', bg: '#d1fae5' };
    return { badge: 'Andamento Padrão', color: '#2563eb', bg: '#dbeafe' };
}

function normalizeCnjItem(record) {
    return {
        id: record.id || record.hash,
        hash: record.hash,
        processo: record.numeroprocessocommascara || record.numeroProcesso || record.numeroprocesso,
        tribunal: record.siglaTribunal || record.sigla_tribunal,
        orgao: record.nomeOrgao || record.nome_orgao,
        classe: record.nomeClasse || record.nome_classe,
        data: record.dataDisponibilizacao || record.data_disponibilizacao,
        partes: [record.nomeDestinatario, record.nomeParte].filter(Boolean),
        texto: (record.texto || record.teor || '').trim()
    };
}

async function fetchBatch(page){
    if(state.controller) state.controller.abort();
    state.controller=new AbortController();
    
    const params=new URLSearchParams({...state.filters, pagina:String(page), itensPorPagina: '100'});
    const response=await fetch((await API_URL) + params.toString(),{
        signal: state.controller.signal,
        headers: { 'Accept': 'application/json' }
    });
    
    if(!response.ok) throw new Error('O CNJ limitou o acesso ou está fora do ar.');
    const data = await response.json();
    if (!data.ok) throw new Error(data.erro || 'Falha na consulta.');
    let itens = data.itens || [];

    // Triagem Local: Filtra pelos processos da lista, se houver
    if (state.processList.length > 0) {
        itens = itens.filter(item => {
            const procLimpo = (item.processo || '').replace(/\D/g, '');
            return state.processList.includes(procLimpo);
        });
    }

    return { ok: true, total: itens.length, itens: itens };
}

function preview(text){const norm=(text||'').replace(/\s+/g,' ').trim();return norm.length>340?norm.slice(0,340)+'…':(norm||'Sem teor.');}

function showDetails(item){
    state.currentItem=item;
    $('dialogMeta').textContent=[item.processo,item.tribunal,item.orgao,dateForDisplay(item.data)].filter(Boolean).join(' • ');
    $('dialogText').textContent=item.texto||'Sem teor disponível.';
    $('details').showModal();
}

function itemCard(item,index){
    const classeAto = classificarTeor(item.texto);
    const article = node('article','publication');
    article.style.borderLeft = `5px solid ${classeAto.color}`;
    
    const head = node('div','pub-head');
    head.append(node('span','tribunal',item.tribunal||'DJEN'));
    
    const tagAto = node('span','pub-type', classeAto.badge);
    tagAto.style.backgroundColor = classeAto.bg;
    tagAto.style.color = classeAto.color;
    tagAto.style.fontWeight = 'bold';
    head.append(tagAto);
    
    head.append(node('span','pub-date',dateForDisplay(item.data)));
    
    const proc = node('h3','pub-process');
    proc.append(node('span','',item.processo||'Processo não informado'));
    article.append(head,proc);
    
    if(item.orgao||item.classe){
        const org = node('p','pub-origin');
        org.textContent = `Órgão: ${item.orgao||'-'} | Classe: ${item.classe||'-'}`;
        article.append(org);
    }
    if(item.partes&&item.partes.length){
        const part = node('p','pub-parties');
        part.textContent = `Partes/Advogados: ${item.partes.join(' · ')}`;
        article.append(part);
    }
    
    article.append(node('div','pub-snippet',preview(item.texto)));
    
    const actions = node('div','pub-actions');
    actions.append(node('span','pub-index','Registro '+index));
    const btnLer = node('button','read-btn','Ler publicação completa →');
    btnLer.addEventListener('click',()=>showDetails(item));
    actions.append(btnLer);
    article.append(actions);
    
    return article;
}

async function showPage(newPage){
    if(!state.filters) return;
    state.page=newPage;
    $('pager').hidden=true;
    notice('');
    const list=$('results');
    list.replaceChildren(...Array.from({length:3},()=>node('div','loading-shape')));
    setLoading(true);
    
    try{
        const data = await fetchBatch(newPage);
        if(!data.itens.length){
            empty('Nenhuma publicação nesta página','Verifique sua lista de processos ou amplie as datas.');
        }else{
            list.replaceChildren(...data.itens.map((item,i)=>itemCard(item, i+1)));
        }
        
        $('summary').textContent=`${data.itens.length} resultados filtrados · Triagem Local`;
        return data.itens.length;
    }catch(e){
        empty('Não foi possível concluir','Erro na requisição ao CNJ.');
        notice(e.message||'Erro.','error');
        return 0;
    }finally{
        setLoading(false);
    }
}

form.addEventListener('submit',event=>{
    event.preventDefault();
    if(isMonitoring) return alert("Pare o monitoramento antes de realizar busca manual.");
    
    const rawList = '';
    state.processList = rawList.split('\n').map(p => p.replace(/\D/g, '')).filter(p => p.length > 0);
    
    const filters = formFilters();
    if(verify(filters)){ notice(verify(filters),'error'); return; }
    
    state.filters = filters;
    showPage(1);
});

$('closeDetails').addEventListener('click',()=>$('details').close());
$('doneDetails').addEventListener('click',()=>$('details').close());

// ==========================================
// MONITORAMENTO (2 HORAS)
// ==========================================
async function checarPermissaoNotificacao() {
    if (!("Notification" in window)) return false;
    if (Notification.permission === "granted") return true;
    if (Notification.permission !== "denied") {
        const permissao = await Notification.requestPermission();
        return permissao === "granted";
    }
    return false;
}

const btnMonitor = node('button', 'search-btn', '⏱️ Iniciar Monitoramento (2h)');
btnMonitor.type = 'button';
btnMonitor.style.backgroundColor = '#10b981'; 
btnMonitor.style.marginLeft = '10px';
$('searchButton').parentNode.insertBefore(btnMonitor, $('searchButton').nextSibling);

btnMonitor.addEventListener('click', async () => {
    if (isMonitoring) {
        clearInterval(monitorInterval);
        isMonitoring = false;
        btnMonitor.textContent = '⏱️ Iniciar Monitoramento (2h)';
        btnMonitor.style.backgroundColor = '#10b981';
        notice('Monitoramento desligado.', 'success');
    } else {
        await checarPermissaoNotificacao();
        
        const rawList = '';
        state.processList = rawList.split('\n').map(p => p.replace(/\D/g, '')).filter(p => p.length > 0);
        state.filters = formFilters();
        
        isMonitoring = true;
        btnMonitor.textContent = '🛑 Parar Monitoramento';
        btnMonitor.style.backgroundColor = '#dc2626';
        notice('Monitoramento ligado. Buscando na OAB e filtrando localmente a cada 2 horas.', 'success');

        lastKnownTotal = await showPage(1) || 0;

        // Intervalo de 2 horas (7.200.000 milissegundos)
        monitorInterval = setInterval(async () => {
            if (!state.filters) return;
            try {
                const data = await fetchBatch(1);
                const totalAtual = data.itens.length;
                if (totalAtual > lastKnownTotal) {
                    const novos = totalAtual - lastKnownTotal;
                    if (Notification.permission === "granted") {
                        new Notification("🚨 Nova Movimentação DJEN", { body: `${novos} nova(s) publicação(ões) na sua lista!`, icon: "https://comunica.pje.jus.br/favicon.ico" });
                    }
                    lastKnownTotal = totalAtual;
                    showPage(1);
                }
            } catch (e) {
                console.error("Falha no monitoramento.", e);
            }
        }, 7200000);
    }
});