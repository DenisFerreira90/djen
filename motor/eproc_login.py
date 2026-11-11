"""Etapas de autenticação; códigos nunca entram em logs ou checkpoints."""
import os,re
from urllib.parse import urlsplit
import eproc_tribunais as courts

OTP_FIELDS='input[autocomplete="one-time-code"], input[name="otp"], input[name="totp"], input#otp, input#totp, input#txtToken, input#txtCodigoAcesso'

def visible(locator):
    return [locator.nth(i) for i in range(locator.count()) if locator.nth(i).is_visible()]

def select_profile(frames,court,state,log,manual):
    if state.get('profile_sent') or state.get('profile_failed'):return False
    candidates=[]
    for frame in frames:
        parsed=urlsplit(frame.url)
        if parsed.scheme!='https' or parsed.hostname!=courts.config(court)['host'] or not parsed.path.startswith('/eproc/'):continue
        profiles=visible(frame.locator('button[data-descricao="ADVOGADO-TITULAR"]'))
        if not profiles:
            for button in visible(frame.locator('button[data-descricao]')):
                label=button.get_attribute('data-descricao')
                if isinstance(label,str) and re.fullmatch(r'(?:[A-Z]{2}\d{3,8}[A-Z]?\s*/\s*)?ADVOGADO[\s-]+TITULAR',label.strip(),re.I):profiles.append(button)
        if not profiles:profiles=visible(frame.get_by_text(re.compile(r'^ADVOGADO[\s-]+TITULAR$',re.I)))
        candidates.extend(profiles)
    if len(candidates)>1:
        if not state.get('profile_ambiguous'):
            state['profile_ambiguous']=True
            manual('Há mais de um perfil Advogado Titular. Selecione a conta desejada na janela do tribunal.')
        return False
    if not candidates:return False
    button=candidates[0]
    # Click the label area, outside the nested "Definir como padrão" action.
    label=button.locator('xpath=./div[1]')
    target=label if label.count()==1 and label.is_visible() else button
    try:target.click(timeout=15000)
    except Exception:
        state['profile_failed']=True
        manual('Não foi possível confirmar a seleção automática do perfil. Confira a janela e selecione Advogado Titular manualmente.')
        return False
    state['profile_sent']=True
    log('Perfil ADVOGADO-TITULAR selecionado. Aguardando painel.')
    return True


def step(collector,context):
    court=collector.options.get('tribunal','TJRS');cfg=courts.config(court)
    state=getattr(collector,'login_steps',None)
    if state is None:state={};collector.login_steps=state
    for frame in collector.surfaces(context):
        host=urlsplit(frame.url).hostname
        if host not in (cfg['host'],cfg['sso'],*cfg.get('auth_hosts',())):continue
        fields=visible(frame.locator(OTP_FIELDS))
        if len(fields)>1:collector.wait_user('Mais de um campo 2FA encontrado; é necessário conferir a página.');return
        if fields:
            if state.get('otp_sent'):return
            key=collector.options.get('autenticador_id')
            if not key or not getattr(collector,'actor',None):
                collector.wait_user('Selecione o autenticador 2FA desta conta nas opções de Coleta eproc.');return
            # Only recognized submit controls inside the detected OTP form.
            forms=fields[0].locator('xpath=ancestor::form[1]')
            if forms.count()!=1:collector.wait_user('Formulário 2FA não reconhecido.');return
            submits=visible(forms.locator('button[type="submit"], input[type="submit"], #kc-login'))
            if len(submits)!=1:collector.wait_user('Botão de confirmação 2FA não reconhecido.');return
            try:
                import twofa
                from juridico import store
                provider=getattr(collector,'authentication_code',None)
                code=provider() if provider else twofa.collector_code(store,collector.actor,key)
            except Exception:
                collector.wait_user('Não foi possível usar o autenticador selecionado. Confira a permissão 2FA e a conta Windows do servidor.');return
            if code is None:return
            fields[0].fill(code,timeout=10000)
            state['otp_sent']=True
            submits[0].click(timeout=15000)
            collector.log('2FA enviado com o autenticador selecionado. Aguardando confirmação do tribunal.')
            return
        if host in (cfg['sso'],*cfg.get('auth_hosts',())) and not state.get('credentials_sent'):
            prefix='EPROC' if court=='TJRS' else 'EPROC_'+court
            username,password=os.environ.get(prefix+'_USUARIO'),os.environ.get(prefix+'_SENHA')
            users=visible(frame.locator('input[name="username"]'));passwords=visible(frame.locator('input[name="password"]'));buttons=visible(frame.locator('#kc-login'))
            if len(users)==len(passwords)==len(buttons)==1 and not (username and password) and collector.background():
                collector.wait_user('Login '+court+' sem usuário/senha configurados e sem sessão autenticada. O A1 instalado não está integrado ao login deste coletor.');return
            if username and password and len(users)==len(passwords)==len(buttons)==1:
                users[0].fill(username,timeout=10000);passwords[0].fill(password,timeout=10000)
                state['credentials_sent']=True;buttons[0].click(timeout=15000)
                collector.log('Login enviado. Aguardando próxima etapa de autenticação.');return
    select_profile(collector.surfaces(context),court,state,collector.log,collector.wait_user)
