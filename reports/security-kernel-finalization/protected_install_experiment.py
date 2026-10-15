"""Explicitly authorized disposable protected installation; OS prompts authorize each mutation."""
from __future__ import annotations
import json
import os
from pathlib import Path
import shlex
import subprocess
from tools.build_macos_seed import verify_app

SOURCE=Path('/Users/huangruibang/Applications/Khaos-Finalization-Disposable.app')
UPDATE=Path('/Users/huangruibang/Applications/Khaos-Finalization-Disposable-v2.app')
ROOT=Path('/Library/Application Support/Khaos')
APP=ROOT/'Finalization.app'
CERT='81E5B3D53290732C30A9D823874EBAB6E947AB55'
REPORT=Path(__file__).with_name('protected-install.json')
record={'scope':'authorized disposable protected code; state remains user owned','phases':[]}

def save():REPORT.write_text(json.dumps(record,indent=2)+'\n')

def admin(script):
    # Pass a literal script as AppleScript data; no repository code executes as root.
    command='set -eu\n'+script
    apple='do shell script '+json.dumps(command)+' with administrator privileges with prompt '+json.dumps('Khaos disposable security acceptance: /Library/Application Support/Khaos; install, update, rollback, remove only test apps.')
    result=subprocess.run(['/usr/bin/osascript','-e',apple],capture_output=True,text=True,timeout=900)
    if result.returncode:raise RuntimeError('administrator operation failed: '+result.stderr.strip())

def verify_shell(app):
    text=''
    for suffix,identifier in (('', 'org.khaos.Seed'),('/Contents/XPCServices/KhaosAgentHost.xpc','org.khaos.Seed.AgentHost'),('/Contents/XPCServices/KernelProduction.xpc','org.khaos.Seed.KernelProduction'),('/Contents/XPCServices/KernelSnapshotBroker.xpc','org.khaos.Seed.KernelSnapshotBroker')):
        requirement=f'identifier "{identifier}" and certificate leaf = H"{CERT}"'
        text+='/usr/bin/codesign --verify --deep --strict '+shlex.quote('-R='+requirement)+' '+shlex.quote(str(app)+suffix)+'\n'
    return text

def launch(phase):
    verify_app(APP,CERT)
    out=Path('/tmp/khaos-protected-'+phase+'.stdout');err=out.with_suffix('.stderr')
    result=subprocess.run(['/usr/bin/open','-n','-W','-a',str(APP),'--stdout',str(out),'--stderr',str(err),'--args','--bootstrap-check'],capture_output=True,text=True,timeout=60)
    output=out.read_text().strip() if out.exists() else ''
    assert result.returncode==0 and output=='kernel-and-snapshot-broker-peer-authentication=verified',(phase,result.returncode,output)
    verify_app(APP,CERT)
    record['phases'].append({'phase':phase,'bootstrap':output,'signature':'PASS','build_version':__import__('plistlib').loads((APP/'Contents/Info.plist').read_bytes())['CFBundleVersion']});save()


def main():
    assert not os.path.lexists(ROOT),'Refuse to touch a pre-existing Khaos installation'
    for parent in ROOT.parents:
        assert not parent.is_symlink() and not os.access(parent,os.W_OK),str(parent)
    verify_app(SOURCE,CERT)
    verify_app(UPDATE,CERT)
    assert __import__('plistlib').loads((UPDATE/'Contents/Info.plist').read_bytes())['CFBundleVersion']=='2'
    root=shlex.quote(str(ROOT));app=shlex.quote(str(APP));source=shlex.quote(str(SOURCE))
    admin(f'test ! -e {root}\n/bin/mkdir -m 755 {root}\n/usr/sbin/chown root:wheel {root}\n/usr/bin/ditto {source} {app}\n/usr/sbin/chown -R root:wheel {app}\n'+verify_shell(APP))
    record['permissions']=[]
    for path in (Path('/'),Path('/Library'),ROOT.parent,ROOT,APP):
        info=path.lstat();record['permissions'].append({'path':str(path),'uid':info.st_uid,'gid':info.st_gid,'mode':oct(info.st_mode&0o7777),'writable':os.access(path,os.W_OK),'symlink':path.is_symlink()})
        assert info.st_uid==0 and not os.access(path,os.W_OK) and not path.is_symlink()
    acl=subprocess.run(['/bin/ls','-lde',str(ROOT.parent),str(ROOT),str(APP)],capture_output=True,text=True,check=True).stdout
    record['acl_observation']=acl
    attacks=[]
    targets=(APP/'Contents/MacOS/KhaosSeed',APP/'Contents/XPCServices/KernelProduction.xpc/Contents/MacOS/KernelProduction')
    for target in targets:
        try:
            descriptor=os.open(target,os.O_WRONLY);os.close(descriptor)
            attacks.append({'operation':'open-write','target':str(target),'denied':False})
        except OSError as error:attacks.append({'operation':'open-write','target':str(target),'denied':True,'errno':error.errno})
    for target in (APP,APP/'Contents/XPCServices/KernelProduction.xpc',ROOT):
        try:
            target.rename(target.with_name(target.name+'.attack'))
            attacks.append({'operation':'rename','target':str(target),'denied':False})
        except OSError as error:attacks.append({'operation':'rename','target':str(target),'denied':True,'errno':error.errno})
    try:
        (ROOT/'current').symlink_to(SOURCE)
        attacks.append({'operation':'create-symlink','denied':False})
    except OSError as error:attacks.append({'operation':'create-symlink','denied':True,'errno':error.errno})
    record['same_uid_attacks']=attacks;save();assert all(a['denied'] for a in attacks)
    launch('install');launch('restart')
    new=ROOT/'Next.app';old=ROOT/'Previous.app'
    admin(f'/usr/bin/ditto '+shlex.quote(str(UPDATE))+' '+shlex.quote(str(new))+'\n/usr/sbin/chown -R root:wheel '+shlex.quote(str(new))+'\n'+verify_shell(new)+f'/bin/mv {app} '+shlex.quote(str(old))+'\n/bin/mv '+shlex.quote(str(new))+' '+app+'\n')
    launch('upgrade')
    admin(f'/bin/mv {app} '+shlex.quote(str(new))+'\n/bin/mv '+shlex.quote(str(old))+' '+app+'\n')
    launch('rollback')
    # Exact disposable destinations only; never delete Plugin state or generic parents.
    admin(f'/bin/rm -rf {app} '+shlex.quote(str(new))+f'\n/bin/rmdir {root}\n')
    record['uninstalled']=not ROOT.exists();record['distinct_version_upgrade']='PASS (build 1 -> 2 -> 1; no state schema migration)'
    assert [p['build_version'] for p in record['phases']]==['1','1','2','1'];record['protected_state']='NOT PROVEN';save()

if __name__=='__main__':main()
