# Gate B — Kernel to DSH Result Correlation

## Result

Correlation is **NOT_RUN**. Neither Task A trial reached a Launcher request, so there is no operation result to associate with a DSH call. This report deliberately does not infer correlation from event counts, names, or ordering.

| Correlation field | Trial 01 | Trial 02 |
|---|---|---|
| Trial ID | `gate-b-task-a-01` — not started | `gate-b-task-a-02` — not started |
| Model turn ID | NOT_AVAILABLE | NOT_AVAILABLE |
| Tool call ID | NOT_AVAILABLE | NOT_AVAILABLE |
| Launcher task ID | NOT_AVAILABLE | NOT_AVAILABLE |
| Launcher request ID | NOT_AVAILABLE | NOT_AVAILABLE |
| Invocation digest | NOT_AVAILABLE | NOT_AVAILABLE |
| Approval digest | NOT_AVAILABLE | NOT_AVAILABLE |
| Workspace identity | NOT_AVAILABLE | NOT_AVAILABLE |
| Kernel operation result | NOT_AVAILABLE | NOT_AVAILABLE |
| Runner return code | NOT_AVAILABLE | NOT_AVAILABLE |
| Kernel result digest | NOT_AVAILABLE | NOT_AVAILABLE |
| DSH delivered result | NOT_AVAILABLE | NOT_AVAILABLE |
| DSH next-turn observation | NOT_AVAILABLE | NOT_AVAILABLE |
| Agent terminal state | NOT_RUN | NOT_RUN |

Unresolved Kernel results: **0**, because no Kernel operation was submitted. This is not evidence that the result-delivery path works. The experimental evidence adapter and per-operation correlation evaluator were not exercised.

The signed runtime was not launched after deep strict verification returned `CSSMERR_TP_NOT_TRUSTED`. No internal Kernel identifier, request ID, digest, or model turn ID is claimed for these trials.
