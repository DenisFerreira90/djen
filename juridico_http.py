"""HTTP API for the local legal workspace; all changes require individual login."""
import base64
from http.cookies import SimpleCookie
import io
import json
import re
import urllib.parse
import zipfile
import juridico as legal
import gestao
import planilhas


def cookie_name(handler):
    return 'conectaadv_chat_session' if getattr(handler.server,'chat_independente',False) else 'juridico_session'

def token(handler):
    cookies=SimpleCookie()
    try: cookies.load(handler.headers.get('Cookie',''))
    except Exception: return ''
    name=cookie_name(handler)
    return cookies[name].value if name in cookies else ''


def handle(h, method):
    url=urllib.parse.urlsplit(h.path)
    path=url.path
    if not path.startswith(('/api/juridico/','/api/eproc/')): return False
    try:
        import rede_piloto
        expected_origin=rede_piloto.origin(h)
        secure=expected_origin.startswith('https://')
        if method=='POST':
            if (h.headers.get('Content-Type')!='application/json' or h.headers.get('Origin') not in (None,expected_origin)
                    or h.headers.get('Sec-Fetch-Site')=='cross-site'):
                raise legal.AppError('Origem não permitida.',403)
            try: size=int(h.headers.get('Content-Length','0'))
            except ValueError: raise legal.AppError('Tamanho inválido.')
            if not 0<size<=48*1024*1024: raise legal.AppError('Requisição excede o limite.',413)
            try: body=json.loads(h.rfile.read(size))
            except (ValueError,UnicodeError): raise legal.AppError('JSON inválido.')
            if not isinstance(body,dict): raise legal.AppError('Requisição inválida.')
        else: body={}
        if path=='/api/juridico/sessao' and method=='GET':
            try:
                user,csrf=legal.store.auth(token(h));output={'ok':True,'usuario':user,'csrf':csrf,'configurar':False,'modo_chat':getattr(h.server,'chat_only',False),'chat_externo':getattr(h.server,'chat_externo',False)}
            except legal.AppError: output={'ok':True,'usuario':None,'configurar':legal.store.setup_needed(),'modo_chat':getattr(h.server,'chat_only',False),'chat_externo':getattr(h.server,'chat_externo',False)}
            h.send_json(200,output);return True
        if path=='/api/juridico/configurar' and method=='POST':
            user=legal.store.create_user(body,setup=True)
            h.send_json(201,{'ok':True,'usuario':user});return True
        if path=='/api/juridico/entrar' and method=='POST':
            result,session=legal.store.login(body.get('login',''),body.get('senha',''),rede_piloto.peer(h))
            h.send_json(200,{'ok':True,**result},{'Set-Cookie':cookie_name(h)+'='+session+'; Path=/; HttpOnly; SameSite=Strict; Max-Age=28800'+('; Secure' if secure else '')});return True
        actor,csrf=legal.store.auth(token(h))
        if method=='POST' and not __import__('hmac').compare_digest(h.headers.get('X-CSRF-Token',''),csrf):
            raise legal.AppError('Sessão inválida. Atualize a página e entre novamente.',403)
        query=urllib.parse.parse_qs(url.query)
        def q(key,default=''): return query.get(key,[default])[0]
        try: page=max(1,int(q('pagina','1')))
        except ValueError: raise legal.AppError('Página inválida.')
        output=None
        if path=='/api/juridico/calendarios' and method=='GET':
            import calendario
            output=calendario.calendars(legal.store,actor)
        elif path=='/api/juridico/calendarios' and method=='POST':
            import calendario
            output=calendario.create(legal.store,actor,body.get('nome',''))
        elif re.fullmatch(r'/api/juridico/calendarios/\d+/permissoes',path):
            import calendario
            output=calendario.grants(legal.store,actor,int(path.split('/')[-2]),body.get('permissoes',[]) if method=='POST' else None)
        elif re.fullmatch(r'/api/juridico/calendarios/\d+/eventos',path):
            import calendario
            cid=int(path.split('/')[-2])
            output=calendario.events(legal.store,actor,cid,q('de'),q('ate')) if method=='GET' else calendario.save(legal.store,actor,cid,body)
        elif re.fullmatch(r'/api/juridico/calendarios/\d+/eventos/\d+',path) and method=='POST':
            import calendario
            output=calendario.save(legal.store,actor,int(path.split('/')[-3]),body,int(path.split('/')[-1]))
        elif path=='/api/juridico/servico-coleta' and method=='POST':
            import agendamento
            output=agendamento.configure_service(legal.store,actor,body)
        elif path=='/api/juridico/fila-coleta' and method=='GET':
            import fila_coleta
            output=fila_coleta.status(legal.store,actor)
        elif path.startswith('/api/juridico/chat/'):
            if getattr(h.server,'chat_externo',False):raise legal.AppError('Chat transferido para o serviço independente na porta 8766.',409)
            import chat_interno as chat
            route=path.removeprefix('/api/juridico/chat/')
            if route=='organizacao':
                import chat_escritorio as office
                output=office.directory(legal.store,actor,body if method=='POST' else None)
            elif route=='avisos/previa' and method=='POST':
                import chat_escritorio as office
                output=office.preview(legal.store,actor,body)
            elif route=='avisos' and method=='POST':
                import chat_escritorio as office
                output=office.broadcast(legal.store,actor,body)
            elif route=='configuracoes':
                import chat_visualizacao as visual
                output=visual.config(legal.store,actor,body if method=='POST' else None)
            elif route=='previas' and method=='GET':
                import chat_visualizacao as visual
                output=visual.previews(legal.store,actor)
            elif re.fullmatch(r'mensagens/\d+/leituras',route) and method=='GET':
                import chat_visualizacao as visual
                output=visual.receipt(legal.store,actor,int(route.split('/')[1]))
            elif re.fullmatch(r'conversas/\d+/recebidas',route) and method=='POST':
                import chat_visualizacao as visual
                output=visual.acknowledge(legal.store,actor,int(route.split('/')[1]),body.get('mensagens',[]))
            elif route=='alertas' and method=='GET':
                import chat_alertas
                output=chat_alertas.feed(legal.store,actor,None if q('apos','')=='' else int(q('apos')))
            elif route=='controle':
                import chat_recursos as features
                output=features.config(legal.store,actor,body if method=='POST' else None)
            elif re.fullmatch(r'mensagens/\d+/acao',route) and method=='POST':
                import chat_recursos as features
                output=features.action(legal.store,actor,int(route.split('/')[1]),body)
            elif re.fullmatch(r'mensagens/\d+/encaminhar',route) and method=='POST':
                import chat_recursos as features
                output=features.forward(legal.store,actor,int(route.split('/')[1]),body)
            elif re.fullmatch(r'conversas/\d+/silenciar',route) and method=='POST':
                import chat_recursos as features
                output=features.mute(legal.store,actor,int(route.split('/')[1]),body)
            elif route=='preferencias':
                import chat_preferencias as prefs
                output=prefs.get(legal.store,actor) if method=='GET' else prefs.save(legal.store,actor,body)
            elif route=='presenca' and method=='POST':
                import chat_preferencias as prefs
                output=prefs.heartbeat(legal.store,actor,body)
            elif re.fullmatch(r'conversas/\d+/fixar',route) and method=='POST':
                import chat_preferencias as prefs
                output=prefs.pin(legal.store,actor,int(route.split('/')[1]),body.get('fixada') is True)
            elif route=='foto' and method=='POST':
                import chat_preferencias as prefs
                output=prefs.avatar_save(legal.store,actor,body)
            elif re.fullmatch(r'foto/\d+',route) and method=='GET':
                import chat_preferencias as prefs
                photo=prefs.avatar(legal.store,int(route.split('/')[1]));data=photo['conteudo']
                h.send_response(200);h.send_header('Content-Type',photo['mime']);h.send_header('Content-Length',str(len(data)));h.send_header('Cache-Control','private, no-store');h.send_header('X-Content-Type-Options','nosniff');h.end_headers();h.wfile.write(data);return True
            elif route=='usuarios' and method=='GET':output=chat.users(legal.store)
            elif re.fullmatch(r'usuarios/\d+',route) and method=='POST':output=chat.profile(legal.store,actor,int(route.split('/')[1]),body)
            elif re.fullmatch(r'conversas/\d+/nome',route) and method=='POST':output=chat.rename(legal.store,actor,int(route.split('/')[1]),body.get('titulo',''))
            elif route=='conversas':
                output=chat.rooms(legal.store,actor,q('auditoria')=='1') if method=='GET' else chat.create(legal.store,actor,body)
            elif re.fullmatch(r'conversas/\d+/mensagens',route):
                rid=int(route.split('/')[1])
                output=chat.messages(legal.store,actor,rid,int(q('apos','0')),int(q('antes','0')),q('busca'),q('motivo')) if method=='GET' else chat.send(legal.store,actor,rid,body)
            elif re.fullmatch(r'conversas/\d+/lida',route) and method=='POST':output=chat.read(legal.store,actor,int(route.split('/')[1]),body.get('mensagens') if 'mensagens' in body else int(body.get('mensagem_id',0)))
            elif re.fullmatch(r'conversas/\d+/membros',route) and method=='POST':output=chat.members(legal.store,actor,int(route.split('/')[1]),body.get('membros',[]))
            elif re.fullmatch(r'arquivos/[a-f0-9]{32}',route) and method=='GET':
                f=chat.download(legal.store,actor,route.split('/')[1],q('motivo'))
                inline=f['mime'] in ('image/png','image/jpeg','image/webp','image/gif','audio/ogg','audio/wav','audio/webm','video/mp4','video/webm')
                h.send_response(200);h.send_header('Content-Type',f['mime']);h.send_header('Content-Length',str(f['tamanho']));h.send_header('Content-Disposition',('inline' if inline else 'attachment')+"; filename*=UTF-8''"+urllib.parse.quote(f['nome']));h.send_header('Cache-Control','private, no-store');h.send_header('X-Content-Type-Options','nosniff');h.send_header('Content-Security-Policy',"default-src 'none'; sandbox");h.end_headers();h.wfile.write(f['conteudo']);return True
            elif re.fullmatch(r'conversas/\d+/exportar',route) and method=='GET':
                import chat_recursos as features
                features.require_manager(legal.store,actor,True)
                rid=int(route.split('/')[1]);output=chat.messages(legal.store,actor,rid,before=int(q('antes','0')),reason=q('motivo'))
                with legal.store.lock,legal.store.connect() as db:legal.store.audit(db,actor,'exportar_conversa','chat',rid)
                h.send_json(200,output,{'Content-Disposition':'attachment; filename="chat-'+str(rid)+'.json"'});return True
            else:raise legal.AppError('Rota de chat não encontrada.',404)
        elif path=='/api/juridico/agendamento' and method=='GET':
            import agendamento
            if actor['role']!='administrador':raise legal.AppError('Agendamento restrito ao administrador.',403)
            with legal.store.lock,legal.store.connect() as db:
                agendamento.schema(db);row=db.execute('SELECT config FROM collection_schedule WHERE id=1').fetchone()
                output=json.loads(row[0]) if row else {'ativo':False}
        elif path=='/api/juridico/painel-operacional' and method=='GET':
            import painel_operacional
            output=painel_operacional.report(legal.store,actor)
        elif path.startswith('/api/eproc/'):
            if method=='POST':
                if actor['role']=='leitor': raise legal.AppError('Seu perfil permite apenas leitura.',403)
                import eproc
                action=path.rsplit('/',1)[-1]
                if action not in ('iniciar','continuar','cancelar'): raise legal.AppError('Ação inválida.',404)
                try:
                    options=body.get('opcoes',{})
                    if not isinstance(options,dict) or options.get('modo','incremental') not in ('incremental','completa','falhas','individual'):raise legal.AppError('Modo de coleta inválido.')
                    if 'limite_minutos' in options and (type(options['limite_minutos'])is not int or not 10<=options['limite_minutos']<=55):raise legal.AppError('Orçamento inválido.')
                    if 'automatico' in options and type(options['automatico'])is not bool:raise legal.AppError('Modo automático inválido.')
                    eproc.tribunais.config(options.get('tribunal','TJRS'))
                    extra=options.get('complementos',[])
                    if not isinstance(extra,list) or len(extra)>6 or any(v not in eproc.READ_ACTIONS.values() for v in extra) or len(set(extra))!=len(extra):raise legal.AppError('Listagens complementares inválidas.')
                    if not isinstance(options.get('descobrir_consultas',False),bool):raise legal.AppError('Descoberta de consultas inválida.')
                    import eproc_relatorios
                    for report_action,kind in eproc_relatorios.ACTIONS.items():
                        if type(options.get('incluir_'+kind,kind=='prazos_a_encerrar'))is not bool:raise legal.AppError('Seleção de relatório inválida.')
                        if options.get('url_'+kind) and not eproc_relatorios.valid_url(options['url_'+kind],report_action,options.get('tribunal','TJRS')):raise legal.AppError('Endereço de relatório inválido.')
                    if options.get('modo')=='individual' and not legal.CNJ.fullmatch(str(options.get('numero',''))):raise legal.AppError('Informe o número CNJ completo e formatado.')
                    output=eproc.collector.start(actor=actor,options=options) if action=='iniciar' else eproc.collector.action(action)
                except ValueError as exc: raise legal.AppError(str(exc))
                with legal.store.lock,legal.store.connect() as db:
                    legal.store.audit(db,actor,'eproc_'+action,'coletas',(output.get('atual') or {}).get('id',''))
            else:
                # The original handler serves authenticated status/files.
                if path=='/api/eproc/exportar':
                    with legal.store.lock,legal.store.connect() as db: legal.store.audit(db,actor,'baixar_coleta','coletas',q('id'))
                return False
        elif path=='/api/juridico/sair' and method=='POST':
            import chat_preferencias as prefs
            prefs.offline(legal.store,actor,body.get('dispositivo',''))
            legal.store.logout(token(h),actor)
            h.send_json(200,{'ok':True},{'Set-Cookie':cookie_name(h)+'=; Path=/; HttpOnly; SameSite=Strict; Max-Age=0'+('; Secure' if secure else '')});return True
        elif path=='/api/juridico/backup' and method=='GET':
            data=gestao.backup(legal.store,actor)
            h.send_response(200);h.send_header('Content-Type','application/zip');h.send_header('Content-Disposition','attachment; filename="backup-'+('chat' if getattr(h.server,'chat_independente',False) else 'juridico')+'-'+legal.now()[:10]+'.zip"');h.send_header('Content-Length',str(len(data)));h.send_header('Cache-Control','private, no-store');h.send_header('X-Content-Type-Options','nosniff');h.end_headers();h.wfile.write(data);return True
        elif path=='/api/juridico/restaurar' and method=='POST':
            import eproc,controladoria
            if controladoria.queue.active():raise legal.AppError('Pause o preenchimento em lote e aguarde terminar a ficha atual antes de restaurar o banco.')
            if eproc.collector.thread and eproc.collector.thread.is_alive():raise legal.AppError('Encerre a coleta antes de restaurar o banco.')
            if body.get('confirmacao')!='RESTAURAR':raise legal.AppError('Digite RESTAURAR para confirmar a substituição dos cadastros.')
            output=gestao.restore(legal.store,base64.b64decode(body.get('arquivo_base64',''),validate=True),actor)
        elif re.fullmatch(r'/api/juridico/(?:complementos|consultas)/\d+',path) and method=='GET':
            rid=int(path.rsplit('/',1)[-1])
            with legal.store.lock,legal.store.connect() as db:
                db.execute('CREATE TABLE IF NOT EXISTS source_complements(id INTEGER PRIMARY KEY,case_id INTEGER,tipo TEXT,payload TEXT,signature TEXT,import_id TEXT,UNIQUE(case_id,tipo,signature))')
                rows=db.execute('SELECT tipo,payload,import_id FROM source_complements WHERE case_id=? ORDER BY id DESC LIMIT 30',(rid,)).fetchall()
                output=[{'tipo':r['tipo'],'dados':json.loads(r['payload']),'importacao':r['import_id']} for r in rows]
        elif re.fullmatch(r'/api/juridico/diagnostico/\d+',path) and method=='GET':
            import reprocessamento
            output=reprocessamento.diagnose(legal.store,int(path.rsplit('/',1)[-1]))
        elif re.fullmatch(r'/api/juridico/reprocessar/\d+',path) and method=='POST':
            import reprocessamento
            output=reprocessamento.repair(legal.store,actor,int(path.rsplit('/',1)[-1]))
        elif path=='/api/juridico/reprocessar' and method=='POST':
            import reprocessamento
            output=reprocessamento.repair(legal.store,actor)
        elif re.fullmatch(r'/api/juridico/processos/[0-9.\-]+/dados',path) and method=='GET':
            number=path.split('/')[-2]
            if not legal.CNJ.fullmatch(number):raise legal.AppError('Número CNJ inválido.')
            with legal.store.lock,legal.store.connect() as db:
                case=db.execute("SELECT id FROM records WHERE kind='processos' AND json_extract(data,'$.numero')=?",(number,)).fetchone()
                if not case:raise legal.AppError('Processo ainda não cadastrado.',404)
            import reprocessamento
            output=legal.store.detail(case['id'])
            output['diagnostico_origem']=reprocessamento.diagnose(legal.store,case['id'])
            output['consultas']={'eventos':'/api/juridico/eventos/'+str(case['id']),'complementos':'/api/juridico/complementos/'+str(case['id']),'reprocessar':'/api/juridico/reprocessar/'+str(case['id'])}
        elif path=='/api/juridico/email' and method=='GET':
            import email_alertas
            output=email_alertas.status(legal.store,actor)
        elif path=='/api/juridico/email' and method=='POST':
            import email_alertas
            output=email_alertas.save(legal.store,actor,body)
        elif path=='/api/juridico/email/teste' and method=='POST':
            import email_alertas
            output=email_alertas.test(legal.store,actor)
        elif path=='/api/juridico/mandados' and method=='GET':
            import mandados
            output=mandados.status(legal.store)
        elif path=='/api/juridico/mandados/lista/ler' and method=='POST':
            import mandados
            if actor['role']=='leitor':raise legal.AppError('Seu perfil permite apenas leitura.',403)
            output=mandados.extract_watchlist(base64.b64decode(body.get('arquivo_base64',''),validate=True),str(body.get('nome','')))
        elif path=='/api/juridico/mandados/lista' and method=='POST':
            import mandados
            output=mandados.set_scope(legal.store,actor,body.get('numeros',[]),body.get('somente_lista',True) is not False)
        elif path=='/api/juridico/mandados/varrer' and method=='POST':
            import mandados
            if actor['role']=='leitor':raise legal.AppError('Seu perfil permite apenas leitura.',403)
            output=mandados.scan(legal.store)
        elif re.fullmatch(r'/api/juridico/mandados/\d+/revisar',path) and method=='POST':
            import mandados
            output=mandados.review(legal.store,actor,int(path.split('/')[-2]))
        elif path=='/api/juridico/controladoria' and method=='GET':
            import controladoria
            output={'indicadores':controladoria.report(legal.store),**controladoria.queue.status(legal.store)}
        elif path=='/api/juridico/controladoria/preencher' and method=='POST':
            import controladoria
            auto=body.get('automatico',False)
            if not isinstance(auto,bool):raise legal.AppError('Modo automático inválido.')
            output=controladoria.queue.start(legal.store,actor,auto)
        elif path=='/api/juridico/controladoria/pausar' and method=='POST':
            import controladoria
            output=controladoria.queue.pause(legal.store,actor)
        elif path=='/api/juridico/organizar' and method=='POST':output=gestao.organize(legal.store,actor)
        elif path=='/api/juridico/agenda' and method=='GET':output=gestao.agenda(legal.store,{k:q(k) for k in ('responsavel','status','origem','de','ate','periodo','abertas','escopo')},page)
        elif path=='/api/juridico/atencao' and method=='GET':output=gestao.attention(legal.store,{k:q(k) for k in ('responsavel','q')},page)
        elif path=='/api/juridico/sincronizacao' and method=='GET':output=gestao.sync_rows(legal.store)
        elif re.fullmatch(r'/api/juridico/eventos/\d+',path) and method=='GET':
            rid=int(path.rsplit('/',1)[-1])
            with legal.store.lock,legal.store.connect() as db:
                db.execute('CREATE TABLE IF NOT EXISTS source_events(id INTEGER PRIMARY KEY,case_id INTEGER,numero TEXT,data TEXT,payload TEXT,signature TEXT,import_id TEXT,UNIQUE(case_id,numero,signature))')
                rows=db.execute('SELECT payload FROM source_events WHERE case_id=? ORDER BY CAST(numero AS INTEGER) DESC LIMIT 100 OFFSET ?',(rid,(page-1)*100)).fetchall()
                output={'itens':[json.loads(r[0]) for r in rows],'total':db.execute('SELECT COUNT(*) FROM source_events WHERE case_id=?',(rid,)).fetchone()[0],'pagina':page}
        elif re.fullmatch(r'/api/juridico/comparar/\d+',path) and method=='GET':output=gestao.compare_sources(legal.store,int(path.rsplit('/',1)[-1]))
        elif re.fullmatch(r'/api/juridico/linha-tempo/\d+',path) and method=='GET':output=gestao.timeline(legal.store,int(path.rsplit('/',1)[-1]))
        elif path=='/api/juridico/planilha/ler' and method=='POST':
            if actor['role']=='leitor':raise legal.AppError('Seu perfil permite apenas leitura.',403)
            try:parsed=planilhas.parse(base64.b64decode(body.get('arquivo_base64',''),validate=True),str(body.get('nome','')))
            except (ValueError,zipfile.BadZipFile,KeyError) as exc:raise legal.AppError('Não foi possível ler a planilha: '+str(exc))
            # Uploaded data remains in the browser for column mapping; no temporary server file.
            for sheet in parsed['abas']:
                sheet['cabecalho_sugerido']=planilhas.header_row(sheet['linhas'])
                headers=sheet['linhas'][sheet['cabecalho_sugerido']] if sheet['linhas'] else []
                sheet['sugestao']=planilhas.suggest(headers)
                if {'Processo','Partes','Evento e Prazo','Final Prazo'}<=set(headers):
                    sheet['tipo_origem']='eproc_lista_prazos'
                    if 'orgao' in sheet['sugestao']:
                        sheet['sugestao']['juizo_codigo']=sheet['sugestao'].pop('orgao')
                if planilhas.norm(sheet['nome']) in ('financeiro','tarefas','pessoas','documentos','auditoria'):
                    sheet['sugestao']={}
                    parsed['avisos'].append('A aba '+sheet['nome']+' é de consulta. A importação tabular cadastra processos, partes e prazos oficiais; para recuperar a base inteira, use o backup restaurável.')
            output=parsed
        elif path=='/api/juridico/planilha/importar' and method=='POST':
            sheet=body.get('aba',{});header=body.get('cabecalho',0)
            if not isinstance(sheet,dict) or not isinstance(sheet.get('linhas'),list) or type(header)is not int or not 0<=header<len(sheet['linhas']):raise legal.AppError('Aba ou cabeçalho inválido.')
            output=gestao.import_table(legal.store,sheet,header,body.get('mapa',{}),actor,str(body.get('nome','planilha')),bool(body.get('previa',True)))
        elif path=='/api/juridico/planilha/modelo' and method=='GET':
            data=planilhas.xlsx([('Importar',[[v for k,v in planilhas.FIELDS.items() if k not in ('nome_parte','papel','oab','uf')]])])
            h.send_response(200);h.send_header('Content-Type','application/vnd.openxmlformats-officedocument.spreadsheetml.sheet');h.send_header('Content-Disposition','attachment; filename="modelo-importacao.xlsx"');h.send_header('Content-Length',str(len(data)));h.send_header('Cache-Control','private, no-store');h.send_header('X-Content-Type-Options','nosniff');h.end_headers();h.wfile.write(data);return True
        elif path=='/api/juridico/planilha/exportar' and method=='GET':
            data=planilhas.xlsx(gestao.export_sheets(legal.store,actor))
            h.send_response(200);h.send_header('Content-Type','application/vnd.openxmlformats-officedocument.spreadsheetml.sheet');h.send_header('Content-Disposition','attachment; filename="juridico-'+legal.now()[:10]+'.xlsx"');h.send_header('Content-Length',str(len(data)));h.send_header('Cache-Control','private, no-store');h.send_header('X-Content-Type-Options','nosniff');h.end_headers();h.wfile.write(data);return True
        elif path=='/api/juridico/painel' and method=='GET': output=legal.store.dashboard()
        elif path=='/api/juridico/usuarios':
            output=legal.store.users(actor) if method=='GET' else legal.store.create_user(body,actor)
        elif re.fullmatch(r'/api/juridico/usuarios/\d+',path) and method=='POST': output=legal.store.update_user(int(path.rsplit('/',1)[-1]),body,actor)
        elif path=='/api/juridico/registros':
            kind=q('tipo') if method=='GET' else body.get('tipo','')
            output=legal.store.list(kind,q('q'),q('processo_id'),page) if method=='GET' else legal.store.save(kind,body,actor)
        elif re.fullmatch(r'/api/juridico/registros/\d+',path):
            rid=int(path.rsplit('/',1)[-1])
            output=legal.store.detail(rid) if method=='GET' else legal.store.save(body.get('tipo',''),body,actor,rid)
        elif path=='/api/juridico/auditoria' and method=='GET': output=legal.store.audits(actor,q('q'),page)
        elif re.fullmatch(r'/api/juridico/evidencias/\d+',path) and method=='GET': output=legal.store.evidence(int(path.rsplit('/',1)[-1]))
        elif path=='/api/juridico/importar' and method=='POST':
            if 'execucao_id' in body:
                import eproc
                run=str(body['execucao_id'])
                if not re.fullmatch(r'\d{8}-\d{6}-[a-f0-9]{8}',run): raise legal.AppError('Execução inválida.')
                file=eproc.collector.data/run/'processos.json'
                if not file.is_file(): raise legal.AppError('Dados da execução não disponíveis.',404)
                payload=json.loads(file.read_text(encoding='utf-8'))
            elif 'arquivo_base64' in body:
                try:
                    data=base64.b64decode(body['arquivo_base64'],validate=True)
                    if data.startswith(b'PK'):
                        with zipfile.ZipFile(io.BytesIO(data)) as archive:
                            info=archive.getinfo('processos.json')
                            if info.file_size>128*1024*1024: raise ValueError()
                            data=archive.read(info)
                    payload=json.loads(data.decode('utf-8-sig'))
                except (ValueError,KeyError,zipfile.BadZipFile,UnicodeError): raise legal.AppError('Envie processos.json ou o ZIP de uma coleta eproc.')
            else: raise legal.AppError('Informe uma execução ou arquivo de coleta.')
            output=legal.store.import_corpus(payload,actor)
        elif path=='/api/juridico/exportar' and method=='GET':
            output=legal.store.export(actor)
            filename='juridico-'+legal.now()[:10]+'.json'
            h.send_json(200,output,{'Content-Disposition':'attachment; filename="'+filename+'"'});return True
        else: raise legal.AppError('Rota não encontrada.',404)
        h.send_json(200,{'ok':True,'resultado':output});return True
    except legal.AppError as exc:
        h.send_json(exc.code,{'ok':False,'erro':str(exc)});return True
    except (ValueError,TypeError):
        h.send_json(400,{'ok':False,'erro':'Confira os dados enviados.'});return True
    except Exception:
        h.send_json(500,{'ok':False,'erro':'Não foi possível concluir a operação. Os dados anteriores foram preservados.'})
        import traceback;traceback.print_exc()
        return True
