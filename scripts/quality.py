"""Fail-closed structural/evidence binding gates; semantic judgements remain explicit."""
from __future__ import annotations
import csv
import io
import re
import shutil
import unicodedata
from collections import Counter
from datetime import date, datetime, timedelta
from pathlib import Path
from difflib import SequenceMatcher
from model import (GROUPS, HEADINGS, CHECKS, QA_CHECKS, STAGES, TZ, digest, file_hash, load, save, local,
    norm, plain, numbers, slots, policy_hash, entry_binding, matrix_binding, texts, now, math_italic)
from ingest import read_csv, validate_history_tables

HIGH_RISK=r'首次|全球第一|全部|全面|正式批准|已投产|已交付|已经实施|创历史新高|世界首[款个家]'
INTERNAL=r'https?://|www\.|\[[^\]]+\]\(|信源|查重|待核|候选编号|审核记录|事实指纹|来源URL|source\s*:'
POLICY_HINT=r'关税|补贴|法规|法案|草案|征求意见|税率|准入政策|政策生效|议会通过'

# Editorial quality gates.  These are deliberately conservative keyword
# screens: they flag a candidate for replacement or an explicit fallback
# rationale, while the evidence and semantic review remain authoritative.
RETAIL_LOW_VALUE_HINT = re.compile(
    r'优惠券|促销|融资优惠|购车优惠|抽奖|试驾.*抽奖|免费升级|节日活动|'
    r'promotion|promotional|coupon|raffle|draw|financing offer|free upgrade|'
    r'special offer|test drive', re.I,
)
DISPLAY_ONLY_HINT = re.compile(
    r'车展|展会|展销|商场|静态展示|展厅展示|车展陈列|'
    r'auto show|motor show|showroom display|mall exhibition|displayed at', re.I,
)
DEALER_OPENING_HINT = re.compile(
    r'开设(?:当地)?第?\d*家?(?:经销店|经销商|展厅|网点)|启用(?:新)?(?:经销店|展厅)|'
    r'开业|经销店开设|opened? (?:a |the )?(?:\d+(?:st|nd|rd|th) )?(?:dealership|showroom)|'
    r'inaugurated? (?:a |the )?(?:dealership|showroom)', re.I,
)
MATERIAL_INDUSTRY_HINT = re.compile(
    r'正式上市|上市销售|发布车型|推出车型|新车型|产能|年产|投资|工厂|基地|生产|量产|'
    r'组装|本地制造|供应链|零部件|售后|服务中心|服务网络|授权服务点|经销网络|'
    r'订单(?:量|数|达到|累计|增长)|车队订单|交付(?:量|数据|车辆)|销量|销售数据|注册量|市场份额|市场数据|统计|政策|法规|法案|补贴|关税|'
    r'launch(?:ed)? for sale|official launch|model debut|introduced the .* model|'
    r'capacity|production|manufactur|assembly|plant|investment|supply chain|'
    r'parts|after-sales|service (?:hub|network|points?)|dealer network|'
    r'order volume|orders received|confirmed orders|fleet orders|deliver(?:y|ies) (?:volume|data|vehicles|began|reached|totaled)|sales data|registrations?|market share|statistics|'
    r'policy|regulation|law|tariff|subsid', re.I,
)
NON_DISPLAY_MATERIAL_HINT = re.compile(
    r'正式上市|上市销售|正式发布|首发|正式引入|产能|年产|投资|工厂|基地|生产|量产|组装|'
    r'本地制造|供应链|零部件|售后|服务中心|服务网络|授权服务点|经销网络|订单(?:量|数|达到|累计|增长)|交付(?:量|数据|车辆)|'
    r'销量|销售数据|注册量|市场份额|市场数据|统计|政策|法规|法案|补贴|关税|'
    r'official(?:ly)? launched?|launched? in .* market|debut(?:ed)?|introduced for sale|'
    r'capacity|production|manufactur|assembly|plant|investment|supply chain|parts|'
    r'after-sales|service (?:hub|network|points?)|dealer network|order volume|orders received|confirmed orders|fleet orders|deliver(?:y|ies) (?:volume|data|vehicles|began|reached|totaled)|'
    r'sales data|registrations?|market share|statistics|policy|regulation|law|tariff|subsid', re.I,
)
FORMAL_PRODUCT_HINT = re.compile(
    r'正式上市|上市销售|正式发布|首发|推出.*车型|发布.*车型|正式引入|'
    r'official(?:ly)? launched?|launched? in .* market|debut(?:ed)?|introduced for sale', re.I,
)
NETWORK_SCALE_HINT = re.compile(
    r'第\s*\d+\s*家|覆盖\s*\d+\s*座?城市|\d+\s*家(?:经销|服务)|'
    r'\d+\s*(?:dealerships?|service points?|cities|outlets)|'
    r'\d+(?:st|nd|rd|th)\s+(?:dealerships?|service points?|outlets)', re.I,
)
WEAK_COUNTRY_HINT = re.compile(
    r'加快.*筹备|上市筹备|展示.*定位|品牌定位|行业人士.*呼吁|分析人士.*呼吁|'
    r'尚未公布具体车型|尚未公布.*上市日期|未公布.*措施|'
    r'intensif(?:y|ied).*pre-launch|pre-launch campaign|positioning|'
    r'interviewees?.*(?:called for|urged)|analysts?.*(?:called for|urged)|'
    r'has not disclosed (?:the )?(?:specific models|an official launch date)|'
    r'did not announce (?:new )?government measures', re.I,
)
ACTUAL_STAGE_HINT = re.compile(
    r'已开工|已经开工|开工建设|已投产|已经投产|已生产|已上市|正式上市|已交付|已经交付|'
    r'construction has begun|construction started|in production|already launched|'
    r'officially delivered|deliveries have begun', re.I,
)
PLANNED_CONSTRUCTION_HINT = re.compile(
    r'(?:计划|预计|拟)(?:于)?[^。；，,]{0,18}(?:正式)?开工|'
    r'(?:construction|site work) is scheduled to begin|expected to start construction', re.I,
)
PRELIMINARY_CONSTRUCTION_HINT = re.compile(
    r'前期建设|前期工作|场地准备|启动前期|preliminary site preparation|site preparation', re.I,
)
YEAR_SCOPE_HINT = re.compile(
    r'当年生产|本年生产|今年生产|全部生产年份|不限定生产年份|按全部年份|'
    r'produced .* this year|all production years|regardless of production year|'
    r'year-of-production', re.I,
)
COMMENTARY_SIGNAL_HINT = re.compile(
    r'行业人士|分析人士|受访者|呼吁|建议|诉求|评论|analysts?|interviewees?|'
    r'called for|urged|requested|opinion', re.I,
)

# Date evidence is intentionally stricter than a page's publication metadata.
# A citation must tie the candidate date to the event, announcement, or data
# release itself; a recent repost/update date is not sufficient.
PUBLICATION_DATE_ONLY_HINT = re.compile(
    r'发布|报道|转载|转发|刊发|更新|页面日期|文章日期|发布时间|'
    r'published|reported|republished|reposted|updated|posted|article date|publication date', re.I,
)
EVENT_DATE_ACTION_HINT = re.compile(
    r'宣布|公布|披露|介绍|表示|发布(?:车型|产品|数据|计划)?|签署|签订|获批|批准|开工|投产|生产|量产|'
    r'上市|交付|启动|举行|完成|设立|投资|订单|销量|销售|注册|统计|生效|实施|'
    r'announc(?:e(?:d|s)?|ement|ing)|began rolling out|debut(?:s|ing|ed)?|released|report(?:ed|s)|said|start(?:ed)?|launch(?:ed)?|sign(?:ed)?|approved|construction|production|'
    r'manufactur|assembly|delivered|deliveries|started|opened|invest(?:ed|ment)?|now adds|Financial Results For The Quarter Ended|'
    r'orders?|sales|registrations?|statistics?|effective|implemented|recall|filed|earns|revealed|unveiled|arriv(?:e|es|ed) in (?:[A-Za-z-]+\s+){0,3}dealerships|'
    r'أعلنت|استدعاء|inaugurad|inauguró|inauguración|lanzamiento|presenta|presentati|annunciando|anunciado|'
    r'ลงนาม|เริ่ม|pemesanan|immatricolat|sottoscrit|podpisa|заключ|объяв|стартовал|reservas|superó|'
    r'発売|ra mắt|ký kết|obowiązuje|tanıtım|seri üretim|обсуждены|entrega|entró en vigencia|inaugurując|analizada|abrió|'
    r'a reçu|a effectué[^.\n]{0,100}une visite|kelishuvga erishdi|inicio de obra|serah terima|gündeme getir|adım atıyor|açılacak|z najnowszego raportu|incorporó|recibió|برگزاری نشست|آغاز|کلید خورده|صادر شده|ابلاغ|စိစစ်ထုတ်ပေး', re.I,
)
MONTH_NAMES = (
    'January|February|March|April|May|June|July|August|September|October|November|December|'
    'Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec'
)


def _entry_body(entry):
    """Return only customer-facing factual fields for editorial screening."""
    zh, en = texts(entry)
    fp = entry.get('fingerprint') or {}
    return ' '.join(str(x or '') for x in (
        zh, en, fp.get('subject'), fp.get('action'), fp.get('object'),
        fp.get('place'), fp.get('scope'), entry.get('label'),
    ))


def has_material_industry_value(entry):
    """Whether a candidate contains a durable product/industry signal.

    This is a screening aid, not a truth assertion.  A formal model launch,
    quantified network milestone, production/investment node, after-sales
    infrastructure, market statistic, or formal policy is material.
    """
    if entry.get('section') == 6 or entry.get('fingerprint', {}).get('stage') == 'data_released':
        return True
    body = _entry_body(entry)
    if NETWORK_SCALE_HINT.search(body):
        return True
    if FORMAL_PRODUCT_HINT.search(body):
        return True
    return bool(MATERIAL_INDUSTRY_HINT.search(body))


def is_low_value_retail_event(entry):
    """Return true for a promotion/discount/draw without a material node."""
    body = _entry_body(entry)
    return bool(RETAIL_LOW_VALUE_HINT.search(body)) and not has_material_industry_value(entry)


