"""Opt-in real Chromium integration, using synthetic local pages only.

Run with the core Python: python tests/crawler_smoke.py
"""
import json
import sys
import subprocess
import tempfile
import threading
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from crawler import capture_many
from model import load,file_hash,save

class Fixture(BaseHTTPRequestHandler):
    posts=0
    def log_message(self,*args): pass
    def do_POST(self):
        Fixture.posts+=1
        self.send_response(200);self.end_headers()
    def do_GET(self):
        status=200;content=''
        if self.path=='/robots.txt': content='User-agent: *\nDisallow: /blocked\n'
        elif self.path=='/dynamic':
            content='''<html><head><title>SYNTHETIC TEST</title></head><body><article id="story"></article>
            <script>setTimeout(()=>{document.getElementById('story').textContent='DYNAMIC_FIXTURE_ONLY '+
            'Synthetic local browser test paragraph. '.repeat(20);fetch('/submit',{method:'POST',body:'synthetic'}).catch(()=>{});},100);</script></body></html>'''
        elif self.path=='/paywall':
            content='<html><title>SYNTHETIC TEST</title><body><article>'+('Synthetic teaser. '*30)+' This news is for paid members only.</article></body></html>'
        elif self.path=='/redirect':
            self.send_response(302);self.send_header('Location','/dynamic');self.end_headers();return
        elif self.path=='/blocked': content='<article>'+('ROBOTS_BLOCKED_FIXTURE '*30)+'</article>'
        else: status=404;content='<html><title>404 not found</title><body>Missing fixture</body></html>'
        self.send_response(status);self.send_header('Content-Type','text/plain; charset=utf-8' if self.path=='/robots.txt' else 'text/html; charset=utf-8');self.end_headers();self.wfile.write(content.encode())

def main():
    server=ThreadingHTTPServer(('127.0.0.1',0),Fixture)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    try:
        with tempfile.TemporaryDirectory(prefix='crawler-smoke-') as td:
            root=Path(td);base=f'http://127.0.0.1:{server.server_port}'
            auto=capture_many(root,[base+'/dynamic'],engine='auto',concurrency=1)
            item=auto['items'][0];assert item['engine']=='browser',item
            artifact=load(root/item['artifact']);text=(root/artifact['text_path']).read_text(encoding='utf-8')
            assert 'DYNAMIC_FIXTURE_ONLY' in text,text
            original=root/artifact['original_response_path']
            assert 'id="story"></article>' in original.read_text(encoding='utf-8')
            assert file_hash(original)==artifact['original_response_sha256']
            assert file_hash((root/item['artifact']).with_name('response.html'))==artifact['raw_sha256']
            assert Fixture.posts==0,Fixture.posts
            batch=capture_many(root,[base+'/paywall',base+'/missing',base+'/blocked',base+'/redirect'],engine='browser',concurrency=2)
            assert any('truncated_article' in f for f in batch['items'][0].get('flags',[])),batch
            assert batch['items'][1].get('error') or batch['items'][1].get('flags'),batch
            assert batch['items'][2].get('error'),batch
            redirect=batch['items'][3];assert redirect.get('artifact'),batch
            redirected_artifact=load(root/redirect['artifact'])
            assert redirected_artifact['final_url']==base+'/dynamic',redirected_artifact
            assert redirected_artifact['status_code']==200,redirected_artifact
            assert redirected_artifact.get('original_response_path'),redirected_artifact
            assert Fixture.posts==0,Fixture.posts
            cli_urls=root/'cli-urls.json';save(cli_urls,[base+'/dynamic',base+'/missing'])
            cli=subprocess.run([sys.executable,str(ROOT/'scripts/brief.py'),'--root',str(root),
                'fetch-batch',str(cli_urls),'--engine','http'],capture_output=True,encoding='utf-8')
            assert cli.returncode==2,(cli.returncode,cli.stdout,cli.stderr)
            cli_result=json.loads(cli.stdout);assert cli_result['status']=='INCOMPLETE',cli_result
            assert len(cli_result['items'])==2,cli_result
            print(json.dumps({'status':'PASS','checks':['dynamic_text','auto_fallback','blocked_POST',
                'original_and_DOM_hashes','paywall_flag','404_flag','robots_disallow','redirect','CLI_partial_failure_exit'],
                'fact_verification':'NOT_PERFORMED'},indent=2))
    finally:
        server.shutdown();server.server_close();thread.join()

if __name__=='__main__': main()
