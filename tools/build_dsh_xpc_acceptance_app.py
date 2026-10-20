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


def run(command: list[str], *, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=cwd,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )


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
    test_inputs = (
        override,
        probe_dir / "dsh-agenthost-runtime.ts",
        probe_dir / "khaos-capability-adapter.ts",
        probe_dir / "malicious-cordis-plugin.ts",
        ROOT / "tools/build_dsh_xpc_acceptance_app.py",
        ROOT / "tools/run_dsh_xpc_attack_acceptance.py",
        ROOT / "tools/run_dsh_signed_runtime_probe.py",
        ROOT / "tools/run_dsh_feasibility_probe.py",
        ROOT / "tests/signed_cancellation_fixture.py",
        ROOT / "tests/macos_xpc_probe/TrustedEditApprovalProbe.swift",
    )
    temporary = Path(tempfile.mkdtemp(prefix="khaos-dsh-xpc-acceptance-", dir=output_app.parent))
    completed = False
    try:
        source_root = temporary / "inputs"
        source_hashes = seed_builder._snapshot_sources(source_root, None)
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
            fixed_script = json.loads(run([str(candidate_probe), "--fixed-script-json"]))["fixed_script"]
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
            "dsh_sha": PINNED_DSH_SHA,
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
        with host_info_path.open("wb") as stream:
            plistlib.dump(host_info, stream, sort_keys=True)
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
        host_entitlements = app.parent / "agent-host-entitlements.plist"
        run(sign + ["--sign", identity, "--entitlements", str(host_entitlements), str(host)])

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
