"""Isolated functional regression tests; never touch the actual user's home."""
import io
import json
import sys
import tempfile
import threading
import unittest
import zipfile
import http.client
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'app'))
import server as app
from discovery import known_roots, structural_roots, CATALOG

DOC = '---\nname: demo\ndescription: A test skill\n---\n\n# Demo\n'

def fixture(path, content=DOC):
    path.mkdir(parents=True, exist_ok=True)
    (path / 'SKILL.md').write_text(content)
    return path

class StoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.home = self.base / 'home'; self.home.mkdir()
        self.store = app.Store(self.base / 'store', home=self.home, empty=True)
        for name in ['one', 'two']:
            self.store.add_root({'label': name, 'path': str(self.home / name / 'skills')})
        self.one, self.two = self.store.config['roots']
    def tearDown(self): self.temp.cleanup()
    def create(self):
        return self.store.create({'rootId': self.one['id'], 'folder': 'demo', 'content': DOC})['id']
    def rejects(self, code, fn, *args):
        with self.assertRaises(app.Problem) as ctx: fn(*args)
        self.assertEqual(ctx.exception.status, code)
    def test_create_read_update_backup(self):
        id = self.create(); detail = self.store.detail(id)
        self.assertEqual(detail['content'], DOC)
        self.store.update({'id': id, 'version': detail['version'], 'content': DOC+'Changed\n'})
        self.assertEqual(len(list((self.store.history/id).iterdir())), 1)
        self.assertEqual(next((self.store.history/id).iterdir()).read_text(), DOC)
        self.assertIn('Changed', self.store.detail(id)['content'])
    def test_create_write_failure_cleanup(self):
        with patch.object(app, 'atomic', side_effect=OSError('full disk')):
            with self.assertRaises(OSError): self.create()
        self.assertFalse((Path(self.one['path'])/'demo').exists())
    def test_copy_to_own_descendant_rejected(self):
        id=self.create();source=Path(self.store.skill(id)['path'])
        self.store.add_root({'label':'nested','path':str(source/'nested/skills')})
        root=self.store.config['roots'][-1]
        self.rejects(400,self.store.copy,{'id':id,'rootId':root['id']})
    def test_external_change_conflict(self):
        id=self.create(); old=self.store.detail(id)
        (Path(old['path'])/'SKILL.md').write_text(DOC+'external')
        self.rejects(409,self.store.update,{'id':id,'version':old['version'],'content':DOC})
    def test_duplicate_and_path_traversal(self):
        self.create()
        self.rejects(409,self.store.create,{'rootId':self.one['id'],'folder':'demo','content':DOC})
        for folder in ['../escape','/escape','.','..','bad/name','']:
            with self.subTest(folder=folder):self.rejects(400,self.store.create,{'rootId':self.one['id'],'folder':folder,'content':DOC})
    def test_document_validation(self):
        for content in ['', 'no YAML', '---\nname: demo\n---\n', DOC.replace('demo','""',1)]:
            with self.subTest(content=content):self.rejects(400,app.validate_document,content)
        for desc in ['>\n  folded\n  text','|\n  literal\n  text',"'quoted text'",'"quoted text"']:
            self.assertTrue(app.validate_document('---\nname: demo\ndescription: '+desc+'\n---\n')['valid'])
    def test_copy_includes_attachments_excludes_links_dependencies(self):
        id=self.create(); source=Path(self.store.skill(id)['path'])
        (source/'scripts').mkdir(); (source/'scripts/run.sh').write_text('echo ok');(source/'scripts/run.sh').chmod(0o755)
        (source/'node_modules').mkdir();(source/'node_modules/no').write_text('no')
        (source/'linked').symlink_to(source/'scripts/run.sh')
        new=self.store.copy({'id':id,'rootId':self.two['id']})['id']; dest=Path(self.store.skill(new)['path'])
        self.assertTrue((dest/'scripts/run.sh').exists());self.assertTrue((dest/'scripts/run.sh').stat().st_mode&0o111)
        self.assertFalse((dest/'node_modules').exists());self.assertFalse((dest/'linked').exists())
    def test_trash_restore_conflict_and_root_remove(self):
        id=self.create(); result=self.store.delete({'id':id}); self.assertFalse(self.store.records())
        self.rejects(400,self.store.remove_root,{'id':self.one['id']})
        self.create();self.rejects(409,self.store.restore,{'id':result['trashId']})
        self.store.delete({'id':id}); self.store.restore({'id':result['trashId']})
        self.assertEqual(self.store.detail(id)['content'],DOC)
    def test_system_and_plugins_readonly(self):
        base=Path(self.one['path']);fixture(base/'.system/demo'); self.one['readonly']=False
        id=self.store.records()[0]['id'];self.rejects(403,self.store.update,{'id':id,'version':'x','content':DOC});self.rejects(403,self.store.delete,{'id':id})
        self.one['readonly']=True;self.rejects(403,self.store.create,{'rootId':self.one['id'],'folder':'new','content':DOC})
    def test_symlink_delete_preserves_source(self):
        id=self.create();source=Path(self.store.skill(id)['path']);link=Path(self.two['path'])/'demo';link.parent.mkdir(parents=True);link.symlink_to(source,target_is_directory=True)
        record=next(r for r in self.store.records() if r['rootId']==self.two['id'])
        self.assertTrue(record['readonly']);self.assertEqual(record['canonicalId'],id)
        result=self.store.delete({'id':record['id']});self.assertTrue(source.exists());self.assertFalse(link.exists())
        self.store.restore({'id':result['trashId']});self.assertTrue(link.is_symlink())
    def test_outside_symlinks_hidden(self):
        outside=fixture(self.base/'outside');base=Path(self.one['path']);base.mkdir(parents=True)
        (base/'outside').symlink_to(outside);self.assertFalse(self.store.records())
    def test_root_add_remove_protected(self):
        self.rejects(409,self.store.add_root,{'label':'same','path':self.one['path']})
        self.rejects(400,self.store.add_root,{'label':'bad','path':'/'})
        self.one['readonly']=True
        self.store.add_root({'label':'nested','path':str(Path(self.one['path'])/'nested')})
        self.assertTrue(self.store.config['roots'][-1]['readonly'])
        self.store.remove_root({'id':self.two['id']});self.assertEqual(len(self.store.config['roots']),2)
    def test_reopen_persists_state(self):
        id=self.create(); reopened=app.Store(self.base/'store',home=self.home,empty=True)
        self.assertEqual(reopened.detail(id)['content'],DOC)
    def test_reveal(self):
        id=self.create()
        with patch.object(app.sys,'platform','darwin'),patch.object(app.subprocess,'Popen') as spawn:
            self.store.reveal({'id':id});self.assertEqual(spawn.call_args.args[0][0],'/usr/bin/open')
    def archive(self):
        buffer=io.BytesIO()
        with zipfile.ZipFile(buffer,'w') as z:
            z.writestr('repo-main/skills/demo/SKILL.md',DOC)
            executable=zipfile.ZipInfo('repo-main/skills/demo/scripts/run.sh');executable.external_attr=0o100755<<16;z.writestr(executable,'echo ok')
            z.writestr('repo-main/skills/demo/../escape','bad')
            z.writestr('repo-main/skills/demo/node_modules/bad','bad')
            link=zipfile.ZipInfo('repo-main/skills/demo/link');link.external_attr=0o120777<<16;z.writestr(link,'outside')
        return buffer.getvalue()
    def test_remote_preview_install_full_attachments(self):
        with patch.object(self.store,'archive',return_value=self.archive()):
            preview=self.store.preview({'source':'owner/repo','skillId':'demo'})
            self.assertEqual({f['path'] for f in preview['files']},{'SKILL.md','scripts/run.sh'});self.assertNotIn('_archive',preview)
            self.store.install({'source':'owner/repo','skillId':'demo','rootIds':[self.one['id'],self.two['id']]})
        self.assertEqual(len(self.store.records()),2)
        for r in self.store.records():
            path=Path(r['path']);self.assertTrue((path/'scripts/run.sh').stat().st_mode&0o111);self.assertEqual(r['source']['source'],'owner/repo');self.assertFalse((path.parent/'escape').exists())
    def test_install_collision_no_partial_writes(self):
        self.create()
        with patch.object(self.store,'archive',return_value=self.archive()):
            self.rejects(409,self.store.install,{'source':'owner/repo','skillId':'demo','rootIds':[self.two['id'],self.one['id']]})
        self.assertFalse((Path(self.two['path'])/'demo').exists())
    def test_install_failure_rolls_back(self):
        original=Path.write_bytes; calls=0
        def fail(path,data):
            nonlocal calls
            calls+=1
            if calls==3:raise OSError('simulated full disk')
            return original(path,data)
        with patch.object(self.store,'archive',return_value=self.archive()),patch.object(Path,'write_bytes',fail):
            with self.assertRaises(OSError): self.store.install({'source':'owner/repo','skillId':'demo','rootIds':[self.one['id'],self.two['id']]})
        self.assertFalse(self.store.records())
    def test_search_normalization_and_network_errors(self):
        response=io.BytesIO(json.dumps({'skills':[{'id':'owner/repo/demo','source':'owner/repo','name':'demo','installs':42}]}).encode())
        with patch.object(app.urllib.request,'urlopen',return_value=response):
            result=self.store.remote('demo');self.assertTrue(result['skills'][0]['installable']);self.assertIn('q=demo',result['endpoint'])
        with patch.object(app.urllib.request,'urlopen',side_effect=OSError('offline')):self.rejects(502,self.store.remote,'demo')
        self.rejects(400,self.store.remote,'')
        self.rejects(400,self.store.archive,'not a repo')

class DiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.home=Path(self.temp.name).resolve()/'home';self.home.mkdir()
    def tearDown(self):self.temp.cleanup()
    def test_catalog_environment_shared_dedup(self):
        self.assertEqual(len(CATALOG['agents']),77)
        roots=known_roots(self.home,{'XDG_CONFIG_HOME':str(self.home/'xdg'),'CODEX_HOME':str(self.home/'cx')})
        self.assertIn(self.home/'cx/skills',[r[2] for r in roots])
        store=app.Store(self.home.parent/'store',home=self.home)
        paths=[r['path'] for r in store.config['roots']];self.assertEqual(len(paths),len(set(paths)))
        shared=next(r for r in store.config['roots'] if r['path']==str(self.home/'.agents/skills'))
        self.assertGreater(len(shared['supportedAgents']),5)
    def test_heuristic_locations_confirm_and_refresh(self):
        for path in ['.unknown/skills/demo','.local/share/new-agent/skills/demo','Library/Application Support/Agent/skills/demo']:
            fixture(self.home/path)
        store=app.Store(self.home.parent/'store',home=self.home)
        pending=[r for r in store.config['roots'] if r.get('discovery')=='heuristic'];self.assertEqual(len(pending),3)
        root=pending[0];self.assertTrue(root['readonly']);store.confirm_root({'id':root['id']});self.assertFalse(root['readonly'])
        record=next(r for r in store.records() if r['rootId']==root['id']);store.update({'id':record['id'],'version':record['version'],'content':DOC+'confirmed'})
        store.discover();self.assertEqual(store.root(root['id'])['discovery'],'confirmed')
    def test_skip_projects_dependencies_symlinks_and_budget(self):
        fixture(self.home/'Documents/project/skills/demo');fixture(self.home/'.unknown/node_modules/pkg/skills/demo');fixture(self.home/'.ssh/skills/demo')
        fixture(self.home/'.real/skills/demo');(self.home/'.alias').symlink_to(self.home/'.real')
        found,report=structural_roots(self.home,set());self.assertEqual(found,[self.home/'.real/skills'])
        _,report=structural_roots(self.home,set(),max_dirs=1);self.assertTrue(report['truncated'])
    def test_known_path_is_not_pending(self):
        fixture(self.home/'.codex/skills/demo');store=app.Store(self.home.parent/'store',home=self.home)
        self.assertFalse([r for r in store.config['roots'] if r.get('discovery')=='heuristic'])
        self.assertEqual(len(store.records()),1)
    def test_removed_heuristic_stays_removed(self):
        fixture(self.home/'.unknown/skills/demo');store=app.Store(self.home.parent/'store',home=self.home)
        root=next(r for r in store.config['roots'] if r.get('discovery')=='heuristic');store.remove_root({'id':root['id']});store.discover()
        self.assertFalse(any(r['id']==root['id'] for r in store.config['roots']))
    def test_old_openclaw_path(self):
        fixture(self.home/'.clawdbot/skills/demo');roots=known_roots(self.home,{})
        self.assertIn(self.home/'.clawdbot/skills',[r[2] for r in roots])

class HTTPTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();base=Path(self.temp.name)
        self.server=app.ThreadingHTTPServer(('127.0.0.1',0),app.Handler);self.server.store=app.Store(base/'store',home=base/'home',empty=True);self.server.token='test-session'
        self.server.store.add_root({'label':'test','path':str(base/'skills')})
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
    def tearDown(self):self.server.shutdown();self.server.server_close();self.thread.join();self.temp.cleanup()
    def request(self,path,method='GET',body=None,headers=None,auth=True):
        client=http.client.HTTPConnection('127.0.0.1',self.server.server_port)
        h={'Cookie':'skilldock=test-session'} if auth else {}
        if method=='POST':h.update({'X-SkillDock':'1','Content-Type':'application/json'})
        h.update(headers or {});client.request(method,path,body=json.dumps(body) if body is not None else None,headers=h)
        r=client.getresponse();status=r.status;response=r.read();rh=dict(r.getheaders());client.close();return status,response,rh
    def test_auth_token_static_and_routes(self):
        self.assertEqual(self.request('/api/state',auth=False)[0],401)
        status,_,h=self.request('/?token=test-session',auth=False);self.assertEqual(status,302);self.assertIn('HttpOnly',h['Set-Cookie'])
        for path in ['/','/app.js','/style.css','/icon.svg','/api/state']:
            with self.subTest(path=path):self.assertEqual(self.request(path)[0],200)
        self.assertEqual(self.request('/missing')[0],404);self.assertEqual(self.request('/api/skill?id=bad')[0],404)
    def test_host_origin_and_request_guards(self):
        self.assertEqual(self.request('/api/state',headers={'Host':'evil.com'})[0],403)
        self.assertEqual(self.request('/api/discover','POST',{},headers={'Origin':'https://evil.com'})[0],403)
        self.assertEqual(self.request('/api/discover','POST',{},headers={'X-SkillDock':'0'})[0],403)
        self.assertEqual(self.request('/api/create','POST',[])[0],400)
        self.assertEqual(self.request('/api/create','POST')[0],413)
        self.assertEqual(self.request('/api/none','POST',{})[0],404)
    def test_crud_over_http(self):
        root=self.server.store.config['roots'][0]['id'];status,body,_=self.request('/api/create','POST',{'rootId':root,'folder':'demo','content':DOC});self.assertEqual(status,200);id=json.loads(body)['id']
        status,body,_=self.request('/api/skill?id='+id);self.assertEqual(status,200);version=json.loads(body)['version']
        self.assertEqual(self.request('/api/update','POST',{'id':id,'version':version,'content':DOC+'edit'})[0],200)
        status,body,_=self.request('/api/delete','POST',{'id':id});self.assertEqual(status,200)
        self.assertEqual(self.request('/api/restore','POST',{'id':json.loads(body)['trashId']})[0],200)

if __name__=='__main__':unittest.main()
