"""Dependency-free local HTTP application. Run: python server.py"""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import sys
import webbrowser

from textnavigator.engine import analyse, date_text, money_text
from textnavigator.qa import preset_answers

ROOT = Path(__file__).resolve().parent
WEB = ROOT / 'web'
DEMO = ROOT / 'documents'
MAX_COUNT = 30
MAX_BYTES = 2 * 1024 * 1024
MAX_POST = MAX_COUNT * MAX_BYTES + 4096
AS_OF_DEFAULT = '2026-03-10'


def evidence_json(ev):
    if ev is None:
        return None
    return {'source_id': ev.source_id, 'filename': ev.filename, 'paragraph': ev.paragraph, 'quote': ev.quote}


def condition_json(condition, field):
    if condition is None:
        return None
    return {'value': str(condition.value),
            'display': date_text(condition.value) if field == 'deadline' else money_text(condition.value),
            'evidence': evidence_json(condition.evidence)}


def result_json(analysis):
    return {
        'as_of': date_text(analysis.as_of),
        'sources': [
            {'source_id': s.source_id, 'filename': s.filename, 'kind': s.kind,
             'contract_ids': s.contract_ids, 'signed': s.signed,
             'effective_date': date_text(s.effective_date) if s.effective_date else None,
             'amount': condition_json(s.amount, 'amount'), 'deadline': condition_json(s.deadline, 'deadline'),
             'paragraphs': s.paragraphs, 'issues': s.issues} for s in analysis.sources
        ],
        'contracts': [
            {'id': c.contract_id, 'supplier': c.supplier or 'нет данных',
             'supplier_evidence': evidence_json(c.supplier_evidence),
             'amount': condition_json(c.amount, 'amount'),
             'deadline': condition_json(c.deadline, 'deadline'),
             'base_filenames': [s.filename for s in c.base_sources],
             'applied': [{'filename': s.filename, 'effective_date': date_text(s.effective_date)} for s in c.applied_amendments],
             'notices': [{'filename': n.source.filename, 'kind': n.source.kind,
                          'reason': n.reason,
                          'amount': condition_json(n.proposed_amount, 'amount'),
                          'deadline': condition_json(n.proposed_deadline, 'deadline')} for n in c.notices],
             'issues': c.issues, 'needs_review': c.needs_review} for c in analysis.contracts
        ],
        'unmatched': [{'filename': s.filename, 'issues': s.issues} for s in analysis.unmatched],
        'global_issues': analysis.global_issues,
        'answers': [
            {'title': a.title, 'text': a.text,
             'evidence': [evidence_json(e) for e in a.evidence], 'caveats': a.caveats}
            for a in preset_answers(analysis)
        ]
    }


def parse_payload(payload):
    if not isinstance(payload, dict) or not isinstance(payload.get('files'), list):
        raise ValueError('Ожидается объект с массивом files.')
    files = payload['files']
    if not 1 <= len(files) <= MAX_COUNT:
        raise ValueError(f'Загрузите от 1 до {MAX_COUNT} TXT-файлов.')
    try:
        as_of = date.fromisoformat(payload.get('as_of', AS_OF_DEFAULT))
    except (TypeError, ValueError):
        raise ValueError('Дата проверки должна быть в формате ГГГГ-ММ-ДД.') from None
    docs = []
    for entry in files:
        if not isinstance(entry, dict) or not isinstance(entry.get('name'), str) or not isinstance(entry.get('text'), str):
            raise ValueError('Неверный формат записи файла.')
        name, text = entry['name'], entry['text']
        if not name.lower().endswith('.txt') or not 0 < len(name) <= 255:
            raise ValueError('Допускаются только файлы TXT.')
        if len(text.encode('utf-8')) > MAX_BYTES:
            raise ValueError(f'{name}: превышен лимит 2 МБ.')
        docs.append((name, text))
    return docs, as_of


class Handler(BaseHTTPRequestHandler):
    def json_response(self, status, obj):
        encoded = json.dumps(obj, ensure_ascii=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(encoded)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.end_headers()
        self.wfile.write(encoded)

    def do_GET(self):
        if self.path == '/api/demo':
            files = [{'name': p.name, 'text': p.read_text(encoding='utf-8')}
                     for p in sorted(DEMO.glob('*.txt'))]
            self.json_response(200, {'files': files})
            return
        mapping = {'/': ('index.html', 'text/html; charset=utf-8'),
                   '/style.css': ('style.css', 'text/css; charset=utf-8'),
                   '/app.js': ('app.js', 'application/javascript; charset=utf-8')}
        item = mapping.get(self.path)
        if item is None:
            self.json_response(404, {'error': 'Страница не найдена.'})
            return
        data = (WEB / item[0]).read_bytes()
        self.send_response(200)
        self.send_header('Content-Type', item[1])
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        if self.path != '/api/analyse':
            self.json_response(404, {'error': 'Неизвестный адрес API.'})
            return
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if not 0 < length <= MAX_POST:
                raise ValueError('Размер запроса превышает ограничение.')
            if 'application/json' not in self.headers.get('Content-Type', ''):
                raise ValueError('Ожидается JSON.')
            payload = json.loads(self.rfile.read(length).decode('utf-8'))
            docs, as_of = parse_payload(payload)
            self.json_response(200, result_json(analyse(docs, as_of)))
        except (ValueError, UnicodeError, json.JSONDecodeError) as error:
            self.json_response(400, {'error': str(error)})
        except Exception as error:
            print(f'Internal error: {error!r}', file=sys.stderr)
            self.json_response(500, {'error': 'Внутренняя ошибка. Смотрите терминал сервера.'})

    def log_message(self, fmt, *args):
        print('%s - %s' % (self.address_string(), fmt % args), file=sys.stderr)


def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8501
    # Bind to loopback only: never expose uploaded contracts on an open network interface.
    server = ThreadingHTTPServer(('127.0.0.1', port), Handler)
    print(f'Сервер запущен: http://127.0.0.1:{port}')
    print('Откройте адрес в браузере. Остановка: Ctrl+C.')
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print('\nСервер остановлен.')
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