def is_display_only_event(entry):
    """Return true for an exhibition/display item without a material node."""
    body = _entry_body(entry)
    return bool(DISPLAY_ONLY_HINT.search(body)) and not bool(NON_DISPLAY_MATERIAL_HINT.search(body))


def _is_ordinary_dealer_opening(entry):
    body = _entry_body(entry)
    return bool(DEALER_OPENING_HINT.search(body)) and not has_material_industry_value(entry)


def editorial_value_errors(entry):
    """Return explicit editorial-value blockers for one candidate."""
    errors = []
    if entry.get('section') not in {2, 3, 4, 5}:
        return errors
    if is_low_value_retail_event(entry):
        errors.append('编辑价值：纯零售促销/优惠/抽奖/免费升级不得作为常规条目，请替换为产业、产品、网络或数据事实')
    if is_display_only_event(entry):
        errors.append('编辑价值：单纯车展、商场展销或静态展示不得作为常规条目，请补充正式上市或产业节点')
    if _is_ordinary_dealer_opening(entry):
        errors.append('编辑价值：普通经销店/展厅开业不得作为常规条目，请补充重大网络规模或售后基础设施价值')

    # Country slots need a concrete event.  A weaker fallback is allowed only
    # when the editor records why stronger candidates were unavailable.
    if entry.get('section') == 5 and WEAK_COUNTRY_HINT.search(_entry_body(entry)) and not has_material_industry_value(entry):
        quality = entry.get('editorial_quality') or {}
        required = ('classification', 'search_scope', 'missing_facts', 'rationale', 'signal_type')
        if quality.get('classification') != 'fallback' or any(not quality.get(k) for k in required[1:]):
            errors.append('重点国家条目偏弱：须补充具体车型/日期/项目/数据/正式政策，或记录fallback的检索范围、缺失事实、保留理由和信号类型')
    return errors


def source_outline_errors(entry):
    """Check editorial decisions and mappings, not the truth of those decisions."""
    errors=[]; outline=entry.get('source_outline') or {}
    if not all(outline.get(k) for k in ('event_type','reader_context','industry_value_after_dedup')):
        errors.append('重点覆盖：事件类型、读者必要上下文或去重后价值说明缺失')
    if outline.get('industry_relation') != 'direct':
        errors.append('产业关联：须有直接汽车业务关联；fallback不能豁免')
    points=outline.get('points')
    if not isinstance(points,list) or not points:
        return errors+['重点覆盖：缺少来源信息点清单']
    ids=set(); covered=set(); mains=0
    atoms={a.get('id') for a in entry.get('atoms',[])}
    for point in points:
        pid=point.get('id'); role=point.get('role'); decision=point.get('decision')
        if not pid or pid in ids:errors.append('重点覆盖：信息点ID为空或重复')
        ids.add(pid)
        if not point.get('text') or role not in {'main','key','condition','background','nonessential'}:
            errors.append('重点覆盖：信息点内容或层级缺失')
        refs=point.get('atom_ids',[])
        if decision=='included':
            if not refs or not set(refs).issubset(atoms):errors.append('重点覆盖：纳入点未映射有效事实原子')
            covered.update(refs)
            if role=='main':mains+=1
        elif decision=='excluded':
            if refs or not point.get('reason') or point.get('exclusion_kind') not in {'duplicate','outside_event','nonessential','unsupported'}:
                errors.append('重点覆盖：排除点须登记类型、理由且不能映射正文')
            if role=='main':errors.append('重点覆盖：事件主线不得排除后仍作为合格条目')
        else:errors.append('重点覆盖：存在未处理的信息点')
    if not mains:errors.append('重点覆盖：没有纳入事件主线')
    if covered!=atoms:errors.append('重点覆盖：正文原子未被来源信息点完整覆盖')
    return errors


def stage_consistency_errors(entry):
    """Prevent planned text from being rendered as a completed stage."""
    errors = []
    stage = (entry.get('fingerprint') or {}).get('stage', '')
    zh, en = texts(entry)
    body = f'{zh} {en}'
    if stage in {'announced', 'planned', 'mou', 'signed', 'proposed', 'draft', 'under_review'}:
        actual_match = None
        for match in ACTUAL_STAGE_HINT.finditer(body):
            prefix = body[max(0, match.start() - 18):match.start()]
            # A negative disclosure such as “尚未公布正式上市日期” is not
            # an assertion that the model has launched.
            if re.search(r'尚未|未(?:有|公布|宣布|开始)|没有|not disclosed|not announced|not yet|has not', prefix, re.I):
                continue
            actual_match = match
            break
        if actual_match:
            errors.append('阶段：计划/拟议条目含已开工、已投产、已上市或已交付等完成态表述')
    if PRELIMINARY_CONSTRUCTION_HINT.search(body) and re.search(
        r'正式开工|已开工|开工建设|construction has begun|construction started|construction begins',
        body, re.I,
    ):
        errors.append('阶段：前期建设/场地准备不得同时写成正式开工')
    return errors


def statistical_scope_errors(entry):
    """Require paired year/production scopes when a data item compares them."""
    if (entry.get('fingerprint') or {}).get('stage') != 'data_released':
        return []
    zh, en = texts(entry)
    body = f'{zh} {en}'
    current_scope = re.search(
        r'(?:当年|本年|今年)[^。；，,]{0,24}(?:生产|制造)|'
        r'produced .* this year|year-of-production', body, re.I,
    )
    all_year_scope = re.search(r'全部生产年份|不限定生产年份|按全部(?:生产)?年份|all production years|regardless of production year', body, re.I)
    multi_scope_signal = re.search(
        r'同一期间|同期|总计|合计|其中|same period|total(?:ed)?|including', body, re.I,
    ) and len(re.findall(r'生产|产量|生产的|produced|production|vehicles', body, re.I)) >= 2
    if not (current_scope and (all_year_scope or multi_scope_signal)):
        return []
    errors = []
    if not current_scope:
        errors.append('统计口径：缺少“当年生产”范围说明')
    if not all_year_scope:
        errors.append('统计口径：缺少“全部生产年份”范围说明')
    if entry.get('section') == 6 and not (entry.get('event') or {}).get('statistical_period'):
        errors.append('统计口径：多范围数据缺少统计期')
    return errors


def _date_tokens(value):
    """Return date spellings that may appear in an evidence excerpt."""
    try:
        d = date.fromisoformat(str(value))
    except (TypeError, ValueError):
        return []
    tokens = [
        d.isoformat(),
        f'{d.year}/{d.month}/{d.day}', f'{d.year}-{d.month}-{d.day}',
        f'{d.day:02d}.{d.month:02d}.{d.year}', f'{d.day}.{d.month}.{d.year}',
        f'{d.year}年{d.month}月{d.day}日', f'{d.year}年{d.month}月{d.day}号',
        f'{d.month}月{d.day}日', f'{d.month}月{d.day}号',
        d.strftime(f'%B {d.day}, %Y'), d.strftime(f'%b {d.day}, %Y'),
        d.strftime(f'%B {d.day} %Y'), d.strftime(f'%b {d.day} %Y'),
        d.strftime(f'%b. {d.day}, %Y'), d.strftime(f'%b. {d.day} %Y'),
        d.strftime(f'{d.day} %B %Y'), d.strftime(f'{d.day} %b %Y'),
        d.strftime(f'{d.day} %B, %Y'), d.strftime(f'{d.day} %b. %Y'),
        d.strftime(f'{d.day}-%b-%Y'),
        f'{d.day:02d}/{d.month:02d}/{d.year}',
        f'{d.day}/{d.month}/{d.year}',
        f'{d.month:02d}/{d.day:02d}/{d.year}',
        f'{d.month}/{d.day}/{d.year}',
        f'Ngày {d.day}/{d.month}',
        f'{d.day}-{d.month}-{d.year}',
        f'{d.day:02d}-{d.month:02d}-{d.year}',
        f'{d.year}.{d.month:02d}.{d.day:02d}',
        d.strftime(f'%B {d.day}'), d.strftime(f'%b {d.day}'),
        d.strftime(f'%b. {d.day}'), d.strftime(f'{d.day} %B'),
        d.strftime(f'{d.day} %b'), d.strftime(f'{d.day} %b.'),
        f'ngày {d.day} tháng {d.month} năm {d.year}',
    ]
    # These are spelling variants only. The action/date relationship still
    # requires reading the cited passage and recording the semantic review.
    month_names = {
        'es': ['enero','febrero','marzo','abril','mayo','junio','julio','agosto','septiembre','octubre','noviembre','diciembre'],
        'pt': ['janeiro','fevereiro','março','abril','maio','junho','julho','agosto','setembro','outubro','novembro','dezembro'],
        'id': ['Januari','Februari','Maret','April','Mei','Juni','Juli','Agustus','September','Oktober','November','Desember'],
        'ar': ['يناير','فبراير','مارس','أبريل','مايو','يونيو','يوليو','أغسطس','سبتمبر','أكتوبر','نوفمبر','ديسمبر'],
        'th': ['มกราคม','กุมภาพันธ์','มีนาคม','เมษายน','พฤษภาคม','มิถุนายน','กรกฎาคม','สิงหาคม','กันยายน','ตุลาคม','พฤศจิกายน','ธันวาคม'],
        'ru': ['января','февраля','марта','апреля','мая','июня','июля','августа','сентября','октября','ноября','декабря'],
        'pl': ['stycznia','lutego','marca','kwietnia','maja','czerwca','lipca','sierpnia','września','października','listopada','grudnia'],
        'it': ['gennaio','febbraio','marzo','aprile','maggio','giugno','luglio','agosto','settembre','ottobre','novembre','dicembre'],
        'tr': ['Ocak','Şubat','Mart','Nisan','Mayıs','Haziran','Temmuz','Ağustos','Eylül','Ekim','Kasım','Aralık'],
        'fr': ['janvier','février','mars','avril','mai','juin','juillet','août','septembre','octobre','novembre','décembre'],
    }
    for language, names in month_names.items():
        month = names[d.month - 1]
        year = d.year + 543 if language == 'th' else d.year
        tokens.extend([f'{d.day} {month} {year}', f'{d.day} {month} ,{year}',
                       f'{d.day} de {month} de {year}', f'{d.day} de {month} del {year}',
                       f'{d.day} de {month} {year}'])
        tokens.extend([f'{d.day} {month}', f'{d.day} de {month}',
                       f'{month} {d.day}, {year}', f'{month} {d.day} {year}',
                       f'{month} {d.day}, {year}'])
        if language == 'th':
            # Thai sources also use Gregorian years alongside Buddhist years.
            tokens.append(f'{d.day} {month} {d.year}')
    return tokens


