"""Build a locally signed macOS Seed app with its fixed Kernel XPC services."""

from __future__ import annotations

import argparse
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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True, help="new .app output path")
    parser.add_argument(
        "--signing-identity",
        required=True,
        help="stable code-signing identity available in the keychain",
    )
    parser.add_argument("--keychain", type=Path)
    parser.add_argument("--python-executable", type=Path, default=Path(sys.executable))
    parser.add_argument("--llama-cli", type=Path)
    parser.add_argument("--model-file", type=Path)
    parser.add_argument("--model-license", type=Path)
    args = parser.parse_args()
    try:
        build_app(
            args.output,
            args.signing_identity,
            keychain=args.keychain,
            python_executable=args.python_executable,
            llama_cli=args.llama_cli,
            model_file=args.model_file,
            model_license=args.model_license,
        )
    except (BuildError, OSError, subprocess.SubprocessError) as error:
        print(f"build-macos-seed-error: {error}", file=sys.stderr)
        return 1
    print(f"macos-seed-app={args.output.expanduser().resolve()}")
    return 0


def build_app(
    output: Path,
    signing_identity: str,
    *,
    keychain: Path | None = None,
    python_executable: Path,
    llama_cli: Path | None = None,
    model_file: Path | None = None,
    model_license: Path | None = None,
) -> None:
    if sys.platform != "darwin":
        raise BuildError("the Seed app supports macOS only")
    if not signing_identity.strip():
        raise BuildError("a stable code-signing identity is required")
    if any((llama_cli, model_file, model_license)) and not all(
        (llama_cli, model_file, model_license)
    ):
        raise BuildError("--llama-cli, --model-file, and --model-license must be used together")

    output = output.expanduser().absolute()
    if output.suffix != ".app" or os.path.lexists(output):
        raise BuildError("output must be a new .app path")
    output.parent.mkdir(parents=True, exist_ok=True)
    _require_signing_identity(signing_identity, keychain)
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
        app = Path(temporary) / output.name
        _assemble_app(
            app,
            sdk=sdk,
            swiftc=swiftc,
            install_name_tool=install_name_tool,
            python=python,
            architecture=architecture,
            signing_identity=signing_identity,
            keychain=keychain,
            llama_cli=llama_cli,
            model_file=model_file,
            model_license=model_license,
        )
        os.replace(app, output)


