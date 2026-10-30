"""Isolated multi-agent candidate packages and phase progress.

Sub-agents write only package files.  The main CLI validates and imports a
package atomically into the single authoritative matrix.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from model import file_hash, load, now, save, slots


def _slot_map():
    return {item['id']: item for item in slots()}


def package_path(root, report_date, agent):
    if not agent or '/' in agent or '\\' in agent or '..' in agent:
        raise ValueError('代理名非法')
    folder = Path(root) / 'candidates' / report_date / 'submissions' / agent
    folder.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime('%Y%m%d-%H%M%S-%f')
    return folder / f'{stamp}.json'


def create_package(root, matrix, agent, slot_ids):
    allowed = _slot_map()
    requested = [x.strip() for x in slot_ids if x.strip()]
    if not requested or len(set(requested)) != len(requested):
        raise ValueError('候选包必须包含不重复槽位')
    unknown = [x for x in requested if x not in allowed]
    if unknown:
        raise ValueError('候选包含未知槽位: ' + ','.join(unknown))
    path = package_path(root, matrix['report_date'], agent)
    package = {
        'schema_version': 1,
        'kind': 'isolated_candidate_package',
        'created_at': now(),
        'agent': agent,
        'report_date': matrix['report_date'],
        'rules_sha256': matrix['rules_sha256'],
        'history': matrix['history'],
        'slots': requested,
        'entries': [],
        'unresolved': requested,
        'imported': False,
    }
    save(path, package)
    return {'package': str(path.relative_to(root)).replace('\\', '/'), 'slots': requested}


def validate_package(root, matrix, package_path_value):
    path = Path(package_path_value).resolve()
    submissions = (Path(root) / 'candidates' / matrix['report_date'] / 'submissions').resolve()
    if not path.is_relative_to(submissions):
        raise ValueError('候选包必须位于当日隔离提交目录')
    package = load(path)
    if package.get('kind') != 'isolated_candidate_package' or package.get('schema_version') != 1:
        raise ValueError('候选包schema不受支持')
    if package.get('report_date') != matrix.get('report_date'):
        raise ValueError('候选包业务日与矩阵不一致')
    if package.get('rules_sha256') != matrix.get('rules_sha256'):
        raise ValueError('候选包规则版本已过期')
    if package.get('history') != matrix.get('history'):
        raise ValueError('候选包历史快照已过期')
    if package.get('imported') is True:
        raise ValueError('候选包已导入，禁止重复导入')
    allowed = _slot_map()
    declared = package.get('slots') or []
    if not declared or len(set(declared)) != len(declared) or any(x not in allowed for x in declared):
        raise ValueError('候选包槽位声明无效')
    entries = package.get('entries') or []
    entry_slots = [e.get('slot') for e in entries]
    if len(set(entry_slots)) != len(entry_slots) or any(x not in declared for x in entry_slots):
        raise ValueError('候选包条目与槽位声明不一致')
    if set(package.get('unresolved') or []) != set(declared) - set(entry_slots):
        raise ValueError('候选包未解决槽位记录不一致')
    current = {e.get('slot'): e for e in matrix.get('entries', [])}
    # A blank pending placeholder created by ``add`` may be filled by the
    # assigned agent.  Any existing factual candidate is a real conflict and
    # must use the normal reuse/edit path instead of being silently replaced.
    conflicts = [slot for slot in entry_slots
                 if slot in current and current[slot].get('decision') != 'pending']
    if conflicts:
        raise ValueError('候选包与主矩阵槽位冲突: ' + ','.join(conflicts))
    if any(not e.get('candidate_id') for e in entries):
        raise ValueError('候选包存在空候选ID')
    return package


def import_package(root, matrix_path, package_path_value):
    matrix_path = Path(matrix_path)
    matrix = load(matrix_path)
    package = validate_package(root, matrix, package_path_value)
    by_slot = {e.get('slot'): e for e in matrix.get('entries', [])}
    for entry in package.get('entries', []):
        by_slot[entry['slot']] = entry
    matrix['entries'] = list(by_slot.values())
    matrix['qa'] = {}
    save(matrix_path, matrix)
    package['imported'] = True
    package['imported_at'] = now()
    package['matrix_sha256'] = file_hash(matrix_path)
    save(package_path_value, package)
    return {'imported': len(package.get('entries', [])), 'unresolved': package.get('unresolved', []), 'matrix': str(matrix_path)}


def progress(matrix):
    result = []
    for entry in matrix.get('entries', []):
        phase = 'found'
        if entry.get('event', {}).get('date') and entry.get('event', {}).get('date_basis'):
            phase = 'date_verified'
        if entry.get('history_review', {}).get('result') in {'no_duplicate', 'new_milestone'}:
            phase = 'history_checked'
        if entry.get('atoms') and entry.get('decision') == 'keep':
            phase = 'drafted'
        review = entry.get('semantic_review', {})
        if review.get('reviewer') and review.get('checks'):
            phase = 'reviewed'
        result.append({'slot': entry.get('slot'), 'candidate_id': entry.get('candidate_id'), 'phase': phase})
    counts = {}
    for item in result:
        counts[item['phase']] = counts.get(item['phase'], 0) + 1
    return {'report_date': matrix.get('report_date'), 'counts': counts, 'entries': result}
