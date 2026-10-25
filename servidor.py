# -*- coding: utf-8 -*-
"""DJEN Consulta — servidor local para VS Code (Python 3.9+, sem pip/venv).

Executar: python servidor.py
Não armazena os resultados e não requer contas/credenciais.
"""
from __future__ import annotations

import argparse
import datetime as dt
from html.parser import HTMLParser
import json
import mimetypes
import os
from pathlib import Path
import re
import ssl
import threading
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = Path(__file__).resolve().parent
API_URL = 'https://comunicaapi.pje.jus.br/api/v1/comunicacao'
USER_AGENT = 'DJEN-Consulta-VSCode/1.0'
MAX_REMOTE_BYTES = 24 * 1024 * 1024
BATCH_SIZE = 100
ALLOWED_STATIC = {'/', '/index.html', '/css/style.css', '/js/app.js'}
FIELD_LIMITS = {
    'numeroOab': 32, 'ufOab': 2, 'nomeAdvogado': 140,
    'numeroProcesso': 32, 'nomeParte': 140, 'siglaTribunal': 12,
    'texto': 250, 'dataDisponibilizacaoInicio': 10,
    'dataDisponibilizacaoFim': 10, 'meio': 2,
}
SEARCH_FIELDS = {'numeroOab', 'nomeAdvogado', 'numeroProcesso', 'nomeParte', 'siglaTribunal', 'texto'}


class ValidationError(ValueError):
    pass


def validate_query(raw: str) -> tuple[dict[str, str], int]:
    if len(raw) > 4096:
        raise ValidationError('A consulta possui filtros muito longos.')
    try:
        parsed = urllib.parse.parse_qs(raw, keep_blank_values=True, strict_parsing=False, max_num_fields=30)
    except ValueError as exc:
        raise ValidationError('Quantidade de filtros inválida.') from exc
    allowed = set(FIELD_LIMITS) | {'pagina'}
    if any(k not in allowed for k in parsed):
        raise ValidationError('A consulta contém filtros não reconhecidos.')
    if any(len(v) != 1 for v in parsed.values()):
        raise ValidationError('Não repita o mesmo filtro.')
    out = {}
    for field, limit in FIELD_LIMITS.items():
        values = parsed.get(field, [''])
        value = values[0].strip()
        if len(value) > limit:
            raise ValidationError('Campo muito longo: ' + field)
        if any(ord(char) < 32 and char not in '\t\n' for char in value):
            raise ValidationError('Caracteres inválidos no filtro: ' + field)
        if value:
            out[field] = value

    number = out.get('numeroOab')
    if number and not re.fullmatch(r'[a-zA-Z0-9.\-/]+', number):
        raise ValidationError('Número da OAB inválido.')
    if 'ufOab' in out:
        out['ufOab'] = out['ufOab'].upper()
        if not re.fullmatch(r'[A-Z]{2}', out['ufOab']):
            raise ValidationError('UF da OAB inválida.')
        if not number:
            raise ValidationError('Preencha a OAB ou deixe a UF vazia.')
    if 'numeroProcesso' in out:
        out['numeroProcesso'] = re.sub(r'\D+', '', out['numeroProcesso'])
        if not 8 <= len(out['numeroProcesso']) <= 25:
            raise ValidationError('Confira o número do processo.')
    if 'siglaTribunal' in out:
        out['siglaTribunal'] = out['siglaTribunal'].upper()
        if not re.fullmatch(r'[A-Z0-9]{2,12}', out['siglaTribunal']):
            raise ValidationError('Sigla de tribunal inválida.')
    if out.get('meio') not in (None, 'D', 'E'):
        raise ValidationError('Tipo de publicação inválido.')
    for field in ('dataDisponibilizacaoInicio', 'dataDisponibilizacaoFim'):
        if field not in out:
            continue
        try:
            v = dt.date.fromisoformat(out[field])
        except ValueError as exc:
            raise ValidationError('Data inválida.') from exc
        if v.isoformat() != out[field]:
            raise ValidationError('Informe datas no formato AAAA-MM-DD.')
    start = out.get('dataDisponibilizacaoInicio')
    end = out.get('dataDisponibilizacaoFim')
    if bool(start) != bool(end):
        raise ValidationError('Preencha as duas datas ou deixe ambas vazias.')
    if start and end and start > end:
        raise ValidationError('A data inicial não pode ser posterior à final.')
    if not any(field in out for field in SEARCH_FIELDS):
        raise ValidationError('Informe tribunal, processo, nome, OAB ou teor para pesquisar.')
    page_raw = parsed.get('pagina', ['1'])[0]
    if not re.fullmatch(r'\d{1,5}', page_raw) or not (1 <= int(page_raw) <= 10000):
        raise ValidationError('Página inválida.')
    page = int(page_raw)
    out['pagina'] = str(page)
    out['itensPorPagina'] = str(BATCH_SIZE)
    return out, page


