# M8.1 — Agent Action schema review

## Existing contract

The model output is one JSON object with exactly ten keys:

| Key | Swift type | Unused value in the existing correction contract |
| --- | --- | --- |
| `type` | `String` | none |
| `text` | `String` | `""` |
| `argv` | `[String]` | `[]` |
| `readScope` | `[String]` | `[]` |
| `writeScope` | `[String]` | `[]` |
| `pluginID` | `String` | `""` |
| `candidateDigest` | `String` | `""` |
| `generation` | `Int` | `0` |
| `pluginInput` | `String` | `""` |
| `evolutionGoal` | `String` | `""` |

Synthesized `Decodable` requires every property. The Host then checks the exact
set of JSON keys and verifies the Swift field types before action-specific
validation. Text, workspace, Plugin, and evolution replies each require their
documented empty values for unrelated fields. The local grammar and prompt
describe this same fixed object. BigModel's `response_format: json_object`
requests JSON-object output; it does not enforce the ten required keys or their
types.

This fixed form asks a model to emit fields irrelevant to many actions. That is
a plausible source of output complexity. M8.0 did not preserve the rejected
output, so it cannot establish that any unused field was absent, that extra
fields appeared, or that a particular Action type caused the failure. Do not
turn this plausible concern into the root cause.

## Options

| Option | Model complexity | Safety/compatibility | TCB and code cost | Assessment |
| --- | --- | --- | --- | --- |
| A. Keep ten fields | Highest of the three; all keys must be emitted every time | Existing exact-key check, action validators, Launcher review and Kernel scope stay in place | No ABI or Kernel change; smallest | **Recommend for M8.1** while collecting exact failure categories |
| B. Schema per Action type | Fewer irrelevant fields per response | Requires a tagged parser that rejects unknown/missing fields and preserves empty-vs-absent authority semantics; must keep Launcher review unchanged | Host-only in principle, but more parsing paths/tests and compatibility work | Defer until diagnostics show schema errors and an offline comparison demonstrates improvement |
| C. Fixed outer type with payload | Potentially fewer fields | Does not itself provide safety; payload validation still must be strict and typed | Adds a new wire/model representation and conversion logic | No evidence justifies this extra representation |

### Recommendation

**Option A: retain the current ten-field contract for this change.** M8.1 adds
no protocol relaxation. It centralizes the exact expected key list in the
untrusted Host decoder and reports shape metadata only when diagnostics are
explicitly enabled. It continues rejecting missing/extra keys, wrong field
types, unsupported action types, and semantic field misuse.

If a separately authorized experiment later shows repeated missing/extra keys,
compare the current contract with a per-action candidate offline first. Require
the candidate to reject unknown fields, avoid defaults that create read/write
scope, round-trip through the current Launcher ABI, and preserve independent
approval. Do not send unapproved scopes merely because the model omitted a
field. Do not change the Kernel or Launcher schema to simplify model output.

## Reliability and security conclusions

The present schema may increase model formatting burden, but its causal effect
on GLM-5.3 is **NOT_PROVEN**. JSON-object mode is not a schema guarantee. The
current strict parser's exact-key failure is deterministic and fail-closed; the
Host's allowed action types and field combinations are checked after decoding.
Any future schema reduction must preserve those checks and independent Launcher
approval. Coding reliability and hidden-test completion remain **NOT_PROVEN**.
