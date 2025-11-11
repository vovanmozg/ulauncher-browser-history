import os, shlex, sqlite3, hashlib
from datetime import datetime, timedelta
from urllib.parse import urlparse
from ulauncher.api.client.Extension import Extension
from ulauncher.api.client.EventListener import EventListener
from ulauncher.api.shared.event import KeywordQueryEvent, PreferencesUpdateEvent
from ulauncher.api.shared.item.ExtensionSmallResultItem import ExtensionSmallResultItem
from ulauncher.api.shared.action.RunScriptAction import RunScriptAction
from ulauncher.api.shared.action.OpenUrlAction import OpenUrlAction
from ulauncher.api.shared.action.RenderResultListAction import RenderResultListAction
from history_search import (
    find_history_db,
    find_history_dbs,
    search_history,
    get_profile_label,
    get_profile_icon_path,
)

BASE_DIR = os.path.dirname(__file__)
WEBKIT_EPOCH = datetime(1601, 1, 1)
PROFILE_ICON_SEQUENCE = [
    'images/icon.png',
    'images/icon-add.png',
    'web-browser',
    'applications-internet',
    'system-search',
]
def _icon_exists(relative_path):
    return os.path.isfile(os.path.join(BASE_DIR, relative_path))

PROFILE_HASHED_ICONS = [
    rel for rel in (f'images/profiles/{i:02d}.png' for i in range(20))
    if _icon_exists(rel)
]

def fmt_time(last_visit_time):
    try:
        dt = WEBKIT_EPOCH + timedelta(microseconds=int(last_visit_time))
        return dt.strftime('%Y-%m-%d %H:%M')
    except Exception:
        return ''


def get_profile_icon(extension, profile_label, icon_hint=None):
    if icon_hint and os.path.isfile(icon_hint):
        return icon_hint
    icon = None
    if profile_label and PROFILE_HASHED_ICONS:
        digest = hashlib.sha1(profile_label.encode('utf-8')).digest()
        idx = int.from_bytes(digest[:4], 'big') % len(PROFILE_HASHED_ICONS)
        icon = PROFILE_HASHED_ICONS[idx]
    if icon:
        return icon
    return PROFILE_ICON_SEQUENCE[0]

def build_open_action(browser_cmd, profile_id, url):
    if not browser_cmd or browser_cmd == 'xdg-open':
        return OpenUrlAction(url)
    cmd = browser_cmd
    if profile_id and '--profile-directory' not in cmd:
        cmd = f'{cmd} --profile-directory={shlex.quote(profile_id)}'
    return RunScriptAction(f'{cmd} {shlex.quote(url)}')


class ChromeHistoryExtension(Extension):
    def __init__(self):
        super().__init__()
        self.subscribe(KeywordQueryEvent, KeywordQueryEventListener())
        self.subscribe(PreferencesUpdateEvent, PrefsUpdateListener())

class PrefsUpdateListener(EventListener):
    def on_event(self, event, extension):
        extension.preferences = event.preferences
        user_path = (event.preferences.get('history_path') or '').strip()
        resolved_path = user_path or find_history_db()
        source = 'preferences' if user_path else 'auto-detected'
        if resolved_path:
            profile_label = get_profile_label(resolved_path)


class KeywordQueryEventListener(EventListener):
    def on_event(self, event, extension):
        prefs = extension.preferences
        query = (event.get_argument() or '').strip()
        max_results = int(prefs.get('max_results') or 20)
        default_icon = PROFILE_ICON_SEQUENCE[0]
        pref_path = (prefs.get('history_path') or '').strip()
        source = 'preferences' if pref_path else 'auto-detected'
        if pref_path:
            profile_dir = os.path.basename(os.path.dirname(pref_path))
            db_sources = [{
                'path': pref_path,
                'profile_label': get_profile_label(pref_path),
                'profile_icon': get_profile_icon_path(pref_path),
                'profile_id': profile_dir,
            }]
        else:
            db_sources = find_history_dbs()
        items = []
        if not db_sources:
            items.append(ExtensionSmallResultItem(name='History database not found', description='Please set the path manually.', icon=default_icon, on_enter=RunScriptAction('')))
            return RenderResultListAction(items)
        try:
            results = search_history(db_sources, query, limit=max_results)
        except sqlite3.Error as e:
            items.append(ExtensionSmallResultItem(name='Database error', description=str(e), icon=default_icon, on_enter=RunScriptAction('')))
            return RenderResultListAction(items)
        if not results:
            items.append(ExtensionSmallResultItem(name='Nothing found', description='Try a different query.', icon=default_icon, on_enter=RunScriptAction('')))
            return RenderResultListAction(items)
        browser_cmd = (prefs.get('browser_cmd') or 'xdg-open').strip()
        for url, title, visit_count, last_visit_time, profile_label, profile_icon_hint, profile_id in results:
            profile_icon = get_profile_icon(extension, profile_label, profile_icon_hint)
            host = urlparse(url).netloc
            time_str = fmt_time(last_visit_time)
            subtitle_parts = [host]
            if profile_label:
                subtitle_parts.append(f'profile: {profile_label}')
            subtitle_parts.append(f'visits: {visit_count}')
            if time_str:
                subtitle_parts.append(time_str)
            subtitle = ' • '.join(subtitle_parts)
            display_name = title or url
            action = build_open_action(browser_cmd, profile_id, url)
            items.append(ExtensionSmallResultItem(name=display_name, description=subtitle, icon=profile_icon, on_enter=action))
        return RenderResultListAction(items)

if __name__ == '__main__':
    ChromeHistoryExtension().run()
