#!/usr/bin/env python3
"""Build and run a signed App Sandbox probe containing the pinned DSH runtime."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import plistlib
import re
import shutil
import subprocess
import tarfile
import tempfile
import uuid


PINNED_DSH_SHA = "687f282e8625c6b8d11ff58211a90524be2e4317"
PINNED_PNPM = "11.28.5"
PINNED_NODE_VERSION = "v22.19.0"
PINNED_NODE_ARCHIVE_SHA256 = "1c3a9e78da501bbc1f0c99fbbb69bb7c722bc7a9bf30128b21ea502f3905892a"


def run(command: list[str], *, cwd: Path | None = None, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, cwd=cwd, env=env, check=True, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def output(command: list[str], *, cwd: Path | None = None, env: dict[str, str] | None = None) -> str:
    result = run(command, cwd=cwd, env=env)
    return (result.stdout + result.stderr).strip()


def digest(path: Path) -> str:
    checksum = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            checksum.update(chunk)
    return checksum.hexdigest()


def sandbox_path(path: Path) -> str:
    return str(path.resolve()).replace("\\", "\\\\").replace('"', '\\"')


def create_build_sandbox(path: Path, dsh_source: Path, scratch: Path) -> None:
    root = sandbox_path(dsh_source)
    users = sandbox_path(Path("/Users"))
    scratch_path = sandbox_path(scratch)
    path.write_text(
        "\n".join(
            [
                "(version 1)",
                "(allow default)",
                f'(deny file-read* (subpath "{users}"))',
                f'(allow file-read* (subpath "{root}"))',
                "(deny file-write*",
                "  (require-all",
                f'    (require-not (subpath "{root}"))',
                f'    (require-not (subpath "{scratch_path}"))',
                '    (require-not (literal "/dev/null"))))',
                "(deny network* (require-not (local unix-socket)))",
                "",
            ]
        ),
        encoding="utf-8",
    )


def build_dsh_bundle(
    dsh_source: Path,
    probe_dir: Path,
    pnpm: str,
    temp_root: Path,
    *,
    runtime_entry: str = "runtime-probe.ts",
    bundle_name: str = "runtime-probe.mjs",
) -> tuple[Path, str]:
    tests = dsh_source / "packages/core/agent-loop/tests"
    build_directory = dsh_source / ".tmp"
    build_directory.mkdir(exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix="khaos-signed-runtime-", dir=tests))
    output_dir = Path(tempfile.mkdtemp(prefix="khaos-runtime-bundle-", dir=build_directory))
    tsconfig = build_directory / "khaos-runtime-tsconfig.json"
    sandbox = build_directory / "khaos-runtime-build.sb"
    try:
        shutil.copy2(probe_dir / "dsh-capability-lifecycle-probe.ts", staging / "dsh-capability-lifecycle-probe.ts")
        shutil.copy2(probe_dir / "khaos-capability-adapter.ts", staging / "khaos-capability-adapter.ts")
        shutil.copy2(probe_dir / "dsh-tool-result.ts", staging / "dsh-tool-result.ts")
        shutil.copy2(probe_dir / "malicious-cordis-plugin.ts", staging / "malicious-cordis-plugin.ts")
        shutil.copy2(probe_dir / runtime_entry, staging / runtime_entry)
        tsconfig.write_text(
            json.dumps(
                {
                    "compilerOptions": {
                        "target": "ES2022",
                        "module": "NodeNext",
                        "moduleResolution": "NodeNext",
                        "skipLibCheck": True,
                        "baseUrl": ".",
                    }
                }
            ),
            encoding="utf-8",
        )
        create_build_sandbox(sandbox, dsh_source, temp_root)
        build_env = {
            "PATH": os.pathsep.join(
                [
                    str(Path(pnpm).parent),
                    "/opt/homebrew/bin",
                    "/opt/homebrew/sbin",
                    "/usr/bin",
                    "/bin",
                    "/usr/sbin",
                    "/sbin",
                    str(dsh_source / "node_modules/.bin"),
                ]
            ),
            "HOME": str(dsh_source),
            "TMPDIR": str(dsh_source / ".tmp"),
            "NODE_COMPILE_CACHE": str(temp_root / "node-compile-cache"),
            "XDG_CACHE_HOME": str(temp_root / "cache"),
            "npm_config_cache": str(temp_root / "npm-cache"),
            "npm_config_userconfig": "/dev/null",
            "npm_config_globalconfig": "/dev/null",
        }
        command = [
            "/usr/bin/sandbox-exec",
            "-f",
            str(sandbox),
            str(Path(shutil.which("node") or "node")),
            str(dsh_source / "node_modules/tsdown/dist/run.mjs"),
            str((staging / runtime_entry).relative_to(dsh_source)),
            "--format",
            "esm",
            "--platform",
            "node",
            "--target",
            "node22",
            "--out-dir",
            str(output_dir.relative_to(dsh_source)),
            "--no-config",
            "--no-clean",
            "--no-report",
            "--no-dts",
            "--tsconfig",
            str(tsconfig.relative_to(dsh_source)),
        ]
        result = subprocess.run(
            command,
            cwd=dsh_source,
            env=build_env,
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        print(result.stdout, end="")
        if result.returncode != 0:
            raise RuntimeError(f"DSH runtime bundling failed with exit {result.returncode}")
        generated = list(output_dir.glob(f"{Path(runtime_entry).stem}.*"))
        if len(generated) != 1:
            raise RuntimeError(f"expected exactly one runtime bundle; generated {generated}")
        bundle = temp_root / bundle_name
        shutil.copy2(generated[0], bundle)
        imports = re.findall(r'^import .*? from [\"\']([^\"\']+)[\"\']', bundle.read_text(encoding="utf-8"), re.MULTILINE)
        non_builtins = [name for name in imports if not name.startswith("node:")]
        if non_builtins:
            raise RuntimeError(f"bundle retained external imports: {non_builtins}")
        return bundle, digest(bundle)
    finally:
        shutil.rmtree(staging, ignore_errors=True)
        shutil.rmtree(output_dir, ignore_errors=True)
        tsconfig.unlink(missing_ok=True)
        sandbox.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dsh-source", type=Path, required=True)
    parser.add_argument("--node-archive", type=Path, required=True)
    parser.add_argument("--signing-identity", required=True)
    parser.add_argument("--output-app", type=Path, required=True)
    parser.add_argument("--pnpm", default="pnpm")
    args = parser.parse_args()

    if platform.system() != "Darwin":
        parser.error("signed runtime feasibility requires macOS")
    for command in ("/usr/bin/sandbox-exec", "/usr/bin/codesign", "/usr/bin/security", "/usr/bin/swiftc", "/usr/bin/otool"):
        if not Path(command).is_file():
            parser.error(f"required macOS tool missing: {command}")

    dsh_source = args.dsh_source.resolve(strict=True)
    if not (dsh_source / "node_modules").is_dir():
        parser.error("DSH_SOURCE must be an installed checkout")
    try:
        dsh_source.relative_to(Path("/Users"))
    except ValueError:
        pass
    else:
        parser.error("clone DSH outside /Users so its code build can deny host-home reads")
    if output(["git", "rev-parse", "HEAD"], cwd=dsh_source) != PINNED_DSH_SHA:
        parser.error(f"DSH must be pinned at {PINNED_DSH_SHA}")
    if output(["git", "status", "--porcelain", "--untracked-files=normal"], cwd=dsh_source):
        parser.error("DSH checkout must be clean before this probe")

    pnpm = shutil.which(args.pnpm)
    if pnpm is None or output([pnpm, "--version"], cwd=dsh_source) != PINNED_PNPM:
        parser.error(f"pnpm {PINNED_PNPM} is required")
    if digest(args.node_archive.resolve(strict=True)) != PINNED_NODE_ARCHIVE_SHA256:
        parser.error("Node.js archive SHA-256 does not match the pinned official macOS arm64 release")

    identity_output = output(["/usr/bin/security", "find-identity", "-v", "-p", "codesigning"])
    if args.signing_identity not in identity_output:
        parser.error("requested signing identity is not available in the keychain")
    app = args.output_app.expanduser().resolve()
    if app.exists() or app.suffix != ".app":
        parser.error("--output-app must be a new .app path")

    temp_root = Path(tempfile.mkdtemp(prefix="khaos-dsh-signed-runtime-", dir="/tmp"))
    app_contents = app / "Contents"
    resources = app_contents / "Resources"
    dsh_resources = resources / "dsh"
    node_root = temp_root / "node"
    bundle_identifier = f"com.khaos.dsh-feasibility-probe.{uuid.uuid4().hex[:12]}"
    container = Path.home() / "Library/Containers" / bundle_identifier / "Data"
    completed = False
    try:
        node_root.mkdir()
        with tarfile.open(args.node_archive.resolve(strict=True), "r:xz") as archive:
            archive.extractall(node_root, filter="data")
        node_dir = node_root / "node-v22.19.0-darwin-arm64"
        node = node_dir / "bin/node"
        if not node.is_file() or output([str(node), "--version"]) != PINNED_NODE_VERSION:
            raise RuntimeError("verified Node archive does not contain the expected runtime")

        probe_dir = Path(__file__).resolve().parents[1] / "experiments/dsh-feasibility"
        runtime_bundle, runtime_hash = build_dsh_bundle(dsh_source, probe_dir, pnpm, temp_root)
        dsh_resources.mkdir(parents=True)
        (app_contents / "MacOS").mkdir(parents=True)
        shutil.copy2(node, resources / "node")
        shutil.copy2(runtime_bundle, dsh_resources / "runtime-probe.mjs")
        shutil.copy2(probe_dir / "crash-probe.mjs", dsh_resources / "crash-probe.mjs")
        shutil.copy2(node_dir / "LICENSE", resources / "NODE_LICENSE")
        shutil.copy2(dsh_source / "LICENSE", resources / "DSH_LICENSE")
        (resources / "package.json").write_text(
            json.dumps({"name": "khaos-dsh-feasibility-probe", "version": "0.2.1-rc.2"}),
            encoding="utf-8",
        )

        info = {
            "CFBundleDevelopmentRegion": "en",
            "CFBundleExecutable": "KhaosDSHRuntimeProbe",
            "CFBundleIdentifier": bundle_identifier,
            "CFBundleInfoDictionaryVersion": "6.0",
            "CFBundleName": "Khaos DSH Runtime Probe",
            "CFBundlePackageType": "APPL",
            "CFBundleShortVersionString": "1.0",
            "CFBundleVersion": "1",
            "LSBackgroundOnly": True,
            "LSMinimumSystemVersion": "13.0",
        }
        with (app_contents / "Info.plist").open("wb") as stream:
            plistlib.dump(info, stream)
        entitlements = temp_root / "app-sandbox-entitlements.plist"
        with entitlements.open("wb") as stream:
            plistlib.dump({"com.apple.security.app-sandbox": True}, stream)
        node_entitlements = temp_root / "node-entitlements.plist"
        with node_entitlements.open("wb") as stream:
            plistlib.dump({"com.apple.security.cs.allow-jit": True}, stream)

        host_source = Path(__file__).resolve().parents[1] / "experiments/dsh-feasibility/SignedRuntimeHost.swift"
        controller_source = Path(__file__).resolve().parents[1] / "experiments/dsh-feasibility/LaunchSignedRuntimeProbe.swift"
        swift_cache = temp_root / "swift-module-cache"
        swift_cache.mkdir()
        run(
            [
                "/usr/bin/swiftc",
                "-O",
                "-parse-as-library",
                "-module-cache-path",
                str(swift_cache),
                str(host_source),
                "-o",
                str(app_contents / "MacOS/KhaosDSHRuntimeProbe"),
            ]
        )
        controller = temp_root / "LaunchSignedRuntimeProbe"
        run(
            [
                "/usr/bin/swiftc",
                "-O",
                "-parse-as-library",
                "-module-cache-path",
                str(swift_cache),
                str(controller_source),
                "-o",
                str(controller),
            ]
        )

        signing_options = ["--force", "--options", "runtime", "--timestamp=none", "--sign", args.signing_identity]
        run(
            [
                "/usr/bin/codesign",
                *signing_options,
                "--entitlements",
                str(node_entitlements),
                "--identifier",
                f"{bundle_identifier}.node",
                str(resources / "node"),
            ]
        )
        run(
            [
                "/usr/bin/codesign",
                *signing_options,
                "--entitlements",
                str(entitlements),
                "--identifier",
                bundle_identifier,
                str(app),
            ]
        )
        run(["/usr/bin/codesign", "--verify", "--deep", "--strict", "--verbose=2", str(app)])

        result = subprocess.run(
            [str(controller), str(app)],
            cwd=Path.home(),
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=70,
        )
        print(result.stdout, end="")
        if result.returncode != 0:
            raise RuntimeError(f"Launch Services controller failed with exit {result.returncode}")
        if "signed_app_terminated=true" not in result.stdout:
            raise RuntimeError("Launch Services controller did not observe app termination")
        log_result = subprocess.run(
            [
                "/usr/bin/log",
                "show",
                "--last",
                "3m",
                "--style",
                "compact",
                "--predicate",
                f'subsystem == "{bundle_identifier}" AND eventMessage CONTAINS "KHAOS_DSH_EVIDENCE"',
            ],
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        evidence_lines = [
            line.split("KHAOS_DSH_EVIDENCE ", 1)[1]
            for line in log_result.stdout.splitlines()
            if "KHAOS_DSH_EVIDENCE " in line
        ]
        if len(evidence_lines) != 1:
            raise RuntimeError(f"expected one sanitized signed-app log event, got {len(evidence_lines)}")
        app_result = json.loads(evidence_lines[0])
        app_exit = app_result.get("childExitStatus")
        print(f"signed_app_exit={app_exit}")
        print(f"signed_app_evidence={json.dumps(app_result, sort_keys=True)}")
        if app_exit != 0 or app_result.get("evidenceDecode") == "FAILED":
            raise RuntimeError(f"signed app or DSH runtime smoke probe failed with exit {app_exit}")
        if app_result.get("intentionalChildTermination") != "PASS":
            raise RuntimeError("signed app did not observe the intentional child-process signal")
        evidence = {
            "signedRuntime": "PASS",
            "dshToolRoundTrip": app_result.get("dshToolRoundTrip"),
            "intentionalChildTermination": app_result.get("intentionalChildTermination"),
            "nodeRssBytes": app_result.get("nodeRssBytes"),
        }
        if evidence["dshToolRoundTrip"] != "PASS":
            raise RuntimeError("signed standalone runtime did not complete the DSH adapter roundtrip")

        node_deps = output(["/usr/bin/otool", "-L", str(resources / "node")]).splitlines()[1:]
        node_signature = output(["/usr/bin/codesign", "-dv", "--verbose=2", str(resources / "node")])
        node_entitlement_output = output(["/usr/bin/codesign", "-d", "--entitlements", ":-", str(resources / "node")])
        app_signature = output(["/usr/bin/codesign", "-dv", "--verbose=2", str(app)])
        print(f"DSH_SHA={PINNED_DSH_SHA}")
        print(f"Node.js={PINNED_NODE_VERSION}")
        print(f"Node_archive_sha256={PINNED_NODE_ARCHIVE_SHA256}")
        print(f"Node_binary_sha256={digest(resources / 'node')}")
        print(f"DSH_runtime_bundle_bytes={runtime_bundle.stat().st_size}")
        print(f"DSH_runtime_bundle_sha256={runtime_hash}")
        print(f"DSH_runtime_rss_bytes={evidence.get('nodeRssBytes')}")
        print(f"Intentional_child_termination={evidence.get('intentionalChildTermination')}")
        print(f"Node_non_system_dylib_count={sum('/System/' not in line and '/usr/lib/' not in line for line in node_deps)}")
        print(f"App_sandbox_entitlements=com.apple.security.app-sandbox:true; network.client:false")
        print(f"Node_entitlements=com.apple.security.cs.allow-jit:{'true' if 'com.apple.security.cs.allow-jit' in node_entitlement_output else 'missing'}")
        print(f"Node_signature_team={next((line.split('=', 1)[1] for line in node_signature.splitlines() if line.startswith('TeamIdentifier=')), 'unknown')}")
        print(f"App_signature_team={next((line.split('=', 1)[1] for line in app_signature.splitlines() if line.startswith('TeamIdentifier=')), 'unknown')}")
        print("Hostile OS probes=NOT_RUN in this standalone runtime smoke check; see the signed AgentHost XPC attack acceptance")
        print(f"Signed_app={app}")
        print(f"Signed_app_bytes={sum(path.stat().st_size for path in app.rglob('*') if path.is_file())}")
        completed = True
        return 0
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)
        shutil.rmtree(container.parent, ignore_errors=True)
        if not completed and app.exists():
            shutil.rmtree(app, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
