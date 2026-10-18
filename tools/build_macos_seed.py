"""Build a locally signed macOS Seed app with its fixed Kernel XPC services."""

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
import stat
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[1]
APP_ID = "org.khaos.Seed"
AGENT_HOST_ID = f"{APP_ID}.AgentHost"
SERVICE_ID = f"{APP_ID}.KernelProduction"
SNAPSHOT_BROKER_ID = f"{APP_ID}.KernelSnapshotBroker"
MODEL_RUNTIME_VERSION_TIMEOUT_SECONDS = 60
SEED_PYTHON_SOURCES = (
    "khaos/__init__.py",
    "khaos/ipc.py",
    "khaos/launcher.py",
    "khaos/runner.py",
    "khaos/runner_sdk.py",
    "khaos/kernel/__init__.py",
    "khaos/kernel/broker.py",
    "khaos/kernel/macos_seatbelt.py",
    "khaos/kernel/plugin_lifecycle.py",
    "khaos/kernel/peer_identity.py",
    "khaos/kernel/worker.py",
    "khaos/kernel/workspace_changes.py",
    "khaos/kernel/workspace_snapshot.py",
    "khaos/kernel/workspace_xpc_bridge.py",
)
PYTHON_CODE = (
    "import json,sys; "
    "print(json.dumps({'version': f'{sys.version_info.major}.{sys.version_info.minor}', "
    "'executable': sys.executable}))"
)


class BuildError(RuntimeError):
    pass


def _query_model_runtime_version(executable: Path) -> str:
    try:
        version_result = subprocess.run(
            [str(executable), "--version"],
            check=False,
            capture_output=True,
            text=True,
            timeout=MODEL_RUNTIME_VERSION_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise BuildError(f"could not query bundled llama.cpp version: {error}") from error
    if version_result.returncode != 0:
        raise BuildError("could not query bundled llama.cpp version")
    model_version = (version_result.stdout or version_result.stderr).strip()
    if not model_version:
        raise BuildError("llama.cpp returned no runtime version")
    return model_version


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, help="new .app output path")
    parser.add_argument("--verify-app", type=Path, help="verify an existing app against the supplied certificate SHA-1")
    parser.add_argument("--expected-inputs", type=Path, help="reviewed source SHA-256 map; require an exact match")
    parser.add_argument(
        "--signing-identity",
        required=True,
        help="stable code-signing identity available in the keychain",
    )
    parser.add_argument("--build-version", default="1", help="numeric dotted local build version")
    parser.add_argument(
        "--agent-action-diagnostics", action="store_true",
        help="opt in to bounded Agent Host diagnostics in this signed build",
    )
    parser.add_argument("--keychain", type=Path)
    parser.add_argument("--python-executable", type=Path, default=Path(sys.executable))
    parser.add_argument(
        "--model-provider",
        choices=("local", "bigmodel", "bigmodel-coding-plan"),
        default="local",
        help="local model (default) or the opt-in BigModel GLM-5.3-Flash API",
    )
    parser.add_argument("--llama-cli", type=Path)
    parser.add_argument("--model-file", type=Path)
    parser.add_argument("--model-license", type=Path)
    args = parser.parse_args()
    try:
        if args.verify_app is not None:
            verify_app(args.verify_app, args.signing_identity)
            print("macos-seed-verification=PASS")
            return 0
        if args.output is None:
            raise BuildError("--output is required for a build")
        build_app(
            args.output,
            args.signing_identity,
            expected_inputs=args.expected_inputs,
            build_version=args.build_version,
            agent_action_diagnostics=args.agent_action_diagnostics,
            keychain=args.keychain,
            python_executable=args.python_executable,
            model_provider=args.model_provider,
            llama_cli=args.llama_cli,
            model_file=args.model_file,
            model_license=args.model_license,
        )
    except (BuildError, KeyError, OSError, subprocess.SubprocessError) as error:
        print(f"build-macos-seed-error: {error}", file=sys.stderr)
        return 1
    print(f"macos-seed-app={args.output.expanduser().resolve()}")
    return 0


