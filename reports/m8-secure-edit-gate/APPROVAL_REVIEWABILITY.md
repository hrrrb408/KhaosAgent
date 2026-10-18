# Approval Reviewability

## Exact short request

The signed v8 and separately authorized replay showed the short deterministic request with the selected workspace, argv, exact `tags.py` read/write scopes and request digest. The replay used digest `17f3d3b5dcf7f29269a262a738c048f32ca6628769e3872cadb5059b01117f7e`; the approved operation matched the one executed Runner call. Deep strict product signature validation passed.

This is L4 evidence for the exact short ASCII request only. The historical v2 denial is also a narrow request-display observation and did not execute a Runner.

## Static and offline evidence

The existing deterministic probe tests keep the fixed script in bounded argv data and validate the short fixture's JSON-encoded arguments and scope. These are L1/L2 checks; they do not prove what a user can practically inspect in the signed Launcher.

## Missing reviewability evidence

No signed UI evidence covers multiline text, Unicode, quotes, backslashes, near-limit input, complete scrolling, truncation, or a byte-for-byte comparison between a displayed long payload and executed parameters. No Trusted Launcher UI change was made. Approval Reviewability remains **NOT_PROVEN** for those cases; this does not imply that the current UI truncates them.
