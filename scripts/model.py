"""Shared schema, immutable content bindings and file utilities. Standard library only."""
from __future__ import annotations
import hashlib
import json
import re
import unicodedata
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TZ = timezone(timedelta(hours=8))
CN = ['奇瑞','上汽','比亚迪','吉利','长安','长城','北汽','东风','特斯拉中国','广汽']
GLOBAL = ['特斯拉','丰田','比亚迪','大众','现代起亚','斯泰兰蒂斯','雷诺日产','通用','福特','本田']
REGIONS = ['欧洲','美洲','东南亚','澳新','中东','中北亚','中北非']
COUNTRIES = ['俄罗斯','沙特阿拉伯','伊朗','墨西哥','越南','巴西','意大利','西班牙','土耳其','波兰','菲律宾','印度尼西亚','尼日利亚','巴基斯坦','缅甸','智利','秘鲁','阿联酋','乌拉圭','厄瓜多尔','委内瑞拉']
GROUPS = {2:CN, 3:GLOBAL, 4:REGIONS, 5:COUNTRIES}
HEADINGS = {1:'一、核心信息摘要',2:'二、中国汽车出口TOP10集团动态',3:'三、全球跨国汽车集团TOP10动态',4:'四、分区域政策与市场动态',5:'五、重点国家信息扫描',6:'六、今日关键数据快报'}
CHECKS = ['evidence','event_date','stage','numbers_units','bilingual','history','relevance','policy','cross_section','high_risk',
          'key_point_coverage','reader_context','industry_value_after_dedup']
QA_CHECKS = ['all_entries','summary_mapping','bilingual','policy_count','cross_section','history','value','source_to_draft']
STAGES = {'announced','planned','mou','signed','proposed','draft','under_review','approved','under_construction','completed','in_production','launched','delivered','effective','data_released','ongoing','other'}

def now(): return datetime.now(TZ).isoformat(timespec='seconds')
def digest(value):
    raw = value if isinstance(value, bytes) else json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',',':')).encode('utf-8')
    return hashlib.sha256(raw).hexdigest()
def file_hash(path): return digest(Path(path).read_bytes())
def load(path): return json.loads(Path(path).read_text(encoding='utf-8-sig'))
def save(path, value):
    path=Path(path); path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_suffix(path.suffix+'.tmp')
    temp.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    temp.replace(path)
def local(root, relative):
    p=(Path(root)/relative).resolve()
    if not p.is_relative_to(Path(root).resolve()): raise ValueError('项目内路径越界')
    return p
def norm(value): return re.sub(r'\s+','',unicodedata.normalize('NFKC',str(value))).lower()
def slots(): return [{'id':f'S{s}-{i:02d}','section':s,'label':label} for s,labels in GROUPS.items() for i,label in enumerate(labels,1)]
def policy_hash(root):
    return digest({p.name:file_hash(p) for p in sorted((Path(root)/'rules').iterdir()) if p.is_file() and p.suffix in {'.md','.json'}})
def math_italic(value):
    out=[]
    for c in value:
        if 'A'<=c<='Z': c=chr(0x1D434+ord(c)-65)
        elif 'a'<=c<='z': c='ℎ' if c=='h' else chr(0x1D44E+ord(c)-97)
        out.append(c)
    return ''.join(out)
def plain(value): return unicodedata.normalize('NFKC',value)
def new_entry(slot, candidate_id=''):
    return {'candidate_id':candidate_id,'slot':slot['id'],'section':slot['section'],'label':slot['label'],
      'decision':'pending','event':{'date':'','date_basis':[],'reported_date':'','target_date':'','statistical_period':''},
      'fingerprint':{'subject':'','aliases':[],'action':'','object':'','place':'','partners':[], 'numbers':[], 'stage':'','scope':''},
      'relevance':{'kind':'','rationale':''},'policy':{'is_policy':None,'stage':'','rationale':''},
      'source_status':'','sources':[], 'atoms':[],
      'source_outline':{'event_type':'','points':[], 'reader_context':'',
                        'industry_relation':'','industry_value_after_dedup':''},
      'history_review':{'result':'pending','search_terms':[],'comparisons':[],'rationale':''},
      'cross_section_review':{'compared_ids':[],'conflicts':[],'rationale':''},'semantic_review':{}}
def entry_content(entry): return {k:v for k,v in entry.items() if k!='semantic_review'}
def entry_binding(entry, matrix):
    return digest({'entry':entry_content(entry),'report_date':matrix['report_date'],'history':matrix['history'],'rules':matrix['rules_sha256']})
def matrix_binding(matrix): return digest({k:v for k,v in matrix.items() if k!='qa'})
def initial_matrix(root, report_date, history):
    date.fromisoformat(report_date)
    return {'schema_version':1,'report_date':report_date,'timezone':'Asia/Shanghai','rules_sha256':policy_hash(root),
      'history':history,'entries':[], 'summary':{'zh':'','en':'','items':[]},'qa':{}}
def numbers(value):
    value=plain(value)
    # Currency prefixes such as RMB/HK$ must not hide the first digit;
    # alphanumeric model names (V2G, X700) remain excluded by the boundary.
    value=re.sub(r'(?i)\b(?:RMB|HK\$|US\$|USD|EUR|GBP|CNY|VND|PKR|IDR)\s*', ' ', value)
    found=sorted(re.findall(r'(?<![A-Za-z0-9])\d+(?:[,，]\d{3})*(?:\.\d+)?',value.replace('，',',')))
    # Treat written English month names as their numeric month counterpart so
    # bilingual dates compare on the same numeric basis.
    months={'january':'1','february':'2','march':'3','april':'4','may':'5','june':'6',
            'july':'7','august':'8','september':'9','october':'10','november':'11','december':'12',
            'jan':'1','feb':'2','mar':'3','apr':'4','jun':'6','jul':'7','aug':'8','sep':'9','sept':'9','oct':'10','nov':'11','dec':'12'}
    lower=value.lower()
    for name,num in months.items():
        # Only count a month when it is part of a date expression; modal
        # “may” in ordinary prose must not become a phantom number.
        pat=(r'(?:\b\d{1,2}\s+'+name+r'\b|\b'+name+r'\s+\d{1,2}\b|\b'+name+r',?\s+\d{4}\b)')
        found.extend(num for _ in re.finditer(pat,lower))
    return sorted(found)
def texts(entry): return (' '.join(a.get('zh','') for a in entry.get('atoms',[])), ' '.join(a.get('en','') for a in entry.get('atoms',[])))
