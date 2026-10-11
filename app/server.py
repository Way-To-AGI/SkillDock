#!/usr/bin/env python3
"""SkillDock local API. Python 3.10+, standard library only."""
import argparse
import hashlib
import hmac
import io
import json
import os
import re
import secrets
import shutil
import stat
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from datetime import datetime, timezone
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path, PurePosixPath

from discovery import known_roots, structural_roots, CATALOG

WEB = Path(__file__).parent / 'web'
EXCLUDED = {'.git', '.venv', 'venv', 'node_modules', 'dist', 'build', '.next',
            '__pycache__', 'tmp', 'temp', '.DS_Store'}
LOCK = threading.RLock()
LIMIT = 2 * 1024 * 1024
REPO_LIMIT = 60 * 1024 * 1024


class Problem(Exception):
    def __init__(self, message, status=400):
        self.message, self.status = message, status


def digest(value):
    return hashlib.sha256(str(value).encode()).hexdigest()[:24]


def inside(path, parent):
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def atomic(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix='.skilldock-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            stream.write(text)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def metadata(content):
    match = re.match(r'^\ufeff?---\s*\n(.*?)\n---\s*(?:\n|$)', content, re.S)
    if not match:
        return {'name': '', 'description': '', 'valid': False}
    front = match.group(1).splitlines()
    values = {}
    for i, line in enumerate(front):
        item = re.match(r'^(name|description):\s*(.*)$', line)
        if not item:
            continue
        key, value = item.groups()
        if value in {'>', '|', '>-', '|-', '>+', '|+'} or not value:
            body = []
            for following in front[i + 1:]:
                if following and not following[0].isspace():
                    break
                body.append(following.strip())
            value = ('\n' if value.startswith('|') else ' ').join(body).strip()
        elif value.startswith('"'):
            try:
                value = json.loads(value)
            except ValueError:
                value = value.strip('"')
        elif value.startswith("'") and value.endswith("'"):
            value = value[1:-1].replace("''", "'")
        values[key] = value
    return {**values, 'valid': all(isinstance(values.get(k), str) and bool(values[k].strip()) for k in ('name', 'description'))}


def validate_document(content):
    if not isinstance(content, str) or len(content.encode()) > LIMIT:
        raise Problem('技能文档不能超过 2 MB')
    meta = metadata(content)
    if not meta['valid']:
        raise Problem('SKILL.md 必须以 YAML frontmatter 开头，并包含非空的 name 和 description')
    if len(meta['name']) > 150 or '\n' in meta['name']:
        raise Problem('技能名称过长或包含换行')
    return meta


def slug(value):
    if not isinstance(value, str) or not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9._-]{0,99}', value):
        raise Problem('目录名请使用字母、数字、点、下划线或连字符，最多 100 字符')
    return value


def now():
    return datetime.now(timezone.utc).isoformat()