def _citation_has_date(citation, value):
    quote = str(citation.get('quote', ''))
    # Myanmar and Arabic decimal digits retain their calendar value.
    quote = ''.join(str(unicodedata.decimal(c)) if c.isdecimal() else c for c in quote)
    # Keep numeric tokens on adjacent lines separate before norm removes
    # whitespace (e.g. a year followed by the page's comment count).
    quote = re.sub(r'(?<=\d)\s+(?=\d)', ' · ', quote)
    q = norm(quote)
    if any(re.search(r'(?<!\d)' + re.escape(norm(token)) +
                     (r'(?!\d)' if norm(token)[-1:].isdigit() else ''), q)
           for token in _date_tokens(value)):
        return True
    # Explicit Spanish date ranges preserve both endpoints. A page timestamp
    # alone still cannot establish the business action or its date.
    try:
        d = date.fromisoformat(value)
        names = ['enero','febrero','marzo','abril','mayo','junio','julio','agosto','septiembre','octubre','noviembre','diciembre']
        for match in re.finditer(r'\bdel?\s+(\d{1,2})\s+al\s+(\d{1,2})\s+de\s+(\w+)\s+de\s+(\d{4})', quote, re.I):
            first,last,month,year=match.groups()
            if int(year)==d.year and month.lower()==names[d.month-1] and d.day in {int(first),int(last)}:
                return True
    except (TypeError,ValueError):
        pass
    return False


def event_date_evidence_errors(root, entry, matrix):
    """Ensure the event date is supported by event-date evidence, not metadata."""
    errors = []
    event = entry.get('event') or {}
    event_date = event.get('date')
    basis = event.get('date_basis') or []
    if not event_date:
        return ['时效：实际事件日期未填写，日期不清的候选可留在线索池但不能进入交付槽位']
    supporting = [c for c in basis if _citation_has_date(c, event_date)]
    # Relative weekdays require an independently cited publication anchor;
    # a date supplied by the editor alone must never satisfy this check.
    resolution = event.get('date_resolution') or {}
    if resolution.get('mode') == 'relative' and (not supporting or not any(
            EVENT_DATE_ACTION_HINT.search(str(c.get('quote',''))) for c in supporting)):
        try:
            reported = date.fromisoformat(event['reported_date'])
            resolved = date.fromisoformat(event_date)
            term = resolution['term']
            delta = (reported - resolved).days
            weekdays = {name.lower(): n for n, name in enumerate(
                ('Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'))}
            valid = ((term.lower() in ('yesterday', 'ayer', 'أمس') and delta == 1) or
                     (term.lower() in ('today', 'hoy') and delta == 0) or
                     (term.lower() in weekdays and 0 <= delta <= 6 and
                      resolved.weekday() == weekdays[term.lower()]))
            anchor = any(_citation_has_date(c, event['reported_date']) for c in basis)
            if valid and anchor and resolution.get('rationale'):
                supporting = [c for c in basis if re.search(r'\b' + re.escape(term) + r'\b', c.get('quote', ''), re.I)]
        except (KeyError, ValueError, TypeError):
            pass
    if not supporting and resolution.get('mode') == 'calendar':
        # Solar-Hijri dates are checked as a numeric Julian-day conversion.
        try:
            import jdatetime
            y, mo, day = map(int, resolution['source_date'].split('-'))
            converted = jdatetime.date(y, mo, day).togregorian().isoformat()
            if converted == event_date and resolution.get('calendar') == 'Solar Hijri':
                supporting = [c for c in basis if norm(resolution['source_literal']) in norm(c.get('quote', ''))]
        except (ImportError, KeyError, TypeError, ValueError):
            pass
    if not supporting:
        errors.append('时效：事件日期摘录未出现实际事件日，不能用文章发布日期/转载日期替代')
        return errors
    has_event_action = False
    publication_only = True
    for citation in supporting:
        quote = str(citation.get('quote', ''))
        if EVENT_DATE_ACTION_HINT.search(quote):
            has_event_action = True
        if not PUBLICATION_DATE_ONLY_HINT.search(quote) or EVENT_DATE_ACTION_HINT.search(quote):
            publication_only = False
    # A date tied only to repost/update/report metadata is not an event date.
    if publication_only or not has_event_action:
        errors.append('时效：事件日期依据只证明发布日期/转载日期，未证明实际事件发生日或数据发布日')
    if event.get('reported_date') and event.get('reported_date') != event_date:
        reported_support = any(_citation_has_date(c, event.get('reported_date')) for c in basis)
        if reported_support and not supporting:
            errors.append('时效：近期报道日期与实际事件日未区分，禁止按转载日期计算窗口')
    return errors


def timeliness_errors(root, entry, matrix):
    """Check the rolling event window separately from publication deduplication."""
    errors = []
    try:
        t = date.fromisoformat(matrix['report_date'])
        ev = date.fromisoformat(entry['event']['date'])
    except (KeyError, TypeError, ValueError):
        return ['时效：实际事件日期无法核准，不能交付']
    if not t - timedelta(days=29) <= ev <= t:
        errors.append('时效：实际事件日超出30天窗口，报道/转载日期不能替代事件日')
    try:
        reported = date.fromisoformat(entry['event']['reported_date'])
        if reported > t:
            errors.append('时效：报道日期在业务日之后')
    except (KeyError, TypeError, ValueError):
        errors.append('时效：报道日期无精确有效锚点')
    try:
        target = entry['event'].get('target_date')
        if target:
            date.fromisoformat(target)
    except (TypeError, ValueError):
        errors.append('时效：未来目标日期格式无效')
    return errors


def recent_local_duplicate_errors(root, entry, matrix):
    """Block exact core-fingerprint repeats from the two latest local releases."""
    try:
        t = date.fromisoformat(matrix['report_date'])
    except (KeyError, TypeError, ValueError):
        return []
    fp = entry.get('fingerprint') or {}
    current = tuple(norm(fp.get(k, '')) for k in ('subject', 'action', 'object', 'place')) + (norm(entry.get('event', {}).get('date', '')),)
    if not all(current):
        return []
    duplicates = []
    for path in sorted((Path(root) / 'output').glob('*/正式交付/release.json')):
        try:
            release = load(path)
            published_day = date.fromisoformat(release['report_date'])
        except (KeyError, TypeError, ValueError, OSError):
            continue
        if published_day not in {t - timedelta(days=1), t - timedelta(days=2)}:
            continue
        for old in release.get('events', []):
            old_fp = old.get('fingerprint') or {}
            old_core = tuple(norm(old_fp.get(k, '')) for k in ('subject', 'action', 'object', 'place')) + (norm(old.get('event_date', '')),)
            if old_core == current:
                duplicates.append(f'{release["report_date"]}/{old.get("candidate_id", "unknown")}')
    if duplicates:
        return ['近期本地重复：与T-1/T-2正式交付核心事实重复（' + '、'.join(duplicates) + '），须替换或证明实质新节点']
    return []

def numeric_mapping_errors(cn,en,mappings):
    # Calendar dates are represented differently in Chinese and English
    # (month/day versus a named month). They are checked by date_basis, so
    # remove only the leading date expression before comparing other figures.
    def without_leading_date(text):
        text = re.sub(r'^\s*(?:On\s+)?(?:\d{1,2}\s+)?(?:January|February|March|April|May|June|July|August|September|October|November|December|Jan\.?|Feb\.?|Mar\.?|Apr\.?|Jun\.?|Jul\.?|Aug\.?|Sep\.?|Sept\.?|Oct\.?|Nov\.?|Dec\.?)\s+\d{1,2}(?:,?\s+\d{4})?', '', text, flags=re.I)
        text = re.sub(r'^\s*\d{1,4}年\d{1,2}月\d{1,2}日[，,：:]?', '', text)
        text = re.sub(r'^\s*\d{1,2}月\d{1,2}日[，,：:]?', '', text)
        return text
    cn_core, en_core = without_leading_date(cn), without_leading_date(en)
    # Chinese ten-thousand units and English full-unit currency/quantity
    # spellings carry the same value but different digit strings.
    cn_core = re.sub(r'(\d+(?:\.\d+)?)万', lambda m: str(float(m.group(1))*10000).rstrip('0').rstrip('.'), cn_core)
    cn_core = re.sub(r'(\d+(?:\.\d+)?)亿', lambda m: str(float(m.group(1))*100000000).rstrip('0').rstrip('.'), cn_core)
    en_core = re.sub(r'(?i)(\d+(?:\.\d+)?)\s*billion', lambda m: str(float(m.group(1))*1000000000).rstrip('0').rstrip('.'), en_core)
    en_core = re.sub(r'(?i)(\d+(?:\.\d+)?)\s*million', lambda m: str(float(m.group(1))*1000000).rstrip('0').rstrip('.'), en_core)
    cn_nums, en_nums = numbers(cn_core), numbers(en_core)
    if cn_nums==en_nums and not mappings: return []
    errors=[]; mapped_cn=[]; mapped_en=[]
    for mapping in mappings:
        if not all(mapping.get(k) for k in ['zh','en','unit_zh','unit_en','scope','rationale']): errors.append('数值映射不完整')
        if mapping.get('zh','') not in cn or mapping.get('en','') not in en: errors.append('数值映射未出现在中英正文')
        mapped_cn+=numbers(mapping.get('zh','')); mapped_en+=numbers(mapping.get('en',''))
    # Mapping strings quote the original text, so coverage must use the same
    # original units. Comparing raw "21.98" against converted "219800"
    # incorrectly rejects an explicit, valid 万元/yuan mapping.
    raw_cn, raw_en = numbers(without_leading_date(cn)), numbers(without_leading_date(en))
    if Counter(mapped_cn)!=Counter(raw_cn) or Counter(mapped_en)!=Counter(raw_en): errors.append('数值映射未完整覆盖正文数字，不能以一项映射跳过全部核对')
    return errors

