import sys,os,errno,json,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path.cwd()/'tests'))
from test_macos_seatbelt import MacOSSeatbeltTests
real_killpg=os.killpg
calls=[]
def post_reap_eperm(pid,sig):
 calls.append([pid,int(sig)])
 if len(calls)==2:raise PermissionError(errno.EPERM,'injected post-reap group cleanup')
 return real_killpg(pid,sig)
test=MacOSSeatbeltTests('test_killing_sandbox_process_group_closes_descendant_pipe')
with patch('khaos.kernel.macos_seatbelt.os.killpg',side_effect=post_reap_eperm):
 result=unittest.TestResult();test.run(result)
report={'real_first_group_signal':len(calls)>=1,'group_signal_calls':len(calls),'failures':len(result.failures),'errors':len(result.errors),'successful':result.wasSuccessful(),'error_stages':[v for _,v in result.errors]}
Path(sys.argv[1]).write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps(report,indent=2))