class TextFromHTML(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]):
        if tag.lower() in ('br', 'li'):
            self.parts.append('\n')

    def handle_endtag(self, tag: str):
        if tag.lower() in ('p', 'div', 'li', 'tr', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6'):
            self.parts.append('\n')

    def handle_data(self, data: str):
        self.parts.append(data)


def plain_text(value: str) -> str:
    parser = TextFromHTML()
    parser.feed(value)
    parser.close()
    text = ''.join(parser.parts).replace('\xa0', ' ')
    text = re.sub(r'[ \t]+', ' ', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


def field_text(record: dict, keys: tuple[str, ...]) -> str:
    for key in keys:
        value = record.get(key)
        if isinstance(value, (str, int, float)) and not isinstance(value, bool):
            return str(value).strip()
    return ''


def normalize_item(record: dict) -> dict:
    people = []
    for key in ('destinatarios', 'destinatarioadvogados', 'partes'):
        entries = record.get(key)
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if isinstance(entry, str):
                if entry.strip():
                    people.append(entry.strip())
            elif isinstance(entry, dict):
                label = field_text(entry, ('nome', 'nomeDestinatario', 'nomeParte', 'nomeAdvogado'))
                if label:
                    people.append(label)
    recipient = field_text(record, ('nomeDestinatario',))
    if recipient:
        people.append(recipient)
    people = list(dict.fromkeys(people))[:15]
    return {
        'id': field_text(record, ('id', 'hash')),
        'hash': field_text(record, ('hash',)),
        'processo': field_text(record, ('numeroprocessocommascara', 'numeroProcessoComMascara', 'numeroProcesso', 'numero_processo')),
        'tribunal': field_text(record, ('siglaTribunal', 'sigla_tribunal')),
        'orgao': field_text(record, ('nomeOrgao', 'nome_orgao')),
        'classe': field_text(record, ('nomeClasse', 'nome_classe')),
        'tipo': field_text(record, ('tipoComunicacao', 'tipo_comunicacao')),
        'data': field_text(record, ('dataDisponibilizacao', 'data_disponibilizacao')),
        'partes': people,
        'texto': plain_text(field_text(record, ('texto', 'teor', 'conteudo', 'teorPublicacao'))),
    }


class UpstreamError(Exception):
    def __init__(self, code: int, message: str, retry_after: str | None = None):
        self.code, self.message, self.retry_after = code, message, retry_after


def query_cnj(filters: dict, page: int) -> dict:
    url = API_URL + '?' + urllib.parse.urlencode(filters, quote_via=urllib.parse.quote)
    request = urllib.request.Request(url, headers={
        'Accept': 'application/json', 'Accept-Encoding': 'identity', 'User-Agent': USER_AGENT,
    }, method='GET')
    try:
        with urllib.request.urlopen(request, timeout=25, context=ssl.create_default_context()) as response:
            raw = response.read(MAX_REMOTE_BYTES + 1)
    except urllib.error.HTTPError as exc:
        retry = exc.headers.get('Retry-After') if exc.headers else None
        if exc.code == 429:
            raise UpstreamError(429, 'O CNJ limitou a quantidade de consultas. Aguarde e tente novamente.', retry) from exc
        code = 422 if 400 <= exc.code < 500 else 502
        raise UpstreamError(code, f'A API do CNJ respondeu com HTTP {exc.code}. Confira os filtros e o acesso à API.') from exc
    except (OSError, TimeoutError) as exc:
        raise UpstreamError(502, 'Não foi possível consultar o CNJ. Verifique a internet, o HTTPS e tente novamente.') from exc
    if len(raw) > MAX_REMOTE_BYTES:
        raise UpstreamError(502, 'O retorno do CNJ excedeu o limite seguro. Refine os filtros e o período.')
    try:
        payload = json.loads(raw.decode('utf-8-sig'))
    except (ValueError, UnicodeError) as exc:
        raise UpstreamError(502, 'O CNJ retornou dados fora do formato JSON esperado.') from exc
    if not isinstance(payload, dict):
        raise UpstreamError(502, 'O CNJ retornou dados em formato inesperado.')
    records = next((payload[k] for k in ('items','comunicacoes','content','data') if isinstance(payload.get(k), list)), None)
    if records is None:
        raise UpstreamError(502, 'A resposta do CNJ não contém uma lista válida de publicações.')
    total = None
    for key in ('count', 'total', 'totalElements', 'totalRegistros'):
        value = payload.get(key)
        if isinstance(value, (int, float)) or isinstance(value, str) and value.isdecimal():
            total = max(0, int(value))
            break
    return {
        'ok': True, 'pagina': page, 'tamanho_lote': BATCH_SIZE,
        'total': total,
        'itens': [normalize_item(it) for it in records if isinstance(it, dict)],
        'fonte': 'API pública do CNJ — DJEN',
        'aviso': ('A API do CNJ pode limitar buscas amplas a 10.000 resultados. Refine os filtros/período.'
                  if total is not None and total >= 10000 else None),
    }


class Handler(BaseHTTPRequestHandler):
    server_version = 'DJENConsulta/1.0'

    def do_GET(self):
        path = urllib.parse.urlsplit(self.path)
        if path.path == '/api/buscar':
            try:
                filters, page = validate_query(path.query)
                output = query_cnj(filters, page)
                self.send_json(200, output)
            except ValidationError as exc:
                self.send_json(400, {'ok': False, 'erro': str(exc)})
            except UpstreamError as exc:
                headers = {}
                if exc.retry_after and re.fullmatch(r'\d{1,4}', exc.retry_after.strip()):
                    headers['Retry-After'] = exc.retry_after.strip()
                self.send_json(exc.code, {'ok': False, 'erro': exc.message}, headers)
            except Exception:
                self.send_json(500, {'ok': False, 'erro': 'Erro interno na aplicação local.'})
                raise
            return
        if path.path == '/api/health':
            return self.send_json(200, {'ok': True, 'servidor': 'Python', 'api': 'CNJ'})
        if path.path not in ALLOWED_STATIC:
            return self.send_json(404, {'ok': False, 'erro': 'Arquivo não encontrado.'})
        item = 'index.html' if path.path == '/' else path.path.lstrip('/')
        filename = ROOT / item
        try:
            content = filename.read_bytes()
        except OSError:
            return self.send_json(404, {'ok': False, 'erro': 'Arquivo não encontrado.'})
        ctype = mimetypes.guess_type(str(filename))[0] or 'application/octet-stream'
        if ctype.startswith('text/') or ctype in ('application/javascript',):
            ctype += '; charset=utf-8'
        self.send_response(200)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(content)))
        self.send_header('Cache-Control', 'no-cache')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('X-Frame-Options', 'DENY')
        self.end_headers()
        self.wfile.write(content)

    def send_json(self, status: int, payload: dict, extra_headers: dict | None = None):
        body = json.dumps(payload, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'private, no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        if extra_headers:
            for key, value in extra_headers.items():
                self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        print('[DJEN] %s: %s' % (self.address_string(), fmt % args))


def main():
    parser = argparse.ArgumentParser(description='Consulta DJEN local (VS Code / Python)')
    parser.add_argument('--porta', type=int, default=int(os.environ.get('DJEN_PORT', '8765')))
    parser.add_argument('--sem-navegador', action='store_true', help='Não abrir navegador automaticamente')
    args = parser.parse_args()
    if not 1024 <= args.porta <= 65535:
        parser.error('Escolha uma porta entre 1024 e 65535.')
    try:
        server = ThreadingHTTPServer(('127.0.0.1', args.porta), Handler)
    except OSError as exc:
        parser.error('Não foi possível abrir a porta %d: %s' % (args.porta, exc))
    url = 'http://127.0.0.1:%d/' % args.porta
    print('\n' + '=' * 60)
    print(' DJEN CONSULTA SIMPLES — VSCODE / PYTHON')
    print(' Acesse: ' + url)
    print(' Sem XAMPP, PHP, Docker, MySQL ou ambiente virtual')
    print(' Para encerrar: Ctrl+C')
    print('=' * 60 + '\n')
    if not args.sem_navegador:
        threading.Timer(0.8, lambda: webbrowser.open(url, new=2)).start()
    try:
        server.serve_forever(poll_interval=0.2)
    except KeyboardInterrupt:
        print('\nEncerrando DJEN Consulta...')
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