def history_data(root, matrix, check_fresh=True):
    ref=matrix['history']; manifest_path=local(root,ref['manifest'])
    if file_hash(manifest_path)!=ref['sha256']: raise ValueError('历史manifest绑定失效')
    manifest=load(manifest_path)
    if manifest.get('mode') == 'local_roll30':
        if manifest.get('epoch') != ref.get('epoch'): raise ValueError('本地历史epoch不匹配')
        tables={}
        for name,item in manifest.get('files',{}).items():
            path=local(root,item['path'])
            if file_hash(path)!=item['sha256']: raise ValueError('本地历史CSV哈希失效')
            tables[name]=read_csv(path.read_bytes(), allow_empty=name=='新增表')
        if '事件索引' not in tables: raise ValueError('本地事件索引缺失')
        records=[dict(zip(tables['事件索引'][0],row)) for row in tables['事件索引'][1:] if any(row)]
        if '新增表' in tables:
            records.extend(dict(zip(tables['新增表'][0],row)) for row in tables['新增表'][1:] if any(row))
        if check_fresh is True:
            target=date.fromisoformat(matrix['report_date']); start=target-timedelta(days=30); end=target-timedelta(days=1)
            records=[r for r in records if start <= date.fromisoformat(r.get('日报日期','')) <= end]
            dates={date.fromisoformat(r['日报日期']) for r in records if r.get('日报日期')}
            expected={start+timedelta(days=n) for n in range(30)}
            if not expected.issubset(dates): raise ValueError('本地历史窗口不完整')
        return manifest,records
    if manifest['certificate']['history_epoch']!=ref['epoch']: raise ValueError('历史epoch不匹配')
    tables={}
    for name,item in manifest['files'].items():
        path=local(root,item['path'])
        if file_hash(path)!=item['sha256']: raise ValueError('历史CSV哈希失效')
        tables[name]=read_csv(path.read_bytes())
    certificate={r[0]:r[1] for r in tables['运行摘要'] if len(r)>=2 and r[0]}
    if certificate!=manifest['certificate']: raise ValueError('证书与原始CSV不一致')
    validate_history_tables(tables['去重轻索引'],tables['事件索引'],certificate,matrix['report_date'])
    if check_fresh:
        fetched=datetime.fromisoformat(manifest['fetched_at'])
        age=datetime.now(TZ)-fetched
        if fetched.tzinfo is None or not timedelta(minutes=-5)<=age<=timedelta(hours=24): raise ValueError('历史读取已过期或时间异常，请重新拉取并复核')
    records=[dict(zip(tables['事件索引'][0],row)) for row in tables['事件索引'][1:] if any(row)]
    return manifest,records

def local_publications(root, matrix):
    """Derived from local signed-off manifests; no remote write or shared state."""
    t=date.fromisoformat(matrix['report_date']); result=[]; bindings=[]
    for path in sorted((Path(root)/'output').glob('*/正式交付/release.json')):
        record=load(path); day=date.fromisoformat(record['report_date'])
        if t-timedelta(days=30)<=day<t:
            bindings.append({'path':str(path.relative_to(root)).replace('\\','/'),'sha256':file_hash(path)})
            for e in record['events']:
                result.append({'日报日期':str(day),'主体/国家':e['fingerprint']['subject'],'车型/项目/政策名':e['fingerprint']['object'],
                  '核心动作':e['zh'],'事件指纹':e['candidate_id'],'事件日期':e['event_date'],'来源':'local_release'})
    return result,bindings

def _entry_revision(entry):
    """Digest factual entry content, excluding review artifacts."""
    return digest({k:v for k,v in entry.items()
                   if k not in {'history_review','semantic_review','cross_section_review'}})

def _history_report_reusable(root, entry, matrix, remote_count, local_refs):
    """Check whether a saved shortlist report still matches its inputs."""
    history = entry.get('history_review') or {}
    try:
        report_path = local(root, history['report'])
        if file_hash(report_path) != history['report_sha256']:
            return False
        report = load(report_path)
        return (report.get('entry_content_sha256') == _entry_revision(entry)
                and report.get('history') == matrix['history']
                and report.get('remote_rows_scanned') == remote_count
                and report.get('local_publications') == local_refs)
    except (KeyError, OSError, ValueError, TypeError):
        return False

def _history_source_changed(root, entry, matrix, remote_count, local_refs):
    """Detect a shared history-input change separately from entry edits."""
    history = entry.get('history_review') or {}
    try:
        report_path = local(root, history['report'])
        if file_hash(report_path) != history.get('report_sha256'):
            return True
        report = load(report_path)
        return (report.get('history') != matrix.get('history') or
                report.get('remote_rows_scanned') != remote_count or
                report.get('local_publications') != local_refs)
    except (KeyError, OSError, ValueError, TypeError):
        return True

def history_shortlist(root, matrix):
    manifest,remote=history_data(root,matrix); published,local_refs=local_publications(root,matrix)
    # A just-published release may already be present in the local additions
    # table.  Compare each historical fact once while retaining its source
    # row for audit output.
    all_rows=[]; seen=set()
    for row in remote+published:
        key=tuple(norm(row.get(k,'')) for k in ('日报日期','主体/国家','车型/项目/政策名','核心动作','事件日期'))
        if key in seen: continue
        seen.add(key); all_rows.append(row)
    reusable={e['candidate_id']:_history_report_reusable(root,e,matrix,len(remote),local_refs)
              for e in matrix['entries']}
    old_bindings=matrix.get('cross_section_bindings') or {}
    prior_reports={e['candidate_id']:bool((e.get('history_review') or {}).get('report'))
                   for e in matrix['entries']}
    changed={e['candidate_id'] for e in matrix['entries']
             if not reusable[e['candidate_id']]
             or (e['candidate_id'] in old_bindings
                 and old_bindings[e['candidate_id']] != _entry_revision(e))}
    # A changed history snapshot or local publication set invalidates all
    # history reports.  Entry-only edits invalidate only that entry and the
    # cross-section comparisons that mention it.
    history_changed = any(_history_source_changed(root,e,matrix,len(remote),local_refs)
                          for e in matrix['entries'])
    if history_changed:
        changed={e['candidate_id'] for e in matrix['entries']}
    for entry in matrix['entries']:
        if reusable[entry['candidate_id']]:
            continue
        fp=entry['fingerprint']; terms=[fp.get('subject',''),fp.get('object',''),fp.get('place',''),*fp.get('aliases',[])]
        terms=[x for x in terms if x]
        candidate=norm(' '.join([fp.get(k,'') for k in ['subject','action','object','place']]))
        scored=[]
        for i,row in enumerate(all_rows,1):
            text=' '.join(row.get(k,'') for k in ['主体/国家','车型/项目/政策名','核心动作','事件日期','地点','关键数字'])
            matched=[term for term in terms if norm(term) in norm(text)]
            score=SequenceMatcher(None,candidate,norm(text),autojunk=False).ratio()+len(matched)*0.2
            scored.append({'row_number':i,'score':round(score,4),'matched_terms':matched,'record':row})
        scored.sort(key=lambda x:x['score'],reverse=True)
        report={'candidate_id':entry['candidate_id'],'history':matrix['history'],'entry_content_sha256':_entry_revision(entry),
          'remote_rows_scanned':len(remote),'local_rows_scanned':len(published),'local_publications':local_refs,'search_terms':terms,
          'method':'全行字符相似度与主体/对象/地点/别名检索；排序不是语义无重复结论','matches':scored[:30],
          'full_history_artifact':matrix['history']['manifest'],'generated_at':now()}
        path=Path(root)/'history'/matrix['report_date']/'comparisons'/(entry['candidate_id']+'.json')
        if not re.fullmatch(r'[A-Za-z0-9_-]+',entry['candidate_id']): raise ValueError('候选ID只用英文数字_-')
        save(path,report)
        entry['history_review']={'result':'pending','report':str(path.relative_to(root)).replace('\\','/'),'report_sha256':file_hash(path),
          'search_terms':terms,'comparisons':[],'rationale':'','full_window_semantic_checked':False}
        entry['semantic_review']={}
    for entry in matrix['entries']:
        cross=entry.get('cross_section_review') or {}
        if (old_bindings or cross.get('content_bindings') or
            prior_reports.get(entry['candidate_id'])) and (
                entry['candidate_id'] in changed or changed.intersection(cross.get('compared_ids', []))):
            entry['cross_section_review']={}
        elif (cross.get('compared_ids') and not cross.get('content_bindings')
              and (old_bindings or any(prior_reports.values()))):
            # Legacy comparisons have no proof of which candidate versions
            # were compared; force one real re-review instead of upgrading
            # them silently.
            entry['cross_section_review']={}
    if changed:
        matrix['qa']={}
    matrix['cross_section_bindings']={e['candidate_id']:_entry_revision(e) for e in matrix['entries']}
    return matrix