def build_app(
    output: Path,
    signing_identity: str,
    *,
    keychain: Path | None = None,
    expected_inputs: Path | None = None,
    build_version: str = "1",
    agent_action_diagnostics: bool = False,
    python_executable: Path,
    model_provider: str = "local",
    llama_cli: Path | None = None,
    model_file: Path | None = None,
    model_license: Path | None = None,
) -> None:
    if not re.fullmatch(r"[0-9]{1,6}(?:\.[0-9]{1,6}){0,2}", build_version):
        raise BuildError("build version must contain one to three bounded numeric components")
    if sys.platform != "darwin":
        raise BuildError("the Seed app supports macOS only")
    if not signing_identity.strip():
        raise BuildError("a stable code-signing identity is required")
    if model_provider not in {"local", "bigmodel", "bigmodel-coding-plan"}:
        raise BuildError("unsupported model provider")
    if any((llama_cli, model_file, model_license)) and not all(
        (llama_cli, model_file, model_license)
    ):
        raise BuildError("--llama-cli, --model-file, and --model-license must be used together")
    if model_provider != "local" and any((llama_cli, model_file, model_license)):
        raise BuildError("BigModel builds cannot bundle or fall back to a local model")

    output = output.expanduser().absolute()
    if output.suffix != ".app" or os.path.lexists(output):
        raise BuildError("output must be a new .app path")
    output.parent.mkdir(parents=True, exist_ok=True)
    signing_identity = _require_signing_identity(signing_identity, keychain)
    sdk = _run(["xcrun", "--sdk", "macosx", "--show-sdk-path"]).strip()
    swiftc = _run(["xcrun", "--find", "swiftc"]).strip()
    install_name_tool = _run(["xcrun", "--find", "install_name_tool"]).strip()
    python = _python_framework(python_executable)
    architecture = platform.machine()
    if architecture not in {"arm64", "x86_64"}:
        raise BuildError(f"unsupported macOS architecture: {architecture}")

    with tempfile.TemporaryDirectory(
        prefix=".khaos-seed-build-", dir=output.parent
    ) as temporary:
        source_root = Path(temporary) / "inputs"
        source_hashes = _snapshot_sources(source_root, expected_inputs)
        record = {
            "schema": 1, "source_sha256": source_hashes, "build_version": build_version,
            "builder_sha256": _sha256_file(Path(__file__)),
            "certificate_sha1": signing_identity,
            "architecture": architecture,
            "macos": platform.mac_ver()[0],
            "swift": _run([swiftc, "--version"]).strip(),
            "sdk": _run(["xcrun", "--sdk", "macosx", "--show-sdk-version"]).strip(),
            "python_version": _run([str(python_executable), "-I", "-S", "-c", "import sys; print(sys.version)"]).strip(),
            "input_policy": "expected-map" if expected_inputs else "recorded-development-inputs",
            "agent_action_diagnostics": agent_action_diagnostics,
        }
        app = Path(temporary) / output.name
        _assemble_app(
            app,
            source_root=source_root,
            build_record=record,
            sdk=sdk,
            swiftc=swiftc,
            install_name_tool=install_name_tool,
            python=python,
            architecture=architecture,
            signing_identity=signing_identity,
            keychain=keychain,
            model_provider=model_provider,
            llama_cli=llama_cli,
            model_file=model_file,
            model_license=model_license,
        )
        # renamex_np(RENAME_EXCL) never replaces an output created during the build.
        _publish_app(app, output)


