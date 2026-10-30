"""Render public articles in an ephemeral local browser and archive evidence."""
from __future__ import annotations
import asyncio
import importlib.metadata
import sys
import urllib.parse
from pathlib import Path
from model import load, save, digest, file_hash, now
from ingest import ArticleParser, access_flags, UA
from crawler import validate_urls

LIMIT=12_000_000

def archive_result(root, url, result, original, final_status=None):
    final=result.redirected_url or result.url or url
    raw=result.html.encode('utf-8')
    if len(raw)>LIMIT: raise ValueError('浏览器DOM超过12MB，未截断采信')
    full=ArticleParser();full.feed(result.html)
    cleaned=ArticleParser();cleaned.feed(result.cleaned_html or result.html)
    text=cleaned.text();title=''.join(full.title).strip()
    flags=set(access_flags(title,full.text(),final)+access_flags(title,text,final))
    if not result.success: flags.add('browser_capture_failed')
    status=final_status if final_status is not None else result.status_code
    if status and status>=400: flags.add('http_status_'+str(status))
    key=digest({'url':final,'raw':digest(raw),'engine':'crawl4ai'})[:20]
    folder=Path(root)/'input/web'/key
    if (folder/'artifact.json').exists():
        existing=load(folder/'artifact.json')
        if (existing.get('raw_sha256')==digest(raw) and
            existing.get('text_sha256')==digest(text.encode('utf-8')) and
            (folder/'response.html').exists() and file_hash(folder/'response.html')==digest(raw) and
            (folder/'text.txt').exists() and file_hash(folder/'text.txt')==existing['text_sha256']):
            return {'url':url,'artifact':str((folder/'artifact.json').relative_to(root)).replace('\\','/'),
                    'engine':'browser','flags':existing['access_flags']}
        folder=folder.with_name(key+'-'+digest({'text':text,'at':now()})[:12])
    folder.mkdir(parents=True,exist_ok=True)
    (folder/'response.html').write_bytes(raw)
    (folder/'text.txt').write_text(text,encoding='utf-8')
    markdown=getattr(result.markdown,'raw_markdown','') or ''
    (folder/'article.md').write_text(markdown,encoding='utf-8')
    rel=lambda p:str(p.relative_to(root)).replace('\\','/')
    a={'kind':'web','url':url,'final_url':final,'title':title,'captured_at':now(),
       'mime':'text/html','encoding':'utf-8','text_path':rel(folder/'text.txt'),
       'text_sha256':file_hash(folder/'text.txt'),'raw_sha256':digest(raw),
       'raw_kind':'rendered_dom','metadata':full.meta,'access_flags':sorted(flags),
       'capture_engine':'crawl4ai','engine_version':importlib.metadata.version('crawl4ai'),
       'status_code':status,'markdown_path':rel(folder/'article.md'),
       'markdown_sha256':file_hash(folder/'article.md'),'fact_verification':'NOT_PERFORMED'}
    if original:
        (folder/'original_document.html').write_bytes(original)
        a.update(original_response_path=rel(folder/'original_document.html'),original_response_sha256=digest(original))
    save(folder/'artifact.json',a)
    return {'url':url,'artifact':rel(folder/'artifact.json'),'engine':'browser','flags':a['access_flags']}

async def run(request):
    from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig, CacheMode
    urls=request['urls'];validate_urls(urls);root=Path(request['root']).resolve()
    concurrency=request['concurrency']
    if not 1<=concurrency<=4: raise ValueError('并发须为1至4')
    sem=asyncio.Semaphore(concurrency)
    hosts={urllib.parse.urlsplit(u).netloc:asyncio.Lock() for u in urls}
    originals={}
    async def created(page,context,**kwargs):
        async def readonly(route):
            req=route.request
            if req.method not in {'GET','HEAD','OPTIONS'} or req.resource_type in {'image','media','font'}:
                await route.abort()
            else: await route.continue_()
        await page.route('**/*',readonly)
        return page
    async def navigated(page,response,**kwargs):
        if response:
            body=await response.body()
            if len(body)>LIMIT: raise ValueError('原始HTML超过12MB')
            originals[page.url]=(body,response.status)
        return page
    browser=BrowserConfig(headless=True,verbose=False,user_agent=UA,
                          ignore_https_errors=False,enable_stealth=False,accept_downloads=False)
    config=CrawlerRunConfig(cache_mode=CacheMode.BYPASS,verbose=False,check_robots_txt=True,
                            word_count_threshold=0,wait_until='domcontentloaded',page_timeout=35000,
                            delay_before_return_html=1.0,process_iframes=False,
                            remove_overlay_elements=False,excluded_tags=['nav','footer','header'])
    async with AsyncWebCrawler(config=browser,base_directory=str(root/'.cache/crawler')) as crawler:
        crawler.crawler_strategy.set_hook('on_page_context_created',created)
        crawler.crawler_strategy.set_hook('after_goto',navigated)
        async def one(url):
            async with sem,hosts[urllib.parse.urlsplit(url).netloc]:
                try:
                    result=await asyncio.wait_for(crawler.arun(url=url,config=config),timeout=48)
                    if not result.success:
                        return {'url':url,'engine':'browser','error':result.error_message or 'browser_capture_failed'}
                    final=result.redirected_url or result.url
                    original,status=originals.pop(final,(None,None))
                    return archive_result(root,url,result,original,status)
                except Exception as exc:
                    return {'url':url,'engine':'browser','error':f'{type(exc).__name__}: {exc}'}
                finally: await asyncio.sleep(1)
        return {'items':await asyncio.gather(*(one(u) for u in urls))}

if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8');sys.stderr.reconfigure(encoding='utf-8')
    save(sys.argv[2],asyncio.run(run(load(sys.argv[1]))))
