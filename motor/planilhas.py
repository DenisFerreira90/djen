"""Leitura local de XLSX/CSV e exportação tabular. Não executa fórmulas/macros."""
import csv
import datetime as dt
import io
import posixpath
import re
import unicodedata
import zipfile
from xml.etree import ElementTree as ET
from xml.sax.saxutils import escape

NS={'m':'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
FIELDS={'numero':'Número do processo','titulo':'Título','tribunal':'Tribunal','orgao':'Órgão / vara','classe':'Classe','categoria':'Categoria','autor':'Autor','reu':'Réu','advogado':'Advogado','defensor':'Defensor','disponibilizacao':'Disponibilização','publicacao':'Publicação','vencimento':'Vencimento oficial','data_fatal':'Data fatal oficial','evento':'Identificador da intimação / evento','prazo_titulo':'Descrição do prazo','observacoes':'Observações','nome_parte':'Nome da parte / representante','papel':'Papel da pessoa','oab':'OAB','uf':'UF','partes_texto':'Partes (célula do eproc)','documentos_partes':'Documentos das partes','assunto':'Assunto','juizo_codigo':'Código do juízo','data_envio':'Envio da requisição','data_inicio':'Início do prazo'}
ALIASES={'numero':['processo','numero processo','numero do processo','numero cnj','numeroprocesso'], 'orgao':['orgao','vara','juizo'],'autor':['autor','requerente','exequente'],'reu':['reu','requerido','executado'],'advogado':['advogado','advogados'],'defensor':['defensor','defensores'],'vencimento':['vencimento','fim prazo','final prazo','data final','vencimento oficial'],'data_fatal':['fatal','data fatal','data fatal oficial'],'partes_texto':['partes'],'documentos_partes':['doc partes'],'prazo_titulo':['evento e prazo'],'data_envio':['data envio requisicao'],'data_inicio':['inicio prazo'],'nome_parte':['nome','nome da parte','nome da parte representante'],'papel':['papel','papel da pessoa'],'disponibilizacao':['disponibilizacao','data disponibilizacao'],'publicacao':['publicacao','data publicacao']}

def norm(value):
    return re.sub(r'[^a-z0-9]+',' ',unicodedata.normalize('NFKD',str(value)).encode('ascii','ignore').decode().lower()).strip()

def col_index(ref):
    n=0
    for c in re.match(r'[A-Z]+',ref).group():n=n*26+ord(c)-64
    return n-1

def column(n):
    text=''
    while n:
        n,r=divmod(n-1,26);text=chr(65+r)+text
    return text

def parse(data, filename):
    if len(data)>32*1024*1024:raise ValueError('Arquivo excede 32 MB.')
    warnings=[]
    if filename.lower().endswith('.xls'):
        from vendor import xlrd
        try:
            book=xlrd.open_workbook(file_contents=data,logfile=io.StringIO(),on_demand=True)
            sheets=[]
            for sheet in book.sheets():
                if sheet.nrows>20001:raise ValueError('Cada aba pode ter até 20 mil linhas.')
                rows=[]
                for ri in range(sheet.nrows):
                    row=[]
                    for ci in range(min(sheet.ncols,200)):
                        cell=sheet.cell(ri,ci);value=cell.value
                        if cell.ctype==xlrd.XL_CELL_DATE:
                            value=xlrd.xldate_as_datetime(value,book.datemode).isoformat(timespec='seconds')
                        elif cell.ctype==xlrd.XL_CELL_NUMBER:
                            if abs(value)>=10**15:
                                warnings.append('Número longo guardado como número no Excel: confira a precisão na fonte. Não será aceito como número CNJ.')
                                value='[número Excel sem precisão] '+str(value)
                            else:value=str(int(value)) if value==int(value) else str(value)
                        elif cell.ctype==xlrd.XL_CELL_ERROR:
                            value='[erro na célula do Excel]'
                        row.append(str(value) if value is not None else '')
                    rows.append(row)
                sheets.append({'nome':sheet.name,'linhas':rows,'epoca':'1904-01-01' if book.datemode else '1899-12-30'})
            book.release_resources()
        except xlrd.XLRDError as exc:raise ValueError('Não foi possível ler o XLS: '+str(exc))
    elif filename.lower().endswith('.xlsx'):

        with zipfile.ZipFile(io.BytesIO(data)) as z:
            if sum(i.file_size for i in z.infolist())>128*1024*1024:raise ValueError('Conteúdo descompactado excede 128 MB.')
            strings=[]
            if 'xl/sharedStrings.xml' in z.namelist():
                strings=[''.join(x.itertext()) for x in ET.fromstring(z.read('xl/sharedStrings.xml')).findall('m:si',NS)]
            wb=ET.fromstring(z.read('xl/workbook.xml'));rels=ET.fromstring(z.read('xl/_rels/workbook.xml.rels'))
            targets={r.attrib['Id']:r.attrib['Target'] for r in rels}
            epoch=dt.datetime(1899,12,30)
            prop=wb.find('m:workbookPr',NS)
            if prop is not None and prop.get('date1904') in ('1','true'):epoch=dt.datetime(1904,1,1)
            sheets=[]
            for s in wb.findall('m:sheets/m:sheet',NS):
                target=targets[s.get('{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id')]
                path=posixpath.normpath(target.lstrip('/') if target.startswith('/') else 'xl/'+target)
                if not path.startswith('xl/'):raise ValueError('Referência de aba inválida.')
                rows=[]
                for row in ET.fromstring(z.read(path)).findall('m:sheetData/m:row',NS):
                    cells={}
                    for c in row.findall('m:c',NS):
                        index=col_index(c.get('r','A1'))
                        if index>=200:continue
                        v=c.find('m:v',NS);value=v.text if v is not None else ''
                        if c.get('t')=='s':value=strings[int(value)]
                        elif c.get('t')=='inlineStr':value=''.join(c.find('m:is',NS).itertext())
                        if c.find('m:f',NS) is not None:
                            warnings.append('Fórmulas não são executadas; somente valores salvos pelo Excel são lidos.')
                        if c.get('t') not in ('s','inlineStr','str') and re.fullmatch(r'[-+]?\d+(\.\d+)?([Ee][-+]?\d+)?',value or '') and abs(float(value))>=10**15:
                            warnings.append('Número longo armazenado como número no Excel: a precisão pode ter sido perdida. Essas células serão recusadas como números CNJ; recupere o original em texto.')
                            value='[número Excel sem precisão] '+value
                        cells[index]=value or ''
                    if cells:rows.append([cells.get(i,'') for i in range(max(cells)+1)])
                    if len(rows)>20001:raise ValueError('Cada aba pode ter até 20 mil linhas de dados.')
                sheets.append({'nome':s.get('name'),'linhas':rows,'epoca':epoch.date().isoformat()})
    elif filename.lower().endswith(('.csv','.tsv')):
        try:text=data.decode('utf-8-sig')
        except UnicodeError:text=data.decode('cp1252')
        try: dialect=csv.Sniffer().sniff(text[:10000],delimiters=';,\t')
        except csv.Error:dialect=csv.excel;dialect.delimiter=';'
        rows=list(csv.reader(io.StringIO(text),dialect))
        if len(rows)>20001:raise ValueError('Limite de 20 mil linhas.')
        sheets=[{'nome':'CSV','linhas':rows,'epoca':'1899-12-30'}]
    else:raise ValueError('Use .xls, .xlsx ou .csv.')
    for sheet in sheets:
        text=' '.join(str(c) for row in sheet['linhas'][:2] for c in row)
        stamp=re.search(r'Data gera[çc][ãa]o:\s*(\d{2}/\d{2}/\d{4} \d{2}:\d{2}:\d{2})',text,re.I)
        total=re.search(r'Total Processos Listados:\s*(\d+)',text,re.I)
        sheet['metadados']={'gerado_em':date(stamp.group(1)) if stamp else '', 'total_declarado':int(total.group(1)) if total else None,'titulo':str(sheet['linhas'][0][0]) if sheet['linhas'] and sheet['linhas'][0] else ''}
    return {'abas':sheets,'avisos':list(dict.fromkeys(warnings)),'campos':FIELDS}

def suggest(headers):
    result={}
    for field,label in FIELDS.items():
        aliases={norm(field),norm(label),*(norm(v) for v in ALIASES.get(field,[]))}
        matches=[i for i,h in enumerate(headers) if norm(h) in aliases]
        if len(matches)==1:result[field]=matches[0]
    return result

def date(value,epoch='1899-12-30'):
    value=str(value or '').strip()
    if not value:return ''
    if re.fullmatch(r'\d+(\.\d+)?',value):
        n=float(value)
        if not 1<=n<=100000:raise ValueError('Data serial fora do intervalo.')
        return (dt.datetime.fromisoformat(epoch)+dt.timedelta(seconds=round(n*86400))).isoformat(timespec='seconds')
    for fmt in ('%d/%m/%Y %H:%M:%S','%d/%m/%Y %H:%M','%d/%m/%Y','%Y-%m-%d %H:%M:%S','%Y-%m-%d %H:%M','%Y-%m-%d'):
        try:return dt.datetime.strptime(value,fmt).isoformat(timespec='seconds' if '%S' in fmt else 'minutes') if 'H' in fmt else dt.datetime.strptime(value,fmt).date().isoformat()
        except ValueError:pass
    try:return dt.datetime.fromisoformat(value).isoformat(timespec='seconds' if len(value)>16 else 'minutes')
    except ValueError:raise ValueError('Data não reconhecida: '+value[:40])

def xlsx(sheets):
    """Minimal interoperable XLSX export for the application's runtime (stdlib only)."""
    out=io.BytesIO()
    with zipfile.ZipFile(out,'w',zipfile.ZIP_DEFLATED) as z:
        z.writestr('[Content_Types].xml','<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'+''.join(f'<Override PartName="/xl/worksheets/sheet{i}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>' for i in range(1,len(sheets)+1))+'</Types>')
        z.writestr('_rels/.rels','<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>')
        z.writestr('xl/workbook.xml','<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>'+''.join(f'<sheet name="{escape(name, {chr(34): "&quot;"})}" sheetId="{i}" r:id="rId{i}"/>' for i,(name,rows) in enumerate(sheets,1))+'</sheets></workbook>')
        z.writestr('xl/_rels/workbook.xml.rels','<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'+''.join(f'<Relationship Id="rId{i}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet{i}.xml"/>' for i in range(1,len(sheets)+1))+f'<Relationship Id="rId{len(sheets)+1}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/></Relationships>')
        z.writestr('xl/styles.xml','<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><numFmts count="1"><numFmt numFmtId="164" formatCode="dd/mm/yyyy hh:mm"/></numFmts><fonts count="2"><font><sz val="11"/><name val="Calibri"/></font><font><b/><color rgb="FFFFFFFF"/><sz val="11"/><name val="Calibri"/></font></fonts><fills count="3"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill><fill><patternFill patternType="solid"><fgColor rgb="FF14594E"/></patternFill></fill></fills><borders count="1"><border/></borders><cellStyleXfs count="1"><xf/></cellStyleXfs><cellXfs count="3"><xf fontId="0" fillId="0" borderId="0" xfId="0"><alignment vertical="top" wrapText="1"/></xf><xf fontId="1" fillId="2" borderId="0" xfId="0"><alignment vertical="center" wrapText="1"/></xf><xf numFmtId="164" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/></cellXfs></styleSheet>')
        for si,(name,rows) in enumerate(sheets,1):
            width=max((len(r) for r in rows),default=1);body=[]
            for ri,row in enumerate(rows,1):
                cells=[]
                for ci,value in enumerate(row,1):
                    ref=column(ci)+str(ri)
                    if isinstance(value,(dt.datetime,dt.date)):
                        val=(dt.datetime.combine(value,dt.time()) if isinstance(value,dt.date) and not isinstance(value,dt.datetime) else value).replace(tzinfo=None)
                        n=(val-dt.datetime(1899,12,30)).total_seconds()/86400
                        cells.append(f'<c r="{ref}" s="2"><v>{n}</v></c>')
                    elif isinstance(value,(int,float)) and not isinstance(value,bool):
                        cells.append(f'<c r="{ref}" s="0"><v>{value}</v></c>')
                    else:
                        text=re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]','',str(value if value is not None else ''))[:32767]
                        cells.append(f'<c r="{ref}" s="{1 if ri==1 else 0}" t="inlineStr"><is><t xml:space="preserve">{escape(text)}</t></is></c>')
                body.append(f'<row r="{ri}" ht="{32 if ri==1 else 30}" customHeight="1">'+''.join(cells)+'</row>')
            z.writestr(f'xl/worksheets/sheet{si}.xml','<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetViews><sheetView workbookViewId="0"><pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/></sheetView></sheetViews><cols>'+''.join(f'<col min="{i}" max="{i}" width="{30 if i==1 else 24}" customWidth="1"/>' for i in range(1,width+1))+'</cols><sheetData>'+''.join(body)+f'</sheetData><autoFilter ref="A1:{column(width)}{max(len(rows),1)}"/></worksheet>')
    return out.getvalue()


def header_row(rows):
    candidates=[]
    for i,row in enumerate(rows[:30]):
        mapped=suggest(row)
        if 'numero' in mapped:candidates.append((len(mapped),-i,i))
    return max(candidates)[2] if candidates else 0