def _assemble_app(
    app: Path,
    *,
    source_root: Path,
    build_record: dict[str, object],
    sdk: str,
    swiftc: str,
    install_name_tool: str,
    python: tuple[Path, str],
    architecture: str,
    signing_identity: str,
    keychain: Path | None,
    model_provider: str,
    llama_cli: Path | None,
    model_file: Path | None,
    model_license: Path | None,
) -> None:
    python_framework, version = python
    contents = app / "Contents"
    launcher_dir = contents / "MacOS"
    service = contents / "XPCServices" / "KernelProduction.xpc"
    service_contents = service / "Contents"
    broker = contents / "XPCServices" / "KernelSnapshotBroker.xpc"
    broker_contents = broker / "Contents"
    agent_host = contents / "XPCServices" / "KhaosAgentHost.xpc"
    agent_host_contents = agent_host / "Contents"
    launcher_dir.mkdir(parents=True)

    launcher_binary = launcher_dir / "KhaosSeed"
    service_binary = service_contents / "MacOS" / "KernelProduction"
    _compile(
        swiftc,
        sdk,
        architecture,
        launcher_binary,
        (
            source_root / "khaos/macos/KernelWorkspaceXPC.swift",
            source_root / "khaos/macos/XPCPeerIdentity.swift",
            source_root / "khaos/macos/KernelWorkspaceClient.swift",
            source_root / "khaos/macos/KernelSnapshotBrokerBootstrapXPC.swift",
            source_root / "khaos/macos/KernelSnapshotBrokerBootstrapClient.swift",
            source_root / "khaos/macos/TrustedWorkspacePicker.swift",
            source_root / "khaos/macos/AgentHostProtocol.swift",
            source_root / "khaos/macos/AgentHostClient.swift",
            source_root / "khaos/macos/TrustedWorkspaceLauncherMain.swift",
        ),
    )
    _write_plist(
        contents / "Info.plist",
        {
            "CFBundleIdentifier": APP_ID,
            "CFBundleExecutable": "KhaosSeed",
            "CFBundleInfoDictionaryVersion": "6.0",
            "CFBundlePackageType": "APPL",
            "CFBundleName": "Khaos Seed",
            "CFBundleShortVersionString": "0.1.0",
            "CFBundleVersion": build_record["build_version"],
            "LSMinimumSystemVersion": "13.0",
            "NSPrincipalClass": "NSApplication",
            "KhaosModelProvider": model_provider,
        },
    )
    app_resources = contents / "Resources"
    app_resources.mkdir()
    shutil.copy2(
        source_root / "examples" / "memory" / "evaluation.json",
        app_resources / "memory-evaluation.json",
    )
    app_entitlements = app.parent / "app-entitlements.plist"
    service_entitlements = app.parent / "service-entitlements.plist"
    broker_entitlements = app.parent / "broker-entitlements.plist"
    agent_host_entitlements = app.parent / "agent-host-entitlements.plist"
    _write_plist(
        app_entitlements,
        {
            "com.apple.security.app-sandbox": True,
            "com.apple.security.files.user-selected.read-write": True,
        },
    )
    # This trusted service must apply a stricter Seatbelt profile to its
    # untrusted Runner children. App Sandbox denies sandbox_apply in children.
    _write_plist(service_entitlements, {})
    _write_plist(broker_entitlements, {})
    agent_host_entitlement_values = {"com.apple.security.app-sandbox": True}
    if model_provider != "local":
        agent_host_entitlement_values["com.apple.security.network.client"] = True
    _write_plist(agent_host_entitlements, agent_host_entitlement_values)

    # Derive the stable host requirement before adding its nested XPC service.
    _sign(app, signing_identity, app_entitlements, keychain)
    launcher_requirement = _designated_requirement(launcher_binary, APP_ID)

    agent_host_binary = agent_host_contents / "MacOS" / "KhaosAgentHost"
    agent_host_binary.parent.mkdir(parents=True)
    _compile(
        swiftc,
        sdk,
        architecture,
        agent_host_binary,
        (
            source_root / "khaos/macos/AgentHostProtocol.swift",
            source_root / "khaos/macos/AgentHostCandidateSource.swift",
            source_root / "khaos/macos/AgentHostActionOutput.swift",
            source_root / "khaos/macos/AgentHost.swift",
        ),
        minimum_os_version="26.0",
    )
    xpc_configuration: dict[str, object] = {
        "ServiceType": "Application", "RunLoopType": "NSRunLoop",
    }
    if build_record["agent_action_diagnostics"]:
        xpc_configuration["EnvironmentVariables"] = {"KHAOS_AGENT_ACTION_DIAGNOSTICS": "1"}
    _write_plist(
        agent_host_contents / "Info.plist",
        {
            "CFBundleIdentifier": AGENT_HOST_ID,
            "CFBundleExecutable": "KhaosAgentHost",
            "CFBundleInfoDictionaryVersion": "6.0",
            "CFBundlePackageType": "XPC!",
            "CFBundleName": "Khaos Agent Host",
            "CFBundleShortVersionString": "0.1.0",
            "CFBundleVersion": build_record["build_version"],
            "LSMinimumSystemVersion": "26.0",
            "KhaosLauncherRequirement": launcher_requirement,
            "KhaosModelProvider": model_provider,
            "XPCService": xpc_configuration,
        },
    )
    if llama_cli is not None and model_file is not None and model_license is not None:
        _bundle_local_model(
            agent_host_contents,
            llama_cli=llama_cli,
            model_file=model_file,
            model_license=model_license,
            install_name_tool=install_name_tool,
            signing_identity=signing_identity,
            keychain=keychain,
        )
    _sign(agent_host, signing_identity, agent_host_entitlements, keychain)
    agent_host_requirement = _designated_requirement(agent_host_binary, AGENT_HOST_ID)
    if agent_host_requirement == launcher_requirement:
        raise BuildError("Agent Host must not share the trusted Launcher identity")

    (service_contents / "MacOS").mkdir(parents=True)
    _compile(
        swiftc,
        sdk,
        architecture,
        service_binary,
        (
            source_root / "khaos/macos/KernelWorkspaceXPC.swift",
            source_root / "khaos/macos/KernelWorkspaceClient.swift",
            source_root / "khaos/macos/KernelWorkspaceRoot.swift",
            source_root / "khaos/macos/KernelWorkspaceService.swift",
            source_root / "khaos/macos/XPCPeerIdentity.swift",
            source_root / "khaos/macos/KernelSnapshotBrokerXPC.swift",
            source_root / "khaos/macos/KernelSnapshotStoragePolicy.swift",
            source_root / "khaos/macos/KernelSnapshotBrokerClient.swift",
            source_root / "khaos/macos/KernelWorkspaceBootstrap.swift",
            source_root / "khaos/macos/KernelCStringArray.swift",
            source_root / "khaos/macos/KernelWorkspacePythonExecutor.swift",
            source_root / "khaos/macos/KernelWorkspaceServiceMain.swift",
        ),
    )
    broker_binary = broker_contents / "MacOS" / "KernelSnapshotBroker"
    (broker_contents / "MacOS").mkdir(parents=True)
    _compile(
        swiftc,
        sdk,
        architecture,
        broker_binary,
        (
            source_root / "khaos/macos/KernelSnapshotBrokerXPC.swift",
            source_root / "khaos/macos/KernelSnapshotBrokerBootstrapXPC.swift",
            source_root / "khaos/macos/KernelSnapshotStoragePolicy.swift",
            source_root / "khaos/macos/KernelSnapshotBrokerSandbox.swift",
            source_root / "khaos/macos/XPCPeerIdentity.swift",
            source_root / "khaos/macos/KernelCStringArray.swift",
            source_root / "khaos/macos/KernelSnapshotBrokerToolRunner.swift",
            source_root / "khaos/macos/KernelSnapshotBrokerService.swift",
            source_root / "khaos/macos/KernelSnapshotBrokerServiceMain.swift",
        ),
    )
    _embed_python(
        service_contents,
        (python_framework, version),
        version,
        install_name_tool,
    )
    resources = service_contents / "Resources"
    resources.mkdir()
    for relative_path in SEED_PYTHON_SOURCES:
        source = source_root / relative_path
        if not source.is_file() or source.resolve(strict=True) != source:
            raise BuildError(f"Kernel source is unavailable: {relative_path}")
        destination = resources / relative_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)

    kernel_info = {
        "CFBundleIdentifier": SERVICE_ID,
        "CFBundleExecutable": "KernelProduction",
        "CFBundlePackageType": "XPC!",
        "CFBundleName": "Khaos Seed Kernel",
        "CFBundleVersion": build_record["build_version"],
        "KhaosBootstrapRequirement": launcher_requirement,
        "KhaosWorkspaceCallerRequirement": launcher_requirement,
        "KhaosPythonVersion": version,
        "XPCService": {
            "ServiceType": "Application",
            "RunLoopType": "NSRunLoop",
        },
    }
    _write_plist(
        service_contents / "Info.plist",
        kernel_info,
    )
    _sign(service, signing_identity, service_entitlements, keychain)
    service_requirement = _designated_requirement(service_binary, SERVICE_ID)

    _write_plist(
        broker_contents / "Info.plist",
        {
            "CFBundleIdentifier": SNAPSHOT_BROKER_ID,
            "CFBundleExecutable": "KernelSnapshotBroker",
            "CFBundlePackageType": "XPC!",
            "CFBundleName": "Khaos Snapshot Broker",
            "CFBundleVersion": build_record["build_version"],
            "KhaosLauncherCallerRequirement": launcher_requirement,
            "KhaosKernelCallerRequirement": service_requirement,
            "KhaosKernelContainerIdentifier": SERVICE_ID,
            "XPCService": {
                "ServiceType": "Application",
                "RunLoopType": "NSRunLoop",
            },
        },
    )
    _sign(broker, signing_identity, broker_entitlements, keychain)
    broker_requirement = _designated_requirement(broker_binary, SNAPSHOT_BROKER_ID)

    kernel_info["KhaosSnapshotBrokerRequirement"] = broker_requirement
    _write_plist(service_contents / "Info.plist", kernel_info)
    _sign(service, signing_identity, service_entitlements, keychain)
    if _designated_requirement(service_binary, SERVICE_ID) != service_requirement:
        raise BuildError("Kernel signing requirement changed while embedding the broker")

    app_info = contents / "Info.plist"
    values = _read_plist(app_info)
    values["KhaosKernelProductionServiceRequirement"] = service_requirement
    values["KhaosKernelSnapshotBrokerRequirement"] = broker_requirement
    values["KhaosSnapshotBrokerServiceName"] = SNAPSHOT_BROKER_ID
    _write_plist(app_info, values)
    # Record the actual embedded runtime, including nested signed dependencies,
    # before signing the outer bundle. No signed content is changed afterward.
    build_record["embedded_sha256"] = {
        str(path.relative_to(app)): _sha256_file(path)
        for path in sorted(app.rglob("*"))
        if path.is_file() and not path.is_symlink()
        and path.relative_to(app).parts[1:2] == ("XPCServices",)
    }
    record_path = contents / "Resources" / "build-inputs.json"
    record_path.parent.mkdir(exist_ok=True)
    record_path.write_text(json.dumps(build_record, sort_keys=True, indent=2) + "\n")
    _sign(app, signing_identity, app_entitlements, keychain)
    verify_app(app, signing_identity)


