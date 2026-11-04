"""Focused catalogue: only public portals recovered from supplied bookmarks + TJAC."""
import json
from pathlib import Path
CATALOG=json.loads((Path(__file__).resolve().parent/'jusdown_portais.json').read_text(encoding='utf-8'))
COURTS=list({r['tribunal']:{**r,'id':r['tribunal']} for r in CATALOG}.values())
COURT_IDS={c['id'] for c in COURTS}
BY_ID={r['id']:r for r in CATALOG}
TARGETS=CATALOG
