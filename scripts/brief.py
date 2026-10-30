"""Local editorial CLI. Network operations are GET-only; no LLM/API key required."""
from __future__ import annotations
import argparse
import copy
import sys
from datetime import date, timedelta
from pathlib import Path
from model import (ROOT,CHECKS,QA_CHECKS,HEADINGS,now,load,save,slots,new_entry,initial_matrix,entry_binding,matrix_binding,file_hash,policy_hash)
from ingest import (refresh_history,local_history_ref,migrate_local_history,register_release_history,
    extract_pdf,capture_url,search_web)
from quality import (history_data,history_shortlist,entry_errors,validate_matrix,build,publish,
    editorial_value_errors,is_low_value_retail_event,is_display_only_event,
    stage_consistency_errors,statistical_scope_errors,timeliness_errors,
    event_date_evidence_errors,recent_local_duplicate_errors)
from collab import create_package,import_package,progress


# Search aliases in sources.json are human-readable groups (for example
# ``"BYD Denza Yangwang"``), not literal phrases.  Sending the whole group
# to a search engine makes every name an AND term and produced many empty or
# irrelevant searches in production.  Keep only subject-like terms here; the
# section action and date window are added by query_plan().
_QUERY_NOISE = {
    'after', 'before', 'automotive', 'auto', 'autos', 'car', 'cars',
    'factory', 'fabrica', 'fábrica', 'fábricas', 'launch', 'launched',
    'lanzamiento', 'market', 'mercado', 'production', 'produccion',
    'producción', 'sales', 'sales', 'vehicles', 'vehicle', 'news',
    'export', 'exports', 'overseas', 'industry', 'trade', 'regulation',
    'regulacion', 'regulación', 'concesionario', 'concesionarios',
    'plant', 'plants', 'investment', 'investments', 'technology',
    'technology', 'dealer', 'dealers', 'cars', 'mobil', 'mobilen',
    # Generic Chinese action/market words from sources.json are useful as
    # query modifiers, but must not be treated as separate brand subjects.
    '海外', '汽车', '出口', '工厂', '上市', '经销商', '技术', '投资',
    '市场', '政策', '销量', '生产', '发布', '渠道', 'industry', '行业',
}


def _query_subjects(alias):
    """Expand a grouped alias into subject terms without changing evidence."""
    parts=[p for p in str(alias).split() if p]
    if not parts:
        return []
    # Chinese and other CJK aliases are already separated into subject names
    # in sources.json (e.g. ``比亚迪 腾势 仰望``).
    if any(any('\u4e00' <= c <= '\u9fff' for c in p) for p in parts):
        return [p for p in parts if p.lower() not in _QUERY_NOISE]
    terms=[]
    for part in parts:
        clean=part.strip(',:;()[]')
        if clean and clean.lower() not in _QUERY_NOISE:
            terms.append(clean)
    # A two-word country/region phrase is useful as a whole; otherwise each
    # brand/model name should be searched separately rather than ANDed.
    if len(terms)==2 and len(parts)==2:
        return [' '.join(terms)]
    return terms


def _query_actions(section):
    """Return small concrete action terms instead of one giant AND query."""
    return {
        2: ['export', 'factory', 'launch', 'dealer', 'investment'],
        3: ['launch', 'investment', 'production', 'technology', 'restructuring'],
        4: ['market', 'industry', 'trade', 'regulation'],
        5: ['lanzamiento', 'fábrica', 'concesionario', 'sales', 'market'],
    }.get(section, ['automotive'])