def _compile(
    swiftc: str,
    sdk: str,
    architecture: str,
    output: Path,
    sources: tuple[Path, ...],
    *,
    minimum_os_version: str = "13.0",
) -> None:
    _run(
        [
            swiftc,
            "-sdk",
            sdk,
            "-target",
            f"{architecture}-apple-macosx{minimum_os_version}",
            "-parse-as-library",
            *(str(source) for source in sources),
            "-o",
            str(output),
        ]
    )


def _python_framework(executable: Path) -> tuple[Path, str]:
    executable = executable.expanduser().resolve(strict=True)
    result = _run([str(executable), "-I", "-S", "-c", PYTHON_CODE])
    try:
        details = json.loads(result)
        version = details["version"]
        runtime = Path(details["executable"]).resolve(strict=True)
    except (KeyError, TypeError, ValueError) as error:
        raise BuildError("could not inspect the Python runtime") from error
    framework = next(
        (parent for parent in runtime.parents if parent.name == "Python.framework"),
        None,
    )
    if framework is None or not re.fullmatch(r"\d+\.\d+", version):
        raise BuildError("Python.framework runtime is required for the Kernel")
    expected = framework / "Versions" / version / "bin" / f"python{version}"
    if runtime != expected:
        raise BuildError("Python executable is outside its versioned framework path")
    return framework, version


