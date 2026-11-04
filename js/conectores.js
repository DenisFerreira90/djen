'use strict';
window.Conectores={async render(){
 const {api,head,card,el,table,button,go}=window.Juridico;
 head('Tribunais e conexões','Disponibilidade das fontes e preparação para novas integrações.');
 const data=await api('conectores');const box=card();
 box.append(el('p','callout',data.aviso));
 table(['Fonte','Tribunal','Disponibilidade','Dados disponíveis','Acesso'],data.itens.map(r=>[
  r.sistema,r.tribunal,r.estado==='instalado'?'Conector instalado':r.estado==='desativado_temporariamente'?'Temporariamente desativado':'Integração futura',
  Object.entries(r.capacidades).filter(([,v])=>v).map(([k])=>({cadastro:'Cadastro',eventos:'Eventos',documentos:'Documentos',incremental:'Leitura incremental'}[k])).join(' · ')||'Ainda sem coleta',r.acesso
 ]),box);
 const detail=el('details','ui-disclosure');detail.append(el('summary','','Detalhes das integrações'));
 for(const item of data.itens)detail.append(el('p','',item.sistema+' / '+item.tribunal+': '+item.observacao));
 box.append(detail,button('Consultar processos',()=>go('coletas'),'primary'));
}};
