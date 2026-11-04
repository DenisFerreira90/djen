"""Relações explícitas entre expedições e seus eventos; sem inferir teor de PDFs."""
import re,unicodedata

def norm(text):return ''.join(c for c in unicodedata.normalize('NFKD',str(text).lower()) if not unicodedata.combining(c))

def summarize(events):
 latest={str(e['numero']):e for e in events}
 ordered=sorted(latest.values(),key=lambda e:int(e['numero']) if str(e['numero']).isdigit() else -1)
 mandates={};linked={};changes=[];liminar=None
 for e in ordered:
  text=e.get('descricao','');t=norm(text);number=str(e['numero'])
  refs=re.findall(r'refer(?:ente)?\.?\s*ao\s*evento\s*:?\s*(\d+)',t)
  roots={linked[r] for r in refs if r in linked}
  item={'evento':number,'data':e.get('data'),'descricao':text,'usuario':e.get('usuario_origem',''),'documentos':list(dict.fromkeys(re.findall(r'\b[A-Z][A-Z0-9_]*\d+\b',str(e.get('documentos_referencias',''))))),'referencias':refs}
  if 'concedida a medida liminar' in t:liminar=item
  # Sem relação explícita não associar retorno ao último mandado por proximidade.
  issuance=bool(re.search(r'expedicao de mandado|mandado expedido',t)) and not re.search(r'nao exped|cancel|revog|indefer',t)
  if 'mandado' not in t and not roots:continue
  changes.append(item)
  if issuance:
   linked[number]=number
   mandates[number]={'expedicao':item,'situacao':'Expedido; retorno não identificado','atualizacao':item,'eventos':[item],'retorno_localizado':False}
  elif len(roots)==1:
   root=next(iter(roots));linked[number]=root;m=mandates[root];m['eventos'].append(item);m['atualizacao']=item
   if re.search(r'suspend|revog|cancel|recolhim',t):m['situacao']='Alteração da ordem; conferir documento'
   elif 'recebido' in t and 'cumprimento' in t:m['situacao']='Recebido pelo oficial para cumprimento'
   elif re.search(r'negativ|nao cumprid',t):m['situacao']='Retorno negativo; motivo depende da certidão';m['retorno_localizado']=True
   elif re.search(r'cumprid|apreendid',t):m['situacao']='Cumprimento registrado; conferir certidão';m['retorno_localizado']=True
   elif re.search(r'retorno|devolu|juntada.*certidao',t):m['situacao']='Retorno/documento relacionado localizado; conferir conteúdo';m['retorno_localizado']=True
   else:m['situacao']='Novo evento relacionado; conferir descrição'
 values=list(mandates.values())
 highlight=max(values,key=lambda m:int(m['atualizacao']['evento']),default=None)
 return {'mandados':values,'destaque':highlight,'liminar':liminar,'historico':changes,
 'situacao':highlight['situacao'] if highlight else 'Expedição não identificada nos eventos importados',
 'veiculo':'Consultar o documento: identificação não confirmada pela lista de eventos',
 'cobertura':'Fonte: eventos importados do eproc. Retorno não localizado nesta consulta não confirma ausência de cumprimento. Confira o documento e a data da coleta.'}