def _embed_python(
    service_contents: Path,
    python: tuple[Path, str],
    version: str,
    install_name_tool: str,
) -> None:
    framework, _ = python
    destination = service_contents / "Frameworks" / "Python.framework"
    destination.parent.mkdir(parents=True)
    shutil.copytree(
        framework,
        destination,
        symlinks=True,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )
    version_root = destination / "Versions" / version
    site_packages = version_root / "lib" / f"python{version}" / "site-packages"
    if site_packages.is_symlink():
        site_packages.unlink()
    elif site_packages.exists():
        shutil.rmtree(site_packages)
    for path, replacement in (
        (
            version_root / "bin" / f"python{version}",
            "@executable_path/../Python",
        ),
        (
            version_root / "Resources/Python.app/Contents/MacOS/Python",
            "@executable_path/../../../../Python",
        ),
    ):
        _run(
            [
                install_name_tool,
                "-change",
                str(framework / "Versions" / version / "Python"),
                replacement,
                str(path),
            ]
        )

    python_app = version_root / "Resources/Python.app"
    for path in (
        version_root / "Python",
        version_root / "bin" / f"python{version}",
        python_app / "Contents/MacOS/Python",
    ):
        _run(["codesign", "--force", "--sign", "-", str(path)])
    _run(["codesign", "--force", "--sign", "-", str(python_app)])
    _run(["codesign", "--force", "--sign", "-", str(destination)])
    _run(["codesign", "--verify", "--deep", "--strict", str(destination)])