def evidence_errors(root, entry):
    errors=[]; sources={}; artifacts={}
    for source in entry.get('sources',[]):
        sid=source.get('id','')
        if not sid or sid in sources: errors.append('信源ID缺失/重复'); continue
        sources[sid]=source
        try:
            path=local(root,source['artifact'])
            if file_hash(path)!=source['artifact_sha256']: raise ValueError('信源artifact哈希失效')
            artifact=load(path); textpath=local(root,artifact['text_path'])
            if file_hash(textpath)!=artifact['text_sha256']: raise ValueError('证据正文哈希失效')
            text=textpath.read_text(encoding='utf-8')
            if len(text.strip())<40: raise ValueError('证据正文过短/为空')
            if source.get('tier') not in {'official','trusted_secondary','attributed_secondary'}: raise ValueError('来源等级未复核')
            if not source.get('publisher') or not source.get('origin_key') or not source.get('scope'): raise ValueError('出版机构/同源起源/可支持事实范围缺失')
            if source.get('content_reviewed') is not True: raise ValueError('未确认读到完整相关正文')
            if source.get('tier')=='attributed_secondary' and not source.get('attribution'): raise ValueError('降级转述未记录据何处报道')
            if artifact['kind']=='web':
                if artifact.get('access_flags'): raise ValueError('网页有拦截/付费墙/解码标记，请使用可读证据重新抓取')
                if source.get('url') not in {artifact.get('url'),artifact.get('final_url')}: raise ValueError('实际URL未绑定')
                rawpath=path.parent/'response.html'
                if file_hash(rawpath)!=artifact['raw_sha256']: raise ValueError('网页原始响应哈希失效')
            elif artifact['kind']=='pdf':
                if artifact.get('errors'): raise ValueError('PDF提取存在未解决错误')
                if file_hash(local(root,artifact['archived_pdf']))!=artifact['pdf_sha256']: raise ValueError('PDF原件哈希失效')
                if source.get('page')!=artifact['page']: raise ValueError('PDF页码绑定错误')
                if not source.get('publisher_verified') or not artifact.get('publication_date'): raise ValueError('PDF机构/出版日期未确认')
                if artifact['method']=='ocr' and source.get('visual_checked') is not True: raise ValueError('OCR证据未回看原页')
            else: raise ValueError('不支持的证据类型')
            artifacts[sid]=(artifact,text)
        except (KeyError,ValueError,OSError) as e: errors.append(f'信源{sid}: {e}')
    if not sources: errors.append('没有实际信源')
    def citation_errors(citations, label):
        if not citations: errors.append(label+'缺少摘录'); return
        for cite in citations:
            sid=cite.get('source_id'); quote=cite.get('quote','')
            if sid not in artifacts: errors.append(label+'信源不可用'); continue
            artifact,text=artifacts[sid]
            if len(quote.strip())<6 or norm(quote) not in norm(text): errors.append(label+'摘录不在实际证据正文')
            if not cite.get('locator'): errors.append(label+'未标注段落/页码定位')
    citation_errors(entry.get('event',{}).get('date_basis',[]),'事件日期')
    atom_ids=[]
    for atom in entry.get('atoms',[]):
        atom_ids.append(atom.get('id'))
        if not atom.get('id') or not atom.get('zh') or not atom.get('en'): errors.append('事实原子ID/中英文缺失')
        citation_errors(atom.get('evidence',[]),'事实'+str(atom.get('id')))
        stage=atom.get('stage')
        if stage not in STAGES: errors.append('事实阶段未登记')
        # Same node in the selected quote must be attested explicitly, including future/draft state.
        if atom.get('supported_stage')!=stage: errors.append('原文阶段与正文阶段不一致')
        cn,en=atom.get('zh',''),plain(atom.get('en',''))
        errors+=numeric_mapping_errors(cn,en,atom.get('number_mappings',[]))
        for word in re.findall(HIGH_RISK,cn):
            proofs=atom.get('high_risk_evidence',{})
            if word not in proofs: errors.append('高风险词无单独依据: '+word)
            else: citation_errors(proofs[word],'高风险词'+word)
        for txt in [cn,en]:
            if re.search(INTERNAL,txt,re.I): errors.append('正文有链接/内部标记')
            if '\n' in txt: errors.append('单条正文不能插入新段落')
    if not atom_ids or len(atom_ids)!=len(set(atom_ids)): errors.append('事实原子为空/ID重复')
    for point in (entry.get('source_outline') or {}).get('points',[]):
        citation_errors(point.get('evidence',[]),'来源信息点'+str(point.get('id')))
    return errors

def semantic_binding_errors(entry,matrix):
    errors=[]; review=entry.get('semantic_review',{})
    if review.get('binding')!=entry_binding(entry,matrix): errors.append('逐条语义复核不存在或已失效')
    for key in CHECKS:
        item=review.get('checks',{}).get(key,{})
        if item.get('result')!='pass' or not item.get('note'): errors.append('语义复核未通过: '+key)
    if not review.get('reviewer') or not review.get('reviewed_at'): errors.append('复核身份/时间缺失')
    return errors

def entry_errors(root, entry, matrix, remote_count=None, require_review=True):
    errors=evidence_errors(root,entry)
    errors += timeliness_errors(root, entry, matrix)
    errors += event_date_evidence_errors(root, entry, matrix)
    errors += recent_local_duplicate_errors(root, entry, matrix)
    fp=entry.get('fingerprint',{})
    if not all(fp.get(k) for k in ['subject','action','object','place','stage','scope']): errors.append('事实指纹不完整')
    if fp.get('stage') not in STAGES: errors.append('主体阶段未登记')
    if entry.get('decision')!='keep': errors.append('最终决定不是保留')
    if entry.get('source_status') not in {'一手验证','可信二手支持','降级转述'}: errors.append('核验状态未填写')
    if not all(entry.get('relevance',{}).get(k) for k in ['kind','rationale']): errors.append('槽位关联/新闻价值未说明')
    if entry.get('section')==2 and entry.get('relevance',{}).get('kind') not in {'overseas','major_domestic'}: errors.append('第二部分普通国内事件不得充数')
    policy=entry.get('policy',{})
    if not isinstance(policy.get('is_policy'),bool) or not policy.get('rationale'): errors.append('政策分类未核对')
    if policy.get('is_policy') and policy.get('stage') not in STAGES: errors.append('政策程序状态缺失')
    zh,en=texts(entry)
    errors+=editorial_value_errors(entry)
    errors+=source_outline_errors(entry)
    errors+=stage_consistency_errors(entry)
    errors+=statistical_scope_errors(entry)
    if re.search(POLICY_HINT,zh) and policy.get('is_policy') is not True and not policy.get('exclusion_rationale'): errors.append('正文含政策事实，须计入或解释非政策语境')
    if entry.get('section')==6:
        stats=entry.get('statistics',{})
        if not entry.get('event',{}).get('statistical_period') or not all(stats.get(k) for k in ['publisher','market','metric','unit','scope']): errors.append('数据统计期/机构/市场/指标/单位/口径缺失')
    history=entry.get('history_review',{})
    try:
        report_path=local(root,history['report'])
        if file_hash(report_path)!=history['report_sha256']: raise ValueError('历史比较报告绑定失效')
        report=load(report_path)
        current=digest({k:v for k,v in entry.items() if k not in {'history_review','semantic_review','cross_section_review'}})
        if report['entry_content_sha256']!=current or report['history']!=matrix['history']: raise ValueError('正文/来源/历史变化，须重做历史比较')
        if remote_count is not None and report['remote_rows_scanned']!=remote_count: raise ValueError('未扫描当前全部历史')
        _,refs=local_publications(root,matrix)
        if refs!=report['local_publications']: raise ValueError('本地发布记录变化，须重做历史比较')
        if history.get('result') not in {'no_duplicate','new_milestone'}: raise ValueError('历史语义判定未通过')
        if history.get('full_window_semantic_checked') is not True: raise ValueError('未完成整个窗口的语义核查')
        if not history.get('search_terms') or not history.get('rationale'): raise ValueError('历史查询和判定依据缺失')
        if not history.get('comparisons'): raise ValueError('历史邻近事实比较缺失，不接受模板无重复')
        for comparison in history['comparisons']:
            if not all(comparison.get(k) for k in ['row_number','published_date','historical_fact','difference']): raise ValueError('历史比较缺ID/日期/事实/实质差异')
            rownum=comparison['row_number']
            candidates={x['row_number']:x for x in report['matches']}
            if rownum not in candidates: raise ValueError('比较行不在已保存候选中')
            row=candidates[rownum]['record']
            if comparison['published_date']!=row['日报日期'] or norm(comparison['historical_fact'])!=norm(row['核心动作']): raise ValueError('历史比较内容与实际记录不一致')
        if history['result']=='new_milestone':
            proofs=history.get('new_milestone_evidence',[])
            if not proofs: raise ValueError('新增节点未绑定证据')
            sources={s['id']:s for s in entry['sources']}
            for proof in proofs:
                source=sources.get(proof.get('source_id'))
                if not source or not proof.get('quote') or not proof.get('locator'): raise ValueError('新增证据无信源/摘录/定位')
                art=load(local(root,source['artifact'])); raw=local(root,art['text_path']).read_text(encoding='utf-8')
                if norm(proof['quote']) not in norm(raw): raise ValueError('新增节点摘录不在原文')
    except (KeyError,ValueError,OSError) as e: errors.append('历史: '+str(e))
    cross=entry.get('cross_section_review',{})
    expected={x['candidate_id'] for x in matrix['entries'] if x['candidate_id']!=entry['candidate_id']}
    if set(cross.get('compared_ids',[]))!=expected or cross.get('conflicts') or not cross.get('rationale'): errors.append('未完成全稿跨栏事实比较/存在冲突')
    bindings=cross.get('content_bindings',{})
    if bindings:
        current={x['candidate_id']:_entry_revision(x) for x in matrix['entries']}
        if any(bindings.get(cid)!=current.get(cid) for cid in expected):
            errors.append('跨栏比较绑定的候选内容已变化，须重做比较')
    else:
        # Synthetic/older matrices may have a matrix-level snapshot created
        # by history_shortlist but no per-entry bindings.  Accept that legacy
        # form only while every candidate still matches the snapshot; newly
        # recorded comparisons use the stronger per-entry bindings above.
        snapshot=matrix.get('cross_section_bindings') or {}
        if cross.get('compared_ids') and cross.get('reviewed_at'):
            if not snapshot or any(snapshot.get(cid)!=current.get(cid) for cid in expected):
                errors.append('跨栏比较缺少候选内容绑定，须重做比较')
    if require_review:
        errors+=semantic_binding_errors(entry,matrix)
    return errors

