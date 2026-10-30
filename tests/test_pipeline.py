"""Isolated synthetic fixtures exercise gates; never represent actual verified news."""
from __future__ import annotations
import copy
import csv
import io
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch
from datetime import date,timedelta
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from model import (ROOT, CHECKS, QA_CHECKS, slots,new_entry,initial_matrix,load,save,file_hash,digest,now,entry_binding,matrix_binding,math_italic)
from ingest import validate_history_tables,capture_url
from quality import (history_shortlist,validate_matrix,build,publish,evidence_errors,numeric_mapping_errors,entry_errors,history_data,render,delivery_format_errors)

class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='car-codex-test-'); self.root=Path(self.temp.name)
        shutil.copytree(ROOT/'rules',self.root/'rules')
        self.report_date='2026-10-26'; self.make_history()
        self.matrix=initial_matrix(self.root,self.report_date,self.history)
        self.make_evidence()
    def tearDown(self): self.temp.cleanup()
    def make_history(self):
        start=date(2026,9,26); light=[['日报日期','主体/国家','核心动作（去重摘要）']]; event=[['日报日期','主体/国家','核心动作']]
        for n in range(30):
            row=[str(start+timedelta(days=n)),f'Historical fixture {n}',f'Historical action {n}']
            light.append(row); event.append(row)
        cert={'schema_version':'test','report_date':self.report_date,'run_status':'COMPLETED','self_audit_status':'VERIFIED','history_health_gate':'PASS','published_body_match':'PASS',
          'history_epoch':'TEST_ONLY','history_window':'2026-09-26:2026-10-25','checked_at':'2026-10-26T10:00:00+08:00'}
        for k in ['final_drive_gap_count','unfinished_batch_count','unregistered_archive_count','terminal_mismatch_count','semantic_invalid_count','placeholder_count','published_body_missing_facts','published_body_pending_versions']: cert[k]='0'
        counts=validate_history_tables(light,event,cert,self.report_date); folder=self.root/'history';folder.mkdir()
        files={}
        for name,table in [('去重轻索引',light),('事件索引',event),('运行摘要',list(cert.items()))]:
            buf=io.StringIO();csv.writer(buf).writerows(table); path=folder/(name+'.csv');path.write_text(buf.getvalue(),encoding='utf-8')
            files[name]={'path':'history/'+path.name,'sha256':file_hash(path),'url':'https://example.invalid/test-only'}
        manifest={'report_date':self.report_date,'certificate':cert,'counts':counts,'fetched_at':now(),'files':files}
        save(folder/'manifest.json',manifest)
        self.history={'manifest':'history/manifest.json','sha256':file_hash(folder/'manifest.json'),'epoch':'TEST_ONLY'}
        self.tables=(light,event,cert)
    def make_evidence(self):
        folder=self.root/'input'/'web'/'test';folder.mkdir(parents=True)
        text='TEST FIXTURE ONLY. On 2026-10-20 the company announced a plan to launch a vehicle. The plan is still a plan. The amount is 10 vehicles, not a production total.'
        (folder/'text.txt').write_text(text,encoding='utf-8');(folder/'response.html').write_bytes(text.encode())
        artifact={'kind':'web','url':'https://example.invalid/test','final_url':'https://example.invalid/test','text_path':'input/web/test/text.txt','text_sha256':file_hash(folder/'text.txt'),
          'raw_sha256':file_hash(folder/'response.html'),'access_flags':[],'captured_at':now()}
        save(folder/'artifact.json',artifact)
        self.source={'id':'SRC','artifact':'input/web/test/artifact.json','artifact_sha256':file_hash(folder/'artifact.json'),'publisher':'TEST FIXTURE','tier':'official',
          'origin_key':'TEST_ONLY','scope':'synthetic unit fixture','content_reviewed':True,'url':'https://example.invalid/test'}
        self.cite={'source_id':'SRC','quote':'On 2026-10-20 the company announced a plan to launch a vehicle.','locator':'test paragraph'}
    def entry(self,slot,n):
        e=new_entry(slot,f'TEST-{n:02d}');e['decision']='keep'
        e['event'].update(date='2026-10-20',reported_date='2026-10-20',date_basis=[self.cite])
        e['fingerprint'].update(subject=f'Test subject {n}',action='announced',object=f'Test vehicle {n}',place=slot['label'],stage='planned',scope='test fixture')
        e['source_status']='一手验证';e['sources']=[copy.deepcopy(self.source)]
        e['policy']={'is_policy':False,'stage':'','rationale':'Test fixture contains a company plan'}
        e['relevance']={'kind':'overseas','rationale':'Synthetic fixture only'}
        e['atoms']=[{'id':'A1','zh':f'测试主体{n}宣布一项新车型计划。','en':f'Test subject {n} announced a vehicle plan.','stage':'planned','supported_stage':'planned','evidence':[self.cite]}]
        e['source_outline']={'event_type':'product','reader_context':'Synthetic plan, not a launch',
            'industry_relation':'direct','industry_value_after_dedup':'Different synthetic vehicle plan',
            'points':[{'id':'P1','text':'Synthetic vehicle plan','role':'main','decision':'included',
                       'atom_ids':['A1'],'evidence':[copy.deepcopy(self.cite)]}]}
        if slot['section']==6:
            e['event']['statistical_period']='2026-09'; e['statistics']={'publisher':'TEST','market':'TEST','metric':'TEST','unit':'vehicles','scope':'TEST'}
        return e
    def fill(self,data=3):
        items=slots()+[{'id':f'S6-{n:02d}','section':6,'label':f'测试数据{n}'} for n in range(1,data+1)]
        self.matrix['entries']=[self.entry(s,n) for n,s in enumerate(items,1)]
        for e in self.matrix['entries']:
            e['cross_section_review']={'compared_ids':[x['candidate_id'] for x in self.matrix['entries'] if x!=e],'conflicts':[],'rationale':'All synthetic subjects differ'}
        history_shortlist(self.root,self.matrix)
        for e in self.matrix['entries']:
            h=e['history_review']; report=load(self.root/h['report']); first=report['matches'][0]
            h.update(result='no_duplicate',full_window_semantic_checked=True,rationale='Synthetic test only, manually prepared different fixture',
              comparisons=[{'row_number':first['row_number'],'published_date':first['record']['日报日期'],'historical_fact':first['record']['核心动作'],'difference':'Different synthetic subject and object'}])
            e['semantic_review']={'reviewer':'TEST FIXTURE','reviewed_at':now(),'binding':entry_binding(e,self.matrix),'checks':{k:{'result':'pass','note':'Synthetic gate fixture, not actual semantic review'} for k in CHECKS}}
        chosen=[self.matrix['entries'][0],self.matrix['entries'][10],self.matrix['entries'][20]]
        mappings=[{'candidate_id':e['candidate_id'],'atom_ids':['A1'],'zh':e['atoms'][0]['zh'],'en':e['atoms'][0]['en']} for e in chosen]
        self.matrix['summary']={'zh':''.join(m['zh'] for m in mappings),'en':' '.join(m['en'] for m in mappings),'items':mappings}
        self.qa()
    def qa(self):
        self.matrix['qa']={'reviewer':'TEST FIXTURE QA','reviewed_at':now(),'binding':matrix_binding(self.matrix),'checks':{k:{'result':'pass','note':'Synthetic integration fixture'} for k in QA_CHECKS}}
    def test_source_point_decisions_are_required(self):
        from quality import source_outline_errors
        e=self.entry(slots()[0],1)
        self.assertEqual(source_outline_errors(e),[])
        p={'id':'P2','text':'Material application scope','role':'key','decision':'pending',
           'atom_ids':[],'evidence':[self.cite]}
        e['source_outline']['points'].append(p)
        self.assertTrue(any('未处理' in s for s in source_outline_errors(e)))
        p.update(decision='excluded',exclusion_kind='duplicate')
        self.assertTrue(any('理由' in s for s in source_outline_errors(e)))
        p['reason']='Already published in the synthetic history fixture'
        self.assertEqual(source_outline_errors(e),[])
        p.update(decision='included',atom_ids=['MISSING'])
        self.assertTrue(any('有效事实原子' in s for s in source_outline_errors(e)))
    def test_outline_evidence_and_industry_relation_are_checked(self):
        from quality import source_outline_errors
        e=self.entry(slots()[0],1)
        e['source_outline']['points'][0]['evidence']=[{**self.cite,'quote':'invented source outline claim'}]
        self.assertTrue(any('来源信息点' in s for s in evidence_errors(self.root,e)))
        e['source_outline']['industry_relation']='indirect'
        e['editorial_quality']={'classification':'fallback'}
        self.assertTrue(any('产业关联' in s for s in source_outline_errors(e)))
    def test_customer_render_never_adds_source_or_scope_facts(self):
        from quality import delivery_entry_text,texts
        e=self.entry(slots()[0],1)
        e['event']['reported_date']='2026-10-25'
        e['sources'][0]['publisher']='A different source'
        self.assertEqual(delivery_entry_text(e),texts(e))
        e['section']=6;e['slot']='S6-02'
        e['statistics']={'publisher':'Malaysian Automotive Association','scope':'MAA TIV销量，非产量'}
        self.assertEqual(delivery_entry_text(e),texts(e))
    def test_annotated_review_is_archived_on_rebuild(self):
        self.fill();path=self.root/'matrix.json';save(path,self.matrix)
        self.assertEqual(build(self.root,path)['status'],'PASS')
        md=self.root/'output'/self.report_date/'送审/全球汽车行业简讯_带信源审核版.md'
        md.write_text(md.read_text(encoding='utf-8')+'\n人工审核：保留这个批注。\n',encoding='utf-8')
        before=md.read_bytes();sha=file_hash(md)
        self.assertEqual(build(self.root,path)['status'],'PASS')
        archived=md.parent.parent/'审核留痕'/sha[:16]/md.name
        self.assertEqual(archived.read_bytes(),before)
        self.assertNotIn('人工审核：',md.read_text(encoding='utf-8'))
    def test_full_51_build_and_release_binding(self):
        self.fill(); result=validate_matrix(self.root,self.matrix); self.assertEqual(result['errors'],[])
        path=self.root/'matrix.json';save(path,self.matrix);self.assertEqual(build(self.root,path)['status'],'PASS')
        preview=self.root/'output'/self.report_date/'送审';raw=(preview/'全球汽车行业简讯_客户终审预览.txt').read_bytes()
        self.assertTrue(raw.startswith(b'\xef\xbb\xbf')); txt=raw.decode('utf-8-sig');self.assertNotIn('http',txt);self.assertNotIn('审核',txt);self.assertIn(math_italic('Test subject'),txt)
        self.assertEqual(len([line for line in txt.splitlines() if '计划。' in line]),52) # 51 body + 1 summary
        self.assertIn('“2”个主要市场 / “2” 𝑀𝑎𝑗𝑜𝑟 𝑀𝑎𝑟𝑘𝑒𝑡𝑠\n欧洲：',txt)
        self.assertIn('“5”个重点市场 / “5” 𝐾𝑒𝑦 𝑀𝑎𝑟𝑘𝑒𝑡𝑠\n东南亚：',txt)
        self.assertEqual(delivery_format_errors(txt),[])
        approval={'approved':True,'reviewer':'TEST HUMAN FIXTURE','approved_at':now(),'authorization_reference':'Synthetic test only',
          'matrix_sha256':file_hash(path),'build_sha256':file_hash(preview/'build.json')}
        approval_path=self.root/'approval.json';save(approval_path,approval)
        self.assertEqual(publish(self.root,path,approval_path)['status'],'PUBLISHED')
        with self.assertRaises(ValueError): publish(self.root,path,approval_path)
    def test_build_blocks_missing_duplicate_or_misplaced_regional_headings(self):
        self.fill();path=self.root/'matrix.json';save(path,self.matrix)
        audit,delivery=render(self.matrix)
        major='“2”个主要市场 / “2” 𝑀𝑎𝑗𝑜𝑟 𝑀𝑎𝑟𝑘𝑒𝑡𝑠'
        key='“5”个重点市场 / “5” 𝐾𝑒𝑦 𝑀𝑎𝑟𝑘𝑒𝑡𝑠'
        lines=delivery.splitlines(); europe=next(i for i,line in enumerate(lines) if line.startswith('欧洲：'))
        reordered=lines[:];reordered[europe:europe+4]=lines[europe+2:europe+4]+lines[europe:europe+2]
        cases={
            'missing_major':delivery.replace(major+'\n',''),
            'missing_key':delivery.replace(key+'\n',''),
            'duplicate':delivery.replace(major,major+'\n'+major),
            'wrong_type':delivery.replace(major,'“2”个主要市场 / “2” Major Markets'),
            'wrong_position':delivery.replace(key+'\n','').replace('澳新：',key+'\n澳新：'),
            'wrong_order':'\n'.join(reordered)+'\n',
        }
        for name,bad in cases.items():
            with self.subTest(name=name),patch('quality.render',return_value=(audit,bad)):
                result=build(self.root,path)
                self.assertEqual(result['status'],'INCOMPLETE')
                self.assertTrue(result['errors'])
                self.assertEqual(load(self.root/'output'/self.report_date/'validation.json')['status'],'INCOMPLETE')
                self.assertFalse((self.root/'output'/self.report_date/'送审').exists())
    def test_publish_also_blocks_regional_format_errors(self):
        self.fill();path=self.root/'matrix.json';save(path,self.matrix)
        self.assertEqual(build(self.root,path)['status'],'PASS')
        preview=self.root/'output'/self.report_date/'送审'
        approval_path=self.root/'approval.json'
        save(approval_path,{'approved':True,'reviewer':'TEST HUMAN FIXTURE','approved_at':now(),
            'authorization_reference':'Synthetic test only','matrix_sha256':file_hash(path),
            'build_sha256':file_hash(preview/'build.json')})
        audit,delivery=render(self.matrix)
        bad=delivery.replace('“5”个重点市场 / “5” 𝐾𝑒𝑦 𝑀𝑎𝑟𝑘𝑒𝑡𝑠\n','')
        with patch('quality.render',return_value=(audit,bad)),self.assertRaisesRegex(ValueError,'格式检查未通过'):
            publish(self.root,path,approval_path)
        self.assertFalse((preview.parent/'正式交付').exists())
    def test_missing_slot_never_emits_preview(self):
        self.fill();self.matrix['entries'].pop(0);path=self.root/'matrix.json';save(path,self.matrix)
        self.assertEqual(build(self.root,path)['status'],'INCOMPLETE');self.assertFalse((self.root/'output'/self.report_date/'送审').exists())
    def test_policy_cap_and_data_bounds(self):
        self.fill()
        for e in self.matrix['entries'][:13]: e['policy']={'is_policy':True,'stage':'draft','rationale':'test policy'}
        self.assertIn('政策条目超过12条',validate_matrix(self.root,self.matrix)['errors'])
        self.matrix['entries']=[e for e in self.matrix['entries'] if e['slot']!='S6-03']
        self.assertIn('数据条目须为3—5条',validate_matrix(self.root,self.matrix)['errors'])
    def test_stage_upgrade_and_number_mismatch(self):
        e=self.entry(slots()[0],1);e['atoms'][0]['stage']='under_construction'
        self.assertIn('原文阶段与正文阶段不一致',evidence_errors(self.root,e))
        e['atoms'][0]['stage']='effective';e['atoms'][0]['supported_stage']='draft'
        self.assertIn('原文阶段与正文阶段不一致',evidence_errors(self.root,e))
        self.assertTrue(numeric_mapping_errors('销量10辆，增长20%','Sales of 100 vehicles, up 20%',[]))
    def test_quote_and_source_tampering(self):
        e=self.entry(slots()[0],1);e['atoms'][0]['evidence']=[{**self.cite,'quote':'unsupported invented quote'}]
        self.assertTrue(any('摘录不在实际证据正文' in x for x in evidence_errors(self.root,e)))
        e=self.entry(slots()[0],1);(self.root/'input/web/test/text.txt').write_text('tampered',encoding='utf-8')
        self.assertTrue(any('哈希失效' in x for x in evidence_errors(self.root,e)))
    def test_paywall_after_long_navigation_is_blocked(self):
        html=('<html><title>Article</title><body><nav>'+('Navigation item '*250)+
              '</nav><article>Accessible teaser. This news is for paid members only. '+
              'If you register as a free member, you can read the rest of this article.</article></body></html>').encode()
        with patch('ingest.fetch',return_value=(html,'https://example.invalid/paywalled','text/html','utf-8')):
            path,artifact=capture_url(self.root,'https://example.invalid/paywalled')
        self.assertTrue(any('truncated_article' in flag for flag in artifact['access_flags']))
        e=self.entry(slots()[0],1)
        e['sources'][0].update(artifact=path,artifact_sha256=file_hash(self.root/path),url=artifact['url'])
        self.assertTrue(any('付费墙' in err for err in evidence_errors(self.root,e)))
    def test_mutations_invalidate_semantic_qa_and_history(self):
        self.fill();e=self.matrix['entries'][0];e['atoms'][0]['zh']+='背景。'
        errs=validate_matrix(self.root,self.matrix)['errors']
        self.assertTrue(any('逐条语义复核不存在或已失效' in x for x in errs))
        self.assertTrue(any('须重做历史比较' in x for x in errs));self.assertIn('独立全稿QA不存在或绑定失效',errs)
    def test_history_zero_schema_mismatch_and_manifest_tamper(self):
        light,event,cert=self.tables
        for bad in [light[:1],[['wrong'],['x']]]:
            with self.assertRaises(ValueError): validate_history_tables(bad,event,cert,self.report_date)
        wrong=copy.deepcopy(event);wrong[1][2]='changed'
        with self.assertRaises(ValueError):validate_history_tables(light,wrong,cert,self.report_date)
        p=self.root/self.history['manifest'];m=load(p);m['certificate']['history_epoch']='changed';save(p,m)
        with self.assertRaises(ValueError):history_data(self.root,self.matrix)
    def test_summary_unmapped_and_human_approval_required(self):
        self.fill();self.matrix['summary']['zh']+='未映射内容。'
        self.assertIn('摘要存在未映射分句或顺序不一致: zh',validate_matrix(self.root,self.matrix)['errors'])
        self.fill();path=self.root/'matrix.json';save(path,self.matrix);build(self.root,path)
        approval=self.root/'approval.json';save(approval,{'approved':False})
        with self.assertRaises(ValueError):publish(self.root,path,approval)

