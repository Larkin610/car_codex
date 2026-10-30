"""Read-only web/history ingestion and per-page PDF evidence. Never certifies facts."""
from __future__ import annotations
import csv
import io
import gzip
import zlib
import json
import re
import shutil
import subprocess
import sys
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from collections import Counter
from datetime import date, datetime, timedelta
from html import unescape
from html.parser import HTMLParser
from pathlib import Path
from model import now, digest, file_hash, load, save, local, norm, TZ

SHEET_ID='1jqF6HpniXn4ZQSRFaiYPHrHcJxBQbb1RSovOmr19N5Q'
UA='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AutomotiveBriefEvidence/1.0'

def fetch(url, timeout=25):
    if urllib.parse.urlparse(url).scheme not in {'http','https'}: raise ValueError('只接受HTTP(S) URL')
    request=urllib.request.Request(url,headers={'User-Agent':UA,'Accept-Language':'zh-CN,zh;q=0.9,en;q=0.8'})
    with urllib.request.urlopen(request,timeout=timeout) as r:
        body=r.read(12_000_001)
        if len(body)>12_000_000: raise ValueError('响应超过12MB，未截断采信')
        compression=r.headers.get('Content-Encoding','').lower()
        if compression=='gzip': body=gzip.decompress(body)
        elif compression=='deflate': body=zlib.decompress(body)
        elif compression and compression!='identity': raise ValueError('不支持的响应压缩: '+compression)
        if len(body)>12_000_000: raise ValueError('解压响应超过12MB')
        return body,r.geturl(),r.headers.get_content_type(),r.headers.get_content_charset()

class ArticleParser(HTMLParser):
    def __init__(self):
        super().__init__(); self.skip=0; self.parts=[]; self.title=[]; self.in_title=False; self.meta={}
    def handle_starttag(self,tag,attrs):
        attrs=dict(attrs)
        if tag in {'script','style','noscript','svg'}: self.skip+=1
        if tag=='title': self.in_title=True
        if tag=='meta':
            key=attrs.get('property',attrs.get('name',''))
            if key: self.meta[key]=attrs.get('content','')
        if tag in {'p','div','article','section','br','h1','h2','li'} and not self.skip: self.parts.append('\n')
    def handle_endtag(self,tag):
        if tag in {'script','style','noscript','svg'}: self.skip=max(0,self.skip-1)
        if tag=='title': self.in_title=False
    def handle_data(self,data):
        if self.in_title: self.title.append(data)
        if not self.skip: self.parts.append(data)
    def text(self):
        return '\n'.join(x for line in ''.join(self.parts).splitlines() if (x:=re.sub(r'\s+',' ',line).strip()))

def access_flags(title, text, final):
    """Conservative access checks shared by HTTP and rendered captures."""
    flags=[]
    for pattern in ['access denied','verify you are human','just a moment','subscribe to read','enable javascript','captcha','page not found','404 not found']:
        if pattern in (title+'\n'+text[:1800]).lower(): flags.append(pattern)
    for pattern in ['this news is for paid members only', 'register as a free member, you can read the rest',
                    'subscribe to continue reading', 'sign in to read the full article']:
        if pattern in text.lower(): flags.append('truncated_article: '+pattern)
    if len(text)<200: flags.append('short_text')
    url_path=urllib.parse.urlparse(final).path.rstrip('/').lower()
    if url_path in {'','/news','/press','/media','/latest','/newsroom','/press-releases'} and not urllib.parse.urlparse(final).query:
        flags.append('listing_or_homepage')
    if '\ufffd' in text: flags.append('decode_replacement')
    return flags

