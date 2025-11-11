import json
import os
import re
import shutil
import sqlite3
import tempfile
from functools import lru_cache
from urllib.parse import urlparse


def find_history_dbs():
    """Return a prioritized list of available History DBs across Chrome/Chromium profiles."""
    home = os.path.expanduser('~')
    chrome_base = os.path.join(home, '.config/google-chrome')
    chromium_base = os.path.join(home, '.config/chromium')
    dbs = []
    for base in (chrome_base, chromium_base):
        dbs.extend(_list_history_dbs_in_dir(base))
    return dbs


def find_history_db():
    """Backward-compatible helper that returns the first available DB path."""
    dbs = find_history_dbs()
    return dbs[0]['path'] if dbs else None


@lru_cache(maxsize=32)
def get_profile_metadata(db_path):
    if not db_path:
        return {'label': '', 'icon': None}
    profile_dir = os.path.dirname(db_path)
    profile_id = os.path.basename(profile_dir) or ''
    base_dir = os.path.dirname(profile_dir)
    state_path = os.path.join(base_dir, 'Local State')
    info_entry = {}
    try:
        with open(state_path, 'r', encoding='utf-8') as fh:
            data = json.load(fh)
        info_cache = data.get('profile', {}).get('info_cache', {})
        info_entry = info_cache.get(profile_id, {}) or {}
    except (OSError, ValueError, json.JSONDecodeError):
        info_entry = {}
    friendly = info_entry.get('name')
    label = friendly or profile_id or 'Unknown profile'
    icon_path = _resolve_profile_icon(profile_dir, info_entry)
    return {'label': label, 'icon': icon_path}


def get_profile_label(db_path):
    return get_profile_metadata(db_path)['label']


def get_profile_icon_path(db_path):
    return get_profile_metadata(db_path)['icon']


def _preferred_profiles(base_dir):
    state_path = os.path.join(base_dir, 'Local State')
    ordered = []
    try:
        with open(state_path, 'r', encoding='utf-8') as fh:
            data = json.load(fh)
        profile_data = data.get('profile', {})
        entries = []
        last_used = profile_data.get('last_used')
        if last_used:
            entries.append(last_used)
        for prof in profile_data.get('last_active_profiles', []):
            if prof:
                entries.append(prof)
        for prof in profile_data.get('info_cache', {}).keys():
            entries.append(prof)
        for entry in entries:
            if entry not in ordered:
                ordered.append(entry)
    except (OSError, ValueError, json.JSONDecodeError):
        pass
    return ordered


def _list_history_dbs_in_dir(base_dir):
    if not os.path.isdir(base_dir):
        return []
    candidates = []
    seen = set()

    def add_candidate(profile_id):
        path = os.path.join(base_dir, profile_id, 'History')
        if path not in seen:
            seen.add(path)
            candidates.append((profile_id, path))

    for profile in _preferred_profiles(base_dir):
        add_candidate(profile)

    for entry in sorted(os.listdir(base_dir)):
        if entry in ('Default', 'Guest Profile') or entry.startswith(('Profile', 'user')):
            add_candidate(entry)

    dbs = []
    for profile_id, path in candidates:
        if os.path.exists(path):
            meta = get_profile_metadata(path)
            dbs.append({
                'path': path,
                'profile_id': profile_id,
                'profile_label': meta['label'],
                'profile_icon': meta['icon'],
            })
    return dbs
def _resolve_profile_icon(profile_dir, info_entry):
    if not profile_dir:
        return None
    candidates = [
        'Google Profile Picture.png',
        'Google Profile Picture',
        'Profile Picture.png',
        'Profile Picture',
        'profile_picture.png',
        'Avatar Image.jpg',
        'Avatar Image.png',
    ]
    for name in candidates:
        path = os.path.join(profile_dir, name)
        if os.path.isfile(path):
            return path
    avatar_icon = (info_entry or {}).get('avatar_icon')
    if avatar_icon:
        avatar_file = avatar_icon.replace('chrome://theme/', '').lower()
        possible = os.path.join(os.path.dirname(__file__), 'images', f'{avatar_file}.png')
        if os.path.isfile(possible):
            return possible
    return None

