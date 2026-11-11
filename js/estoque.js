'use strict';
(()=>{
const C={stock:null,page:1,q:'',local:'',low:false};
const quantity=value=>Number(value).toLocaleString('pt-BR',{maximumFractionDigits:3});
window.Estoque={async render(){
 const J=window.Juridico,{S,api,el,head,card,button,table,toast,stamp}=J;
 const access=await api('estoque/acesso');S.estoque=access;
 const nav=document.querySelector('[data-view="estoque"]');if(nav)nav.hidden=!access.estoques.length;
 head('Estoque','Materiais, saldos e locais de armazenamento.');
 if(!access.estoques.length){card().append(el('p','','Seu usuário não tem acesso aos estoques.'));return;}
 if(!access.estoques.some(s=>s.codigo===C.stock)){C.stock=access.estoques[0].codigo;C.page=1;C.local='';}
 const stock=C.stock,selected=access.estoques.find(s=>s.codigo===stock),write=selected.permissao==='crud';
 const [data,locations]=await Promise.all([api(`estoque/itens?estoque=${stock}&q=${encodeURIComponent(C.q)}&pagina=${C.page}&local=${C.local}&baixos=${C.low?'1':'0'}`),api('estoque/locais?estoque='+stock)]);
 const box=card(),bar=el('div','toolbar'),choose=el('select');box.className+=' inventory';choose.setAttribute('aria-label','Estoque');
 for(const s of access.estoques)choose.append(new Option(s.nome,s.codigo));choose.value=stock;
 choose.onchange=()=>{C.stock=choose.value;C.page=1;C.local='';C.q='';C.low=false;J.render();};
 bar.append(choose,el('span','badge',write?'Visualizar e CRUD':'Somente visualização'));
 if(write)bar.append(button('+ Material',()=>edit(),'primary'),button('Locais de armazenamento',manageLocations));
 if(access.gerenciar_permissoes)bar.append(button('Permissões dos estoques',permissions));
 box.append(bar);
 const summary=el('div','toolbar');summary.append(el('span','badge',`${data.resumo.materiais} materiais`),el('span','badge',`${data.resumo.sem_saldo} sem saldo`),el('span','badge',`${data.resumo.baixos} no mínimo ou abaixo`));box.append(summary);
 const filters=el('form','toolbar inventory-filters'),search=el('input'),local=el('select'),low=el('input'),lowLabel=el('label','');
 search.type='search';search.placeholder='Buscar material, código, categoria ou local';search.setAttribute('aria-label','Buscar materiais');search.value=C.q;
 local.setAttribute('aria-label','Local de armazenamento');local.append(new Option('Todos os locais',''));for(const l of locations)local.append(new Option(l.nome,l.id));local.value=C.local;
 low.type='checkbox';low.checked=C.low;lowLabel.append(low,document.createTextNode(' Somente saldo mínimo ou abaixo'));
 const filter=el('button','','Buscar');filter.type='submit';filters.append(search,local,lowLabel,filter);
 filters.onsubmit=event=>{event.preventDefault();C.q=search.value;C.local=local.value;C.low=low.checked;C.page=1;J.render();};box.append(filters);
 box.append(el('p','',`${data.total} resultado(s) · ${selected.nome}`));
 if(!data.itens.length)box.append(el('p','','Nenhum material encontrado com estes filtros.'));
 else table(['Material','Categoria','Armazenamento','Saldo','Mínimo','Situação','Ações'],data.itens.map(item=>{
  const name=el('div');name.append(el('strong','',item.nome),el('small','',item.codigo?'Código / patrimônio: '+item.codigo:'Material #'+item.id));
  const actions=el('div','toolbar inventory-actions');actions.append(button('Histórico',()=>history(item.id),'link'));
  if(write)actions.append(button('Editar',()=>edit(item),'link'),button('Entrada / Saída',()=>movement(item),'link'),button('Excluir',()=>remove(item),'link'));
  return [name,item.categoria||'—',item.local,quantity(item.quantidade)+' '+item.unidade,quantity(item.minimo)+' '+item.unidade,el('span','badge'+(item.baixo?' warn':''),item.baixo?'Reposição':'Disponível'),actions];
 }),box);
 paginate(box,data.pagina,data.total,p=>{C.page=p;J.render();});

 function paginate(parent,page,total,change){const pages=Math.max(1,Math.ceil(total/100)),bar=el('div','toolbar');
  const prev=button('Anterior',()=>change(page-1)),next=button('Próxima',()=>change(page+1));prev.disabled=page<=1;next.disabled=page>=pages;bar.append(prev,el('span','',`Página ${page} de ${pages}`),next);parent.append(bar);
 }
 function modal(title){const dialog=el('dialog','calendar-dialog inventory-dialog'),form=el('form','form-grid'),error=el('p','full');error.setAttribute('role','alert');dialog.append(el('h2','',title),form);document.body.append(dialog);
  const close=()=>{dialog.close();dialog.remove();};dialog.addEventListener('cancel',()=>dialog.remove());
  return {dialog,form,error,close};
 }
 function field(form,name,label,type,value='',choices=null){const wrap=el('label','',label),input=el(type==='textarea'?'textarea':choices?'select':'input');
  if(choices)for(const [v,t] of choices)input.append(new Option(t,v));else if(type!=='textarea')input.type=type;
  input.name=name;input.value=String(value??'');if(type==='number'){input.min='0';input.step='0.001';}
  wrap.append(input);form.append(wrap);return input;
 }
 function finish(m,submit,action){const save=el('button','primary',submit);save.type='submit';m.form.append(m.error,button('Cancelar',m.close),save);
  m.form.onsubmit=async event=>{event.preventDefault();save.disabled=true;m.error.textContent='';try{await action();m.close();await J.render();}catch(e){m.error.textContent=e.message;save.disabled=false;}};m.dialog.showModal();
 }
 function edit(item){const m=modal(item?'Editar material':'Cadastrar material'),f={};
  for(const [name,label,type,defaultValue] of [['nome','Material','text',''],['categoria','Categoria','text',''],['codigo','Código / patrimônio (opcional)','text',''],['unidade','Unidade (un., caixa, litro…)','text','un.'],['quantidade','Saldo','number','0'],['minimo','Quantidade mínima','number','0'],['observacoes','Detalhes / prateleira / observações','textarea','']])f[name]=field(m.form,name,label,type,item?.[name]??defaultValue);
  f.nome.required=true;f.unidade.required=true;f.quantidade.required=true;f.minimo.required=true;
  f.local_id=field(m.form,'local_id','Local de armazenamento','select',item?.local_id??locations[0]?.id??'',locations.map(l=>[l.id,l.nome]));f.local_id.required=true;
  f.motivo=field(m.form,'motivo','Motivo da alteração de saldo ou local','text','');
  finish(m,'Salvar material',async()=>{const body=Object.fromEntries(Object.entries(f).map(([k,v])=>[k,v.value]));body.estoque=stock;body.local_id=Number(body.local_id);if(item)body.versao=item.versao;await api('estoque/itens'+(item?'/'+item.id:''),body);toast('Material salvo.');});
 }
 function movement(item){const m=modal('Entrada / Saída · '+item.nome);
  m.form.append(el('p','full',`Saldo atual: ${quantity(item.quantidade)} ${item.unidade} · ${item.local}`));
  const type=field(m.form,'tipo','Movimentação','select','entrada',[['entrada','Entrada'],['saida','Saída']]),amount=field(m.form,'quantidade','Quantidade','number',''),reason=field(m.form,'motivo','Motivo / destinatário / referência','textarea','');amount.required=true;amount.min='0.001';reason.required=true;
  finish(m,'Registrar movimentação',async()=>{await api(`estoque/itens/${item.id}/movimentar`,{tipo:type.value,quantidade:amount.value,motivo:reason.value,versao:item.versao});toast('Movimentação registrada.');});
 }
 function remove(item){const m=modal('Excluir material · '+item.nome);
  m.form.append(el('p','full','A exclusão exige saldo zero e mantém a auditoria. Se ainda há material, registre a saída ou corrija o saldo antes.'));
  const reason=field(m.form,'motivo','Motivo da exclusão','textarea','');reason.required=true;
  finish(m,'Excluir material',async()=>{await api(`estoque/itens/${item.id}/excluir`,{versao:item.versao,motivo:reason.value});toast('Material excluído.');});
 }
 async function history(iid,page=1){const data=await api(`estoque/itens/${iid}/historico?pagina=${page}`),m=modal('Histórico · '+data.item.nome);m.form.remove();
  const content=el('div');m.dialog.append(content);table(['Data','Pessoa','Operação','Saldo anterior','Saldo posterior','Local anterior','Local posterior','Motivo'],data.itens.map(r=>[stamp(r.data),r.usuario,r.tipo,quantity(r.antes),quantity(r.depois),r.local_antes_nome||'—',r.local_depois_nome||'—',r.motivo]),content);
  paginate(content,data.pagina,data.total,p=>{m.close();history(iid,p).catch(e=>toast(e.message));});m.dialog.append(button('Fechar',m.close));m.dialog.showModal();
 }
 function manageLocations(){const m=modal('Locais · '+selected.nome),name=field(m.form,'nome','Novo local','text','');name.required=true;
  const list=el('div','full');m.form.prepend(list);
  for(const loc of locations){const row=el('div','toolbar'),input=el('input');input.value=loc.nome;input.setAttribute('aria-label','Nome do local');const error=el('span','');
   const update=async body=>{try{await api('estoque/locais/'+loc.id,{estoque:stock,versao:loc.versao,...body});C.local='';m.close();await J.render();}catch(e){error.textContent=e.message;}};
   row.append(input,button('Renomear',()=>update({nome:input.value}),'link'),button('Excluir local',()=>{if(confirm('Excluir o local '+loc.nome+'?'))return update({excluir:true});},'link'),error);list.append(row);
  }
  finish(m,'Adicionar local',async()=>{await api('estoque/locais',{estoque:stock,nome:name.value});C.local='';toast('Local cadastrado.');});
 }
 async function permissions(){const data=await api('estoque/permissoes'),m=modal('Permissões dos estoques');m.form.remove();
  m.dialog.append(el('p','','Escolha o acesso por pessoa e por estoque. CRUD permite cadastrar, consultar, editar, excluir e movimentar materiais e locais. Administradores gerenciam os dois estoques. A pessoa deve atualizar a página após uma mudança de acesso.'));
  const content=el('div');m.dialog.append(content);
  table(['Pessoa','TI','Escritório e Limpeza',''],data.usuarios.map(user=>{const inputs={};
   for(const stockId of ['ti','escritorio_limpeza']){const select=el('select');for(const [value,label] of [['','Sem acesso'],['ver','Visualizar'],...(user.role==='leitor'?[]:[['crud','Visualizar e CRUD']])])select.append(new Option(label,value));select.value=user.permissoes[stockId]||'';select.disabled=user.role==='administrador';select.setAttribute('aria-label',user.nome+' · '+data.estoques[stockId]);inputs[stockId]=select;}
   const cell=el('div'),message=el('span',''),save=button('Salvar acesso',async()=>{save.disabled=true;try{await api('estoque/permissoes',{user_id:user.id,permissoes:Object.fromEntries(Object.entries(inputs).map(([k,v])=>[k,v.value]))});message.textContent='Acesso salvo.';}catch(e){message.textContent=e.message;}finally{save.disabled=user.role==='administrador';}});save.disabled=user.role==='administrador';cell.append(save,message);
   return [user.nome,inputs.ti,inputs.escritorio_limpeza,cell];
  }),content);m.dialog.append(button('Fechar',m.close));m.dialog.showModal();
 }
}};
})();
