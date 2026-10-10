"""Opt-in live integration: skills.sh search, GitHub preview/install in temp storage."""
import sys
import tempfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'app'))
from server import Store
with tempfile.TemporaryDirectory() as directory:
    base=Path(directory);store=Store(base/'store',home=base/'home',empty=True)
    results=store.remote('find-skills')['skills']
    item=next(r for r in results if r['source']=='vercel-labs/skills' and r['skillId']=='find-skills')
    preview=store.preview(item)
    assert preview['content'] and preview['files']
    store.add_root({'label':'network-test','path':str(base/'skills')})
    store.install({**item,'rootIds':[store.config['roots'][0]['id']]})
    record=store.records()[0]
    assert record['valid'] and record['source']['archiveHash']
    print(f"PASS: live search ({len(results)} results), GitHub preview ({len(preview['files'])} files), isolated install")