def capture_url(root, url, engine='http'):
    if engine != 'http':
        from crawler import capture_many
        item=capture_many(root,[url],engine=engine)['items'][0]
        if item.get('error'): raise ValueError(item['error'])
        return item['artifact'], load(local(root,item['artifact']))
    raw,final,mime,encoding=fetch(url)
    if mime not in {'text/html','application/xhtml+xml','text/plain'}: raise ValueError('此命令只抓网页；PDF请放入PDFday并提取')
    encoding=encoding or (re.search(br'charset=["\s]*([\w-]+)',raw[:4096]).group(1).decode() if re.search(br'charset=["\s]*([\w-]+)',raw[:4096]) else 'utf-8')
    decoded=raw.decode(encoding,errors='replace')
    parser=ArticleParser(); parser.feed(decoded)
    text=parser.text() if mime!='text/plain' else decoded
    title=''.join(parser.title).strip()
    flags=access_flags(title,text,final)
    key=digest({'url':final,'raw':digest(raw)})[:20]; folder=Path(root)/'input'/'web'/key
    # Evidence already referenced by a matrix must remain immutable on recapture.
    if (folder/'artifact.json').exists():
        existing=load(folder/'artifact.json')
        if (existing.get('raw_sha256')==digest(raw) and
            existing.get('text_sha256')==digest(text.encode('utf-8')) and
            (folder/'response.html').exists() and file_hash(folder/'response.html')==digest(raw) and
            (folder/'text.txt').exists() and file_hash(folder/'text.txt')==existing['text_sha256']):
            return str((folder/'artifact.json').relative_to(root)).replace('\\','/'),existing
        folder=folder.with_name(key+'-'+digest({'text':text,'at':now()})[:12])
    folder.mkdir(parents=True,exist_ok=True)
    (folder/'response.html').write_bytes(raw); (folder/'text.txt').write_text(text,encoding='utf-8')
    artifact={'kind':'web','url':url,'final_url':final,'title':title,'captured_at':now(),'mime':mime,
      'encoding':encoding,'text_path':str((folder/'text.txt').relative_to(root)).replace('\\','/'),
      'text_sha256':file_hash(folder/'text.txt'),'raw_sha256':digest(raw),'metadata':parser.meta,'access_flags':flags,'fact_verification':'NOT_PERFORMED'}
    save(folder/'artifact.json',artifact)
    return str((folder/'artifact.json').relative_to(root)).replace('\\','/'),artifact

def read_csv(raw, allow_empty=False):
    text=raw.decode('utf-8-sig',errors='strict')
    if text.lstrip().startswith('<'): raise ValueError('历史通道返回HTML而不是CSV')
    rows=list(csv.reader(io.StringIO(text)))
    if len(rows)<2 and not (allow_empty and rows): raise ValueError('历史CSV为空或仅有表头')
    return rows