def _bundle_local_model(
    agent_host_contents: Path,
    *,
    llama_cli: Path,
    model_file: Path,
    model_license: Path,
    install_name_tool: str,
    signing_identity: str,
    keychain: Path | None,
) -> None:
    executable = _regular_source(llama_cli, executable=True)
    model = _regular_source(model_file, maximum_bytes=24 * 1024**3)
    license_file = _regular_source(model_license, maximum_bytes=1024**2)
    otool = shutil.which("otool")
    if otool is None:
        raise BuildError("otool is required to bundle llama.cpp dependencies")

    runtime = agent_host_contents / "Frameworks" / "KhaosLlama"
    runtime.mkdir(parents=True)
    library_sources: dict[str, Path] = {}
    pending = [(executable, runtime / "llama-cli")]
    examined: set[Path] = set()
    while pending:
        source, _ = pending.pop()
        resolved_source = source.resolve(strict=True)
        if resolved_source in examined:
            continue
        examined.add(resolved_source)
        for dependency in _linked_libraries(otool, resolved_source):
            if dependency.startswith(("/System/Library/", "/usr/lib/")):
                continue
            resolved = _resolve_library(
                dependency,
                binary=resolved_source,
                executable=executable,
                otool=otool,
            )
            name = Path(dependency.removeprefix("@rpath/")).name
            previous = library_sources.get(name)
            if previous is not None and previous.resolve(strict=True) != resolved:
                raise BuildError(f"llama.cpp has conflicting libraries named {name}")
            if previous is None:
                library_sources[name] = resolved
                pending.append((resolved, runtime / name))
    executable_destination = runtime / "llama-cli"
    shutil.copy2(executable, executable_destination)
    for name, source in library_sources.items():
        shutil.copy2(source, runtime / name)

    destinations = [executable_destination, *(runtime / name for name in library_sources)]
    for destination in destinations:
        source = executable if destination == executable_destination else library_sources[destination.name]
        for dependency in _linked_libraries(otool, source):
            if dependency.startswith(("/System/Library/", "/usr/lib/")):
                continue
            _run([
                install_name_tool,
                "-change",
                dependency,
                f"@loader_path/{Path(dependency.removeprefix('@rpath/')).name}",
                str(destination),
            ])
        if destination != executable_destination:
            _run([
                install_name_tool,
                "-id",
                f"@loader_path/{destination.name}",
                str(destination),
            ])
        _sign_code(destination, signing_identity, keychain)

    resources = agent_host_contents / "Resources"
    notices = resources / "THIRD_PARTY_NOTICES"
    notices.mkdir(parents=True)
    shutil.copy2(model, resources / "agent-model.gguf")
    shutil.copy2(license_file, notices / "AgentModel-LICENSE")
    formula_prefixes: dict[str, Path] = {}
    for source in (executable, *library_sources.values()):
        prefix = source.parent.parent if source.parent.name == "bin" else source.parents[1]
        if prefix.parent.parent.name == "Cellar":
            formula_prefixes[prefix.parent.name] = prefix
    for formula, prefix in formula_prefixes.items():
        candidates = [
            prefix / "LICENSE", prefix / "LICENSE.txt", prefix / "LICENSE.TXT",
            prefix / "COPYING",
        ]
        license_path = next((path for path in candidates if path.is_file()), None)
        if license_path is None:
            raise BuildError(f"missing license for bundled Homebrew dependency {formula}")
        shutil.copy2(license_path, notices / f"{formula}-LICENSE")
    source_license = next(
        (
            parent / "LICENSE"
            for parent in executable.parents
            if (parent / "CMakeLists.txt").is_file()
            and (parent / "LICENSE").is_file()
        ),
        None,
    )
    if source_license is not None:
        shutil.copy2(source_license, notices / "llama.cpp-LICENSE")
    (notices / "RUNTIME-VERSIONS.txt").write_text(
        "\n".join(
            f"{formula} {prefix.name}"
            for formula, prefix in sorted(formula_prefixes.items())
        ) + "\n",
        encoding="utf-8",
    )
    model_version = _query_model_runtime_version(executable)
    host_info = agent_host_contents / "Info.plist"
    values = _read_plist(host_info)
    values["KhaosLocalModelRuntime"] = model_version
    values["KhaosLocalModelSHA256"] = _sha256_file(model)
    _write_plist(host_info, values)


def _regular_source(
    path: Path,
    *,
    executable: bool = False,
    maximum_bytes: int | None = None,
) -> Path:
    source = path.expanduser().resolve(strict=True)
    info = source.stat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise BuildError(f"input must be a regular, single-link file: {path.name}")
    if executable and not os.access(source, os.X_OK):
        raise BuildError("llama-cli must be executable")
    if maximum_bytes is not None and not 0 < info.st_size <= maximum_bytes:
        raise BuildError(f"input file has an unsupported size: {path.name}")
    return source