def status(root,matrix):
    good=[]; problems={}; editorial_flags={}
    for e in matrix['entries']:
        errs=entry_errors(root,e,matrix)
        if errs: problems[e['slot']]=errs
        else: good.append(e['slot'])
        flags=[]
        if is_low_value_retail_event(e): flags.append('low_value_retail')
        if is_display_only_event(e): flags.append('display_only')
        if editorial_value_errors(e): flags.append('editorial_value')
        if stage_consistency_errors(e): flags.append('stage_consistency')
        if statistical_scope_errors(e): flags.append('statistical_scope')
        if timeliness_errors(root,e,matrix): flags.append('timeliness_unresolved')
        if event_date_evidence_errors(root,e,matrix): flags.append('event_date_evidence_missing')
        if recent_local_duplicate_errors(root,e,matrix): flags.append('recent_local_duplicate')
        if flags: editorial_flags[e['slot']]=sorted(set(flags))
    fixed=slots(); missing=[s for s in fixed if s['id'] not in good]
    prep=sum(s.startswith(('S2-','S3-')) for s in good)==20 and 3<=sum(s.startswith('S6-') for s in good)<=5
    main=len([s for s in good if not s.startswith('S6-')])==48
    return {'report_date':matrix['report_date'],'state':'READY_FOR_QA' if main and prep else 'INCOMPLETE','PREP':'PASS' if prep else 'INCOMPLETE',
      'MAIN':'PASS' if main else 'INCOMPLETE','qualified_fixed_slots':48-len(missing),'missing_or_unqualified':missing,
      'problems':problems,'editorial_flags':editorial_flags}

def query_plan(root,matrix,slot_id,days):
    spec=load(Path(root)/'rules'/'sources.json'); item=next((s for s in slots() if s['id']==slot_id),None)
    if item is None: raise ValueError('不支持的固定槽位')
    label=item['label']; aliases=spec['aliases'].get(label,[label]); section=item['section']
    t=date.fromisoformat(matrix['report_date']); start=t-timedelta(days=days-1)
    templates=[]
    subjects=[label]
    for alias in aliases:
        subjects.extend(_query_subjects(alias))
    # Preserve order while removing duplicate terms from the label/aliases.
    subjects=list(dict.fromkeys(x for x in subjects if x))
    for subject in subjects:
        for action in _query_actions(section):
            templates.append(f'{subject} {action} after:{start} before:{t+timedelta(days=1)}')
    sites=['auto.gasgoo.com','cnautonews.com','marklines.com','reuters.com']
    site_subject=subjects[0] if subjects else label
    for site in sites: templates.append(f'site:{site} {site_subject} automotive after:{start}')
    if label in spec.get('official_sites',{}):
        for site in spec['official_sites'][label]: templates.append(f'site:{site} news {site_subject} after:{start}')
    return {'slot':slot_id,'label':label,'days':days,'queries':templates,'instruction':'针对未完成槽位顺次执行3/7/14/30天；搜完实际正文核事件日，排序/过滤不保证时效。失败换词、当地语言、官网及备用。'}