def validate_history_tables(light, event, certificate, report_date):
    lh=['日报日期','主体/国家','核心动作（去重摘要）']
    eh=['日报日期','主体/国家','核心动作']
    for table,required in [(light,lh),(event,eh)]:
        if not set(required).issubset(table[0]): raise ValueError('历史真实表头不符合约定，禁止按列序猜测')
    def records(table,keys):
        indices=[table[0].index(k) for k in keys]; result=[]
        for row in table[1:]:
            if not any(row): continue
            if len(row)!=len(table[0]): raise ValueError('历史行宽异常')
            values=[row[i] for i in indices]
            date.fromisoformat(values[0])
            if not all(x.strip() for x in values): raise ValueError('历史核心事实为空')
            result.append(tuple(norm(x) for x in values))
        if not result: raise ValueError('历史解析0条')
        return result
    left=records(light,lh); right=records(event,eh)
    if Counter(left)!=Counter(right): raise ValueError('轻索引与事件索引核心事实/数量不一致')
    required={'run_status':'COMPLETED','self_audit_status':'VERIFIED','history_health_gate':'PASS','published_body_match':'PASS'}
    for key,value in required.items():
        if certificate.get(key)!=value: raise ValueError(f'历史健康证书异常：{key}')
    for key in ['final_drive_gap_count','unfinished_batch_count','unregistered_archive_count','terminal_mismatch_count','semantic_invalid_count','placeholder_count','published_body_missing_facts','published_body_pending_versions']:
        if certificate.get(key)!='0': raise ValueError(f'历史健康计数异常/缺失：{key}')
    if not certificate.get('history_epoch'): raise ValueError('历史epoch为空')
    t=date.fromisoformat(report_date); start=t-timedelta(days=30); end=t-timedelta(days=1)
    # The read-only history job is published after the last historical issue is
    # closed, so its certificate is allowed to carry the window end date (T-1)
    # while the matrix report date is T.  Keep the certificate bound to either
    # the requested report date or the exact end of the required 30-day window.
    if certificate.get('report_date') not in {report_date, str(end)}: raise ValueError('历史证书业务日不匹配')
    if certificate.get('history_window')!=f'{start}:{end}': raise ValueError('历史证书未覆盖本期前30天')
    dates={date.fromisoformat(x[0]) for x in left}
    expected={start+timedelta(days=n) for n in range(30)}
    if dates!=expected: raise ValueError('历史刊发日有缺失/越界，不能声称完成30天比对')
    checked=datetime.fromisoformat(certificate['checked_at'])
    if checked.tzinfo is None or checked.astimezone(TZ).date() not in {t,end}: raise ValueError('历史证书检查时间缺失时区或业务日不符')
    return {'light_rows':len(left),'event_rows':len(right),'start':str(start),'end':str(end)}

def refresh_history(root, report_date):
    captures={}; tables={}; base=f'https://docs.google.com/spreadsheets/d/{SHEET_ID}/gviz/tq?'
    # Explicit headers and C15:D40 prevent GViz merging stale columns/guessing headers.
    for name,opts in [('去重轻索引',{'headers':1}),('事件索引',{'headers':1}),('运行摘要',{'headers':0,'range':'C15:D40'})]:
        url=base+urllib.parse.urlencode({'tqx':'out:csv','sheet':name,**opts})
        raw,final,mime,_=fetch(url)
        tables[name]=read_csv(raw); captures[name]={'raw':raw,'url':final,'sha256':digest(raw)}
    cert={r[0]:r[1] for r in tables['运行摘要'] if len(r)>=2 and r[0]}
    counts=validate_history_tables(tables['去重轻索引'],tables['事件索引'],cert,report_date)
    captured_at=now()
    key=digest({'files':{k:v['sha256'] for k,v in captures.items()},'at':captured_at})[:16]
    folder=Path(root)/'history'/report_date/key; folder.mkdir(parents=True,exist_ok=True)
    for name,item in captures.items(): (folder/(name+'.csv')).write_bytes(item['raw'])
    manifest={'schema_version':1,'mode':'google_readonly_roll30','report_date':report_date,'fetched_at':captured_at,'certificate':cert,'counts':counts,
      'files':{k:{'path':str((folder/(k+'.csv')).relative_to(root)).replace('\\','/'),'sha256':v['sha256'],'url':v['url']} for k,v in captures.items()}}
    save(folder/'manifest.json',manifest)
    return {'manifest':str((folder/'manifest.json').relative_to(root)).replace('\\','/'),'sha256':file_hash(folder/'manifest.json'),'epoch':cert['history_epoch']}