def validate_matrix(root, matrix, require_qa=True):
    errors=[]; t=matrix.get('report_date','')
    try: date.fromisoformat(t)
    except ValueError: errors.append('业务日期格式错误')
    if matrix.get('schema_version')!=1 or matrix.get('timezone')!='Asia/Shanghai': errors.append('矩阵schema/时区错误')
    if matrix.get('rules_sha256')!=policy_hash(root): errors.append('活动规则已变化，须复核')
    remote_count=None
    try: _,remote=history_data(root,matrix); remote_count=len(remote)
    except (KeyError,ValueError,OSError) as e: errors.append('历史快照: '+str(e))
    entries=matrix.get('entries',[]); ids=[e.get('candidate_id') for e in entries]
    if not all(ids) or len(set(ids))!=len(ids): errors.append('候选ID为空/重复')
    expected={x['id']:x for x in slots()}; actual=[e.get('slot') for e in entries if e.get('section')!=6]
    if Counter(actual)!=Counter(expected.keys()): errors.append('48固定槽位未完整且唯一覆盖')
    data=[e for e in entries if e.get('section')==6]
    if not 3<=len(data)<=5: errors.append('数据条目须为3—5条')
    if len(set(e.get('slot') for e in data))!=len(data) or any(not re.fullmatch(r'S6-0[1-5]',e.get('slot','')) for e in data): errors.append('数据槽位不唯一/非法')
    policy_count=sum(e.get('policy',{}).get('is_policy') is True for e in entries)
    if policy_count>12: errors.append('政策条目超过12条')
    seen_fingerprints={}
    for entry in entries:
        eid=entry.get('candidate_id','?'); slot=entry.get('slot')
        if slot in expected and (entry.get('section'),entry.get('label'))!=(expected[slot]['section'],expected[slot]['label']): errors.append(eid+': 槽位对象/板块错误')
        fp=entry.get('fingerprint',{}); key=norm(' '.join(str(fp.get(k,'')) for k in ['subject','action','object','place','stage']))
        if key and key in seen_fingerprints: errors.append(eid+': 同稿事实指纹与'+seen_fingerprints[key]+'重复')
        seen_fingerprints[key]=eid
        for error in entry_errors(root,entry,matrix,remote_count): errors.append(eid+': '+error)
    summary=matrix.get('summary',{}); mapping=summary.get('items',[])
    if not all(summary.get(k) and '\n' not in summary[k] for k in ['zh','en']): errors.append('摘要须中英各一段')
    if len({m.get('candidate_id') for m in mapping})<3: errors.append('摘要未映射至少3个正文事件')
    sections=set(); entries_by_id={e['candidate_id']:e for e in entries}
    for m in mapping:
        entry=entries_by_id.get(m.get('candidate_id'))
        if not entry: errors.append('摘要引用不存在的正文'); continue
        sections.add(entry['section']); atom_ids={a['id'] for a in entry['atoms']}
        if not m.get('atom_ids') or not set(m['atom_ids']).issubset(atom_ids): errors.append('摘要原子映射失效')
        if not m.get('zh') or m.get('zh','') not in summary.get('zh','') or not m.get('en') or m.get('en','') not in summary.get('en',''): errors.append('摘要分句未绑定中英文段落')
    if len(sections)<2: errors.append('摘要未覆盖至少2个板块')
    for lang in ['zh','en']:
        if norm(''.join(m.get(lang,'') for m in mapping))!=norm(summary.get(lang,'')):
            errors.append('摘要存在未映射分句或顺序不一致: '+lang)
    errors+=['摘要: '+e for e in numeric_mapping_errors(summary.get('zh',''),summary.get('en',''),summary.get('number_mappings',[]))]
    if any(re.search(INTERNAL,summary.get(k,''),re.I) for k in ['zh','en']): errors.append('摘要有链接/内部标记')
    if require_qa:
        qa=matrix.get('qa',{})
        if qa.get('binding')!=matrix_binding(matrix): errors.append('独立全稿QA不存在或绑定失效')
        if not qa.get('reviewer') or not qa.get('reviewed_at'): errors.append('全稿QA身份/时间缺失')
        for key in QA_CHECKS:
            item=qa.get('checks',{}).get(key,{})
            if item.get('result')!='pass' or not item.get('note'): errors.append('全稿QA未通过: '+key)
    return {'status':'PASS' if not errors else 'INCOMPLETE','errors':errors,'fixed_slots':len(actual),'data_entries':len(data),'policy_entries':policy_count,'checked_at':now(),
      'notice':'PASS只表示结构和人工填写的复核记录绑定完整，不能替代事实真实性判断与人工终审'}

def _date_parts(value):
    """Return display-ready date parts without changing the matrix date."""
    try:
        d = date.fromisoformat(str(value))
    except (TypeError, ValueError):
        return '', ''
    return f'{d.year}年{d.month}月{d.day}日', d.strftime('%B %d, %Y').replace(' 0', ' ')


def _short_cn_date(value):
    try:
        d = date.fromisoformat(str(value))
    except (TypeError, ValueError):
        return ''
    return f'{d.month}月{d.day}日'


def _has_zh_date(value):
    return bool(re.search(r'(?:\d{1,4}|[一二三四五六七八九十〇零]+)月(?:\d{1,2}|[一二三四五六七八九十〇零]+)日', value))


def _has_en_date(value):
    return bool(re.search(
        r'\b(?:January|February|March|April|May|June|July|August|September|October|November|December)\b|'
        r'\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b', value, re.I))


def _source_display_name(entry):
    source = (entry.get('sources') or [{}])[0]
    publisher = str(source.get('publisher') or '').strip()
    if ';' in publisher:
        publisher = publisher.split(';', 1)[0].strip()
    return publisher, source.get('tier') or ''


DELIVERY_ZH_HEADINGS = dict(HEADINGS)
DELIVERY_ZH_HEADINGS[5] = '五、重点21国信息扫描'

DELIVERY_EN_HEADINGS = {
    1: 'I. Key Information Summary',
    2: 'II. Updates from the Top 10 Chinese Auto Export Groups',
    3: 'III. Updates from the Top 10 Global Multinational Automotive Groups',
    4: 'IV. Regional Policies and Market Developments',
    5: 'V. Key 21-Country Information Scan',
    6: "VI. Today's Key Data Brief",
}

DELIVERY_EN_LABELS = {
    '奇瑞': 'Chery', '上汽': 'SAIC Motor', '比亚迪': 'BYD', '吉利': 'Geely',
    '长安': 'Changan', '长城': 'Great Wall Motor', '北汽': 'BAIC', '东风': 'Dongfeng',
    '特斯拉中国': 'Tesla China', '广汽': 'GAC', '特斯拉': 'Tesla', '丰田': 'Toyota', '大众': 'Volkswagen',
    '现代起亚': 'Hyundai-Kia', '斯泰兰蒂斯': 'Stellantis', '雷诺日产': 'Renault-Nissan',
    '通用': 'General Motors', '福特': 'Ford', '本田': 'Honda', '欧洲': 'Europe',
    '美洲': 'Americas', '东南亚': 'Southeast Asia', '澳新': 'Australia and New Zealand',
    '中东': 'Middle East', '中北亚': 'Central and North Asia', '中北非': 'Central and North Africa',
    '俄罗斯': 'Russia', '沙特阿拉伯': 'Saudi Arabia', '伊朗': 'Iran', '墨西哥': 'Mexico',
    '越南': 'Vietnam', '巴西': 'Brazil', '意大利': 'Italy', '西班牙': 'Spain',
    '土耳其': 'Türkiye', '波兰': 'Poland', '菲律宾': 'Philippines', '印度尼西亚': 'Indonesia',
    '尼日利亚': 'Nigeria', '巴基斯坦': 'Pakistan', '缅甸': 'Myanmar', '智利': 'Chile',
    '秘鲁': 'Peru', '阿联酋': 'United Arab Emirates', '乌拉圭': 'Uruguay',
    '厄瓜多尔': 'Ecuador', '委内瑞拉': 'Venezuela',
}

def _delivery_label(entry):
    zh = entry.get('label', '')
    en = entry.get('label_en') or DELIVERY_EN_LABELS.get(zh, zh)
    return str(zh), str(en)


def _replace_generic_attribution(entry, zh, en):
    publisher, _ = _source_display_name(entry)
    if not publisher:
        return zh, en
    replacements_zh = r'巴基斯坦当地汽车媒体|阿拉伯语汽车媒体|斯里兰卡媒体|俄语媒体|俄媒|乌拉圭当地媒体|当地汽车媒体|当地媒体'
    changed = bool(re.search(replacements_zh, zh))
    zh = re.sub(replacements_zh, publisher, zh, count=1)
    if changed and zh.startswith(publisher):
        zh = '据' + zh
    if publisher and norm(publisher) in norm(zh):
        zh = re.sub(rf'{re.escape(publisher)}于', f'{publisher}', zh, count=1)
    if not re.search(r'[\u3400-\u9fff]', publisher):
        replacements_en = r'A Pakistani automotive outlet|An Arabic automotive outlet|Sri Lankan media|Russian media|Uruguayan media|local media'
        en = re.sub(replacements_en, publisher, en, count=1, flags=re.I)
    return zh, en


def _delivery_source_lead(entry, zh, en):
    """Add publication context only when the atom text does not already provide it."""
    if entry.get('section') == 6:
        return zh, en
    publisher, tier = _source_display_name(entry)
    event = entry.get('event', {})
    cn_date, en_date = _date_parts(event.get('reported_date'))
    if not publisher or not cn_date:
        return zh, en

    zh, en = _replace_generic_attribution(entry, zh, en)
    # A generic attribution already present in the reviewed atom is sufficient;
    # it should not be wrapped in a second Chinese lead. English still receives
    # the date when the source sentence itself omitted it.
    if _has_zh_date(zh):
        if not _has_en_date(en) and not re.search(r'[\u3400-\u9fff]', publisher):
            en = re.sub(rf'^{re.escape(publisher)} reported that ',
                        f'According to {publisher} on {en_date}, ', en, count=1, flags=re.I)
        return zh, en
    if _has_en_date(en):
        return zh, en
    generic_lead = f'据{publisher}报道，'
    if zh.startswith(generic_lead):
        zh = zh[len(generic_lead):]
    if not re.search(r'[\u3400-\u9fff]', publisher):
        generic_en_lead = rf'^{re.escape(publisher)} reported that '
        en = re.sub(generic_en_lead, '', en, count=1, flags=re.I)
    publisher_norm = norm(publisher)
    zh_has_publisher = publisher_norm and publisher_norm in norm(zh)
    zh_has_context = _has_zh_date(zh) and (
        zh.startswith('据') or zh_has_publisher or bool(re.search(r'据[^，。]{1,30}(?:报道|发布|公布|披露)', zh))
    )
    en_has_publisher = publisher_norm and publisher_norm in norm(en)
    en_has_context = _has_en_date(en) and (
        en_has_publisher or bool(re.search(r'\b(?:according to|reported|published|released)\b', en, re.I))
    )
    if not zh_has_context:
        verb = '发布的信息' if tier == 'official' else '报道'
        # If the atom begins with the source's own company name, avoid repeating it.
        body = zh
        if tier == 'official' and publisher_norm and norm(body).startswith(publisher_norm):
            body = body[len(publisher):].lstrip(' ，，:：')
        zh = f'据{publisher}{_short_cn_date(event.get("reported_date"))}{verb}，{body}'
    # Avoid placing a Chinese publisher name into the English customer copy.
    if not en_has_context and not _has_en_date(en) and not re.search(r'[\u3400-\u9fff]', publisher):
        en = f'According to {publisher} on {en_date}, {en}'
    return zh, en