def _assemble_app(
    app: Path,
    *,
    sdk: str,
    swiftc: str,
    install_name_tool: str,
    python: tuple[Path, str],
    architecture: str,
    signing_identity: str,
    keychain: Path | None,
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
            ROOT / "khaos/macos/KernelWorkspaceXPC.swift",
            ROOT / "khaos/macos/XPCPeerIdentity.swift",
            ROOT / "khaos/macos/KernelWorkspaceClient.swift",
            ROOT / "khaos/macos/KernelSnapshotBrokerBootstrapXPC.swift",
            ROOT / "khaos/macos/KernelSnapshotBrokerBootstrapClient.swift",
            ROOT / "khaos/macos/TrustedWorkspacePicker.swift",
            ROOT / "khaos/macos/AgentHostProtocol.swift",
            ROOT / "khaos/macos/AgentHostClient.swift",
            ROOT / "khaos/macos/TrustedWorkspaceLauncherMain.swift",
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
            "CFBundleVersion": "1",
            "LSMinimumSystemVersion": "13.0",
            "NSPrincipalClass": "NSApplication",
        },
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
    _write_plist(
        agent_host_entitlements,
        {"com.apple.security.app-sandbox": True},
    )

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
            ROOT / "khaos/macos/AgentHostProtocol.swift",
            ROOT / "khaos/macos/AgentHost.swift",
        ),
        minimum_os_version="26.0",
    )
    _write_plist(
        agent_host_contents / "Info.plist",
        {
            "CFBundleIdentifier": AGENT_HOST_ID,
            "CFBundleExecutable": "KhaosAgentHost",
            "CFBundleInfoDictionaryVersion": "6.0",
            "CFBundlePackageType": "XPC!",
            "CFBundleName": "Khaos Agent Host",
            "CFBundleShortVersionString": "0.1.0",
            "CFBundleVersion": "1",
            "LSMinimumSystemVersion": "26.0",
            "KhaosLauncherRequirement": launcher_requirement,
            "XPCService": {
                "ServiceType": "Application",
                "RunLoopType": "NSRunLoop",
            },
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
            ROOT / "khaos/macos/KernelWorkspaceXPC.swift",
            ROOT / "khaos/macos/KernelWorkspaceClient.swift",
            ROOT / "khaos/macos/KernelWorkspaceRoot.swift",
            ROOT / "khaos/macos/KernelWorkspaceService.swift",
            ROOT / "khaos/macos/XPCPeerIdentity.swift",
            ROOT / "khaos/macos/KernelSnapshotBrokerXPC.swift",
            ROOT / "khaos/macos/KernelSnapshotStoragePolicy.swift",
            ROOT / "khaos/macos/KernelSnapshotBrokerClient.swift",
            ROOT / "khaos/macos/KernelWorkspaceBootstrap.swift",
            ROOT / "khaos/macos/KernelCStringArray.swift",
            ROOT / "khaos/macos/KernelWorkspacePythonExecutor.swift",
            ROOT / "khaos/macos/KernelWorkspaceServiceMain.swift",
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
            ROOT / "khaos/macos/KernelSnapshotBrokerXPC.swift",
            ROOT / "khaos/macos/KernelSnapshotBrokerBootstrapXPC.swift",
            ROOT / "khaos/macos/KernelSnapshotStoragePolicy.swift",
            ROOT / "khaos/macos/KernelSnapshotBrokerSandbox.swift",
            ROOT / "khaos/macos/XPCPeerIdentity.swift",
            ROOT / "khaos/macos/KernelCStringArray.swift",
            ROOT / "khaos/macos/KernelSnapshotBrokerToolRunner.swift",
            ROOT / "khaos/macos/KernelSnapshotBrokerService.swift",
            ROOT / "khaos/macos/KernelSnapshotBrokerServiceMain.swift",
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
        source = ROOT / relative_path
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
        "CFBundleVersion": "1",
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
            "CFBundleVersion": "1",
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
    _sign(app, signing_identity, app_entitlements, keychain)
    _verify(
        app,
        launcher_binary,
        agent_host,
        agent_host_binary,
        service_binary,
        broker_binary,
        launcher_requirement,
        agent_host_requirement,
        service_requirement,
        broker_requirement,
    )


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
    model = _regular_source(model_file, maximum_bytes=4 * 1024**3)
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
    try:
        version_result = subprocess.run(
            [str(executable), "--version"],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise BuildError(f"could not query bundled llama.cpp version: {error}") from error
    if version_result.returncode != 0:
        raise BuildError("could not query bundled llama.cpp version")
    model_version = (version_result.stdout or version_result.stderr).strip()
    if not model_version:
        raise BuildError("llama.cpp returned no runtime version")
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


def _require_signing_identity(identity: str, keychain: Path | None) -> None:
    command = ["security", "find-identity", "-p", "codesigning"]
    if keychain is not None:
        command.append(str(keychain.expanduser().resolve(strict=True)))
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    if result.returncode != 0 or identity.lower() not in result.stdout.lower():
        raise BuildError("the requested signing identity is unavailable")


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


def _verify(
    app: Path,
    launcher: Path,
    agent_host: Path,
    agent_host_binary: Path,
    service: Path,
    broker: Path,
    launcher_requirement: str,
    agent_host_requirement: str,
    service_requirement: str,
    broker_requirement: str,
) -> None:
    _run(["codesign", "--verify", "--deep", "--strict", str(app)])
    _run(["codesign", "--verify", f"-R={launcher_requirement}", str(launcher)])
    _run(["codesign", "--verify", "--deep", "--strict", str(agent_host)])
    _run(["codesign", "--verify", f"-R={agent_host_requirement}", str(agent_host_binary)])
    if _satisfies_requirement(agent_host_binary, launcher_requirement):
        raise BuildError("Agent Host unexpectedly satisfies the Launcher XPC identity")
    _run(["codesign", "--verify", f"-R={service_requirement}", str(service)])
    _run(["codesign", "--verify", f"-R={broker_requirement}", str(broker)])


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