def local_history_ref(root, report_date):
    """Return the checked-in local history reference; never contacts Google."""
    path = Path(root) / 'history' / 'local' / 'manifest.json'
    if not path.exists():
        raise ValueError('本地历史库不存在；请先完成迁移，不回退读取Google')
    manifest = load(path)
    if manifest.get('mode') != 'local_roll30':
        raise ValueError('本地历史库模式不受支持')
    if manifest.get('timezone') != 'Asia/Shanghai':
        raise ValueError('本地历史库时区错误')
    expected = date.fromisoformat(report_date) - timedelta(days=30)
    end = date.fromisoformat(report_date) - timedelta(days=1)
    expected_days = {expected + timedelta(days=n) for n in range(30)}
    available = set()
    for name, item in manifest.get('files', {}).items():
        if name not in {'事件索引', '新增表'}:
            continue
        table_path = local(root, item['path'])
        if file_hash(table_path) != item['sha256']:
            raise ValueError('本地历史CSV哈希失效')
        table = read_csv(table_path.read_bytes(), allow_empty=True)
        if '日报日期' not in table[0]:
            raise ValueError(f'本地{name}缺少日报日期列')
        idx = table[0].index('日报日期')
        for row in table[1:]:
            if row and row[idx].strip():
                available.add(date.fromisoformat(row[idx]))
    if not expected_days.issubset(available):
        missing = sorted(expected_days - available)
        raise ValueError('本地历史库未覆盖本期T-30至T-1窗口：缺少 ' + ','.join(map(str, missing)))
    return {'manifest': str(path.relative_to(root)).replace('\\','/'),
            'sha256': file_hash(path), 'epoch': manifest.get('epoch', file_hash(path)[:16]),
            'mode': 'local_roll30'}


def migrate_local_history(root, report_date, source_manifest):
    """Materialize a local read-only window from one verified Google snapshot.

    This is an explicit migration command. It never fetches or writes Google;
    after migration, daily commands use only the resulting local files.
    """
    source = load(source_manifest)
    if source.get('mode') != 'google_readonly_roll30':
        raise ValueError('迁移源必须是已保存且校验过的Google只读快照')
    tables = {}
    for name, item in source.get('files', {}).items():
        tables[name] = read_csv(local(root, item['path']).read_bytes())
    if '事件索引' not in tables or '去重轻索引' not in tables:
        raise ValueError('迁移源缺少事件索引或去重轻索引')
    target_day = date.fromisoformat(report_date)
    start, end = target_day - timedelta(days=30), target_day - timedelta(days=1)
    validate_history_tables(tables['去重轻索引'], tables['事件索引'], source.get('certificate', {}),
                            source.get('report_date') or str(end))
    if source.get('certificate', {}).get('history_window') != f'{start}:{end}':
        raise ValueError('迁移源未覆盖目标业务日前完整30日窗口')
    def filter_window(table):
        header = table[0]
        if '日报日期' not in header:
            raise ValueError('迁移源缺少日报日期列')
        idx = header.index('日报日期')
        rows = [row for row in table[1:] if row and start <= date.fromisoformat(row[idx]) <= end]
        dates = {date.fromisoformat(row[idx]) for row in rows}
        if dates != {start + timedelta(days=n) for n in range(30)}:
            raise ValueError('迁移源未覆盖完整30日窗口')
        return [header, *rows]
    local_tables = {name: filter_window(tables[name]) for name in ('事件索引', '去重轻索引')}
    folder = Path(root) / 'history' / 'local'; folder.mkdir(parents=True, exist_ok=True)
    files = {}
    for name, table in local_tables.items():
        path = folder / f'{name}.csv'
        buf = io.StringIO(); csv.writer(buf, lineterminator='\n').writerows(table)
        path.write_text(buf.getvalue(), encoding='utf-8-sig')
        files[name] = {'path': str(path.relative_to(root)).replace('\\','/'), 'sha256': file_hash(path)}
    additions = folder / '新增表.csv'
    with additions.open('w', encoding='utf-8-sig', newline='') as fh:
        csv.writer(fh, lineterminator='\n').writerow(local_tables['事件索引'][0])
    files['新增表'] = {'path': str(additions.relative_to(root)).replace('\\','/'), 'sha256': file_hash(additions)}
    manifest = {'schema_version': 1, 'mode': 'local_roll30', 'timezone': 'Asia/Shanghai',
                'window': f'{start}:{end}', 'epoch': digest({'source': file_hash(source_manifest), 'window': f'{start}:{end}'})[:16],
                'migrated_at': now(), 'source_manifest': str(Path(source_manifest).resolve().relative_to(root)).replace('\\','/'),
                'files': files}
    save(folder / 'manifest.json', manifest)
    return {'manifest': str((folder/'manifest.json').relative_to(root)).replace('\\','/'),
            'sha256': file_hash(folder/'manifest.json'), 'window': manifest['window'],
            'rows': len(local_tables['事件索引']) - 1}