def main():
    parser=argparse.ArgumentParser(description='东风汽车简讯独立采编工具', epilog='This product includes software developed by UncleCode (https://x.com/unclecode) as part of the Crawl4AI project (https://github.com/unclecode/crawl4ai).')
    parser.add_argument('--root',type=Path,default=ROOT)
    commands=parser.add_subparsers(dest='cmd',required=True)
    start=commands.add_parser('start'); start.add_argument('--date',required=True)
    hist=commands.add_parser('history'); hist.add_argument('--date',required=True)
    migrate=commands.add_parser('history-migrate', help='从已保存的完整Google快照生成本地历史库（不联网）')
    migrate.add_argument('target_date'); migrate.add_argument('source_manifest',type=Path)
    pdf=commands.add_parser('pdf'); pdf.add_argument('--date',required=True); pdf.add_argument('--publisher',required=True); pdf.add_argument('--publication-date',required=True); pdf.add_argument('paths',nargs='*')
    fetch=commands.add_parser('fetch'); fetch.add_argument('url'); fetch.add_argument('--engine',choices=['auto','http','browser'],default='auto')
    batch=commands.add_parser('fetch-batch'); batch.add_argument('urls',type=Path); batch.add_argument('--engine',choices=['auto','http','browser'],default='auto'); batch.add_argument('--concurrency',type=int,choices=range(1,5),default=3)
    search=commands.add_parser('search'); search.add_argument('--date',required=True); search.add_argument('--slot',required=True); search.add_argument('--days',type=int,choices=[3,7,14,30],default=3); search.add_argument('--provider',choices=['bing','duckduckgo'],default='bing'); search.add_argument('query')
    for name in ['status','validate','build','dedup','bind-rules','qa','approval-template']:
        p=commands.add_parser(name); p.add_argument('matrix',type=Path)
        if name=='qa': p.add_argument('notes',type=Path)
    for name in ['add','review','queries','reuse']:
        p=commands.add_parser(name); p.add_argument('matrix',type=Path); p.add_argument('--slot',required=True)
        if name in ['add','reuse']: p.add_argument('--id',required=True)
        if name=='reuse': p.add_argument('candidate',type=Path)
        if name=='review': p.add_argument('notes',type=Path)
        if name=='queries': p.add_argument('--days',type=int,choices=[3,7,14,30],default=3)
    package=commands.add_parser('package-create'); package.add_argument('matrix',type=Path); package.add_argument('--agent',required=True); package.add_argument('--slots',required=True,help='逗号分隔槽位；子代理只写候选包')
    imp=commands.add_parser('package-import'); imp.add_argument('matrix',type=Path); imp.add_argument('package',type=Path)
    prog=commands.add_parser('progress'); prog.add_argument('matrix',type=Path)
    pub=commands.add_parser('publish'); pub.add_argument('matrix',type=Path); pub.add_argument('approval',type=Path)
    reg=commands.add_parser('history-register-release', help='将已正式发布的当天新增登记到本地新增表')
    reg.add_argument('release',type=Path)
    args=parser.parse_args(); root=args.root.resolve(); result=None
    if args.cmd=='history': result=refresh_history(root,args.date)
    elif args.cmd=='history-migrate': result=migrate_local_history(root,args.target_date,args.source_manifest)
    elif args.cmd=='history-register-release': result=register_release_history(root,args.release)
    elif args.cmd=='start':
        path=root/'matrix'/f'{args.date}.json'
        if path.exists(): raise ValueError('已存在当日矩阵，请继续已有任务')
        # Production mode is local-only.  The legacy Google snapshot path is
        # preserved for explicit ``history`` migration/audit calls.
        history=local_history_ref(root,args.date); matrix=initial_matrix(root,args.date,history); save(path,matrix)
        result={'matrix':str(path),'history':history,'state':'PREP','instruction':'先处理早餐并联网采编，不等待国际快讯。'}
    elif args.cmd=='pdf':
        paths=[Path(p) for p in args.paths] if args.paths else sorted((root/'PDFday').glob('*.pdf'))
        if not paths: raise ValueError('PDFday尚无PDF；继续联网，午间再接入国际快讯')
        result=[extract_pdf(root,p,args.date,args.publisher,args.publication_date) for p in paths]
    elif args.cmd=='fetch':
        from crawler import capture_many
        batch_result=capture_many(root,[args.url],engine=args.engine)
        item=batch_result['items'][0]
        artifact=load(root/item['artifact']) if item.get('artifact') else {}
        result={**artifact,**item,'log':batch_result['log'],
                'status':'INCOMPLETE' if item.get('error') or item.get('flags') or item.get('browser_error') else 'CAPTURED_NOT_VERIFIED'}
    elif args.cmd=='fetch-batch':
        from crawler import capture_many
        result=capture_many(root,load(args.urls),engine=args.engine,concurrency=args.concurrency)
        result['status']='INCOMPLETE' if any(i.get('error') or i.get('flags') or i.get('browser_error') for i in result['items']) else 'CAPTURED_NOT_VERIFIED'
    elif args.cmd=='search': result=search_web(root,args.query,args.date,args.slot,args.days,args.provider)
    else:
        matrix=load(args.matrix)
        if args.cmd=='package-create': result=create_package(root,matrix,args.agent,args.slots.split(','))
        elif args.cmd=='package-import': result=import_package(root,args.matrix,args.package)
        elif args.cmd=='progress': result=progress(matrix)
        elif args.cmd=='add':
            spec=next((s for s in slots() if s['id']==args.slot),None)
            if not spec and args.slot.startswith('S6-'): spec={'id':args.slot,'section':6,'label':''}
            if not spec: raise ValueError('未知槽位')
            if any(e['slot']==args.slot or e['candidate_id']==args.id for e in matrix['entries']): raise ValueError('槽位/ID已占用；替换时先将旧候选保存到candidates备用并移出矩阵')
            matrix['entries'].append(new_entry(spec,args.id)); matrix['qa']={}; save(args.matrix,matrix); result={'created':args.id,'state':'pending'}
        elif args.cmd=='reuse':
            candidate=load(args.candidate); candidate['slot']=args.slot; candidate['candidate_id']=args.id
            spec=next(s for s in slots() if s['id']==args.slot); candidate.update(section=spec['section'],label=spec['label'])
            candidate['semantic_review']={}; candidate['history_review']={'result':'pending'}; candidate['cross_section_review']={}; candidate['decision']='pending'
            for source in candidate.get('sources',[]): source['content_reviewed']=False; source['visual_checked']=False
            if any(e['slot']==args.slot for e in matrix['entries']): raise ValueError('槽位已占用')
            matrix['entries'].append(candidate); matrix['qa']={}; save(args.matrix,matrix); result={'reused':args.id,'state':'全部核验已重置，重新取证'}
        elif args.cmd=='queries': result=query_plan(root,matrix,args.slot,args.days)
        elif args.cmd=='status': result=status(root,matrix)
        elif args.cmd=='dedup': matrix=history_shortlist(root,matrix); save(args.matrix,matrix); result={'compared':len(matrix['entries']),'state':'等待全窗口语义比较'}
        elif args.cmd=='bind-rules':
            matrix['rules_sha256']=policy_hash(root); matrix['qa']={}
            for e in matrix['entries']: e['semantic_review']={}
            save(args.matrix,matrix); result={'state':'规则更新，所有语义复核已重置'}
        elif args.cmd=='review':
            entry=next(e for e in matrix['entries'] if e['slot']==args.slot)
            errors=entry_errors(root,entry,matrix,require_review=False)
            if errors: raise ValueError('复核前结构/证据未完成：'+'; '.join(errors))
            notes=load(args.notes)
            if not notes.get('reviewer'): raise ValueError('缺少复核人')
            for key in CHECKS:
                note=notes.get('checks',{}).get(key,{})
                if note.get('result')!='pass' or not note.get('note'): raise ValueError('缺少实际语义核对结论: '+key)
            entry['semantic_review']={'binding':entry_binding(entry,matrix),'reviewer':notes['reviewer'],'reviewed_at':now(),'checks':notes['checks']}
            matrix['qa']={}; save(args.matrix,matrix); result={'reviewed':entry['candidate_id']}
        elif args.cmd=='qa':
            gate=validate_matrix(root,matrix,require_qa=False)
            if gate['status']!='PASS': raise ValueError('QA前检查失败：'+'; '.join(gate['errors'][:20]))
            notes=load(args.notes)
            if not notes.get('reviewer'): raise ValueError('QA复核人缺失')
            for key in QA_CHECKS:
                note=notes.get('checks',{}).get(key,{})
                if note.get('result')!='pass' or not note.get('note'): raise ValueError('QA结论缺失: '+key)
            matrix['qa']={'binding':matrix_binding(matrix),'reviewer':notes['reviewer'],'reviewed_at':now(),'checks':notes['checks']}
            save(args.matrix,matrix); result={'state':'QA_RECORDED','instruction':'生成送审双版本，人工终审后正式发布'}
        elif args.cmd=='validate': result=validate_matrix(root,matrix)
        elif args.cmd=='build': result=build(root,args.matrix)
        elif args.cmd=='approval-template':
            path=root/'output'/matrix['report_date']/'送审'/'build.json'
            result={'approved':False,'reviewer':'','approved_at':'','authorization_reference':'','matrix_sha256':file_hash(args.matrix),'build_sha256':file_hash(path)}
        elif args.cmd=='publish': result=publish(root,args.matrix,args.approval)
    import json
    print(json.dumps(result,ensure_ascii=False,indent=2))
    if isinstance(result,dict) and result.get('status')=='INCOMPLETE': return 2
    return 0

if __name__=='__main__':
    if hasattr(sys.stdout,'reconfigure'): sys.stdout.reconfigure(encoding='utf-8')
    if hasattr(sys.stderr,'reconfigure'): sys.stderr.reconfigure(encoding='utf-8')
    try: sys.exit(main())
    except Exception as e:
        print(f'ERROR {type(e).__name__}: {e}',file=sys.stderr)
        sys.exit(1)
