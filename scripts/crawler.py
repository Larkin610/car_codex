"""HTTP-first capture; optional isolated Crawl4AI worker. No fact approval."""
from __future__ import annotations
import os
import subprocess
import tempfile
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from model import ROOT, load, save, now, digest

def validate_urls(urls):
    if not isinstance(urls,list) or any(not isinstance(u,str) for u in urls):
        raise ValueError('URL输入须为字符串数组')
    if not 1 <= len(urls) <= 50:
        raise ValueError('每批须为1至50个URL')
    for url in urls:
        p=urllib.parse.urlsplit(url)
        if p.scheme not in {'http','https'} or not p.hostname or p.username or p.password:
            raise ValueError('只接受不含凭据的HTTP(S) URL')

def browser_batch(root, urls, concurrency):
    runtime=ROOT/'.venv-crawler'/'Scripts'/'python.exe'
    if not runtime.exists():
        raise ValueError('浏览器采集环境缺失，请运行 scripts/setup-crawler.ps1')
    with tempfile.TemporaryDirectory(prefix='car-crawler-') as td:
        request=Path(td)/'request.json';result=Path(td)/'result.json'
        save(request,{'root':str(Path(root).resolve()),'urls':urls,'concurrency':concurrency})
        run=subprocess.run([str(runtime),str(ROOT/'scripts/crawler_worker.py'),str(request),str(result)],
                           capture_output=True,encoding='utf-8',errors='replace',timeout=120+len(urls)*50,
                           env={**os.environ,'PLAYWRIGHT_BROWSERS_PATH':str(ROOT/'.cache/ms-playwright')})
        if run.returncode or not result.exists():
            raise ValueError('浏览器采集未完成: '+(run.stderr or run.stdout)[-1800:])
        return load(result)['items']

def capture_many(root, urls, engine='auto', concurrency=3):
    validate_urls(urls)
    if engine not in {'auto','http','browser'}: raise ValueError('未知采集引擎')
    if not 1 <= concurrency <= 4: raise ValueError('并发须为1至4')
    from ingest import capture_url
    def http(url):
        try:
            path,a=capture_url(root,url)
            return {'url':url,'artifact':path,'engine':'http','flags':a['access_flags']}
        except Exception as exc:
            return {'url':url,'engine':'http','error':f'{type(exc).__name__}: {exc}'}
    if engine=='browser':
        items=browser_batch(root,urls,concurrency)
    else:
        # One outstanding request per host in HTTP mode, as well as a global bound.
        import threading
        locks={urllib.parse.urlsplit(u).netloc:threading.Lock() for u in urls}
        def limited(url):
            with locks[urllib.parse.urlsplit(url).netloc]: return http(url)
        with ThreadPoolExecutor(max_workers=concurrency) as pool: items=list(pool.map(limited,urls))
        # A listing/homepage is useful for discovery but cannot become article
        # evidence.  Retrying it in a browser only repeats the same request;
        # keep the flag in the audit log and reserve browser fallback for
        # errors or flags that may be resolved by rendering (paywalls,
        # JavaScript pages, short text, etc.).
        pending=[i for i,x in enumerate(items)
                 if x.get('error') or any(f != 'listing_or_homepage' for f in x.get('flags',[]))]
        if engine=='auto' and pending:
            try:
                retry=browser_batch(root,[urls[i] for i in pending],concurrency)
                for i,item in zip(pending,retry,strict=True):
                    previous=items[i]
                    item['http_attempt']=previous
                    if item.get('error') and previous.get('artifact'):
                        previous['browser_error']=item['error']
                    else: items[i]=item
            except Exception as exc:
                for i in pending: items[i]['browser_error']=str(exc)
    record={'captured_at':now(),'requested_engine':engine,'concurrency':concurrency,'items':items,
            'fact_verification':'NOT_PERFORMED'}
    log=Path(root)/'logs'/now()[:10]/'capture'/(digest(record)[:16]+'.json');save(log,record)
    record['log']=str(log.relative_to(root)).replace('\\','/')
    return record
