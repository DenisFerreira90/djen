"""Indicadores com lista de evidências e escopo por responsável."""
import datetime as dt
import json
import juridico as legal


def report(store,actor):
    today=legal.now()[:10];base=dt.date.fromisoformat(today);tomorrow=(base+dt.timedelta(days=1)).isoformat();week=(base+dt.timedelta(days=7)).isoformat()
    admin=actor['role']=='administrador'
    keys=['fatais_vencidos','fatais_hoje','fatais_amanha','fatais_7_dias','prazos_sem_conferencia','tarefas_urgentes','tarefas_atrasadas','documentos_em_revisao','processos_sem_responsavel','processos_sem_checagem','processos_desatualizados','prazos_sem_data','falhas_consulta','mandados_pendentes']
    lists={k:[] for k in keys}
    if admin:lists['financeiro_vencido']=[]
    with store.lock,store.connect() as db:
        sync={}
        if db.execute("SELECT 1 FROM sqlite_master WHERE name='sync_state'").fetchone():sync={r['numero']:dict(r) for r in db.execute('SELECT * FROM sync_state')}
        for row in db.execute('SELECT * FROM records'):
            d=json.loads(row['data']);kind=row['kind']
            if not admin and str(d.get('responsavel_id',''))!=str(actor['id']):continue
            item={'id':row['id'],'tipo':kind,'titulo':d.get('numero') or d.get('titulo') or d.get('nome') or str(row['id']),'vencimento':d.get('data_fatal') or d.get('vencimento'),'responsavel_id':d.get('responsavel_id')}
            def add(key):lists[key].append(item)
            when=str(item['vencimento'] or '')[:10];state=d.get('status','')
            if kind=='prazos' and state in ('pendente','conferir_origem','aguardando_abertura') and d.get('escopo')!='todas_as_partes' and d.get('origem')!='revisao_interna':
                if not d.get('conferido'):add('prazos_sem_conferencia')
                if not when:add('prazos_sem_data')
                if when:
                    if when<today:add('fatais_vencidos')
                    if when==today:add('fatais_hoje')
                    if when==tomorrow:add('fatais_amanha')
                    if today<=when<=week:add('fatais_7_dias')
            if kind=='tarefas' and state not in ('concluida','cancelada'):
                if d.get('prioridade')=='urgente':add('tarefas_urgentes')
                if when and when<today:add('tarefas_atrasadas')
            if kind=='documentos' and state=='em_revisao':add('documentos_em_revisao')
            if kind=='processos' and state!='arquivado':
                if not d.get('responsavel_id'):add('processos_sem_responsavel')
                origin=sync.get(d.get('numero'),{})
                if not origin.get('checked_at'):add('processos_sem_checagem')
                elif origin['checked_at'][:10]<today:add('processos_desatualizados')
                if origin.get('erro') or origin.get('situacao','').startswith('falha'):add('falhas_consulta')
            if admin and kind=='financeiro' and state=='pendente' and when and when<today:add('financeiro_vencido')
        if db.execute("SELECT 1 FROM sqlite_master WHERE name='mandate_alerts'").fetchone():
            for row in db.execute('SELECT a.*,r.data AS case_data FROM mandate_alerts a JOIN records r ON r.id=a.case_id WHERE a.revisado IS NULL'):
                data=json.loads(row['case_data'])
                if admin or str(data.get('responsavel_id',''))==str(actor['id']):lists['mandados_pendentes'].append({'id':row['case_id'],'tipo':'processos','titulo':row['numero']+' · evento '+row['evento'],'vencimento':None,'responsavel_id':data.get('responsavel_id')})
    return {'data':today,'escopo':'Escritório inteiro' if admin else 'Somente registros atribuídos a você','contagens':{k:len(v) for k,v in lists.items()},'listas':{k:sorted(v,key=lambda x:(x['vencimento'] or '',x['id']))[:100] for k,v in lists.items()},'limite_lista':100}
