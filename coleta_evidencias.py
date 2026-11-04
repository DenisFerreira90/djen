"""Evidência de tabelas independente de tribunal e plataforma processual."""
from html import escape
from pathlib import Path
import re


def save_tables(folder, numero, snapshot, cobertura, *, sistema, tribunal, coletado_em):
    digits=re.sub(r'\D','',str(numero))
    if len(digits)!=20:raise ValueError('Número de processo inválido para evidência.')
    target=Path(folder)/'html_processos';target.mkdir(parents=True,exist_ok=True)
    esc=lambda value:escape(str(value))
    rows=['<!doctype html><html lang="pt-BR"><meta charset="utf-8">',
          '<title>Evidência de coleta</title><body><h1>'+esc(numero)+'</h1>',
          '<p>Fonte: '+esc(sistema)+' / '+esc(tribunal)+' · Coletado em: '+esc(coletado_em)+'</p>',
          '<p>Histórico completo confirmado: '+('Sim' if cobertura.get('completo') is True else 'Não')+'</p>',
          '<p>Cópia das tabelas extraídas; não inclui o conteúdo dos documentos.</p>']
    for table in snapshot.get('tabelas',[]):
        rows.append('<table border="1">')
        for row in table.get('linhas',[]):
            rows.append('<tr>'+''.join('<td>'+esc(cell)+'</td>' for cell in row)+'</tr>')
        rows.append('</table>')
    rows.append('</body></html>')
    path=target/(digits+'.html');path.write_text('\n'.join(rows),encoding='utf-8');return path