def _delivery_data_context(entry, zh, en):
    """Make the data section state its publisher, period and measurement basis."""
    if entry.get('section') != 6:
        return zh, en
    stats = entry.get('statistics') or {}
    event = entry.get('event', {})
    period = event.get('statistical_period') or ''
    publisher = stats.get('publisher') or ''
    publisher_zh = {
        'Malaysian Automotive Association': '马来西亚汽车协会',
        'Zapmap': 'Zapmap',
    }.get(publisher, publisher)
    cn_date, en_date = _date_parts(event.get('reported_date'))
    if publisher and not _has_zh_date(zh) and cn_date and norm(publisher_zh) not in norm(zh):
        zh = f'据{publisher_zh}{cn_date}发布的统计，{zh}'
    if publisher and not _has_en_date(en) and en_date and not re.search(r'[\u3400-\u9fff]', publisher):
        en = f'Statistics published by {publisher} on {en_date} show that {en[0].lower() + en[1:] if en else en}'
    scope = stats.get('scope') or ''
    scope_zh = {
        '海关进口口径，来源公布约数': '该口径为汽车进口数量，万位数字为来源公布的约数。',
        'MAA TIV销量，非产量': '统计口径为MAA行业销量。',
        '按网络价格及估算用电量加权，不含会员专项优惠或家庭充电': '指标依据网络电价及估算用电量加权，不含会员或专项优惠，也不含家庭充电。',
    }.get(scope)
    scope_en = {
        '海关进口口径，来源公布约数': 'These are vehicle import volumes, rounded as reported.',
        'MAA TIV销量，非产量': "The figures follow MAA's industry-sales definition.",
        '按网络价格及估算用电量加权，不含会员专项优惠或家庭充电': 'The index weights network tariffs by estimated energy delivered and excludes membership and special offers as well as home charging.',
    }.get(scope)
    if scope_zh and scope_zh not in zh:
        zh += f' {scope_zh}'
    if scope_en and scope_en not in en:
        en += f' {scope_en}'
    if entry.get('slot') == 'S6-01':
        en = en.replace(
            'Cui Dongshu of the CPCA published figures on October 25, reported by Zhitong Finance, showing approximately',
            "Zhitong Finance reported on October 25, citing data published that day by CPCA's Cui Dongshu, that China imported approximately",
        )
        en = en.replace('that China imported approximately 21,000 vehicles imported into China',
                        'that China imported approximately 21,000 vehicles')
    elif entry.get('slot') == 'S6-02':
        en = en.replace(
            'MAA reported Malaysian industry vehicle sales',
            'Industry sales data released by the Malaysian Automotive Association on October 19 show Malaysian industry vehicle sales',
        )
    elif entry.get('slot') == 'S6-03':
        en = en.replace(
            "Zapmap's monthly index updated on October 7 shows",
            "Zapmap's monthly price index, updated on October 7, puts",
        )
    return zh, en


def _dedupe_delivery_context(entry, zh, en):
    """Collapse a source lead when the reviewed atom already states the same source/date."""
    publisher, _ = _source_display_name(entry)
    if not publisher:
        return zh, en
    cn_date = _short_cn_date(entry.get('event', {}).get('reported_date'))
    if not cn_date:
        return zh, en
    # Example: “据X9月30日发布的信息，X9月30日宣布” -> “X9月30日宣布”.
    escaped = re.escape(publisher)
    zh = re.sub(
        rf'^据{escaped}{re.escape(cn_date)}(?:发布的信息|报道)，(?P<body>.+?)',
        lambda m: m.group('body'), zh, count=1,
    )
    # Example: “据X10月12日报道，X于10月12日报道” -> “X于10月12日报道”.
    zh = re.sub(
        rf'^据{escaped}{re.escape(cn_date)}报道，(?P<body>{re.escape(publisher)}于{re.escape(cn_date)}报道，)',
        lambda m: m.group('body'), zh, count=1,
    )
    zh = re.sub(
        rf'^据{escaped}{re.escape(cn_date)}报道，{re.escape(publisher)}于{re.escape(cn_date)}报道，',
        f'{publisher}{cn_date}报道，', zh, count=1,
    )
    # Preserve a single English lead when the atom already has one.
    if re.match(rf'^{re.escape(publisher)} reported on ', en, re.I):
        en = re.sub(rf'^{re.escape(publisher)} reported on ([^,]+) that {re.escape(publisher)} ',
                    rf'{publisher} reported on \1 that ', en, count=1, flags=re.I)
    return zh, en


def delivery_entry_text(entry):
    """Format reviewed text only; source/date/scope facts belong in atoms."""
    return tuple(value.strip() for value in texts(entry))


def render(matrix):
    try:
        report_day = date.fromisoformat(matrix['report_date'])
        delivery_date = f'{report_day.year}年{report_day.month}月{report_day.day}日'
    except (KeyError, ValueError):
        delivery_date = matrix['report_date']
    delivery=[f'全球汽车行业简讯｜{delivery_date}']
    audit=[f'# 全球汽车行业简讯｜{matrix["report_date"]} 带信源审核版','',
      '> 本版供审核使用：先看总表，再按槽位查看正文、来源、摘录、历史比较和审核理由。','',
      f'> 历史口径：{("本地滚动30日历史" if matrix.get("history",{}).get("mode")=="local_roll30" else "Google只读30天")}；epoch `{matrix["history"]["epoch"]}`。','']
    summary=matrix['summary']
    def clean(value):
        return str(value or '').replace('\n',' ').replace('|','／').strip()
    def link_source(source):
        publisher=clean(source.get('publisher') or source.get('id'))
        url=source.get('url') or source.get('origin_key') or ''
        return f'[{publisher}]({url})' if url else publisher
    def source_for(entry, sid):
        return next((s for s in entry.get('sources',[]) if s.get('id')==sid), None)
    def audit_card(entry):
        zh,en=texts(entry); event=entry.get('event',{}); fp=entry.get('fingerprint',{})
        h=entry.get('history_review',{}); policy=entry.get('policy',{})
        lines=[f'### {entry["slot"]}｜{clean(entry["label"])}｜`{entry["candidate_id"]}`', '',
          '**中文正文**', clean(zh), '', '**English**', math_italic(clean(en)), '',
          '**审核结论**', f'- 决定：`{clean(entry.get("decision"))}`；核验状态：{clean(entry.get("source_status"))}',
          f'- 事件日：`{clean(event.get("date"))}`；报道日：`{clean(event.get("reported_date"))}`；阶段：`{clean(fp.get("stage"))}`',
          f'- 新闻价值：{clean(entry.get("relevance",{}).get("rationale"))}',
          f'- 政策分类：`{"政策" if policy.get("is_policy") else "非政策"}`；{clean(policy.get("rationale"))}', '']
        lines += ['**信源**']
        for s in entry.get('sources',[]):
            lines.append(f'- {link_source(s)} · {clean(s.get("tier"))} · 支持范围：{clean(s.get("scope"))}')
        outline=entry.get('source_outline') or {}
        lines += ['', '**来源重点与取舍**',
                  f'- 事件类型：{clean(outline.get("event_type"))}；产业关联：{clean(outline.get("industry_relation"))}',
                  f'- 必要上下文：{clean(outline.get("reader_context"))}',
                  f'- 去重后价值：{clean(outline.get("industry_value_after_dedup"))}']
        for point in outline.get('points',[]):
            lines.append(f'- `{clean(point.get("id"))}` / {clean(point.get("role"))} / {clean(point.get("decision"))} → `{clean(",".join(point.get("atom_ids",[])))}`：{clean(point.get("text"))}；{clean(point.get("reason"))}')
            for cite in point.get('evidence',[]):
                src=source_for(entry,cite.get('source_id'))
                lines.append(f'  - {link_source(src) if src else clean(cite.get("source_id"))}（{clean(cite.get("locator"))}）：“{clean(cite.get("quote"))}”')
        lines += ['', '**证据摘录**']
        for atom in entry.get('atoms',[]):
            lines.append(f'- 事实原子 `{atom.get("id")}`')
            for cite in atom.get('evidence',[]):
                src=source_for(entry,cite.get('source_id'))
                label=link_source(src) if src else clean(cite.get('source_id'))
                lines.append(f'  - {label}（{clean(cite.get("locator"))}）：“{clean(cite.get("quote"))}”')
        for cite in event.get('date_basis',[]):
            src=source_for(entry,cite.get('source_id'))
            label=link_source(src) if src else clean(cite.get('source_id'))
            lines.append(f'- 事件日期依据：{label}（{clean(cite.get("locator"))}）：“{clean(cite.get("quote"))}”')
        lines += ['', '**历史去重**', f'- 结论：`{clean(h.get("result"))}`；{clean(h.get("rationale"))}',
                  f'- 检索词：{"、".join(clean(x) for x in h.get("search_terms",[]))}']
        for c in h.get('comparisons',[]):
            lines.append(f'- {clean(c.get("published_date"))} · {clean(c.get("historical_fact"))}；差异：{clean(c.get("difference"))}')
        cross=entry.get('cross_section_review',{})
        lines += ['', '**跨栏比较**', f'- {clean(cross.get("rationale"))}',
                  f'- 已比较其余 `{len(cross.get("compared_ids",[]))}` 条候选；冲突：`{len(cross.get("conflicts",[]))}`', '',
                  '**逐条审核**', '| 检查项 | 结果 | 依据 |', '|---|---|---|']
        checks=entry.get('semantic_review',{}).get('checks',{})
        for key in CHECKS:
            item=checks.get(key,{})
            lines.append(f'| {key} | `{clean(item.get("result"))}` | {clean(item.get("note"))} |')
        lines += ['', '---', '']
        return lines
    audit += ['## 审稿总表','', '| 槽位 | 主体 | 事件日 | 阶段 | 决定 | 来源 | 政策 |', '|---|---|---|---|---|---|---|']
    for entry in sorted(matrix.get('entries',[]), key=lambda e:e.get('slot','')):
        sources=', '.join(link_source(s) for s in entry.get('sources',[]))
        audit.append(f'| {entry.get("slot")} | {clean(entry.get("label"))} | {clean(entry.get("event",{}).get("date"))} | {clean(entry.get("fingerprint",{}).get("stage"))} | `{clean(entry.get("decision"))}` | {sources} | {"是" if entry.get("policy",{}).get("is_policy") else "否"} |')
    audit += ['', '## 一、核心信息摘要', '', summary['zh'], '', math_italic(summary['en']), '', '**摘要映射**']
    for item in summary.get('items',[]):
        audit.append(f'- `{item.get("candidate_id")}` / `{",".join(item.get("atom_ids",[]))}`：{clean(item.get("zh"))} / {math_italic(clean(item.get("en")))}')
    audit += ['', '']
    for sec in range(1,7):
        delivery += ['', f'{DELIVERY_ZH_HEADINGS[sec]} / {math_italic(DELIVERY_EN_HEADINGS[sec])}']
        if sec==1:
            delivery += [summary['zh'],math_italic(summary['en'])]
            continue
        section=sorted([e for e in matrix['entries'] if e['section']==sec],key=lambda e:e['slot'])
        audit += ['## '+HEADINGS[sec],'']
        for entry in section:
            if sec == 4 and entry['slot'] == 'S4-01':
                delivery.append('“2”个主要市场 / “2” '+math_italic('Major Markets'))
            elif sec == 4 and entry['slot'] == 'S4-03':
                delivery.append('“5”个重点市场 / “5” '+math_italic('Key Markets'))
            zh,en=delivery_entry_text(entry)
            label_zh, label_en = _delivery_label(entry)
            delivery += [label_zh+'：'+zh,math_italic(label_en+': '+en)]
            audit += audit_card(entry)
    audit += ['## 全稿QA','', '| 检查项 | 结果 | 说明 |', '|---|---|---|']
    for key,item in matrix.get('qa',{}).get('checks',{}).items():
        audit.append(f'| {key} | `{clean(item.get("result"))}` | {clean(item.get("note"))} |')
    audit += ['', f'> QA审核人：{clean(matrix.get("qa",{}).get("reviewer"))}；时间：`{clean(matrix.get("qa",{}).get("reviewed_at"))}`', '']
    txt='\n'.join(delivery)+'\n'
    if re.search(INTERNAL,txt,re.I): raise ValueError('客户版残留内部信息')
    return '\n'.join(audit),txt

