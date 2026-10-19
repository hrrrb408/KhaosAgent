# Signed macOS runtime feasibility

## Build and identity

The experimental app was built from the PR #40 source base `707395146bbaf6be9ac6f58ae1f538e443b064a8` and DSH `687f282e8625c6b8d11ff58211a90524be2e4317`. It was signed with the local Apple Development identity under team `UBAP6LN5AM`, launched through Launch Services, and passed `codesign --verify --deep --strict` plus the repository's `verify_app` identity checks.

| Artifact | SHA-256 |
|---|---|
| Test AgentHost source override | `8203adf82adcdd4bc729baf19abfa3726fbdfeadc66705daf01f9fc6d36c1cb7` |
| Successful test AgentHost binary | `7fc90dc8da25021fdd94a4d066bfa6576eee2095da13162f5828186d103df52d` |
| KernelProduction binary in successful app | `20626a01611906d04ab832e515965ccb9761c9a699846628e85ae462f0b4f175` |
| Bundled Node binary | `b8007ed91852cce69cb4772542ed0258ba794fcab884a75bb351cc335231fd62` |
| Bundled DSH AgentHost runtime | `b37cf15b533fa6d5c1cb096aadc2beaf42d20997028af07d95e6b6b6e742d75a` |
| Node archive (official macOS arm64 v22.19.0) | `1c3a9e78da501bbc1f0c99fbbb69bb7c722bc7a9bf30128b21ea502f3905892a` |

The Node binary is 110,068,448 bytes and the bundled runtime is 706,574 bytes. The full signed experimental app is 198,736,452 bytes. The independently built production Seed app is 88,240,336 bytes, so the experimental bundle is 110,496,116 bytes larger. This is a material packaging cost. The DSH source checkout used 2.0 GiB of installed `node_modules` for build and tests; those dependencies were not copied into the app. The DSH runtime entry was bundled as one 706,574-byte module. Node had no non-system dynamic library dependencies in the separate signed runtime probe.

Node's Hardened Runtime signature carries only `com.apple.security.cs.allow-jit`; the XPC AgentHost carries only `com.apple.security.app-sandbox` and no network-client entitlement. JIT was required for Node to initialize under Hardened Runtime. The separate signed probe measured 57,360,384 bytes of Node RSS; the actual Khaos XPC run did not independently sample its child RSS.

## Production build exclusion

The ordinary production builder was run separately after the experiment. It produced a valid signed app from the unchanged AgentHost source (`685b92cec3427540d643c9fb7f0ac62235526a7fc4af09438cfe6b8edd6a7e1b`), with `input_policy=recorded-development-inputs`, no test-only source map, and zero Node binaries. The normal build has no DSH test barrier or override. The builder itself was not modified.

## Repeatable commands

Build the disposable signed XPC app on macOS with the pinned DSH checkout, verified Node archive, and a local signing identity:

```bash
python3 tools/build_dsh_xpc_acceptance_app.py \
  --dsh-source /path/to/khaos-dsh-687f282 \
  --node-archive /path/to/node-v22.19.0-darwin-arm64.tar.xz \
  --pnpm /path/to/pnpm-11.28.5 \
  --signing-identity 'Apple Development: …' \
  --output-app /private/tmp/KhaosSeedDSHAcceptance.app
```

Create a new disposable folder containing only `fixture.txt`, put the deterministic user task and `/exit` on a stdin file, then launch through Launch Services:

```bash
open -n -W -a /private/tmp/KhaosSeedDSHAcceptance.app \
  --stdin /private/tmp/case/stdin.txt \
  --stdout /private/tmp/case/stdout.txt \
  --stderr /private/tmp/case/stderr.txt \
  --args --agent
```

Select only that disposable workspace. Review the actual dialog and approve only the displayed read-only `fixture.txt` request. The owner can instead perform the click directly; if an agent performs it under explicit owner delegation, record that operator exactly as done in this report. The production-build exclusion check is:

```bash
python3 tools/build_macos_seed.py \
  --output /private/tmp/KhaosSeedDSHProductionCheck.app \
  --signing-identity 'Apple Development: …'
```