class EvidenceDateParsingTests(unittest.TestCase):
    def test_model_names_do_not_leak_suffix_digits(self):
        from model import numbers
        self.assertEqual(numbers('X700 RZ350e V2G 900V 6C 100kWh'), ['100', '6', '900'])
        self.assertEqual(numbers('October 11 to October 21'), ['10', '10', '11', '21'])

    def test_explicit_currency_mapping_uses_original_units(self):
        mapping={'zh':'21.98','en':'219,800','unit_zh':'万元','unit_en':'yuan',
                 'scope':'vehicle price','rationale':'21.98 × 10000 = 219800'}
        self.assertEqual(numeric_mapping_errors('10月25日，售价21.98万元。',
                         'On October 25, the price is RMB219,800.',[mapping]),[])
        self.assertTrue(numeric_mapping_errors('价格21.98万元，交付10辆。',
                        'Price RMB219,800; 10 vehicles delivered.',[mapping]))

    def test_foreign_dates_and_publication_metadata(self):
        from quality import event_date_evidence_errors, _citation_has_date
        self.assertTrue(_citation_has_date({'quote':'2026.10.22'}, '2026-10-22'))
        self.assertTrue(_citation_has_date({'quote':'ngày 12 tháng 10 năm 2026'}, '2026-10-12'))
        self.assertTrue(_citation_has_date({'quote':'octubre 23, 2026\n1\n0'}, '2026-10-23'))
        self.assertFalse(_citation_has_date({'quote':'October 23, 2026'}, '2026-10-02'))
        self.assertTrue(_citation_has_date({'quote':'၂၀-၁၀-၂၀၂၆ စိစစ်ထုတ်ပေး'}, '2026-10-20'))
        e={'event':{'date':'2026-10-26','reported_date':'2026-10-26',
                    'date_basis':[{'quote':'Published October 26, 2026'}]}}
        self.assertTrue(event_date_evidence_errors(None,e,{}))

    def test_relative_day_and_calendar_are_computed(self):
        from quality import event_date_evidence_errors
        e={'event':{'date':'2026-10-26','reported_date':'2026-10-27',
                    'date_basis':[{'quote':'October 27, 2026'}, {'quote':'The platform launched yesterday.'}],
                    'date_resolution':{'mode':'relative','term':'yesterday','rationale':'Prior day of dated original article'}}}
        self.assertEqual(event_date_evidence_errors(None,e,{}),[])
        e['event']['date']='2026-10-25'
        self.assertTrue(event_date_evidence_errors(None,e,{}))

    def test_date_spellings_keep_event_action_requirement(self):
        from quality import event_date_evidence_errors, _citation_has_date
        for quote, day in [
            ('10/29/2026 The company has released its results.', '2026-10-29'),
            ('10/29/2026 The attorneys general are announcing an agreement.', '2026-10-29'),
            ('เริ่ม 16 ตุลาคม 2026 เป็นต้นไป', '2026-10-16'),
            ('2026年10月29日 15:12 商务部公布数据。', '2026-10-29'),
            ('The automaker began rolling out the update on Saturday, 24 October.', '2026-10-24'),
        ]:
            with self.subTest(quote=quote):
                e={'event':{'date':day,'reported_date':day,'date_basis':[{'quote':quote}]}}
                self.assertEqual(event_date_evidence_errors(None,e,{}), [])
        for quote in ['10/29/2026 Published', '16 ตุลาคม 2026', '2026年10月29日 15:12']:
            day='2026-10-16' if 'ตุลาคม' in quote else '2026-10-29'
            e={'event':{'date':day,'reported_date':day,'date_basis':[{'quote':quote}]}}
            self.assertTrue(event_date_evidence_errors(None,e,{}))
        self.assertFalse(_citation_has_date({'quote':'October 23, 2026'}, '2026-10-02'))
        self.assertFalse(_citation_has_date({'quote':'2026年10月29日 15:12'}, '2026-10-02'))

    def test_dated_dealership_arrival_is_a_supply_event(self):
        from quality import event_date_evidence_errors
        e={'event':{'date':'2026-10-29','reported_date':'2026-10-27',
            'date_basis':[{'quote':'The MGU9 EV arrives in Australian dealerships from October 29th.'}]}}
        self.assertEqual(event_date_evidence_errors(None,e,{}),[])
        e['event']['date_basis']=[{'quote':'Updated October 29, 2026. Australian dealerships directory.'}]
        self.assertTrue(event_date_evidence_errors(None,e,{}))

    def test_dated_persian_directive_is_not_publication_metadata(self):
        from quality import event_date_evidence_errors
        e={'event':{'date':'2026-10-21','reported_date':'2026-10-24',
            'date_basis':[{'quote':'ابلاغیه در تاریخ ۲۹ مهر ۱۴۰۵ صادر شده است'}],
            'date_resolution':{'mode':'calendar','calendar':'Solar Hijri',
                'source_date':'1405-07-29','source_literal':'۲۹ مهر ۱۴۰۵'}}}
        self.assertEqual(event_date_evidence_errors(None,e,{}),[])
        e['event']['date_basis']=[{'quote':'تاریخ خبر ۲۹ مهر ۱۴۰۵'}]
        self.assertTrue(event_date_evidence_errors(None,e,{}))
        e={'event':{'date':'2026-10-01','reported_date':'2026-10-02',
                    'date_basis':[{'quote':'2 de octubre de 2026'},
                                  {'quote':'La presentación oficial fue ayer a la noche.'}],
                    'date_resolution':{'mode':'relative','term':'ayer','rationale':'Dated eyewitness report of previous evening'}}}
        self.assertEqual(event_date_evidence_errors(None,e,{}),[])
        e['event']['date']='2026-09-30'
        self.assertTrue(event_date_evidence_errors(None,e,{}))
        e={'event':{'date':'2026-10-27','reported_date':'2026-10-27',
                    'date_basis':[{'quote':'27-10-2026'}, {'quote':'El lanzamiento ocurrió de manera oficial hoy.'}],
                    'date_resolution':{'mode':'relative','term':'hoy','rationale':'Dated original report says today'}}}
        self.assertEqual(event_date_evidence_errors(None,e,{}),[])
        e['event']['date']='2026-10-26'
        self.assertTrue(event_date_evidence_errors(None,e,{}))
        e={'event':{'date':'2026-10-26','reported_date':'2026-10-27',
                    'date_basis':[{'quote':'۴ آبان ۱۴۰۵ آغاز شده است'}],
                    'date_resolution':{'mode':'calendar','calendar':'Solar Hijri','source_date':'1405-08-04','source_literal':'۴ آبان ۱۴۰۵'}}}
        self.assertEqual(event_date_evidence_errors(None,e,{}),[])
        e['event']['date']='2026-10-25'
        self.assertTrue(event_date_evidence_errors(None,e,{}))

    def test_dated_release_actions_across_languages(self):
        from quality import event_date_evidence_errors
        for quote, day in [
            ('26.10.2026 ADM Jizzakh va DK&G uskunalarni yetkazib berish va montaj qilish bo‘yicha kelishuvga erishdi.', '2026-10-26'),
            ('SAN FRANCISCO, Oct. 26, 2026 -- Turo is debuting the rental experience.', '2026-10-26'),
            ('October 23, 2026. We announce today a financing round.', '2026-10-23'),
            ('Comunicato stampa del 21 ottobre 2026. Presentati oggi i dati.', '2026-10-21'),
            ('30 de septiembre de 2026 durante la inauguración de nuevas inversiones.', '2026-09-30'),
            ('Il 20 ottobre 2026 si è tenuto il lancio, annunciando l’ingresso in Italia.', '2026-10-20'),
            ('The partnership was unveiled on 10 October 2026.', '2026-10-10'),
            ('Ngày 26/10, hai bên ký kết Biên bản ghi nhớ hợp tác.', '2026-10-26'),
            ('Oferta obowiązuje od 9 października 2026.', '2026-10-09'),
            ('Oct. 23, 2026 -- The company today reported financial results.', '2026-10-23'),
            ('روز ۲۹ مهر ۱۴۰۵ ثبت نام کلید خورده', '2026-10-21'),
            ('26 Ekim 2026, Pazartesi günü seri üretim aşamasına geçti.', '2026-10-26'),
            ('Варианты сотрудничества обсуждены в ходе визита 26 октября 2026.', '2026-10-26'),
            ('La actualización entró en vigencia el martes 13 de octubre de 2026.', '2026-10-13'),
            ('Las reservas del 15 al 18 de octubre de 2026 superó la meta.', '2026-10-18'),
            ('27-Oct-2026 — AUTO1 Group said the price index stood at 132.0.', '2026-10-27'),
            ('24 octobre 2026. Le ministre a reçu samedi une délégation de Tirsam.', '2026-10-24'),
            ('Le directeur a effectué ce samedi 17 octobre 2026 une visite sur le site du projet.', '2026-10-17'),
            ('18 de octubre de 2026, inicio de obra de la nueva nave industrial.', '2026-10-18'),
            ('20 Oktober 2026: serah terima kendaraan berlangsung di Jakarta.', '2026-10-20'),
            ('October 27, 2026. Honda will debut its new race truck on October 29.', '2026-10-27'),
            ('Oct 26, 2026. Isuzu Philippines now adds this new pickup variant.', '2026-10-26'),
            ('Oct 28, 2026 Financial Results For The Quarter Ended September 30, 2026', '2026-10-28'),
            ('Lima, 27 de octubre de 2026. La compañía incorporó más de diez sedanes.', '2026-10-27'),
        ]:
            with self.subTest(quote=quote):
                e={'event':{'date':day,'reported_date':day,'date_basis':[{'quote':quote}]}}
                if '۱۴۰۵' in quote:
                    e['event']['date_resolution']={'mode':'calendar','calendar':'Solar Hijri','source_date':'1405-07-29','source_literal':'۲۹ مهر ۱۴۰۵'}
                self.assertEqual(event_date_evidence_errors(None,e,{}), [])
                e['event']['date']='2026-10-25' if day=='2026-10-28' else '2026-10-28'
                self.assertTrue(event_date_evidence_errors(None,e,{}))
        for quote in ['Published October 26, 2026', '26.10.2026 Yangiliklar ADM Jizzakh', 'Comunicato stampa del 26 ottobre 2026', 'Ngày 26/10: article updated', '26 octobre 2026: page des visites, mise à jour']:
            e={'event':{'date':'2026-10-26','reported_date':'2026-10-26','date_basis':[{'quote':quote}]}}
            self.assertTrue(event_date_evidence_errors(None,e,{}))

    def test_persian_dated_meeting_requires_action_and_correct_calendar(self):
        from quality import event_date_evidence_errors
        e={'event':{'date':'2026-10-26','reported_date':'2026-10-28',
            'date_basis':[{'quote':'برگزاری نشست مذکور در روز دوشنبه ۴ آبان ۱۴۰۵ صورت گرفت.'}],
            'date_resolution':{'mode':'calendar','calendar':'Solar Hijri',
                'source_date':'1405-08-04','source_literal':'۴ آبان ۱۴۰۵'}}}
        self.assertEqual(event_date_evidence_errors(None,e,{}),[])
        e['event']['date']='2026-10-25'
        self.assertTrue(event_date_evidence_errors(None,e,{}))
        e['event']['date']='2026-10-26'
        e['event']['date_basis']=[{'quote':'تاریخ خبر ۴ آبان ۱۴۰۵'}]
        self.assertTrue(event_date_evidence_errors(None,e,{}))

if __name__=='__main__': unittest.main(verbosity=2)