def json_text(value):
    import json
    return json.dumps(value,ensure_ascii=False,separators=(',',':'))

def delivery_format_errors(delivery):
    """Check the delivered regional layout independently of rendering it."""
    lines=delivery.splitlines()
    major='“2”个主要市场 / “2” 𝑀𝑎𝑗𝑜𝑟 𝑀𝑎𝑟𝑘𝑒𝑡𝑠'
    key='“5”个重点市场 / “5” 𝐾𝑒𝑦 𝑀𝑎𝑟𝑘𝑒𝑡𝑠'
    errors=[]
    for heading in (major,key):
        if lines.count(heading)!=1:
            errors.append('客户版分组标题须准确且仅出现一次: '+heading)
    bounds=[f'{DELIVERY_ZH_HEADINGS[n]} / {math_italic(DELIVERY_EN_HEADINGS[n])}' for n in (4,5)]
    if any(lines.count(heading)!=1 for heading in bounds):
        return errors+['客户版第四、第五部分标题缺失或重复']
    start,end=(lines.index(heading) for heading in bounds)
    if start>=end:
        return errors+['客户版第四、第五部分顺序错误']
    region=lines[start+1:end]
    while region and not region[-1]:
        region.pop()
    expected={0:major,1:'欧洲：',3:'美洲：',5:key,6:'东南亚：',8:'澳新：',10:'中东：',12:'中北亚：',14:'中北非：'}
    if len(region)!=16 or any(
        i>=len(region) or (region[i]!=text if i in (0,5) else not region[i].startswith(text))
        for i,text in expected.items()
    ):
        errors.append('客户版第四部分须按2个主要市场、5个重点市场分组，标题紧邻欧洲、东南亚前，七区域顺序固定且中英各一行')
    return errors

def build(root, matrix_path):
    matrix=load(matrix_path); result=validate_matrix(root,matrix)
    folder=Path(root)/'output'/matrix['report_date']; folder.mkdir(parents=True,exist_ok=True)
    if result['status']=='PASS':
        audit,delivery=render(matrix)
        result['errors']+=delivery_format_errors(delivery)
        if result['errors']: result['status']='INCOMPLETE'
    save(folder/'validation.json',result)
    if result['status']!='PASS': return result
    preview=folder/'送审'; preview.mkdir(parents=True,exist_ok=True)
    md=preview/'全球汽车行业简讯_带信源审核版.md'; txt=preview/'全球汽车行业简讯_客户终审预览.txt'
    # A human's annotations are review evidence, never disposable build output.
    if md.exists() and re.search(r'人工审核[：:]',md.read_text(encoding='utf-8-sig')):
        archive=folder/'审核留痕'/file_hash(md)[:16]
        archive.mkdir(parents=True,exist_ok=True)
        for original in (md,txt,preview/'build.json'):
            if original.exists():
                target=archive/original.name
                if target.exists() and file_hash(target)!=file_hash(original):
                    raise ValueError('人工审核留痕已有不同版本，禁止覆盖')
                shutil.copy2(original,target)
    md.write_bytes(audit.encode('utf-8')); txt.write_bytes(delivery.encode('utf-8-sig'))
    save(preview/'build.json',{'matrix':str(Path(matrix_path).resolve().relative_to(root)).replace('\\','/'),'matrix_sha256':file_hash(matrix_path),
      'binding':matrix_binding(matrix),'report_date':matrix['report_date'],'generated_at':now(),'state':'AWAITING_HUMAN_REVIEW',
      'files':{md.name:file_hash(md),txt.name:file_hash(txt)}})
    return result

def publish(root, matrix_path, approval_path):
    matrix=load(matrix_path); result=validate_matrix(root,matrix)
    if result['status']!='PASS': raise ValueError('正式生成闸门未通过：'+ '; '.join(result['errors'][:8]))
    approval=load(approval_path); preview=Path(root)/'output'/matrix['report_date']/'送审'; manifest=load(preview/'build.json')
    if approval.get('approved') is not True or not approval.get('reviewer') or not approval.get('approved_at') or not approval.get('authorization_reference'): raise ValueError('人工终审记录缺失；Codex不能自行代签')
    if approval.get('matrix_sha256')!=file_hash(matrix_path) or manifest['matrix_sha256']!=file_hash(matrix_path): raise ValueError('终审后矩阵变化')
    if approval.get('build_sha256')!=file_hash(preview/'build.json'): raise ValueError('批准未绑定当前送审文件')
    audit,delivery=render(matrix)
    format_errors=delivery_format_errors(delivery)
    if format_errors: raise ValueError('客户版格式检查未通过：'+ '; '.join(format_errors))
    for name,sha in manifest['files'].items():
        if file_hash(preview/name)!=sha: raise ValueError('送审文件变化')
    if (preview/'全球汽车行业简讯_带信源审核版.md').read_bytes()!=audit.encode('utf-8') or (preview/'全球汽车行业简讯_客户终审预览.txt').read_bytes()!=delivery.encode('utf-8-sig'): raise ValueError('送审文件与当前矩阵派生结果不一致')
    folder=preview.parent/'正式交付'
    if folder.exists(): raise ValueError('已存在正式交付，请明确修订版本，禁止静默覆盖')
    folder.mkdir()
    md=folder/f'全球汽车行业简讯_{matrix["report_date"]}_带信源审核版.md'
    txt=folder/f'全球汽车行业简讯_{matrix["report_date"]}_正式交付版.txt'
    md.write_bytes(audit.encode('utf-8')); txt.write_bytes(delivery.encode('utf-8-sig'))
    save(folder/'approval.json',approval)
    release_path=folder/'release.json'
    save(release_path,{'report_date':matrix['report_date'],'matrix_sha256':file_hash(matrix_path),'published_at':now(),
      'files':{md.name:file_hash(md),txt.name:file_hash(txt)},'approval_sha256':file_hash(folder/'approval.json'),
      'events':[{'candidate_id':e['candidate_id'],'fingerprint':e['fingerprint'],'zh':texts(e)[0],'event_date':e['event']['date']} for e in matrix['entries']]})
    if matrix.get('history',{}).get('mode') == 'local_roll30':
        from ingest import register_release_history
        try:
            registration=register_release_history(root,release_path)
        except Exception as exc:
            save(folder/'history-registration-pending.json',{'release':str(release_path.relative_to(root)).replace('\\','/'),'error':str(exc),'created_at':now()})
            return {'status':'PUBLISHED_WITH_HISTORY_PENDING','directory':str(folder),'history_registration_error':str(exc)}
        return {'status':'PUBLISHED','directory':str(folder),'history_registration':registration}
    return {'status':'PUBLISHED','directory':str(folder)}
