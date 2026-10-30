"""Capture integrity and fallback tests; synthetic text is not news evidence."""
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from model import load, file_hash
from crawler import capture_many, validate_urls
from crawler_worker import archive_result

class CrawlerTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='car-crawler-test-')
        self.root=Path(self.temp.name)
    def tearDown(self): self.temp.cleanup()

    def test_url_validation(self):
        for urls in [[], 'https://example.invalid/a', [1], ['file:///c:/x'],
                     ['https://name:secret@example.invalid/a'], ['https://example.invalid/a']*51]:
            with self.assertRaises(ValueError): validate_urls(urls)
        validate_urls(['https://example.invalid/a'])

    def test_clean_http_avoids_browser_and_keeps_core_contract(self):
        html=('<html><title>Synthetic test</title><body><article>'+('Fixture paragraph. '*25)+'</article></body></html>').encode()
        with patch('ingest.fetch',return_value=(html,'https://example.invalid/a','text/html','utf-8')), patch('crawler.browser_batch') as browser:
            record=capture_many(self.root,['https://example.invalid/a'])
        browser.assert_not_called()
        self.assertEqual(record['items'][0]['flags'],[])
        artifact=load(self.root/record['items'][0]['artifact'])
        self.assertEqual(artifact['raw_sha256'],file_hash(self.root/record['items'][0]['artifact'].replace('artifact.json','response.html')))
        self.assertEqual(artifact['fact_verification'],'NOT_PERFORMED')

    def test_auto_fallback_and_partial_failure(self):
        urls=['https://example.invalid/a','https://example.invalid/b']
        with patch('ingest.capture_url',side_effect=OSError('synthetic HTTP failure')), patch('crawler.browser_batch',return_value=[
            {'url':urls[0],'artifact':'synthetic-only.json','engine':'browser','flags':[]},
            {'url':urls[1],'engine':'browser','error':'synthetic browser failure'}]):
            result=capture_many(self.root,urls)
        self.assertEqual(result['items'][0]['engine'],'browser')
        self.assertIn('error',result['items'][0]['http_attempt'])
        self.assertIn('error',result['items'][1])
        self.assertEqual(load(self.root/result['log'])['fact_verification'],'NOT_PERFORMED')

    def test_failed_browser_preserves_flagged_http(self):
        with patch('ingest.capture_url',return_value=('http.json',{'access_flags':['short_text']})), patch('crawler.browser_batch',side_effect=ValueError('missing browser')):
            result=capture_many(self.root,['https://example.invalid/a'])
        self.assertEqual(result['items'][0]['artifact'],'http.json')
        self.assertEqual(result['items'][0]['flags'],['short_text'])
        self.assertIn('missing browser',result['items'][0]['browser_error'])

    def test_recapture_does_not_mutate_bound_artifact(self):
        from ingest import capture_url
        html=('<article>'+('Synthetic immutable capture. '*30)+'</article>').encode()
        with patch('ingest.fetch',return_value=(html,'https://example.invalid/a','text/html','utf-8')):
            path,artifact=capture_url(self.root,'https://example.invalid/a')
            before=(self.root/path).read_bytes()
            with patch('ingest.now',return_value='2099-01-01T00:00:00+08:00'):
                again,reused=capture_url(self.root,'https://example.invalid/a')
        self.assertEqual(path,again)
        self.assertEqual((self.root/path).read_bytes(),before)
        self.assertEqual(artifact,reused)

    def test_rendered_capture_preserves_original_and_paywall(self):
        html='<html><title>Synthetic fixture</title><body>'+('Navigation '*100)+'This news is for paid members only.</body></html>'
        result=SimpleNamespace(redirected_url='https://example.invalid/final',url='https://example.invalid/a',
            html=html,cleaned_html='<article>'+('Synthetic teaser. '*30)+'</article>',
            markdown=SimpleNamespace(raw_markdown='Synthetic markdown'),success=True,status_code=200)
        with patch('crawler_worker.importlib.metadata.version',return_value='TEST ONLY'):
            item=archive_result(self.root,result.url,result,b'<html>Original document fixture</html>')
        artifact=load(self.root/item['artifact'])
        self.assertEqual(artifact['raw_kind'],'rendered_dom')
        self.assertTrue(any('truncated_article' in f for f in item['flags']))
        self.assertEqual(artifact['original_response_sha256'],file_hash(self.root/artifact['original_response_path']))
        self.assertEqual(artifact['text_sha256'],file_hash(self.root/artifact['text_path']))
        before=(self.root/item['artifact']).read_bytes()
        with patch('crawler_worker.importlib.metadata.version',return_value='TEST ONLY'), patch('crawler_worker.now',return_value='2099-01-01T00:00:00+08:00'):
            repeated=archive_result(self.root,result.url,result,b'<html>Original document fixture</html>')
        self.assertEqual(repeated['artifact'],item['artifact'])
        self.assertEqual(before,(self.root/item['artifact']).read_bytes())

if __name__=='__main__': unittest.main()
