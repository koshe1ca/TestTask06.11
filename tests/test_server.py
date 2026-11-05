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
        self.assertEqual(next(c for c in result['contracts'] if c['id']=='STN-101')['deadline']['display'], '22.03.2026')

    def test_api_reacts_to_modified_contract_data(self):
        demo = self.request('/api/demo')['files']
        modified = []
        for f in demo:
            if 'Цена договора: 780 000' in f['text']:
                f = {**f, 'text':f['text'].replace('780 000','975 000')}
            modified.append(f)
        result = self.request('/api/analyse', {'as_of':'2026-03-10','files':modified})
        self.assertIn('975',next(c for c in result['contracts'] if c['id']=='STN-102')['amount']['display'])

    def test_api_changes_by_check_date(self):
        demo = self.request('/api/demo')['files']
        result = self.request('/api/analyse', {'as_of':'2026-03-08','files':demo})
        self.assertEqual(next(c for c in result['contracts'] if c['id']=='STN-101')['deadline']['display'],'12.05.2026')

    def test_api_rejects_non_txt(self):
        try:
            self.request('/api/analyse',{'files':[{'name':'bad.pdf','text':'hello'}]})
            self.fail('Expected HTTP 400')
        except HTTPError as error:
            self.assertEqual(error.code,400)


if __name__=='__main__':
    unittest.main()