def _local_manifest(root):
    path = Path(root) / 'history' / 'local' / 'manifest.json'
    if not path.exists():
        raise ValueError('本地历史库不存在，不能登记新增表')
    manifest = load(path)
    if manifest.get('mode') != 'local_roll30':
        raise ValueError('本地历史库模式不受支持')
    return path, manifest


def _release_rows(release):
    headers = ['日报日期','原板块','页码','槽位对象','主体/国家','车型/项目/政策名','核心动作','事件日期',
               '地点','关键数字','合作方/监管方','原始信源','来源PPT文件名','来源链接','首次出现日期',
               '最近出现日期','涉及日报日期','是否存在实质增量','历史关联事件','事件指纹','处理状态']
    rows=[]
    for event in release.get('events', []):
        fp=event.get('fingerprint') or {}; day=release.get('report_date','')
        rows.append([day,'','','',fp.get('subject',''),fp.get('object',''),event.get('zh',''),event.get('event_date',''),
                     fp.get('place',''),'、'.join(fp.get('numbers') or []),'、'.join(fp.get('partners') or []),'','','',
                     day,day,day,'是','',event.get('candidate_id',''),'已完成'])
    return headers, rows


def register_release_history(root, release_path):
    """Append a signed-off release to the offline additions table idempotently."""
    path, manifest = _local_manifest(root)
    release = load(release_path)
    additions_meta = manifest.get('files', {}).get('新增表')
    if not additions_meta:
        raise ValueError('本地manifest缺少新增表')
    additions = local(root, additions_meta['path'])
    if file_hash(additions) != additions_meta['sha256']:
        raise ValueError('新增表哈希失效，拒绝覆盖')
    headers, rows = _release_rows(release)
    existing = read_csv(additions.read_bytes(), allow_empty=True)
    if existing[0] != headers:
        raise ValueError('新增表表头不符合约定')
    keys={(r[0],r[19]) for r in existing[1:] if len(r)>19}
    new_rows=[r for r in rows if (r[0],r[19]) not in keys]
    if new_rows:
        with additions.open('a', encoding='utf-8', newline='') as fh:
            csv.writer(fh, lineterminator='\n').writerows(new_rows)
        additions_meta['sha256'] = file_hash(additions)
        manifest['epoch'] = digest({'source_manifest': manifest.get('source_manifest'),
                                    'files': {k:v.get('sha256') for k,v in manifest.get('files',{}).items()},
                                    'new_additions': additions_meta['sha256']})[:16]
        save(path, manifest)
    return {'status':'REGISTERED','release':str(Path(release_path).resolve().relative_to(root)).replace('\\','/'),
            'added':len(new_rows),'skipped':len(rows)-len(new_rows)}

