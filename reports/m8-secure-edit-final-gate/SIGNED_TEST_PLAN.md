# Signed Product Test Plan

## Attempt A2-REPLAY-01 — executed under the user's one-time authorization

- Purpose: Replay the existing Candidate B fixed Staged Replacement after correcting the prior test assertion.
- Model/data flow: deterministic signed Runner feasibility fixture; provider=null; no remote model or remote data flow.
- Workspace: disposable acceptance fixture containing synthetic tags.py and a canary.
- Exact argv:

```json
[
  "python3",
  "-I",
  "-B",
  "-c",
  "exec(\"import json, os, stat, sys\\nfrom pathlib import Path\\np=Path(sys.argv[1]); old=json.loads(sys.argv[2]); new=json.loads(sys.argv[3]); st=p.lstat()\\nif not stat.S_ISREG(st.st_mode): raise SystemExit(20)\\ns=p.read_text(encoding=\\\"utf-8\\\"); i=s.find(old)\\nif not old or i<0 or s.find(old,i+1)>=0 or old==new: raise SystemExit(21)\\nd=(s[:i]+new+s[i+len(old):]).encode(\\\"utf-8\\\"); q=p.with_name(\\\".khaos-edit-\\\"+os.urandom(16).hex())\\nu=os.umask(0)\\ntry: fd=os.open(q,os.O_WRONLY|os.O_CREAT|os.O_EXCL,stat.S_IMODE(st.st_mode))\\nfinally: os.umask(u)\\ntry:\\n    with os.fdopen(fd,\\\"wb\\\") as f: f.write(d); f.flush(); os.fsync(f.fileno())\\n    os.replace(q,p); q=None\\nfinally:\\n    if q is not None: os.unlink(q)\\nprint(\\\"EDIT_APPLIED\\\")\")",
  "tags.py",
  "\"value.split(\\\",\\\")\"",
  "\"[part.strip() for part in value.split(\\\",\\\") if part.strip()]\""
]
```
- Exact read scope: [tags.py].
- Exact write scope: [tags.py].
- Expected Runner count: 1.
- Expected result: return code 0; changeset 0/1/0; only tags.py modified; no temporary file; canary unchanged; focused parent test passes; task_completed agrees with the observed workspace.
- Evidence: SIGNED_TEST_REPORT-A2-REPLAY-01.json. Request SHA-256 shown in the approval UI: 2dde6231e8e9f8f215109537f2df98bd9abae9a27d4366cde21ef254d7843679.
- Actual user decision: Run once. Exactly one Runner executed. This one-time authorization is spent.
- Test invocation: KHAOS_RUN_PRODUCT_STAGED_EDIT_FEASIBILITY_UI=1 with KHAOS_STAGED_EDIT_FEASIBILITY_EVIDENCE_PATH=reports/m8-secure-edit-final-gate/SIGNED_TEST_REPORT-A2-REPLAY-01.json, then python3 -m unittest discover -s tests -p test_macos_xpc_sandbox.py -k test_seed_app_builds_and_authenticates_its_kernel_service -v in an interactive terminal.

## Preserved earlier attempts

SIGNED_TEST_REPORT.json preserves the first setup failure: stdin ended before workspace selection, no proposal was presented, no operation was approved, and no Runner command ran. It was not overwritten. An intervening launch was blocked by the evidence-path overwrite guard before a product operation; it did not authorize or execute a Runner. The successful A2-REPLAY-01 report is separate.

The Gate A matrix records the remaining signed conditions as NOT_PROVEN or BLOCKED_PENDING_APPROVAL. This file plans only the authorized A2-REPLAY-01 attempt. It does not authorize or schedule another signed operation; any future attempt needs its own exact argv, scope, expected outcome, and user decision.
