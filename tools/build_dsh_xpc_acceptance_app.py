#!/usr/bin/env python3
"""Build a disposable signed Seed app with DSH in a test-only AgentHost XPC."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import plistlib
import shutil
import subprocess
import sys
import tarfile
import tempfile


ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
sys.path.insert(0, str(TOOLS))
import build_macos_seed as seed_builder  # noqa: E402
from run_dsh_signed_runtime_probe import (  # noqa: E402
    PINNED_DSH_SHA,
    PINNED_NODE_ARCHIVE_SHA256,
    PINNED_NODE_VERSION,
    PINNED_PNPM,
    build_dsh_bundle,
    digest,
    output,
)


KHAOS_BASE_SHA = "b08ab11e01663d2b26304cb541efb5361dea0417"
REPLACED_SOURCE = "khaos/macos/AgentHost.swift"
REMOTE_MODEL_DISCLOSURE_SOURCE = "khaos/macos/TrustedWorkspaceLauncherMain.swift"
EXPERIMENTAL_MODEL_ID = "glm-5.3"
DSH_MODEL_BRIDGE_ID = "org.khaos.Seed.DSHModelBridge"


def run(command: list[str], *, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=cwd,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )


def signed_entitlements(path: Path) -> dict[str, object]:
    result = subprocess.run(
        ["codesign", "-d", "--entitlements", ":-", str(path)],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    for output in (result.stdout, result.stderr):
        try:
            value = plistlib.loads(output)
        except Exception:
            continue
        if isinstance(value, dict):
            return value
    raise RuntimeError(f"could not read signed entitlements from {path.name}")


def candidate_b_fixed_script(candidate_probe: Path) -> str:
    result = run([str(candidate_probe), "--fixed-script-json"])
    payload = json.loads(result.stdout)
    fixed_script = payload.get("fixed_script") if isinstance(payload, dict) else None
    if not isinstance(fixed_script, str) or not fixed_script:
        raise RuntimeError("Candidate B probe returned no fixed script")
    return fixed_script


def apply_experimental_model_disclosure(source_root: Path) -> dict[str, str]:
    path = source_root / REMOTE_MODEL_DISCLOSURE_SOURCE
    original = path.read_text(encoding="utf-8")
    old = (
        '            ? "BigModel GLM-5.3-Flash Coding Plan"\n'
        '            : "BigModel GLM-5.3-Flash"'
    )
    replacement = (
        f'            ? "BigModel GLM-5.3 Coding Plan (model id: {EXPERIMENTAL_MODEL_ID})"\n'
        f'            : "BigModel GLM-5.3 (model id: {EXPERIMENTAL_MODEL_ID})"'
    )
    if original.count(old) != 1:
        raise RuntimeError("expected one remote model disclosure string in the Launcher source")
    path.write_text(original.replace(old, replacement), encoding="utf-8")
    return {
        "path": REMOTE_MODEL_DISCLOSURE_SOURCE,
        "original_sha256": hashlib.sha256(original.encode("utf-8")).hexdigest(),
        "experimental_sha256": digest(path),
        "reason": "show the exact fixed glm-5.3 model id in the disposable signed experiment app",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dsh-source", type=Path, required=True)
    parser.add_argument("--node-archive", type=Path, required=True)
    parser.add_argument("--signing-identity", required=True)
    parser.add_argument("--output-app", type=Path, required=True)
    parser.add_argument("--probe-workspace-read-path", type=Path, required=True)
    parser.add_argument("--probe-workspace-write-path", type=Path, required=True)
    parser.add_argument("--probe-credential-path", type=Path, required=True)
    parser.add_argument("--probe-local-port", type=int, required=True)
    parser.add_argument(
        "--model-provider",
        choices=("local", "bigmodel", "bigmodel-coding-plan"),
        default="local",
        help="remote providers are for synthetic experimental tasks only",
    )
    parser.add_argument("--cancellation-case", choices=("b32", "pre-commit", "post-commit"))
    parser.add_argument("--cancellation-control-path", type=Path)
    parser.add_argument("--pnpm", default="pnpm")
    parser.add_argument("--keychain", type=Path)
    parser.add_argument("--python-executable", type=Path, default=Path(sys.executable))
    args = parser.parse_args()

    if platform.system() != "Darwin":
        parser.error("the signed XPC acceptance app requires macOS")
    source_sha = output(["git", "rev-parse", "HEAD"], cwd=ROOT)
    if subprocess.run(
        ["git", "merge-base", "--is-ancestor", KHAOS_BASE_SHA, "HEAD"],
        cwd=ROOT,
        check=False,
    ).returncode != 0:
        parser.error(f"Khaos HEAD must descend from verified PR #41 head {KHAOS_BASE_SHA}")
    merges = output(["git", "rev-list", "--merges", f"{KHAOS_BASE_SHA}..HEAD"], cwd=ROOT)
    if merges:
        parser.error("integration commits after PR #41 must not contain merge commits")
    if output(["git", "status", "--porcelain", "--untracked-files=normal"], cwd=ROOT):
        parser.error("Khaos integration worktree must be clean so the build binds to its exact source SHA")
    dsh_source = args.dsh_source.resolve(strict=True)
    if output(["git", "rev-parse", "HEAD"], cwd=dsh_source) != PINNED_DSH_SHA:
        parser.error(f"DSH must be pinned at {PINNED_DSH_SHA}")
    if output(["git", "status", "--porcelain", "--untracked-files=normal"], cwd=dsh_source):
        parser.error("DSH checkout must be clean")
    pnpm = shutil.which(args.pnpm)
    if pnpm is None or output([pnpm, "--version"], cwd=dsh_source) != PINNED_PNPM:
        parser.error(f"pnpm {PINNED_PNPM} is required")
    node_archive = args.node_archive.resolve(strict=True)
    if digest(node_archive) != PINNED_NODE_ARCHIVE_SHA256:
        parser.error("Node archive hash differs from the pinned official macOS arm64 release")
    identity = seed_builder._require_signing_identity(args.signing_identity, args.keychain)
    output_app = args.output_app.expanduser().absolute()
    if output_app.suffix != ".app" or os.path.lexists(output_app):
        parser.error("--output-app must be a new .app path")
    output_app.parent.mkdir(parents=True, exist_ok=True)
    probe_paths = {
        "KhaosDSHProbeWorkspaceReadPath": args.probe_workspace_read_path.resolve(strict=True),
        "KhaosDSHProbeWorkspaceWritePath": args.probe_workspace_write_path.resolve(strict=True),
        "KhaosDSHProbeCredentialPath": args.probe_credential_path.resolve(strict=True),
    }
    if not all(path.is_file() for path in probe_paths.values()):
        parser.error("DSH attack probe read, write, and credential canaries must be regular files")
    if not (1 <= args.probe_local_port <= 65_535):
        parser.error("--probe-local-port must be a valid TCP port")
    if (args.cancellation_case is None) != (args.cancellation_control_path is None):
        parser.error("--cancellation-case and --cancellation-control-path must be supplied together")
    cancellation_control = None
    if args.cancellation_control_path is not None:
        cancellation_control = args.cancellation_control_path.resolve(strict=True)
        if not cancellation_control.is_dir() \
                or not (cancellation_control / "kernel-events.jsonl").is_file() \
                or (cancellation_control / "release").exists():
            parser.error("cancellation control must contain an empty event file and no release marker")

    probe_dir = ROOT / "experiments/dsh-feasibility"
    override = probe_dir / "DSHAgentHostAcceptance.swift"
    model_bridge_protocol = probe_dir / "DSHModelBridgeProtocol.swift"
    model_bridge_service_source = probe_dir / "DSHModelBridgeService.swift"
    model_bridge_probe_source = probe_dir / "DSHModelBridgePeerProbe.swift"
    test_inputs = (
        override,
        model_bridge_protocol,
        model_bridge_service_source,
        model_bridge_probe_source,
        probe_dir / "dsh-agenthost-runtime.ts",
        probe_dir / "khaos-model-bridge.ts",
        probe_dir / "dsh-capability-lifecycle-probe.ts",
        probe_dir / "dsh-tool-result.ts",
        probe_dir / "khaos-capability-adapter.ts",
        probe_dir / "malicious-cordis-plugin.ts",
        ROOT / "tools/build_dsh_xpc_acceptance_app.py",
        ROOT / "tools/run_dsh_xpc_attack_acceptance.py",
        ROOT / "tools/run_dsh_signed_runtime_probe.py",
        ROOT / "tools/run_dsh_feasibility_probe.py",
        ROOT / "tools/run_dsh_model_bridge_tests.py",
        ROOT / "tools/run_dsh_plugin_evaluation.py",
        ROOT / "experiments/dsh-feasibility/khaos-model-bridge.test.ts",
        ROOT / "experiments/dsh_phase3/benchmark.py",
        ROOT / "experiments/dsh_phase3/test_benchmark.py",
        ROOT / "experiments/dsh_phase3/plugin_evolution/tag-plugin.ts",
        ROOT / "experiments/dsh_phase3/plugin_evolution/baseline.ts",
        ROOT / "experiments/dsh_phase3/plugin_evolution/candidate_v1.ts",
        ROOT / "experiments/dsh_phase3/plugin_evolution/malicious_candidate.ts",
        ROOT / "experiments/dsh_phase3/plugin_evolution/runner.ts",
        ROOT / "tests/signed_cancellation_fixture.py",
        ROOT / "tests/macos_xpc_probe/TrustedEditApprovalProbe.swift",
    )
    temporary = Path(tempfile.mkdtemp(prefix="khaos-dsh-xpc-acceptance-", dir=output_app.parent))
    completed = False
    try:
        source_root = temporary / "inputs"
        source_hashes = seed_builder._snapshot_sources(source_root, None)
        protocol_target = source_root / "khaos/macos/AgentHostProtocol.swift"
        protocol_original = protocol_target.read_text(encoding="utf-8")
        protocol_extension = model_bridge_protocol.read_text(encoding="utf-8")
        if "enum DSHModelBridgeLimits" in protocol_original:
            raise RuntimeError("base AgentHost protocol unexpectedly contains the experimental bridge")
        protocol_target.write_text(
            protocol_original.rstrip() + "\n\n" + protocol_extension,
            encoding="utf-8",
        )
        source_hashes["khaos/macos/AgentHostProtocol.swift"] = digest(protocol_target)
        protocol_overlay = {
            "path": "khaos/macos/AgentHostProtocol.swift",
            "original_sha256": hashlib.sha256(protocol_original.encode("utf-8")).hexdigest(),
            "experimental_sha256": digest(protocol_target),
            "reason": "share the fixed, bounded model-bridge XPC contract in the disposable app",
        }
        disclosure_override = (
            apply_experimental_model_disclosure(source_root)
            if args.model_provider != "local" else None
        )
        if disclosure_override is not None:
            source_hashes[REMOTE_MODEL_DISCLOSURE_SOURCE] = disclosure_override["experimental_sha256"]
        cancellation_overlay_hashes: dict[str, str] = {}
        if args.cancellation_case is not None and cancellation_control is not None:
            sys.path.insert(0, str(ROOT / "tests"))
            import signed_cancellation_fixture  # noqa: E402

            cancellation_overlay_hashes = signed_cancellation_fixture.overlay(
                source_root,
                cancellation_control,
                args.cancellation_case,
            )
            source_hashes.update(cancellation_overlay_hashes)
        replacement_hash = digest(override)
        replacement_target = source_root / REPLACED_SOURCE
        shutil.copy2(override, replacement_target)
        source_hashes[REPLACED_SOURCE] = replacement_hash

        node_root = temporary / "node"
        node_root.mkdir()
        with tarfile.open(node_archive, "r:xz") as archive:
            archive.extractall(node_root, filter="data")
        node_dir = node_root / "node-v22.19.0-darwin-arm64"
        node_source = node_dir / "bin/node"
        if not node_source.is_file() or output([str(node_source), "--version"]) != PINNED_NODE_VERSION:
            raise RuntimeError("verified Node archive does not contain the expected Node runtime")
        runtime_bundle, runtime_hash = build_dsh_bundle(
            dsh_source,
            probe_dir,
            pnpm,
            temporary,
            runtime_entry="dsh-agenthost-runtime.ts",
            bundle_name="agenthost-runtime.mjs",
        )

        app = temporary / output_app.name
        sdk = output(["xcrun", "--sdk", "macosx", "--show-sdk-path"])
        swiftc = output(["xcrun", "--find", "swiftc"])
        install_name_tool = output(["xcrun", "--find", "install_name_tool"])
        python = seed_builder._python_framework(args.python_executable.resolve(strict=True))
        test_sources = {str(path.relative_to(ROOT)): digest(path) for path in test_inputs}
        fixed_script_argument = None
        if args.cancellation_case is not None:
            candidate_probe = temporary / "TrustedEditApprovalProbe"
            run([
                swiftc,
                "-sdk", sdk,
                "-target", f"{platform.machine()}-apple-macosx26.0",
                str(source_root / "khaos/macos/KernelWorkspaceXPC.swift"),
                str(source_root / "khaos/macos/AgentHostProtocol.swift"),
                str(source_root / "khaos/macos/TrustedEditApproval.swift"),
                str(ROOT / "tests/macos_xpc_probe/TrustedEditApprovalProbe.swift"),
                "-o", str(candidate_probe),
            ])
            fixed_script = candidate_b_fixed_script(candidate_probe)
            fixed_script_argument = "exec(" + json.dumps(fixed_script, separators=(",", ":")) + ")"
        build_record = {
            "schema": 1,
            "source_sha256": source_hashes,
            "build_version": "1",
            "builder_sha256": seed_builder._sha256_file(Path(seed_builder.__file__)),
            "certificate_sha1": identity,
            "architecture": platform.machine(),
            "macos": platform.mac_ver()[0],
            "swift": output([swiftc, "--version"]),
            "sdk": output(["xcrun", "--sdk", "macosx", "--show-sdk-version"]),
            "python_version": output([str(args.python_executable), "-I", "-S", "-c", "import sys; print(sys.version)"]),
            "input_policy": "dsh-test-agenthost-override",
            "khaos_experiment_base_sha": KHAOS_BASE_SHA,
            "khaos_source_sha": source_sha,
            "agent_action_diagnostics": False,
            "test_only_sources_sha256": test_sources,
            "probe_fixture_sha256": {
                key: digest(path) for key, path in probe_paths.items()
            },
            "probe_local_port": args.probe_local_port,
            "cancellation_case": args.cancellation_case,
            "cancellation_overlay_sha256": cancellation_overlay_hashes,
            "dsh_model_provider": args.model_provider,
            "dsh_model_id": EXPERIMENTAL_MODEL_ID if args.model_provider != "local" else None,
            "experimental_source_overrides": (
                [protocol_overlay]
                + ([disclosure_override] if disclosure_override is not None else [])
            ),
            "dsh_model_data_policy": (
                "synthetic disposable benchmark data only; Launcher task-scoped consent"
                if args.model_provider != "local" else "no remote model"
            ),
            "dsh_model_limits": (
                {
                    "model_id": EXPERIMENTAL_MODEL_ID,
                    "max_completion_tokens_per_call": 2_048,
                    "max_model_calls_per_task": 16,
                    "max_task_seconds": 600,
                    "max_request_bytes": 56 * 1_024,
                    "max_response_bytes": 56 * 1_024,
                    "agent_host_network_entitlement": False,
                    "node_network_entitlement": False,
                    "model_bridge_network_entitlement": True,
                    "model_bridge_service": "org.khaos.Seed.DSHModelBridge",
                    "model_bridge_peer": "signed org.khaos.Seed.AgentHost XPC only",
                    "api_key_delivery": "Launcher to fixed AgentHost XPC bridge; not in Node environment",
                }
                if args.model_provider != "local" else None
            ),
            "model_network_boundary": (
                "only the dedicated fixed-endpoint model XPC has network.client; AgentHost and Node do not"
                if args.model_provider != "local" else "no remote model; no network.client entitlement"
            ),
            "dsh_sha": PINNED_DSH_SHA,
            "dsh_host_build": [
                "tsc -b tsconfig.host.json",
                "tsdown --config-loader native --env.DSH_BUILD_FACE host",
            ],
            "dsh_license_sha256": digest(dsh_source / "LICENSE"),
            "dsh_third_party_notices_sha256": digest(dsh_source / "THIRD_PARTY_NOTICES.md"),
            "node_version": PINNED_NODE_VERSION,
            "node_archive_sha256": PINNED_NODE_ARCHIVE_SHA256,
            "node_license_sha256": digest(node_dir / "LICENSE"),
            "dsh_runtime_bundle_sha256": runtime_hash,
        }
        seed_builder._assemble_app(
            app,
            source_root=source_root,
            build_record=build_record,
            sdk=sdk,
            swiftc=swiftc,
            install_name_tool=install_name_tool,
            python=python,
            architecture=platform.machine(),
            signing_identity=identity,
            keychain=args.keychain,
            # Keep the DSH Host sandbox network-free. Remote requests go through
            # the separately signed, peer-verified model XPC below.
            model_provider="local",
            llama_cli=None,
            model_file=None,
            model_license=None,
        )

        host = app / "Contents/XPCServices/KhaosAgentHost.xpc"
        host_resources = host / "Contents/Resources"
        host_info_path = host / "Contents/Info.plist"
        with host_info_path.open("rb") as stream:
            host_info = plistlib.load(stream)
        for key, path in probe_paths.items():
            host_info[key] = str(path)
        host_info["KhaosDSHProbeKernelPath"] = str(
            output_app / "Contents/XPCServices/KernelProduction.xpc/Contents/MacOS/KernelProduction"
        )
        host_info["KhaosDSHProbeLocalPort"] = str(args.probe_local_port)
        if fixed_script_argument is not None:
            host_info["KhaosDSHCandidateBFixedScriptArgument"] = fixed_script_argument
        host_info["KhaosModelProvider"] = args.model_provider
        dsh_resources = host_resources / "dsh"
        dsh_resources.mkdir(parents=True)
        node = host_resources / "node"
        shutil.copy2(node_source, node)
        shutil.copy2(runtime_bundle, dsh_resources / "agenthost-runtime.mjs")
        shutil.copy2(node_dir / "LICENSE", host_resources / "NODE_LICENSE")
        shutil.copy2(dsh_source / "LICENSE", host_resources / "DSH_LICENSE")
        shutil.copy2(dsh_source / "THIRD_PARTY_NOTICES.md", host_resources / "DSH_THIRD_PARTY_NOTICES.md")
        (host_resources / "package.json").write_text(
            json.dumps({"name": "khaos-dsh-xpc-acceptance", "version": "0.2.1-rc.2"}) + "\n",
            encoding="utf-8",
        )

        node_entitlements = temporary / "node-entitlements.plist"
        node_entitlements.write_bytes(plistlib.dumps({"com.apple.security.cs.allow-jit": True}))
        sign = ["codesign", "--force"]
        if args.keychain is not None:
            sign.extend(("--keychain", str(args.keychain.expanduser().resolve(strict=True))))
        run(sign + [
            "--options", "runtime", "--timestamp=none", "--sign", identity,
            "--entitlements", str(node_entitlements), "--identifier",
            "org.khaos.Seed.AgentHost.DSHAcceptanceRuntime", str(node),
        ])

        launcher_info_path = app / "Contents/Info.plist"
        with launcher_info_path.open("rb") as stream:
            launcher_info = plistlib.load(stream)
        launcher_info["KhaosModelProvider"] = args.model_provider
        with launcher_info_path.open("wb") as stream:
            plistlib.dump(launcher_info, stream, sort_keys=True)

        if args.model_provider != "local":
            host_binary = host / "Contents/MacOS/KhaosAgentHost"
            host_requirement = seed_builder._designated_requirement(
                host_binary,
                seed_builder.AGENT_HOST_ID,
            )
            model_bridge_probe = host_resources / "dsh-model-bridge-peer-probe"
            run([
                swiftc,
                "-sdk", sdk,
                "-target", f"{platform.machine()}-apple-macosx26.0",
                str(source_root / "khaos/macos/AgentHostProtocol.swift"),
                str(model_bridge_probe_source),
                "-o", str(model_bridge_probe),
            ])
            run(sign + [
                "--options", "runtime", "--timestamp=none", "--sign", identity,
                "--identifier", "org.khaos.Seed.AgentHost.DSHModelBridgePeerProbe",
                str(model_bridge_probe),
            ])
            host_info["KhaosDSHModelBridgeProbePath"] = model_bridge_probe.name
            bridge = app / "Contents/XPCServices/DSHModelBridge.xpc"
            bridge_contents = bridge / "Contents"
            bridge_binary = bridge_contents / "MacOS/DSHModelBridge"
            bridge_binary.parent.mkdir(parents=True)
            run([
                swiftc,
                "-sdk", sdk,
                "-target", f"{platform.machine()}-apple-macosx26.0",
                str(source_root / "khaos/macos/AgentHostProtocol.swift"),
                str(model_bridge_service_source),
                "-o", str(bridge_binary),
            ])
            plistlib.dump({
                "CFBundleIdentifier": DSH_MODEL_BRIDGE_ID,
                "CFBundleExecutable": "DSHModelBridge",
                "CFBundleInfoDictionaryVersion": "6.0",
                "CFBundlePackageType": "XPC!",
                "CFBundleName": "Khaos DSH Model Bridge",
                "CFBundleShortVersionString": "0.1.0",
                "CFBundleVersion": "1",
                "LSMinimumSystemVersion": "26.0",
                "KhaosAgentHostRequirement": host_requirement,
                "KhaosModelProvider": args.model_provider,
                "XPCService": {"ServiceType": "Application", "RunLoopType": "NSRunLoop"},
            }, (bridge_contents / "Info.plist").open("wb"), sort_keys=True)
            bridge_entitlements = temporary / "dsh-model-bridge-entitlements.plist"
            bridge_entitlements.write_bytes(plistlib.dumps({
                "com.apple.security.app-sandbox": True,
                "com.apple.security.network.client": True,
            }))
            run(sign + [
                "--sign", identity,
                "--entitlements", str(bridge_entitlements),
                str(bridge),
            ])
            bridge_requirement = seed_builder._designated_requirement(
                bridge_binary,
                DSH_MODEL_BRIDGE_ID,
            )
            host_info["KhaosDSHModelBridgeRequirement"] = bridge_requirement
        with host_info_path.open("wb") as stream:
            plistlib.dump(host_info, stream, sort_keys=True)

        host_entitlements = app.parent / "agent-host-entitlements.plist"
        run(sign + ["--sign", identity, "--entitlements", str(host_entitlements), str(host)])

        node_entitlement_values = signed_entitlements(node)
        host_entitlement_values = signed_entitlements(host)
        if node_entitlement_values.get("com.apple.security.network.client") is True:
            raise RuntimeError("signed DSH Node unexpectedly has network.client")
        if host_entitlement_values.get("com.apple.security.network.client") is True:
            raise RuntimeError("signed DSH AgentHost unexpectedly has network.client")
        build_record["signed_network_entitlement_check"] = {
            "node_network_client": False,
            "agent_host_network_client": False,
            "model_bridge_network_client": (
                signed_entitlements(app / "Contents/XPCServices/DSHModelBridge.xpc").get(
                    "com.apple.security.network.client"
                ) is True
                if args.model_provider != "local" else False
            ),
        }
        if args.model_provider != "local" and not build_record["signed_network_entitlement_check"]["model_bridge_network_client"]:
            raise RuntimeError("signed model bridge is missing network.client")

        embedded = {
            str(path.relative_to(app)): seed_builder._sha256_file(path)
            for path in sorted(app.rglob("*"))
            if path.is_file() and not path.is_symlink()
            and path.relative_to(app).parts[1:2] == ("XPCServices",)
        }
        build_record["embedded_sha256"] = embedded
        build_record_path = app / "Contents/Resources/build-inputs.json"
        build_record_path.write_text(json.dumps(build_record, sort_keys=True, indent=2) + "\n")
        app_entitlements = app.parent / "app-entitlements.plist"
        run(sign + ["--sign", identity, "--entitlements", str(app_entitlements), str(app)])
        seed_builder.verify_app(app, identity)
        if args.model_provider != "local":
            run([
                "codesign", "--verify", "--deep", "--strict",
                f'-R=identifier "{DSH_MODEL_BRIDGE_ID}" and certificate leaf = H"{identity}"',
                str(app / "Contents/XPCServices/DSHModelBridge.xpc"),
            ])
        run(["codesign", "--verify", "--deep", "--strict", "--verbose=2", str(app)])
        seed_builder._publish_app(app, output_app)
        seed_builder.verify_app(output_app, identity)

        host_binary = output_app / "Contents/XPCServices/KhaosAgentHost.xpc/Contents/MacOS/KhaosAgentHost"
        kernel_binary = output_app / "Contents/XPCServices/KernelProduction.xpc/Contents/MacOS/KernelProduction"
        print("signed_xpc_acceptance_build=PASS")
        print(f"khaos_base_sha={KHAOS_BASE_SHA}")
        print(f"khaos_source_sha={source_sha}")
        print(f"dsh_sha={PINNED_DSH_SHA}")
        print(f"host_source_override_sha256={replacement_hash}")
        print(f"node_sha256={digest(output_app / 'Contents/XPCServices/KhaosAgentHost.xpc/Contents/Resources/node')}")
        print(f"dsh_runtime_bundle_sha256={runtime_hash}")
        print(f"agent_host_binary_sha256={digest(host_binary)}")
        if args.model_provider != "local":
            print(f"model_bridge_binary_sha256={digest(output_app / 'Contents/XPCServices/DSHModelBridge.xpc/Contents/MacOS/DSHModelBridge')}")
        print(f"kernel_binary_sha256={digest(kernel_binary)}")
        print(f"app_bundle={output_app}")
        print(f"app_bundle_bytes={sum(path.stat().st_size for path in output_app.rglob('*') if path.is_file())}")
        completed = True
        return 0
    finally:
        if not completed and output_app.exists():
            shutil.rmtree(output_app, ignore_errors=True)
        shutil.rmtree(temporary, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