def extract_pdf(root, path, report_date, publisher, publication_date, ocr=True):
    from pypdf import PdfReader
    source=Path(path).resolve(); key=file_hash(source); folder=Path(root)/'input'/'pdf'/report_date/key[:16]
    folder.mkdir(parents=True,exist_ok=True)
    archived=folder/source.name
    if not archived.exists(): shutil.copy2(source,archived)
    reader=PdfReader(archived); pages=[]; engine=None; document=None
    for index,page in enumerate(reader.pages):
        text=(page.extract_text() or '').strip(); method='text_layer'; image_path=''; confidence=[]; errors=[]
        # Per-page fallback catches mixed PDFs; text fragment / large scanned image also triggers OCR.
        needs_ocr=len(re.sub(r'\s+','',text))<80
        if not needs_ocr:
            try:
                import pymupdf as fitz
                check_doc=fitz.open(archived)
                area=check_doc[index].rect.get_area()
                covered=sum(check_doc[index].get_image_bbox(im).get_area() for im in check_doc[index].get_images(full=True))
                needs_ocr=bool(covered>area*0.5 and len(text)<800)
                check_doc.close()
            except Exception: pass
        if needs_ocr and ocr:
            try:
                import pymupdf as fitz
                from rapidocr_onnxruntime import RapidOCR
                if engine is None: engine=RapidOCR(intra_op_num_threads=2,inter_op_num_threads=2)
                if document is None: document=fitz.open(archived)
                image=folder/f'page-{index+1:03d}.png'
                document[index].get_pixmap(matrix=fitz.Matrix(2,2)).save(image)
                result,_=engine(str(image)); result=result or []
                text='\n'.join(str(line[1]) for line in result); confidence=[round(float(line[2]),4) for line in result]
                image_path=str(image.relative_to(root)).replace('\\','/'); method='ocr'
            except Exception as e: errors.append(f'{type(e).__name__}: {e}')
        elif needs_ocr: errors.append('OCR未执行')
        if not text.strip(): errors.append('空白页或OCR无结果，需回看原页确认')
        text_path=folder/f'page-{index+1:03d}.txt'; text_path.write_text(text,encoding='utf-8')
        item={'kind':'pdf','publisher':publisher,'publication_date':publication_date,'publisher_status':'operator_asserted_needs_visual_check',
          'original_path':str(source),'archived_pdf':str(archived.relative_to(root)).replace('\\','/'),'pdf_sha256':key,'page':index+1,
          'captured_at':now(),'method':method,'image_path':image_path,'text_path':str(text_path.relative_to(root)).replace('\\','/'),
          'text_sha256':file_hash(text_path),'ocr_confidence':confidence,'errors':errors,'fact_verification':'NOT_PERFORMED'}
        save(folder/f'page-{index+1:03d}.json',item)
        pages.append({'page':index+1,'artifact':str((folder/f'page-{index+1:03d}.json').relative_to(root)).replace('\\','/'),'chars':len(text),'method':method,'errors':errors})
    if document is not None: document.close()
    manifest={'source':str(source),'pdf_sha256':key,'publisher':publisher,'publication_date':publication_date,'pages':pages,'created_at':now()}
    save(folder/'manifest.json',manifest)
    return manifest

def search_web(root, query, report_date, slot, days, provider='bing'):
    # Search results remain leads. RSS pubDate is deliberately not used as event date.
    if provider=='bing':
        url='https://www.bing.com/search?'+urllib.parse.urlencode({'format':'rss','q':query,'filters':f'ex1:"ez{days}"'})
        raw,final,_,_=fetch(url); doc=ET.fromstring(raw)
        items=[{k:unescape(i.findtext(k) or '') for k in ['title','link','description']} for i in doc.findall('./channel/item')]
    else:
        url='https://html.duckduckgo.com/html/?'+urllib.parse.urlencode({'q':query})
        raw,final,_,_=fetch(url); html=raw.decode('utf-8','replace'); items=[]
        for link,title in re.findall(r'<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>',html,re.S):
            parsed=urllib.parse.parse_qs(urllib.parse.urlparse(unescape(link)).query)
            items.append({'title':re.sub('<[^>]+>','',unescape(title)),'link':parsed.get('uddg',[unescape(link)])[0],'description':''})
    record={'query':query,'provider':provider,'url':final,'slot':slot,'days_requested':days,'report_date':report_date,'searched_at':now(),'items':items,
      'warning':'搜索结果是线索，日期过滤不保证生效，摘要与RSS时间不得作为核验依据'}
    folder=Path(root)/'logs'/report_date/'search'; key=digest(record)[:16]
    save(folder/(key+'.json'),record); (folder/(key+'.response')).write_bytes(raw)
    return record
