# Memory Candidate B

Candidate B keeps the memory logical Plugin ID, the remember / recall / forget
interface, and the opaque khaos-memory-v1 state format. It does not migrate,
copy, or initialize existing production state during replacement.

Its only behavior change is in recall: after an exact key miss, it applies
Unicode NFKC normalization followed by casefold() to stored keys. It returns a
fallback value only when exactly one stored key matches. Exact matches always
win, while ambiguous normalized matches remain not found. It does not trim or
otherwise rewrite stored keys.
