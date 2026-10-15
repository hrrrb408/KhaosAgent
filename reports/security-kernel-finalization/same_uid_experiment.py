"""Disposable same-UID counterexamples; never touches the actual Plugin Store."""
from __future__ import annotations
import hashlib
import hmac
import json
import os
from pathlib import Path
import subprocess
import tempfile
from khaos.kernel import plugin_lifecycle as lifecycle


def main():
    report = {"uid": os.getuid(), "administrator_authorization": False, "scope": "disposable files only"}
    report['ancestors'] = []
    for name in ('/', '/Applications', '/Library', '/Library/Application Support', str(Path.home()), str(Path.home() / 'Applications')):
        path = Path(name)
        if not path.exists():
            report['ancestors'].append({'path': name, 'exists': False})
            continue
        info = path.lstat()
        report['ancestors'].append({'path':name, 'uid': info.st_uid, 'gid':info.st_gid,
                                   'mode':oct(info.st_mode & 0o7777), 'writable':os.access(path, os.W_OK), 'symlink':path.is_symlink()})
    with tempfile.TemporaryDirectory(prefix='khaos-same-uid-') as temporary:
        root = Path(temporary)
        store = root / 'store'
        store.mkdir(mode=0o700)
        fd = os.open(store, os.O_RDONLY | os.O_DIRECTORY)
        try:
            key = lifecycle._read_key(fd, create=True)
            candidate_root = Path(__file__).resolve().parents[2] / "examples/memory"
            candidate = lifecycle.admit_candidate(store, (candidate_root / "manifest.json").read_bytes(), (candidate_root / "plugin.py").read_bytes())
            lifecycle.activate_candidate(store, candidate.candidate_digest, candidate.manifest_digest, candidate.scope_digest, expected_generation=0, now=100)
            # Separate unconfined process replaces both files, despite key mode 0400.
            attack = '''import hashlib,hmac,json,os,pathlib,sys
p=pathlib.Path(sys.argv[1]); key=b"X"*32
state=json.loads((p/'activation.json').read_text())['state'];state['generation']=17
canonical=lambda value:json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=True).encode('ascii')
for name in ('activation.key','activation.json'):(p/name).unlink()
(p/'activation.key').write_bytes(key);os.chmod(p/'activation.key',0o400)
(p/'activation.json').write_bytes(canonical({'state':state,'mac':hmac.new(key,canonical(state),hashlib.sha256).hexdigest()}));os.chmod(p/'activation.json',0o600)
'''
            result = subprocess.run([__import__('sys').executable, '-I', '-c', attack, str(store)], capture_output=True)
            assert result.returncode == 0
            state, replacement = lifecycle._read_state(fd)
            report['co_replaced_key_state_accepted'] = state['generation'] == 17 and replacement != key
            assert report['co_replaced_key_state_accepted']
        finally:
            os.close(fd)
        app = root / 'Demo.app';app.mkdir();file = app / 'kernel';file.write_text('original');file.chmod(0o400);app.chmod(0o500)
        # Owning the parent permits whole-directory replacement, regardless of file mode.
        app.rename(root / 'old.app');app.mkdir();(app/'kernel').write_text('replacement')
        report['readonly_owned_bundle_replaced'] = (app/'kernel').read_text() == 'replacement'
        (root/'old.app').chmod(0o700)
    report['temporary_artifacts_removed'] = not root.exists()
    print(json.dumps(report, indent=2))

if __name__ == '__main__':main()
