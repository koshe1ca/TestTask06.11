"""Integration tests of the real local HTTP entrypoint."""
import json
from pathlib import Path
from threading import Thread
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from http.server import ThreadingHTTPServer

from server import Handler


class ApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        cls.url = f'http://127.0.0.1:{cls.server.server_port}'
        cls.thread = Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(3)

    @classmethod
    def request(cls, route, data=None):
        if data is None:
            return json.loads(urlopen(cls.url + route).read())
        request = Request(cls.url+route, data=json.dumps(data,ensure_ascii=False).encode('utf-8'),
                          headers={'Content-Type':'application/json'})
        return json.loads(urlopen(request).read())

    def test_demo_and_all_four_answers(self):
        demo = self.request('/api/demo')
        self.assertEqual(len(demo['files']), 6)
        result = self.request('/api/analyse', {'as_of':'2026-03-10','files':demo['files']})
        self.assertEqual(len(result['contracts']), 3)
        self.assertEqual(len(result['answers']), 4)
        self.assertTrue(all(answer['evidence'] for answer in result['answers']))
        by_id = {c['id']: c for c in result['contracts']}
        self.assertEqual(by_id['STN-101']['deadline']['display'], '30.04.2026')
        self.assertEqual(by_id['STN-101']['amount']['display'], '1\u00a0380\u00a0000 ₽')
        self.assertEqual(by_id['STN-102']['deadline']['display'], '20.03.2026')
        self.assertEqual(by_id['STN-102']['amount']['display'], '840\u00a0000 ₽')
        self.assertIsNone(by_id['STN-103']['amount'])
        self.assertEqual(by_id['STN-103']['deadline']['display'], '30.04.2026')
        self.assertEqual(len(by_id['STN-101']['applied']), 1)
        self.assertEqual(len(by_id['STN-101']['notices']), 1)
        self.assertEqual(len(by_id['STN-102']['notices']), 1)
        self.assertIn('STN-102 — 20.03.2026', result['answers'][3]['text'])
        self.assertNotIn('STN-101 — 30.04.2026', result['answers'][3]['text'])
        self.assertIn('STN-103 — нет данных', result['answers'][2]['text'])
        self.assertEqual(result['answers'][2]['evidence'][0]['filename'], '04_contract.txt')

    def test_api_reacts_to_modified_contract_data(self):
        demo = self.request('/api/demo')['files']
        modified = []
        for f in demo:
            if 'Общая стоимость поставки составляет 840 000' in f['text']:
                f = {**f, 'text':f['text'].replace('840 000','975 000')}
            modified.append(f)
        result = self.request('/api/analyse', {'as_of':'2026-03-10','files':modified})
        self.assertIn('975',next(c for c in result['contracts'] if c['id']=='STN-102')['amount']['display'])

    def test_api_changes_by_check_date(self):
        demo = self.request('/api/demo')['files']
        result = self.request('/api/analyse', {'as_of':'2026-02-28','files':demo})
        self.assertEqual(next(c for c in result['contracts'] if c['id']=='STN-101')['deadline']['display'],'15.04.2026')

    def test_api_rejects_non_txt(self):
        try:
            self.request('/api/analyse',{'files':[{'name':'bad.pdf','text':'hello'}]})
            self.fail('Expected HTTP 400')
        except HTTPError as error:
            self.assertEqual(error.code,400)


if __name__=='__main__':
    unittest.main()