def _linked_libraries(otool: str, binary: Path) -> list[str]:
    lines = _run([otool, "-L", str(binary)]).splitlines()[1:]
    return [
        match.group(1).strip()
        for line in lines
        if (match := re.match(r"\s*(.+?) \(compatibility version ", line))
    ]


def _resolve_library(
    dependency: str,
    *,
    binary: Path,
    executable: Path,
    otool: str,
) -> Path:
    if dependency.startswith("@loader_path/"):
        candidates = [binary.parent / dependency.removeprefix("@loader_path/")]
    elif dependency.startswith("@executable_path/"):
        candidates = [executable.parent / dependency.removeprefix("@executable_path/")]
    elif dependency.startswith("@rpath/"):
        suffix = dependency.removeprefix("@rpath/")
        candidates = []
        for rpath in _rpaths(otool, binary):
            if rpath == "@loader_path":
                root = binary.parent
            elif rpath.startswith("@loader_path/"):
                root = binary.parent / rpath.removeprefix("@loader_path/")
            elif rpath == "@executable_path":
                root = executable.parent
            elif rpath.startswith("@executable_path/"):
                root = executable.parent / rpath.removeprefix("@executable_path/")
            elif rpath.startswith("/"):
                root = Path(rpath)
            else:
                continue
            candidates.append(root / suffix)
    elif dependency.startswith("/"):
        candidates = [Path(dependency)]
    else:
        raise BuildError(f"unsupported llama.cpp library reference: {dependency}")
    for candidate in candidates:
        if candidate.exists():
            resolved = candidate.resolve(strict=True)
            if resolved.is_file():
                return resolved
    raise BuildError(f"could not resolve llama.cpp library: {dependency}")


def _rpaths(otool: str, binary: Path) -> list[str]:
    lines = _run([otool, "-l", str(binary)]).splitlines()
    values = []
    for index, line in enumerate(lines):
        if line.strip() == "cmd LC_RPATH":
            for candidate in lines[index + 1:index + 4]:
                match = re.match(r"\s*path (.+?) \(offset ", candidate)
                if match:
                    values.append(match.group(1))
                    break
    return values


def _sign_code(path: Path, identity: str, keychain: Path | None) -> None:
    command = ["codesign", "--force"]
    if keychain is not None:
        command.extend(("--keychain", str(keychain.expanduser().resolve(strict=True))))
    command.extend(("--sign", identity, str(path)))
    _run(command)


def _sha256_file(path: Path) -> str:
    import hashlib

    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _require_signing_identity(identity: str, keychain: Path | None) -> str:
    command = ["security", "find-identity", "-p", "codesigning"]
    if keychain is not None:
        command.append(str(keychain.expanduser().resolve(strict=True)))
    output = _run(command)
    identities = re.findall(r'\d+\) ([0-9A-Fa-f]{40}) "([^"\n]+)"([^\n]*)', output)
    # A local self-signed root need not be globally trusted for explicit DR
    # matching. Do not reject it via find-identity -v; still reject expired keys.
    matches = {fingerprint.upper() for fingerprint, name, error in identities
               if error.strip() in {"", "(CSSMERR_TP_NOT_TRUSTED)"}
               and (identity.upper() == fingerprint.upper() or identity == name)}
    if len(matches) != 1:
        raise BuildError("select exactly one available non-expired signing identity by full name or SHA-1")
    return matches.pop()