def _safe_copy(src):
    tmp_dir = tempfile.mkdtemp(prefix='ulauncher_ch_hist_')
    dst = os.path.join(tmp_dir, 'History')
    shutil.copy2(src, dst)
    return dst, tmp_dir

TOKEN_SPLIT_RE = re.compile(r'[^0-9a-zа-яё]+', re.IGNORECASE)


def _word_startswith(text, prefix):
    if not text:
        return False
    tokens = TOKEN_SPLIT_RE.split(text.lower())
    return any(token.startswith(prefix) for token in tokens if token)


def _score_row(url, title, visit_count, typed_count, query_lower):
    title_lower = (title or '').lower()
    parsed = urlparse(url or '')
    host = parsed.netloc.lower()
    path = parsed.path.lower()
    score = 0

    if title_lower.startswith(query_lower):
        score += 400
    elif _word_startswith(title_lower, query_lower):
        score += 260
    elif query_lower in title_lower:
        score += 80

    if host.startswith(query_lower):
        score += 350
    elif query_lower in host:
        score += 140

    if path.startswith(query_lower):
        score += 120
    elif _word_startswith(path, query_lower):
        score += 90
    elif query_lower in path:
        score += 40

    typed = typed_count or 0
    visits = visit_count or 0
    score += min(typed, 20) * 15
    score += min(visits, 50) * 2
    return score


def _rank_entries(entries, query, limit):
    if not entries:
        return []
    if not query:
        entries.sort(key=lambda e: e['last_visit_time'] or 0, reverse=True)
        return entries[:limit]
    query_lower = query.lower()
    scored = []
    for entry in entries:
        score = _score_row(entry['url'], entry['title'], entry['visit_count'], entry['typed_count'], query_lower)
        scored.append((score, entry['last_visit_time'] or 0, entry))
    scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return [entry for _, _, entry in scored[:limit]]


def _fetch_entries(db_path, query, limit):
    copy_path, tmp_dir = _safe_copy(db_path)
    try:
        conn = sqlite3.connect(copy_path)
        cur = conn.cursor()
        column_list = 'url, title, visit_count, last_visit_time, typed_count'
        if query:
            like = f'%{query}%'
            fetch_limit = min(max(limit * 5, 50), 500)
            cur.execute(
                f'SELECT {column_list} FROM urls WHERE url LIKE ? OR title LIKE ? ORDER BY last_visit_time DESC LIMIT ?',
                (like, like, fetch_limit),
            )
        else:
            fetch_limit = limit
            cur.execute(
                f'SELECT {column_list} FROM urls ORDER BY last_visit_time DESC LIMIT ?',
                (fetch_limit,),
            )
        rows = cur.fetchall()
        conn.close()
        entries = []
        for url, title, visit_count, last_visit_time, typed_count in rows:
            entries.append({
                'url': url,
                'title': title,
                'visit_count': visit_count,
                'last_visit_time': last_visit_time,
                'typed_count': typed_count or 0,
            })
        return entries
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def search_history(db_sources, query, limit=20):
    """
    Search across one or more history DBs.

    :param db_sources: Either a path string or an iterable of dicts with keys 'path' and optional 'profile_label'.
    """
    if isinstance(db_sources, str):
        meta = get_profile_metadata(db_sources)
        db_sources = [{'path': db_sources, 'profile_label': meta['label'], 'profile_icon': meta['icon']}]
    elif not db_sources:
        return []

    combined_entries = []
    errors = []
    for source in db_sources:
        path = source.get('path')
        if not path:
            continue
        profile_label = source.get('profile_label') or get_profile_label(path)
        profile_icon = source.get('profile_icon') or get_profile_icon_path(path)
        try:
            entries = _fetch_entries(path, query, limit)
            for entry in entries:
                entry['profile_label'] = profile_label
                entry['profile_icon'] = profile_icon
                entry['profile_id'] = source.get('profile_id')
                combined_entries.append(entry)
        except (sqlite3.Error, OSError) as exc:
            errors.append(exc)

    if not combined_entries and errors:
        raise errors[0]

    ranked = _rank_entries(combined_entries, query, limit)
    return [
        (
            entry['url'],
            entry['title'],
            entry['visit_count'],
            entry['last_visit_time'],
            entry.get('profile_label', ''),
            entry.get('profile_icon'),
            entry.get('profile_id', ''),
        )
        for entry in ranked
    ]