class Store:
    def __init__(self, directory, home=None, empty=False):
        self.directory = Path(directory).resolve()
        self.directory.mkdir(parents=True, exist_ok=True)
        self.file = self.directory / 'settings.json'
        self.trash = self.directory / 'trash'
        self.history = self.directory / 'history'
        self.cache = self.directory / 'cache'
        self.home = Path(home or Path.home()).resolve()
        self.discovery_env = {} if home is not None else None
        self.empty = empty
        self.last_scan = 0
        self.scan_report = {}
        self.config = {'roots': [], 'trash': [], 'activity': [], 'ignoredDiscoveryPaths': []}
        if self.file.exists():
            self.config = json.loads(self.file.read_text())
        self.config.setdefault('ignoredDiscoveryPaths', [])
        for root in self.config['roots']:
            root.setdefault('scope', 'global' if root.get('builtin') else 'custom')
        if not empty:
            self.discover()
        else:
            self.save()

    def discover(self, body=None):
        if self.empty:
            return {'message': '隔离模式不扫描真实目录', 'added': 0}
        added = 0
        existing = {Path(r['path']).resolve(): r for r in self.config['roots']}
        for agent, label, path, readonly, recursive in known_roots(self.home, self.discovery_env):
            resolved = path.resolve()
            if resolved in existing:
                root = existing[resolved]
                supported = root.setdefault('supportedAgents', [root['label']])
                if label not in supported:
                    supported.append(label)
                continue
            root = {'id': digest(path), 'agent': agent, 'label': label, 'path': str(path),
                    'readonly': readonly, 'recursive': recursive, 'builtin': True,
                    'scope': 'global', 'discovery': 'catalog', 'supportedAgents': [label],
                    'origin': 'plugin' if recursive else 'local'}
            self.config['roots'].append(root)
            existing[resolved] = root
            added += 1
        for root in self.config['roots']:
            if root.get('discovery') == 'catalog' and len(root.get('supportedAgents', [])) > 1:
                root['agent'] = 'shared-' + root['id'][:8]
                root['label'] = '共享技能（' + ('XDG' if Path(root['path']).parent.name == 'agents' else '.agents') + '）'
        candidates, report = structural_roots(self.home, set(existing))
        for path in candidates:
            if str(path.resolve()) in self.config['ignoredDiscoveryPaths']:
                continue
            label = path.parent.name.lstrip('.') + ' · 待确认'
            root = {'id': digest(path), 'agent': 'discovered-' + digest(path)[:8], 'label': label,
                    'path': str(path), 'readonly': True, 'recursive': False, 'builtin': False,
                    'scope': 'global', 'discovery': 'heuristic', 'origin': 'local'}
            self.config['roots'].append(root)
            existing[path.resolve()] = root
            added += 1
        self.scan_report = {**report, 'catalogAgents': len(CATALOG['agents']),
                            'pending': sum(r.get('discovery') == 'heuristic' for r in self.config['roots'])}
        self.last_scan = time.monotonic()
        self.save()
        return {'message': f'扫描完成，新增 {added} 个目录', 'added': added, 'report': self.scan_report}

    def confirm_root(self, body):
        root = self.root(body.get('id'))
        if root.get('discovery') != 'heuristic':
            raise Problem('这个目录不需要确认')
        path = Path(root['path']).resolve()
        if '.system' in path.parts or any(r['readonly'] and r.get('discovery') != 'heuristic'
                and inside(path, Path(r['path']).resolve()) for r in self.config['roots']):
            raise Problem('受保护目录不能开放编辑', 403)
        root['discovery'] = 'confirmed'
        root['readonly'] = False
        root['label'] = root['label'].removesuffix(' · 待确认')
        self.scan_report['pending'] = sum(r.get('discovery') == 'heuristic' for r in self.config['roots'])
        self.event('确认管理目录', root['label'])
        return {'message': '已开放这个目录的技能管理'}

    def save(self):
        atomic(self.file, json.dumps(self.config, ensure_ascii=False, indent=2))

    def event(self, action, name, agent=''):
        self.config['activity'].insert(0, {'action': action, 'name': name, 'agent': agent, 'time': now()})
        self.config['activity'] = self.config['activity'][:80]
        self.save()

    def root(self, identity, writable=False):
        result = next((r for r in self.config['roots'] if r['id'] == identity), None)
        if not result:
            raise Problem('技能目录不存在', 404)
        if writable and result['readonly']:
            raise Problem('这个目录只读；未知目录请先确认，内置或插件技能可复制后编辑', 403)
        return result

    def records(self):
        records = []
        for root in self.config['roots']:
            base = Path(root['path'])
            if not base.is_dir():
                continue
            paths = []
            if root['recursive']:
                for folder, dirs, files in os.walk(base, followlinks=False):
                    rel = Path(folder).relative_to(base)
                    dirs[:] = [d for d in dirs if d not in EXCLUDED and len(rel.parts) < 8]
                    if 'SKILL.md' in files:
                        paths.append(Path(folder))
            else:
                try:
                    for child in base.iterdir():
                        if child.name in EXCLUDED:
                            continue
                        if (child / 'SKILL.md').is_file():
                            paths.append(child)
                        elif child.name == '.system' and child.is_dir():
                            paths.extend(p for p in child.iterdir() if (p / 'SKILL.md').is_file())
                except OSError:
                    continue
            for folder in paths:
                try:
                    resolved = folder.resolve()
                    allowed = any(inside(resolved, Path(r['path']).resolve()) for r in self.config['roots'])
                    if not allowed:
                        continue
                    doc = folder / 'SKILL.md'
                    if not any(inside(doc.resolve(), Path(r['path']).resolve()) for r in self.config['roots']):
                        continue
                    if doc.stat().st_size > LIMIT:
                        continue
                    content = doc.read_text(encoding='utf-8', errors='replace')
                    meta = metadata(content)
                    linked = folder.is_symlink()
                    readonly = root['readonly'] or '.system' in folder.relative_to(base).parts or linked or doc.is_symlink()
                    records.append({'id': digest(folder), 'name': meta.get('name') or folder.name,
                        'description': meta.get('description', ''), 'valid': meta['valid'],
                        'folder': folder.name, 'path': str(folder), 'resolvedPath': str(resolved), 'rootId': root['id'],
                        'agent': root['agent'], 'agentLabel': root['label'], 'readonly': readonly,
                        'scope': root.get('scope', 'global'),
                        'linked': linked, 'modified': doc.stat().st_mtime,
                        'origin': 'system' if '.system' in folder.parts else root.get('origin', 'plugin' if root['recursive'] else 'local'),
                        'version': digest(content), 'source': self.source(folder)})
                except (OSError, ValueError):
                    continue
        groups = {}
        for item in records:
            groups.setdefault(item['resolvedPath'], []).append(item)
        for group in groups.values():
            source = next((r for r in group if r['scope'] == 'global' and not r['readonly']), None)
            agents = list(dict.fromkeys(r['agentLabel'] for r in group))
            for item in group:
                item['usedBy'] = agents
                item['canonicalId'] = source['id'] if source else None
        return sorted(records, key=lambda r: (r['name'].lower(), r['agentLabel']))

    def source(self, folder):
        file = folder / '.skilldock-source.json'
        try:
            return json.loads(file.read_text()) if file.is_file() else None
        except (OSError, ValueError):
            return None

    def skill(self, identity, writable=False):
        result = next((r for r in self.records() if r['id'] == identity), None)
        if not result:
            raise Problem('找不到这个技能，请刷新列表', 404)
        if writable and result['readonly']:
            raise Problem('这个技能只读；请先复制到个人技能目录', 403)
        return result

    def state(self):
        if not self.empty and time.monotonic() - self.last_scan > 30:
            self.discover()
        skills = self.records()
        roots = [{**r, 'exists': Path(r['path']).is_dir(),
                  'count': sum(s['rootId'] == r['id'] for s in skills)} for r in self.config['roots']]
        return {'skills': skills, 'roots': roots, 'trash': self.config['trash'],
                'activity': self.config['activity'], 'version': '1.4.0', 'discovery': self.scan_report}

    def detail(self, identity):
        item = self.skill(identity)
        folder = Path(item['path'])
        files = []
        for base, dirs, names in os.walk(folder, followlinks=False):
            dirs[:] = [d for d in dirs if d not in EXCLUDED and not (Path(base) / d).is_symlink()]
            for name in names:
                p = Path(base) / name
                if name not in EXCLUDED and not p.is_symlink():
                    files.append({'path': str(p.relative_to(folder)), 'size': p.stat().st_size})
            if len(files) > 500:
                break
        return {**item, 'content': (folder / 'SKILL.md').read_text(errors='replace'), 'files': files[:500]}

    def destination(self, root_id, name):
        root = self.root(root_id, True)
        base = Path(root['path'])
        target = base / slug(name)
        if base.is_symlink():
            raise Problem('目标根目录是符号链接，请添加实际目录再操作')
        if target.exists() or target.is_symlink():
            raise Problem(f'{root["label"]} 已有同名技能：{name}，请选择其他目录名', 409)
        if not inside(target.resolve(), base.resolve()):
            raise Problem('目标路径越界', 403)
        return root, target

    def create(self, body):
        content = body.get('content', '')
        meta = validate_document(content)
        root, target = self.destination(body.get('rootId'), body.get('folder'))
        target.mkdir(parents=True)
        try:
            atomic(target / 'SKILL.md', content)
        except Exception:
            shutil.rmtree(target, ignore_errors=True)
            raise
        self.event('创建', meta['name'], root['label'])
        return {'id': digest(target), 'message': '技能已创建'}

    def update(self, body):
        item = self.skill(body.get('id'), True)
        content = body.get('content', '')
        validate_document(content)
        path = Path(item['path']) / 'SKILL.md'
        if body.get('version') != digest(path.read_text(errors='replace')):
            raise Problem('文件已被其他应用修改，请重新打开后保存', 409)
        history = self.history / item['id']
        history.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, history / f'{time.time_ns()}-SKILL.md')
        atomic(path, content)
        self.event('编辑', item['name'], item['agentLabel'])
        return {'message': '已保存，原版本已备份', 'version': digest(content)}

    def delete(self, body):
        item = self.skill(body.get('id'))
        root = self.root(item['rootId'])
        if root['readonly'] or item['origin'] == 'system' or (item['readonly'] and not item['linked']):
            raise Problem('内置和插件技能不能从这里删除', 403)
        trash_id = secrets.token_hex(12)
        destination = self.trash / trash_id
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(item['path'], str(destination))
        entry = {'id': trash_id, 'name': item['name'], 'original': item['path'],
                 'agentLabel': item['agentLabel'], 'rootId': item['rootId'], 'time': now()}
        self.config['trash'].insert(0, entry)
        self.event('移入回收站', item['name'], item['agentLabel'])
        return {'message': '技能已移入回收站，可以恢复', 'trashId': trash_id}

    def restore(self, body):
        item = next((x for x in self.config['trash'] if x['id'] == body.get('id')), None)
        if not item:
            raise Problem('回收站条目不存在', 404)
        self.root(item['rootId'], True)
        path = Path(item['original'])
        if path.exists() or path.is_symlink():
            raise Problem('原目录已有同名技能，请先处理冲突', 409)
        path.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(self.trash / item['id']), str(path))
        self.config['trash'].remove(item)
        self.event('恢复', item['name'], item['agentLabel'])
        return {'message': '技能已恢复'}

    def copy(self, body):
        item = self.skill(body.get('id'))
        root, target = self.destination(body.get('rootId'), body.get('folder') or item['folder'])
        source = Path(item['path']).resolve()
        if inside(target.resolve(), source):
            raise Problem('不能将技能复制到自身的子目录', 400)
        def ignore(folder, names):
            return [n for n in names if n in EXCLUDED or (Path(folder) / n).is_symlink()]
        try:
            shutil.copytree(source, target, ignore=ignore)
        except Exception:
            if target.exists():
                shutil.rmtree(target)
            raise
        self.event('复制', item['name'], root['label'])
        return {'message': f'已复制到 {root["label"]}，包含技能附件', 'id': digest(target)}

    def add_root(self, body):
        label = str(body.get('label', '')).strip()
        raw = str(body.get('path', '')).strip()
        if not label or not raw:
            raise Problem('请输入名称和目录路径')
        path = Path(os.path.expanduser(raw))
        if path == Path('/') or path == Path.home() or not path.is_absolute():
            raise Problem('请选择具体的 skills 目录')
        if path.exists() and not path.is_dir():
            raise Problem('这个路径不是文件夹')
        if any(Path(r['path']).resolve() == path.resolve() for r in self.config['roots']):
            raise Problem('这个目录已经添加', 409)
        protected = any((r['readonly'] and inside(path.resolve(), Path(r['path']).resolve()))
                        for r in self.config['roots']) or '.system' in path.resolve().parts
        item = {'id': digest(path), 'agent': 'custom', 'label': label, 'path': str(path),
                'readonly': protected or bool(body.get('readonly', False)), 'recursive': False, 'builtin': False,
                'scope': 'global' if body.get('scope', 'global') == 'global' else 'custom'}
        self.config['roots'].append(item)
        ignored = self.config['ignoredDiscoveryPaths']
        if str(path.resolve()) in ignored:
            ignored.remove(str(path.resolve()))
        self.event('添加目录', label)
        return {'message': '目录已添加；文件夹会在首次创建技能时建立'}

    def remove_root(self, body):
        root = self.root(body.get('id'))
        if root.get('builtin'):
            raise Problem('默认目录不能移除')
        if any(x['rootId'] == root['id'] for x in self.config['trash']):
            raise Problem('请先恢复这个目录在回收站中的技能')
        self.config['roots'].remove(root)
        if root.get('discovery') in {'heuristic', 'confirmed'}:
            self.config['ignoredDiscoveryPaths'].append(str(Path(root['path']).resolve()))
        self.event('移除目录', root['label'])
        return {'message': '已从管理列表移除，磁盘文件保留'}

    def reveal(self, body):
        path = Path(self.skill(body['id'])['path']) if body.get('id') else Path(self.root(body.get('rootId'))['path'])
        if not path.exists():
            raise Problem('目录尚未建立')
        if sys.platform == 'darwin':
            subprocess.Popen(['/usr/bin/open', '-R', str(path)])
        return {'message': '已在 Finder 中显示'}

    def remote(self, query):
        query = query.strip()
        if not query or len(query) > 150:
            raise Problem('请输入 1–150 字符的搜索词')
        url = 'https://skills.sh/api/search?' + urllib.parse.urlencode({'q': query, 'limit': 30})
        req = urllib.request.Request(url, headers={'User-Agent': 'SkillDock/1.0', 'Accept': 'application/json'})
        try:
            with urllib.request.urlopen(req, timeout=25) as response:
                data = json.loads(response.read(LIMIT))
        except (OSError, ValueError) as error:
            raise Problem(f'skills.sh 暂时不可用：{error}', 502)
        results = []
        for item in data.get('skills', []):
            source = str(item.get('source', ''))
            identifier = str(item.get('skillId') or item.get('id', '').split('/')[-1])
            results.append({'name': item.get('name') or identifier, 'skillId': identifier,
                            'source': source, 'id': item.get('id', ''),
                            'installs': item.get('installs', 0),
                            'url': 'https://skills.sh/' + urllib.parse.quote(str(item.get('id', '')), safe='/'),
                            'installable': bool(re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', source))})
        return {'skills': results, 'query': query, 'endpoint': url}

    def archive(self, source):
        if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', source):
            raise Problem('这个来源不是公开 GitHub 仓库，暂时只能查看 skills.sh 详情')
        cache = self.cache / (digest(source) + '.zip')
        if cache.exists() and time.time() - cache.stat().st_mtime < 600:
            return cache.read_bytes()
        req = urllib.request.Request(f'https://codeload.github.com/{source}/zip/HEAD',
                                     headers={'User-Agent': 'SkillDock/1.0'})
        try:
            with urllib.request.urlopen(req, timeout=45) as response:
                data = response.read(REPO_LIMIT + 1)
            if len(data) > REPO_LIMIT:
                raise Problem('仓库超过 60 MB，请使用本地导入')
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                infos = archive.infolist()
                if len(infos) > 20000 or sum(x.file_size for x in infos) > 200 * 1024 * 1024:
                    raise Problem('仓库解压内容过大，请使用本地导入')
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_bytes(data)
            return data
        except (OSError, zipfile.BadZipFile) as error:
            raise Problem(f'无法获取 GitHub 仓库：{error}', 502)

    def remote_skill(self, source, name):
        slug(name)
        data = self.archive(source)
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            candidates = []
            for info in archive.infolist():
                path = PurePosixPath(info.filename)
                if path.is_absolute() or '..' in path.parts or stat.S_ISLNK(info.external_attr >> 16):
                    continue
                if path.name != 'SKILL.md' or any(x in EXCLUDED for x in path.parts) or info.file_size > LIMIT:
                    continue
                content = archive.read(info).decode('utf-8', errors='replace')
                meta = metadata(content)
                if meta.get('name') == name or path.parent.name == name:
                    candidates.append((len(path.parts), str(path.parent), content, meta))
            if not candidates:
                raise Problem('仓库内未找到对应 SKILL.md；来源可能已更新', 404)
            candidates.sort(key=lambda c: c[0])
            _, prefix, content, meta = candidates[0]
            files = []
            for info in archive.infolist():
                if not info.filename.startswith(prefix + '/') or info.is_dir():
                    continue
                rel = PurePosixPath(info.filename[len(prefix) + 1:])
                if rel.is_absolute() or '..' in rel.parts or any(x in EXCLUDED for x in rel.parts):
                    continue
                if stat.S_ISLNK(info.external_attr >> 16):
                    continue
                files.append({'path': str(rel), 'size': info.file_size})
            return {'source': source, 'skillId': name, 'content': content, 'name': meta.get('name') or name,
                    'description': meta.get('description', ''), 'files': files, '_archive': data, '_prefix': prefix}

    def preview(self, body):
        item = self.remote_skill(body.get('source', ''), body.get('skillId', ''))
        return {k: v for k, v in item.items() if not k.startswith('_')}

    def install(self, body):
        item = self.remote_skill(body.get('source', ''), body.get('skillId', ''))
        validate_document(item['content'])
        ids = body.get('rootIds', [])
        if not isinstance(ids, list) or not ids or len(ids) > 15 or len(set(ids)) != len(ids):
            raise Problem('请选择至少一个目标 agent')
        targets = [self.destination(r, body.get('folder') or item['skillId']) for r in ids]
        written = []
        try:
            with zipfile.ZipFile(io.BytesIO(item['_archive'])) as archive:
                for root, target in targets:
                    target.mkdir(parents=True)
                    written.append(target)
                    for file in item['files']:
                        destination = target / file['path']
                        destination.parent.mkdir(parents=True, exist_ok=True)
                        destination.write_bytes(archive.read(item['_prefix'] + '/' + file['path']))
                        mode = archive.getinfo(item['_prefix'] + '/' + file['path']).external_attr >> 16
                        if mode & 0o111:
                            destination.chmod(0o755)
                    atomic(target / '.skilldock-source.json', json.dumps({
                        'source': item['source'], 'skillId': item['skillId'], 'installedAt': now(),
                        'archiveHash': hashlib.sha256(item['_archive']).hexdigest()}, ensure_ascii=False))
            for root, target in targets:
                self.event('安装', item['name'], root['label'])
        except Exception:
            for target in written:
                shutil.rmtree(target, ignore_errors=True)
            raise
        return {'message': f'已安装到 {len(targets)} 个 agent，包含全部技能附件'}


class Handler(BaseHTTPRequestHandler):
    server_version = 'SkillDock/1.0'

    def log_message(self, *_):
        pass

    def send(self, status, body, kind='application/json; charset=utf-8', cookie=None, location=None):
        data = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header('Content-Type', kind)
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'")
        if cookie:
            self.send_header('Set-Cookie', cookie)
        if location:
            self.send_header('Location', location)
        self.end_headers()
        self.wfile.write(data)

    def authorized(self):
        if self.headers.get('Host') not in {f'127.0.0.1:{self.server.server_port}', f'localhost:{self.server.server_port}'}:
            raise Problem('非法 Host', 403)
        jar = SimpleCookie()
        try:
            jar.load(self.headers.get('Cookie', ''))
            value = jar.get('skilldock')
            if not value or not hmac.compare_digest(value.value, self.server.token):
                raise Problem('请从 SkillDock 桌面窗口打开应用', 401)
        except Exception as error:
            if isinstance(error, Problem):
                raise
            raise Problem('无效会话', 401)

    def do_GET(self):
        try:
            url = urllib.parse.urlsplit(self.path)
            query = urllib.parse.parse_qs(url.query)
            if url.path == '/' and hmac.compare_digest(query.get('token', [''])[0], self.server.token):
                return self.send(302, b'', cookie=f'skilldock={self.server.token}; HttpOnly; SameSite=Strict; Path=/', location='/')
            self.authorized()
            if url.path == '/api/state':
                with LOCK:
                    return self.send(200, self.server.store.state())
            if url.path == '/api/skill':
                with LOCK:
                    return self.send(200, self.server.store.detail(query.get('id', [''])[0]))
            if url.path == '/api/search':
                return self.send(200, self.server.store.remote(query.get('q', [''])[0]))
            static = {'/': ('index.html', 'text/html; charset=utf-8'),
                      '/app.js': ('app.js', 'text/javascript; charset=utf-8'),
                      '/style.css': ('style.css', 'text/css; charset=utf-8'),
                      '/icon.svg': ('icon.svg', 'image/svg+xml')}
            if url.path not in static:
                raise Problem('页面不存在', 404)
            filename, kind = static[url.path]
            self.send(200, (WEB / filename).read_bytes(), kind)
        except Problem as error:
            self.send(error.status, {'error': error.message})
        except Exception as error:
            print(f'API error: {type(error).__name__}: {error}', file=sys.stderr, flush=True)
            self.send(500, {'error': '操作失败，请检查目录权限或应用日志'})

    def do_POST(self):
        try:
            self.authorized()
            if self.headers.get('X-SkillDock') != '1':
                raise Problem('缺少请求标识', 403)
            origin = self.headers.get('Origin')
            if origin and origin != f'http://{self.headers.get("Host")}':
                raise Problem('跨来源请求被拒绝', 403)
            length = int(self.headers.get('Content-Length', 0))
            if length <= 0 or length > LIMIT:
                raise Problem('请求体过大或为空', 413)
            body = json.loads(self.rfile.read(length))
            if not isinstance(body, dict):
                raise Problem('请求格式无效')
            operations = {'/api/create': 'create', '/api/update': 'update', '/api/delete': 'delete',
                '/api/restore': 'restore', '/api/copy': 'copy', '/api/roots/add': 'add_root',
                '/api/discover': 'discover', '/api/roots/confirm': 'confirm_root',
                '/api/roots/remove': 'remove_root', '/api/reveal': 'reveal',
                '/api/preview': 'preview', '/api/install': 'install'}
            method = operations.get(self.path)
            if not method:
                raise Problem('接口不存在', 404)
            # Preview downloads do not block local reads. Mutations are serialized.
            if method == 'preview':
                result = getattr(self.server.store, method)(body)
            else:
                with LOCK:
                    result = getattr(self.server.store, method)(body)
            self.send(200, result)
        except Problem as error:
            self.send(error.status, {'error': error.message})
        except (ValueError, TypeError, KeyError):
            self.send(400, {'error': '请求参数无效'})
        except Exception as error:
            print(f'API error: {type(error).__name__}: {error}', file=sys.stderr, flush=True)
            self.send(500, {'error': '操作失败，请检查目录权限或应用日志'})


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--data', default=str(Path(__file__).parent.parent / 'data'))
    parser.add_argument('--port', type=int, default=0)
    parser.add_argument('--home')
    parser.add_argument('--empty', action='store_true')
    args = parser.parse_args()
    server = ThreadingHTTPServer(('127.0.0.1', args.port), Handler)
    server.daemon_threads = True
    server.store = Store(args.data, args.home, args.empty)
    server.token = secrets.token_urlsafe(32)
    print(f'SKILLDOCK_URL=http://127.0.0.1:{server.server_port}/?token={server.token}', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