def verify_app(app: Path, certificate_sha1: str) -> None:
    """Verify actual code against an independently supplied signer, not its metadata."""
    if not re.fullmatch(r"[0-9A-Fa-f]{40}", certificate_sha1):
        raise BuildError("verification requires the expected certificate SHA-1")
    app = app.expanduser().resolve(strict=True)
    bundles = ((app, APP_ID),
               (app / "Contents/XPCServices/KhaosAgentHost.xpc", AGENT_HOST_ID),
               (app / "Contents/XPCServices/KernelProduction.xpc", SERVICE_ID),
               (app / "Contents/XPCServices/KernelSnapshotBroker.xpc", SNAPSHOT_BROKER_ID))
    for bundle, identifier in bundles:
        requirement = f'identifier "{identifier}" and certificate leaf = H"{certificate_sha1}"'
        _run(["codesign", "--verify", "--deep", "--strict", f"-R={requirement}", str(bundle)])
    info = _read_plist(app / "Contents/Info.plist")
    kernel = bundles[2][0]
    broker = bundles[3][0]
    host = bundles[1][0]
    kernel_info = _read_plist(kernel / "Contents/Info.plist")
    broker_info = _read_plist(broker / "Contents/Info.plist")
    host_info = _read_plist(host / "Contents/Info.plist")
    links = ((app, host_info["KhaosLauncherRequirement"]),
             (app, kernel_info["KhaosBootstrapRequirement"]),
             (app, kernel_info["KhaosWorkspaceCallerRequirement"]),
             (app, broker_info["KhaosLauncherCallerRequirement"]),
             (kernel, broker_info["KhaosKernelCallerRequirement"]),
             (kernel, info["KhaosKernelProductionServiceRequirement"]),
             (broker, info["KhaosKernelSnapshotBrokerRequirement"]),
             (broker, kernel_info["KhaosSnapshotBrokerRequirement"]))
    for code, requirement in links:
        _run(["codesign", "--verify", f"-R={requirement}", str(code)])
    if _satisfies_requirement(host, kernel_info["KhaosWorkspaceCallerRequirement"]):
        raise BuildError("Agent Host satisfies the Launcher requirement")


def _snapshot_sources(destination: Path, expected_inputs: Path | None) -> dict[str, str]:
    paths = set(SEED_PYTHON_SOURCES)
    paths.update(str(p.relative_to(ROOT)) for p in (ROOT / "khaos/macos").glob("*.swift"))
    paths.add("examples/memory/evaluation.json")
    hashes = {}
    for relative in sorted(paths):
        source = ROOT / relative
        descriptor = os.open(source, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(descriptor, "rb") as stream:
            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode) or source.resolve() != source:
                raise BuildError(f"source must be a regular non-symlink file: {relative}")
            data = stream.read()
        hashes[relative] = hashlib.sha256(data).hexdigest()
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    if expected_inputs is not None and json.loads(expected_inputs.read_text()) != hashes:
        raise BuildError("source inputs differ from the reviewed SHA-256 map")
    return hashes


def _publish_app(source: Path, output: Path) -> None:
    import ctypes
    library = ctypes.CDLL("/usr/lib/libSystem.B.dylib", use_errno=True)
    rename = library.renamex_np
    rename.argtypes = (ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint)
    rename.restype = ctypes.c_int
    if rename(os.fsencode(source), os.fsencode(output), 0x4) != 0:  # RENAME_EXCL
        raise OSError(ctypes.get_errno(), "could not publish new app without replacement")


def _sign(
    bundle: Path,
    identity: str,
    entitlements: Path,
    keychain: Path | None,
) -> None:
    command = ["codesign", "--force"]
    if keychain is not None:
        command.extend(("--keychain", str(keychain.expanduser().resolve(strict=True))))
    command.extend(("--sign", identity, "--entitlements", str(entitlements), str(bundle)))
    _run(command)


def _designated_requirement(executable: Path, identifier: str) -> str:
    result = _run_result(["codesign", "-dr-", str(executable)])
    output = result.stdout + "\n" + result.stderr
    requirements = set(re.findall(r"designated => (.+)", output))
    if len(requirements) != 1:
        raise BuildError(f"could not derive one designated requirement for {executable.name}")
    requirement = requirements.pop().strip()
    if f'identifier "{identifier}"' not in requirement or "cdhash H" in requirement:
        raise BuildError("signing identity does not yield a stable bundle requirement")
    return requirement


def _satisfies_requirement(executable: Path, requirement: str) -> bool:
    result = subprocess.run(
        ["codesign", "--verify", f"-R={requirement}", str(executable)],
        capture_output=True,
        text=True,
        check=False,
    )
    return result.returncode == 0


def _write_plist(path: Path, values: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as stream:
        plistlib.dump(values, stream)


def _read_plist(path: Path) -> dict[str, object]:
    with path.open("rb") as stream:
        value = plistlib.load(stream)
    if type(value) is not dict:
        raise BuildError(f"invalid property list: {path.name}")
    return value


def _run(arguments: list[str]) -> str:
    result = _run_result(arguments)
    return result.stdout


def _run_result(arguments: list[str]) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(arguments, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or "command failed"
        raise BuildError(f"{Path(arguments[0]).name}: {detail}")
    return result


if __name__ == "__main__":
    raise SystemExit(main())
