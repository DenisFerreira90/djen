"""Conferência das páginas observadas, sem fabricar URLs de navegação."""
import hashlib
import json
import re


def signature(rows):
    return hashlib.sha256(json.dumps(rows, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def page_info(tables):
    """Read totals/ranges only from the selected listing's captions."""
    totals, ranges = set(), set()
    for table in tables:
        caption = ' '.join(str(table.get('titulo', '')).split())
        match = re.search(r'([\d.]+)\s+registros?\b', caption, re.I)
        if match:
            totals.add(int(match[1].replace('.', '')))
        match = re.search(r'registros?\s*[-–—:]\s*([\d.]+)\s+a\s+([\d.]+)', caption, re.I)
        if match:
            ranges.add(tuple(int(v.replace('.', '')) for v in match.groups()))
    return totals, ranges


class ListCoverage:
    def __init__(self, expected=None):
        self.expected = expected
        self.rows = 0
        self.pages = 0
        self.seen = set()
        self.ranges = []
        self.complete = False
        self.reason = 'lista_nao_lida'
        self.used_ranges = False

    def accept(self, rows, tables):
        if not tables:
            self.reason = "estrutura_da_lista_nao_confirmada"; return False
        totals, ranges = page_info(tables)
        if len(totals) > 1 or len(ranges) > 1:
            self.reason = 'legendas_divergentes'; return False
        if totals:
            total = next(iter(totals))
            if self.pages and self.expected is not None and total != self.expected:
                self.reason = 'total_alterado_durante_coleta'; return False
            # Before the first page the panel count may already be stale.
            self.expected = total
        interval = next(iter(ranges), None)
        key = (signature(rows), interval)
        if key in self.seen:
            self.reason = 'pagina_repetida'; return False
        if interval:
            first, last = interval
            if first != self.rows + 1 or last < first or last - first + 1 != len(rows):
                self.reason = 'intervalo_da_pagina_divergente'; return False
            if self.expected is None or last > self.expected:
                self.reason = 'intervalo_da_pagina_divergente'; return False
            self.used_ranges = True
        elif self.used_ranges:
            self.reason = 'intervalo_da_pagina_ausente'; return False
        if self.expected is not None and self.rows + len(rows) > self.expected:
            self.reason = 'total_divergente'; return False
        if not rows and self.expected != 0:
            self.reason = 'estrutura_ou_lista_vazia_nao_confirmada'; return False
        self.seen.add(key)
        self.rows += len(rows)
        self.pages += 1
        if interval:
            self.ranges.append(list(interval))
        self.complete = self.expected is not None and self.rows == self.expected
        self.reason = 'total_conferido' if self.complete else 'leitura_em_andamento'
        return True

    def stop(self, reason):
        self.complete = False
        self.reason = reason

    def export(self):
        return {'paginas': self.pages, 'registros': self.rows, 'esperados': self.expected,
                'completo': self.complete, 'motivo': self.reason, 'intervalos': self.ranges,
                'intervalos_conferidos': self.used_ranges}


def wait_table(collector, page, snapshot_js, extract, previous):
    """Wait for changed listing rows, then require three stable observations.

    A spinner/body change is not evidence of a new page. The caller must still
    validate the caption range and total before accepting the returned rows.
    """
    candidate = None
    stable = 0
    for _ in range(120):
        collector.check()
        page.wait_for_timeout(250)
        try:
            snap = page.evaluate(snapshot_js)
            rows, tables = extract(snap)
            key = (signature(rows), tuple(sorted(page_info(tables)[1])))
        except Exception:
            continue
        if not rows or key == previous:
            candidate = None; stable = 0
            continue
        if key == candidate:
            stable += 1
        else:
            candidate = key; stable = 0
        if stable >= 2:
            return snap
    return None


def wait_initial(collector,page,snapshot_js,extract,attempts=240):
    """A list URL or panel counter is not proof that its table has loaded."""
    stable=None;count=0
    for _ in range(attempts):
        collector.check();page.wait_for_timeout(250)
        try:
            snap=page.evaluate(snapshot_js);rows,tables=extract(snap)
            tracker=ListCoverage()
            if not tracker.accept(rows,tables):
                stable=None;count=0;continue
            key=(signature(rows),tuple(sorted(page_info(tables)[0])),tuple(sorted(page_info(tables)[1])))
        except Exception:
            stable=None;count=0;continue
        if key==stable:count+=1
        else:stable=key;count=0
        if count>=2:return snap
    return None
