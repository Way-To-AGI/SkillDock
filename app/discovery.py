"""Offline path catalog and bounded structural discovery. Never scans projects."""
import json
import os
import time
from pathlib import Path

CATALOG = json.loads((Path(__file__).parent / 'agent-catalog.json').read_text())
SKIP = {'.git', '.ssh', '.gnupg', '.aws', '.azure', '.cache', '.npm', '.nvm',
        '.rustup', '.cargo', '.Trash', '.local', 'node_modules', 'dist', 'build',
        '.next', '.venv', 'venv', '__pycache__', 'tmp', 'temp', 'cache', 'Cache',
        'Caches', 'plugins', 'logs', 'Logs', 'sessions', 'history', 'Downloads'}


def absolute_env(env, key, fallback):
    value = env.get(key, '').strip()
    path = Path(os.path.expanduser(value)) if value else fallback
    return path if path.is_absolute() else fallback


def known_roots(home, env=None):
    env = os.environ if env is None else env
    config = absolute_env(env, 'XDG_CONFIG_HOME', home / '.config')
    items = []
    for definition in CATALOG['agents']:
        base = config if definition['base'] == 'config' else home
        path = base / definition['path']
        if definition.get('env'):
            fallback = home / definition['path'].split('/')[0]
            path = absolute_env(env, definition['env'], fallback) / definition['envPath']
        if definition.get('alternatives'):
            choices = [path] + [home / p for p in definition['alternatives']]
            path = next((p for p in choices if p.parent.is_dir()), path)
            for alternate in choices:
                if alternate != path and alternate.is_dir():
                    items.append((definition['agent'], definition['label'] + ' (旧目录)', alternate, False, False))
        items.append((definition['agent'], definition['label'], path, False, False))
    codex = absolute_env(env, 'CODEX_HOME', home / '.codex')
    claude = absolute_env(env, 'CLAUDE_CONFIG_DIR', home / '.claude')
    items += [('codex', 'Codex 个人', codex / 'skills', False, False),
              ('plugins', 'Codex 插件', codex / 'plugins/cache', True, True),
              ('claude-plugins', 'Claude 插件', claude / 'plugins/cache', True, True)]
    return items


def structural_roots(home, known, max_dirs=2400, max_seconds=2):
    """Only existing `skills` collections in user config areas. No symlink traversal."""
    started = time.monotonic()
    visited, found, stack, seen = 0, [], [], set()
    try:
        stack.extend((p, 0) for p in sorted(home.iterdir())
                     if p.name.startswith('.') and p.name not in SKIP and p.is_dir() and not p.is_symlink())
    except OSError:
        pass
    for area in [home / 'Library/Application Support', home / 'AppData/Roaming', home / 'AppData/Local', home / '.local/share']:
        if area.is_dir() and not area.is_symlink():
            stack.append((area, 0))
    while stack and visited < max_dirs and time.monotonic() - started < max_seconds:
        path, depth = stack.pop()
        visited += 1
        try:
            resolved = path.resolve()
            if resolved in seen:
                continue
            seen.add(resolved)
            if path.name.lower() == 'skills':
                # Do not classify arbitrary reference/source folders as Agent skill collections.
                if resolved not in known and any(
                    p.is_dir() and not p.is_symlink() and (p / 'SKILL.md').is_file()
                    and not (p / 'SKILL.md').is_symlink() for p in path.iterdir()):
                    found.append(path)
                continue
            if depth >= 4:
                continue
            children = sorted(path.iterdir(), key=lambda p: p.name)
            stack.extend((p, depth + 1) for p in reversed(children[:200])
                         if p.name not in SKIP and p.is_dir() and not p.is_symlink())
        except (OSError, ValueError):
            continue
    return found, {'visited': visited, 'truncated': bool(stack), 'seconds': round(time.monotonic() - started, 3)}
