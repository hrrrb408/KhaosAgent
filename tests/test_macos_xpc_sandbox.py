from __future__ import annotations

from collections.abc import Callable
import errno
from functools import partial
import hashlib
import json
import os
import platform
from pathlib import Path
import plistlib
import re
import secrets
import shlex
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import uuid
from unittest.mock import patch


PROBE_SOURCES = Path(__file__).with_name("macos_xpc_probe")
MACOS_TCB_SOURCES = Path(__file__).resolve().parents[1] / "khaos" / "macos"
_PRODUCT_WRITEBACK_EVIDENCE = (
    "workspace-kernel-smoke=preselection-read=denied",
    "workspace-kernel-smoke=workspace-selected",
    "workspace-kernel-smoke=selected-read=available",
    "workspace-kernel-smoke=selected-read=denied",
    "workspace-kernel-smoke=runner-read-list-scope=allow-deny-verified",
    "workspace-kernel-smoke=runner-write-scope=allow-deny-verified",
    "workspace-kernel-smoke=kernel-commit=one-addition-no-overwrite",
    "workspace-kernel-smoke=released-scope-direct-write=denied",
    "workspace-kernel-smoke=passed direct-write=denied",
)


@unittest.skipUnless(
    sys.platform == "darwin"
    and shutil.which("xcrun")
    and shutil.which("codesign")
    and shutil.which("security")
    and shutil.which("openssl"),
    "requires the macOS App Sandbox, XPC runtime and temporary signing tools",
)
class MacOSXPCSandboxTests(unittest.TestCase):
    def _assert_product_writeback_evidence(
        self,
        diagnostic_output: str,
        acceptance_run_id: str,
    ) -> None:
        run_marker = f"workspace-kernel-smoke=acceptance-run-id={acceptance_run_id}"
        self.assertIn(run_marker, diagnostic_output)
        try:
            evidence_positions = tuple(
                diagnostic_output.index(marker)
                for marker in _PRODUCT_WRITEBACK_EVIDENCE
            )
        except ValueError as exc:
            self.fail(f"selected-workspace evidence is incomplete: {exc}")
        self.assertEqual(
            evidence_positions,
            tuple(sorted(evidence_positions)),
            "selected-workspace evidence must be emitted in order",
        )
        self.assertIn(
            f"run-id={acceptance_run_id}",
            diagnostic_output[evidence_positions[-1] :],
        )

    def test_kernel_workspace_reply_decoder_requires_the_matching_abi_version(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory(prefix="khaos-seed-reply-version-") as value:
            root = Path(value)
            sdk = subprocess.run(
                ["xcrun", "--sdk", "macosx", "--show-sdk-path"],
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
            swiftc = subprocess.run(
                ["xcrun", "--find", "swiftc"],
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
            executable = root / "KernelWorkspaceReplyVersionProbe"
            compiled = subprocess.run(
                [
                    swiftc,
                    "-sdk",
                    sdk,
                    "-parse-as-library",
                    str(MACOS_TCB_SOURCES / "KernelWorkspaceXPC.swift"),
                    str(PROBE_SOURCES / "KernelWorkspaceReplyVersionProbe.swift"),
                    "-o",
                    str(executable),
                ],
                check=False,
                capture_output=True,
                text=True,
                timeout=60,
            )
            self.assertEqual(compiled.returncode, 0, compiled.stderr)
            result = subprocess.run(
                [str(executable)],
                check=False,
                capture_output=True,
                text=True,
                timeout=10,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(
                result.stdout.strip(),
                "kernel-workspace-response-versions=8-and-9-separated;"
                "bridge-input=one-request-frame-plus-bookmark",
            )

    def test_product_launcher_process_lookup_resolves_symlinked_temp_path(self) -> None:
        with tempfile.TemporaryDirectory(prefix="khaos-seed-launcher-") as value:
            launcher = Path(value) / "KhaosSeed"
            launcher.touch()
            executable = launcher.resolve(strict=True)
            self.assertNotEqual(launcher, executable)
            with patch(
                "subprocess.run",
                return_value=subprocess.CompletedProcess(
                    ["/bin/ps"],
                    0,
                    stdout=f"123 {executable} --acceptance-workspace /tmp/test\n",
                    stderr="",
                ),
            ) as list_processes:
                self.assertEqual(
                    self._product_executable_process_ids(launcher),
                    [123],
                )
        list_processes.assert_called_once_with(
            ["/bin/ps", "-ww", "-axo", "pid=,command="],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )

    def test_seed_app_builds_and_authenticates_its_kernel_service(self) -> None:
        signer_directory = tempfile.TemporaryDirectory(
            prefix="khaos-seed-test-signer-"
        )
        self.addCleanup(
            self._cleanup_signing_identity,
            Path(signer_directory.name),
            signer_directory.cleanup,
        )
        signing_identity, signing_keychain = self._create_signing_identity(
            Path(signer_directory.name)
        )
        python_executable = Path(sys.executable).resolve(strict=True)
        if not any(
            parent.name == "Python.framework" for parent in python_executable.parents
        ):
            self.skipTest("a Python.framework runtime is required for the Seed bundle")

        application_directory = Path.home() / "Applications"
        application_directory.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(
            prefix="khaos-seed-app-",
            dir=application_directory,
        ) as value:
            root = Path(value)
            product_app = root / "KhaosSeed.app"
            model_probe = self._compile_agent_host_model_probe(root)
            model_file = root / "agent-model.gguf"
            model_file.write_bytes(b"test model fixture\n")
            model_license = root / "model-license.txt"
            model_license.write_text("test license fixture\n", encoding="utf-8")
            build_product = subprocess.run(
                [
                    sys.executable,
                    str(
                        Path(__file__).resolve().parents[1]
                        / "tools"
                        / "build_macos_seed.py"
                    ),
                    "--output",
                    str(product_app),
                    "--signing-identity",
                    signing_identity,
                    "--keychain",
                    str(signing_keychain),
                    "--python-executable",
                    str(python_executable),
                    "--llama-cli",
                    str(model_probe),
                    "--model-file",
                    str(model_file),
                    "--model-license",
                    str(model_license),
                ],
                check=False,
                capture_output=True,
                text=True,
                timeout=300,
            )
            self.assertEqual(
                build_product.returncode,
                0,
                build_product.stdout + build_product.stderr,
            )

            launcher_entitlements = self._signed_entitlements(product_app)
            self.assertIs(
                launcher_entitlements.get("com.apple.security.app-sandbox"),
                True,
            )
            self.assertIs(
                launcher_entitlements.get(
                    "com.apple.security.files.user-selected.read-write"
                ),
                True,
            )
            self.assertNotIn(
                "com.apple.security.files.bookmarks.app-scope",
                launcher_entitlements,
            )
            self.assertNotIn(
                "com.apple.security.network.client", launcher_entitlements
            )
            self.assertNotIn(
                "com.apple.security.network.server", launcher_entitlements
            )
            agent_host_bundle = (
                product_app
                / "Contents"
                / "XPCServices"
                / "KhaosAgentHost.xpc"
            )
            agent_host_entitlements = self._signed_entitlements(agent_host_bundle)
            self.assertIs(
                agent_host_entitlements.get("com.apple.security.app-sandbox"),
                True,
            )
            self.assertNotIn(
                "com.apple.security.files.user-selected.read-write",
                agent_host_entitlements,
            )
            self.assertNotIn(
                "com.apple.security.network.client", agent_host_entitlements
            )
            self.assertNotIn(
                "com.apple.security.network.server", agent_host_entitlements
            )
            service_entitlements = self._signed_entitlements(
                product_app
                / "Contents"
                / "XPCServices"
                / "KernelProduction.xpc"
            )
            self.assertNotIn("com.apple.security.app-sandbox", service_entitlements)
            self.assertNotIn(
                "com.apple.security.files.bookmarks.app-scope",
                service_entitlements,
            )
            self.assertNotIn(
                "com.apple.security.network.client", service_entitlements
            )
            self.assertNotIn(
                "com.apple.security.network.server", service_entitlements
            )

            broker_bundle = (
                product_app
                / "Contents"
                / "XPCServices"
                / "KernelSnapshotBroker.xpc"
            )
            broker_entitlements = self._signed_entitlements(broker_bundle)
            self.assertNotIn(
                "com.apple.security.app-sandbox", broker_entitlements
            )
            broker_binary = (
                broker_bundle / "Contents" / "MacOS" / "KernelSnapshotBroker"
            )
            broker_requirement = self._designated_code_requirement(
                broker_binary, "org.khaos.Seed.KernelSnapshotBroker"
            )
            kernel_binary = (
                product_app
                / "Contents"
                / "XPCServices"
                / "KernelProduction.xpc"
                / "Contents"
                / "MacOS"
                / "KernelProduction"
            )
            kernel_requirement = self._designated_code_requirement(
                kernel_binary, "org.khaos.Seed.KernelProduction"
            )
            service_info_path = (
                product_app
                / "Contents"
                / "XPCServices"
                / "KernelProduction.xpc"
                / "Contents"
                / "Info.plist"
            )
            with service_info_path.open("rb") as stream:
                service_info = plistlib.load(stream)
            self.assertEqual(
                service_info.get("KhaosSnapshotBrokerRequirement"),
                broker_requirement,
            )
            self.assertNotIn("KhaosSnapshotBrokerServiceName", service_info)

            kernel_resources = service_info_path.parent / "Resources"
            packaged_sources = {
                path.relative_to(kernel_resources).as_posix()
                for path in (kernel_resources / "khaos").rglob("*")
                if path.is_file()
            }
            self.assertNotIn(
                "khaos/kernel/macos_disk_image.py",
                packaged_sources,
                "the signed Kernel must not bundle its source-tree-only direct APFS backend",
            )
            self.assertEqual(
                packaged_sources,
                {
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
                },
                "the signed Kernel package gained an unreviewed Python module",
            )

            python_framework = (
                product_app
                / "Contents"
                / "XPCServices"
                / "KernelProduction.xpc"
                / "Contents"
                / "Frameworks"
                / "Python.framework"
            )
            with service_info_path.open("rb") as stream:
                bundled_python_version = plistlib.load(stream)["KhaosPythonVersion"]
            bundled_python = (
                python_framework
                / "Versions"
                / bundled_python_version
                / "bin"
                / f"python{bundled_python_version}"
            )
            nested_import = subprocess.run(
                [
                    str(bundled_python),
                    "-I",
                    "-S",
                    "-B",
                    "-c",
                    (
                        "import subprocess, sys; "
                        "subprocess.run((sys.executable, '-I', '-S', '-B', '-c', "
                        "'import asyncio, json, pathlib'), check=True)"
                    ),
                ],
                check=False,
                capture_output=True,
                text=True,
                env={
                    "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
                    "TMPDIR": str(root),
                    "PYTHONDONTWRITEBYTECODE": "1",
                },
                timeout=30,
            )
            self.assertEqual(
                nested_import.returncode,
                0,
                nested_import.stdout + nested_import.stderr,
            )
            self.assertFalse(
                list(python_framework.rglob("__pycache__")),
                "nested Python imports must not mutate the signed framework",
            )
            package_signature = subprocess.run(
                ["codesign", "--verify", "--deep", "--strict", str(product_app)],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(
                package_signature.returncode,
                0,
                package_signature.stderr,
            )
            product_bundle_id = "org.khaos.Seed"
            product_launcher = product_app / "Contents" / "MacOS" / "KhaosSeed"
            product_requirement = self._designated_code_requirement(
                product_launcher,
                product_bundle_id,
            )
            agent_host_binary = (
                agent_host_bundle / "Contents" / "MacOS" / "KhaosAgentHost"
            )
            agent_host_requirement = self._designated_code_requirement(
                agent_host_binary,
                "org.khaos.Seed.AgentHost",
            )
            self.assertNotEqual(agent_host_requirement, product_requirement)
            rejected_agent_host = subprocess.run(
                [
                    "codesign",
                    "--verify",
                    f"-R={product_requirement}",
                    str(agent_host_binary),
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(
                rejected_agent_host.returncode,
                0,
                "the untrusted Agent Host must not satisfy the Kernel caller requirement",
            )
            self._verify_agent_host_xpc_sandbox(
                product_app=product_app,
                launcher_binary=product_launcher,
                scratch=root,
            )
            broker_info_path = broker_bundle / "Contents" / "Info.plist"
            with broker_info_path.open("rb") as stream:
                broker_info = plistlib.load(stream)
            self.assertEqual(
                broker_info.get("KhaosLauncherCallerRequirement"),
                product_requirement,
            )
            app_info_path = product_app / "Contents" / "Info.plist"
            with app_info_path.open("rb") as stream:
                app_info = plistlib.load(stream)
            self.assertEqual(
                app_info.get("KhaosSnapshotBrokerServiceName"),
                "org.khaos.Seed.KernelSnapshotBroker",
            )
            self.assertEqual(
                app_info.get("KhaosKernelSnapshotBrokerRequirement"),
                broker_requirement,
            )
            with tempfile.TemporaryDirectory(prefix="khaos-seed-bootstrap-") as value:
                stdout_path = Path(value) / "launcher.stdout"
                stderr_path = Path(value) / "launcher.stderr"
                bootstrap = self._launch_product_app(
                    product_app,
                    stdout_path,
                    stderr_path,
                    "--bootstrap-check",
                )
                bootstrap_stdout, bootstrap_stderr = bootstrap.communicate(
                    timeout=30
                )
                self.assertEqual(
                    bootstrap.returncode,
                    0,
                    bootstrap_stdout + bootstrap_stderr,
                )
                self.assertEqual(
                    stdout_path.read_text(encoding="utf-8").strip(),
                    "kernel-and-snapshot-broker-peer-authentication=verified",
                    stderr_path.read_text(encoding="utf-8", errors="replace"),
                )

            sdk = subprocess.run(
                ["xcrun", "--sdk", "macosx", "--show-sdk-path"],
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
            swiftc = subprocess.run(
                ["xcrun", "--find", "swiftc"],
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
            self._assert_product_snapshot_broker_positive(
                product_app=product_app,
                kernel_binary=kernel_binary,
                directory=root,
                sdk=sdk,
                swiftc=swiftc,
                signing_identity=signing_identity,
                signing_keychain=signing_keychain,
                launcher_entitlements=launcher_entitlements,
                service_entitlements=service_entitlements,
                kernel_requirement=kernel_requirement,
            )
            self._assert_snapshot_broker_xpc_os_restrictions(
                product_app=product_app,
                broker_binary=broker_binary,
                kernel_binary=kernel_binary,
                directory=root,
                sdk=sdk,
                swiftc=swiftc,
                signing_identity=signing_identity,
                signing_keychain=signing_keychain,
                launcher_entitlements=launcher_entitlements,
                broker_entitlements=broker_entitlements,
                broker_requirement=broker_requirement,
            )
            self._assert_packaged_runner_file_access_isolation(
                bundled_python=bundled_python,
                product_app=product_app,
                service_resources=service_info_path.parent / "Resources",
                signing_identity=signing_identity,
                signing_keychain=signing_keychain,
                service_entitlements=service_entitlements,
                kernel_requirement=kernel_requirement,
                sdk=sdk,
                swiftc=swiftc,
            )
            wrong_client = root / "KernelXPCClientAttack"
            compiled = subprocess.run(
                [
                    swiftc,
                    "-sdk",
                    sdk,
                    "-parse-as-library",
                    str(MACOS_TCB_SOURCES / "KernelWorkspaceXPC.swift"),
                    str(PROBE_SOURCES / "KernelBootstrapPeerProbe.swift"),
                    str(PROBE_SOURCES / "KernelXPCClientAttack.swift"),
                    "-o",
                    str(wrong_client),
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(compiled.returncode, 0, compiled.stderr)
            self._assert_rejected_xpc_client(
                wrong_client,
                product_bundle_id,
                product_requirement,
                f"{product_bundle_id}.KernelProduction",
            )
            broker_attack = root / "SnapshotBrokerXPCClientAttack"
            broker_attack_compile = subprocess.run(
                [
                    swiftc,
                    "-sdk",
                    sdk,
                    "-parse-as-library",
                    str(MACOS_TCB_SOURCES / "KernelSnapshotBrokerXPC.swift"),
                    str(PROBE_SOURCES / "SnapshotBrokerPeerProbe.swift"),
                    str(PROBE_SOURCES / "SnapshotBrokerXPCClientAttack.swift"),
                    "-o",
                    str(broker_attack),
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(
                broker_attack_compile.returncode, 0, broker_attack_compile.stderr
            )
            self._assert_rejected_xpc_client(
                broker_attack,
                "org.khaos.Seed.KernelSnapshotBroker",
                broker_requirement,
                "org.khaos.Seed.KernelSnapshotBroker",
            )
            if "KHAOS_RUN_PRODUCT_XPC_ATTACK_UI" in os.environ:
                self.fail(
                    "the duplicate interactive XPC attack flow was retired; "
                    "use KHAOS_RUN_PRODUCT_WRITEBACK_UI=1"
                )
            if os.environ.get("KHAOS_RUN_PRODUCT_WRITEBACK_UI") == "1":
                workspace = root / "user-selected-writeback-workspace"
                workspace.mkdir()
                self._assert_product_writeback_smoke(
                    product_launcher,
                    product_app,
                    workspace,
                )

            self._assert_product_xpc_request_attacks(
                swiftc=swiftc,
                sdk=sdk,
                launcher=product_launcher,
                product_app=product_app,
                product_bundle_id=product_bundle_id,
                product_requirement=product_requirement,
                signing_identity=signing_identity,
                signing_keychain=signing_keychain,
                verify_missing_broker=True,
            )

    def _assert_packaged_runner_file_access_isolation(
        self,
        *,
        bundled_python: Path,
        product_app: Path,
        service_resources: Path,
        signing_identity: str,
        signing_keychain: Path,
        service_entitlements: dict[str, object],
        kernel_requirement: str,
        sdk: str,
        swiftc: str,
    ) -> None:
        kernel_file = (
            service_resources / "khaos" / "kernel" / "workspace_changes.py"
        )
        self.assertTrue(kernel_file.is_file(), str(kernel_file))
        kernel_digest = hashlib.sha256(kernel_file.read_bytes()).digest()
        kernel_temporary_root = Path(tempfile.gettempdir()).resolve(strict=True)
        self.assertTrue(kernel_temporary_root.is_dir(), str(kernel_temporary_root))
        canary_app = product_app.parent / "KernelContainerCanaryProbe.app"
        canary_executable = (
            canary_app / "Contents" / "MacOS" / "KernelContainerCanaryProbe"
        )
        canary_executable.parent.mkdir(parents=True)
        compiled = subprocess.run(
            [
                swiftc,
                "-sdk",
                sdk,
                "-parse-as-library",
                str(PROBE_SOURCES / "KernelContainerCanaryProbe.swift"),
                "-o",
                str(canary_executable),
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(compiled.returncode, 0, compiled.stderr)
        self._write_plist(
            canary_app / "Contents" / "Info.plist",
            {
                "CFBundleIdentifier": "org.khaos.Seed.KernelProduction",
                "CFBundleExecutable": "KernelContainerCanaryProbe",
                "CFBundlePackageType": "APPL",
                "CFBundleVersion": "1",
                "CFBundleShortVersionString": "0.1.0",
            },
        )
        entitlements_path = product_app.parent / "kernel-canary-probe-entitlements.plist"
        entitlements_path.write_bytes(plistlib.dumps(service_entitlements))
        subprocess.run(
            [
                "codesign",
                "--force",
                "--keychain",
                str(signing_keychain),
                "--sign",
                signing_identity,
                "--identifier",
                "org.khaos.Seed.KernelProduction",
                "--entitlements",
                str(entitlements_path),
                str(canary_app),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        self.assertEqual(
            self._designated_code_requirement(
                canary_executable, "org.khaos.Seed.KernelProduction"
            ),
            kernel_requirement,
        )
        canary_id = str(uuid.uuid4())

        def run_canary_probe(operation: str) -> subprocess.CompletedProcess[str]:
            result = subprocess.run(
                [
                    str(canary_executable),
                    operation,
                    canary_id,
                    str(kernel_temporary_root),
                ],
                check=False,
                capture_output=True,
                text=True,
                timeout=15,
                env={
                    "HOME": str(Path.home()),
                    "LC_ALL": "C",
                    "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
                    "TMPDIR": str(kernel_temporary_root),
                },
            )
            self.assertEqual(
                result.returncode, 0, result.stdout + result.stderr
            )
            return result

        create_result = run_canary_probe("create")
        create_output = create_result.stdout.splitlines()
        self.assertEqual(create_output[-1:], ["kernel-container-canary=created"])
        canary_path = Path(json.loads(create_output[0])["path"])
        self.assertEqual(
            canary_path.resolve(strict=True),
            kernel_temporary_root
            / f"khaos-runner-container-probe-{canary_id}"
            / "kernel-container-secret.txt",
        )
        with tempfile.TemporaryDirectory(
            prefix="khaos-product-runner-kernel-write-",
            dir=str(Path("/tmp").resolve(strict=True)),
        ) as value:
            root = Path(value)
            workspace = root / "workspace"
            workspace.mkdir()
            fixture = workspace / "fixture.txt"
            fixture.write_bytes(b"unchanged")
            self.assertEqual(set(os.listdir(workspace)), {fixture.name})
            self.assertEqual(fixture.stat().st_size, len(b"unchanged"))
            host_secret = root / "host-secret.txt"
            host_secret.write_bytes(b"host-only-secret")
            self.assertEqual(host_secret.read_bytes(), b"host-only-secret")
            # The host positive control can open the same live file for writing.
            live_descriptor = os.open(
                fixture,
                os.O_WRONLY | os.O_CLOEXEC | os.O_NOFOLLOW,
            )
            os.close(live_descriptor)

            from khaos.kernel.macos_disk_image import mounted_apfs_volume
            from khaos.kernel.workspace_snapshot import _apfs_case_sensitivity

            workspace_descriptor = os.open(
                workspace,
                os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | os.O_NOFOLLOW,
            )
            try:
                case_sensitive = _apfs_case_sensitivity(workspace_descriptor)
            finally:
                os.close(workspace_descriptor)
            broker_storage_bytes = 2 * 1024**3 + 256 * 1024**2
            broker_storage_root = root / "khaos-snapshot-broker"
            broker_storage_root.mkdir(mode=0o700)
            os.chmod(broker_storage_root, 0o700)

            command = [
                "/bin/sh",
                "-c",
                "printf '%s' packaged-runner-output > output.txt",
            ]
            runner_source = f"""\
import errno
import os
from pathlib import Path
import khaos
from khaos.runner_sdk import process_exec, workspace_commit

kernel_file = (
    Path(khaos.__file__).resolve().parent
    / "kernel"
    / "workspace_changes.py"
)
live_fixture = Path({str(fixture)!r})
host_secret = Path({str(host_secret)!r})
broker_canary = Path({str(canary_path)!r})

def require_open_denied(path, flags, failure_code):
    try:
        descriptor = os.open(
            path,
            flags | os.O_CLOEXEC | os.O_NOFOLLOW,
        )
    except OSError as error:
        if error.errno not in (errno.EPERM, errno.EACCES):
            raise SystemExit(failure_code + 10) from error
    else:
        os.close(descriptor)
        raise SystemExit(failure_code)

def require_read_denied(action, failure_code):
    try:
        action()
    except OSError as error:
        if error.errno not in (errno.EPERM, errno.EACCES):
            raise SystemExit(failure_code + 10) from error
    else:
        raise SystemExit(failure_code)

def run():
    require_open_denied(kernel_file, os.O_WRONLY, 81)
    require_open_denied(live_fixture, os.O_RDONLY, 82)
    require_open_denied(live_fixture, os.O_WRONLY, 83)
    require_open_denied(host_secret, os.O_RDONLY, 84)
    require_open_denied(broker_canary, os.O_RDONLY, 88)
    require_read_denied(lambda: os.listdir(broker_canary.parent), 89)
    require_read_denied(lambda: os.listdir(live_fixture.parent), 86)
    require_read_denied(
        lambda: os.stat(live_fixture, follow_symlinks=False),
        87,
    )

    result = process_exec({tuple(command)!r})
    if result["returncode"] != 0:
        raise SystemExit(85)
    workspace_commit()
    return 0
"""
            execution = (
                "import json, sys\n"
                f"sys.path.insert(0, {str(service_resources)!r})\n"
                "from khaos.launcher import run_workspace_command\n"
                f"runner_source = {runner_source!r}\n"
                "result = run_workspace_command(\n"
                "    sys.argv[1],\n"
                "    runner_source=runner_source,\n"
                "    timeout_seconds=10,\n"
                "    workspace_write_scope=(\"output.txt\",),\n"
                "    brokered_snapshot_mount_path=sys.argv[2],\n"
                "    brokered_snapshot_storage_bytes=int(sys.argv[3]),\n"
                ")\n"
                "print(json.dumps({\n"
                "    'returncode': result.returncode,\n"
                "    'added': result.added,\n"
                "    'modified': result.modified,\n"
                "    'deleted': result.deleted,\n"
                "}, sort_keys=True))\n"
            )
            with mounted_apfs_volume(
                broker_storage_root,
                size_bytes=broker_storage_bytes,
                case_sensitive=case_sensitive,
                directory_name=f"khaos-snapshot-broker-{uuid.uuid4()}",
            ) as broker_mount_path:
                try:
                    run = subprocess.run(
                        [
                            str(bundled_python),
                            "-I",
                            "-S",
                            "-B",
                            "-c",
                            execution,
                            str(workspace),
                            str(broker_mount_path),
                            str(broker_storage_bytes),
                        ],
                        check=False,
                        capture_output=True,
                        text=True,
                        env={
                            "HOME": str(root),
                            "LC_ALL": "C",
                            "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
                            "PYTHONDONTWRITEBYTECODE": "1",
                            "TMPDIR": str(root),
                        },
                        timeout=120,
                    )
                    self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
                    verify_result = run_canary_probe("verify")
                    self.assertEqual(
                        verify_result.stdout.strip(),
                        "kernel-container-canary=verified",
                    )
                finally:
                    cleanup_result = run_canary_probe("cleanup")
                    self.assertEqual(
                        cleanup_result.stdout.strip(),
                        "kernel-container-canary=removed",
                    )
            self.assertEqual(
                json.loads(run.stdout),
                {"added": 1, "deleted": 0, "modified": 0, "returncode": 0},
            )
            self.assertEqual(fixture.read_bytes(), b"unchanged")
            self.assertEqual(host_secret.read_bytes(), b"host-only-secret")
            output = workspace / "output.txt"
            self.assertEqual(output.read_bytes(), b"packaged-runner-output")
            self.assertEqual(output.stat().st_nlink, 1)
            self.assertEqual(output.stat().st_mode & 0o777, 0o600)

        self.assertEqual(hashlib.sha256(kernel_file.read_bytes()).digest(), kernel_digest)
        signature = subprocess.run(
            ["codesign", "--verify", "--deep", "--strict", str(product_app)],
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(signature.returncode, 0, signature.stderr)

    def test_app_sandbox_cannot_consume_an_untrusted_scope_bookmark(self) -> None:
        with tempfile.TemporaryDirectory(prefix="khaos-scope-bookmark-") as value:
            root = Path(value)
            workspace = root / "workspace"
            workspace.mkdir()
            (workspace / "canary.txt").write_text(
                "outside-sandbox", encoding="utf-8"
            )
            compiler = subprocess.run(
                ["xcrun", "--find", "swiftc"],
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
            sdk = subprocess.run(
                ["xcrun", "--sdk", "macosx", "--show-sdk-path"],
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
            binary = root / "ScopeBookmark"
            compiled = subprocess.run(
                [
                    compiler,
                    "-sdk",
                    sdk,
                    "-parse-as-library",
                    str(MACOS_TCB_SOURCES / "KernelWorkspaceXPC.swift"),
                    str(MACOS_TCB_SOURCES / "KernelWorkspaceRoot.swift"),
                    str(PROBE_SOURCES / "ScopeBookmark.swift"),
                    "-o",
                    str(binary),
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(compiled.returncode, 0, compiled.stderr)

            created = subprocess.run(
                [str(binary), "create", str(workspace)],
                check=True,
                capture_output=True,
                text=True,
            )
            bookmark = created.stdout.strip()
            self.assertTrue(bookmark)

            _, executable = self._build_sandboxed_app(
                root,
                binary,
                name="ScopeBookmarkProbe",
                bundle_id=(
                    f"org.khaos.ScopeBookmarkProbe.{secrets.token_hex(8)}"
                ),
            )

            consumed = subprocess.run(
                [str(executable), "consume", bookmark, str(workspace)],
                check=False,
                capture_output=True,
                text=True,
                timeout=10,
            )
            self.assertEqual(consumed.returncode, 0, consumed.stderr)
            self.assertRegex(
                consumed.stdout,
                r"^scope=denied open=denied:(?:1|13)\n$",
            )

    def test_app_sandbox_cannot_create_or_mount_kernel_apfs_images(self) -> None:
        with tempfile.TemporaryDirectory(prefix="khaos-app-sandbox-image-") as value:
            root = Path(value)
            host_image = root / "host-positive-control.sparsebundle"
            host_mount = root / "host-positive-control-mount"
            host_mount.mkdir()
            host_mount_path = host_mount.resolve(strict=True)
            create_arguments = [
                "/usr/bin/hdiutil",
                "create",
                "-type", "SPARSEBUNDLE",
                "-sectors", "131072",
                "-layout", "NONE",
                "-fs", "APFS",
                "-volname", "KhaosWork",
                "-nospotlight",
                str(host_image),
            ]
            host_result = subprocess.run(
                create_arguments,
                check=False,
                capture_output=True,
                text=True,
                timeout=120,
            )
            self.assertEqual(host_result.returncode, 0, host_result.stderr)

            host_attach = subprocess.run(
                [
                    "/usr/bin/hdiutil",
                    "attach",
                    "-plist",
                    "-nobrowse",
                    "-mountpoint",
                    str(host_mount_path),
                    str(host_image),
                ],
                check=False,
                capture_output=True,
                timeout=120,
            )
            try:
                self.assertEqual(
                    host_attach.returncode,
                    0,
                    host_attach.stderr.decode(),
                )
                host_response = plistlib.loads(host_attach.stdout)
                host_entities = host_response.get("system-entities", [])
                self.assertTrue(
                    any(
                        entity.get("mount-point") == str(host_mount_path)
                        for entity in host_entities
                        if isinstance(entity, dict)
                    ),
                    host_response,
                )
            finally:
                host_detach = subprocess.run(
                    ["/usr/bin/hdiutil", "detach", str(host_mount_path)],
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=60,
                )
                if host_attach.returncode == 0:
                    self.assertEqual(
                        host_detach.returncode,
                        0,
                        host_detach.stdout + host_detach.stderr,
                    )

            host_diskutil_attach = subprocess.run(
                [
                    "/usr/sbin/diskutil",
                    "image",
                    "attach",
                    "--plist",
                    "--nobrowse",
                    "--mountPoint",
                    str(host_mount_path),
                    str(host_image),
                ],
                check=False,
                capture_output=True,
                timeout=120,
            )
            try:
                self.assertEqual(
                    host_diskutil_attach.returncode,
                    0,
                    host_diskutil_attach.stderr.decode(),
                )
                self.assertTrue(host_mount_path.is_mount())
                inventory_result = subprocess.run(
                    ["/usr/bin/hdiutil", "info", "-plist"],
                    check=False,
                    capture_output=True,
                    timeout=30,
                )
                self.assertEqual(
                    inventory_result.returncode,
                    0,
                    inventory_result.stderr.decode(),
                )
                inventory = plistlib.loads(inventory_result.stdout)
                self.assertTrue(
                    any(
                        isinstance(entry, dict)
                        and isinstance(entry.get("image-path"), str)
                        and Path(entry["image-path"]).resolve(strict=False)
                        == host_image.resolve(strict=False)
                        and any(
                            isinstance(entity, dict)
                            and entity.get("mount-point") == str(host_mount_path)
                            for entity in entry.get("system-entities", [])
                        )
                        for entry in inventory.get("images", [])
                    ),
                    inventory,
                )
            finally:
                host_detach = subprocess.run(
                    ["/usr/bin/hdiutil", "detach", str(host_mount_path)],
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=60,
                )
                if host_diskutil_attach.returncode == 0:
                    self.assertEqual(
                        host_detach.returncode,
                        0,
                        host_detach.stdout + host_detach.stderr,
                    )

            compiler = subprocess.run(
                ["xcrun", "--find", "swiftc"],
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
            sdk = subprocess.run(
                ["xcrun", "--sdk", "macosx", "--show-sdk-path"],
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
            binary = root / "AppSandboxDiskImageProbe"
            compiled = subprocess.run(
                [
                    compiler,
                    "-sdk",
                    sdk,
                    "-parse-as-library",
                    str(PROBE_SOURCES / "AppSandboxDiskImageProbe.swift"),
                    "-o",
                    str(binary),
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(compiled.returncode, 0, compiled.stderr)

            bundle_id = f"org.khaos.AppSandboxDiskImageProbe.{secrets.token_hex(8)}"
            _, executable = self._build_sandboxed_app(
                root,
                binary,
                name="AppSandboxDiskImageProbe",
                bundle_id=bundle_id,
                resources={"workspace.sparsebundle": host_image},
            )
            probe = subprocess.run(
                [str(executable)],
                check=False,
                capture_output=True,
                text=True,
                timeout=120,
            )
            self.assertIn("sandbox-temporary-write=allowed", probe.stdout)
            self.assertRegex(
                probe.stdout,
                r"(?m)^sandbox-nested-seatbelt-status=(?!0$)\d+$",
            )
            self.assertIn(
                "sandbox-nested-seatbelt-apply-denied=true", probe.stdout
            )
            attachment_probes: dict[str, tuple[Path, Path]] = {}
            for tool in ("hdiutil", "diskutil"):
                image_path_match = re.search(
                    rf"(?m)^sandbox-{tool}-image-path=(.+)$",
                    probe.stdout,
                )
                mount_path_match = re.search(
                    rf"(?m)^sandbox-{tool}-mount-point=(.+)$",
                    probe.stdout,
                )
                self.assertIsNotNone(image_path_match, probe.stdout)
                self.assertIsNotNone(mount_path_match, probe.stdout)
                attachment_probes[tool] = (
                    Path(image_path_match.group(1)).resolve(strict=False),
                    Path(mount_path_match.group(1)).resolve(strict=False),
                )

            def attachment_inventory() -> list[dict[str, object]]:
                result = subprocess.run(
                    ["/usr/bin/hdiutil", "info", "-plist"],
                    check=False,
                    capture_output=True,
                    timeout=30,
                )
                self.assertEqual(result.returncode, 0, result.stderr.decode())
                return plistlib.loads(result.stdout).get("images", [])

            def matching_images(
                image_path: Path, entries: list[dict[str, object]]
            ) -> list[dict[str, object]]:
                return [
                    entry
                    for entry in entries
                    if isinstance(entry, dict)
                    and isinstance(entry.get("image-path"), str)
                    and Path(entry["image-path"]).resolve(strict=False) == image_path
                ]

            def cleanup_attachments(entries: list[dict[str, object]]) -> None:
                for image_path, mount_path in attachment_probes.values():
                    attached = matching_images(image_path, entries)
                    if not attached and not mount_path.is_mount():
                        continue
                    detach_target = str(mount_path) if mount_path.is_mount() else None
                    if detach_target is None:
                        detach_target = next(
                            (
                                entity["dev-entry"]
                                for entry in attached
                                for entity in (
                                    entry["system-entities"]
                                    if isinstance(entry.get("system-entities"), list)
                                    else []
                                )
                                if isinstance(entity, dict)
                                and isinstance(entity.get("dev-entry"), str)
                                and re.fullmatch(
                                    r"/dev/disk[0-9]+",
                                    entity["dev-entry"],
                                )
                            ),
                            None,
                        )
                    self.assertIsNotNone(detach_target, attached)
                    detached = subprocess.run(
                        ["/usr/bin/hdiutil", "detach", detach_target],
                        check=False,
                        capture_output=True,
                        text=True,
                        timeout=60,
                    )
                    self.assertEqual(
                        detached.returncode,
                        0,
                        detached.stdout + detached.stderr,
                    )

            observed_mount = False
            observed_sources: list[str] = []
            observed_images: list[str] = []
            observed_image_tools: set[str] = set()
            settle_deadline = time.monotonic() + 5
            try:
                while True:
                    inventory = attachment_inventory()
                    for tool, (image_path, mount_path) in attachment_probes.items():
                        matching = matching_images(image_path, inventory)
                        mounted = mount_path.is_mount()
                        if matching:
                            observed_images.append(f"{tool}:{image_path}")
                            observed_image_tools.add(tool)
                        if mounted:
                            observed_mount = True
                            observed_sources.append(
                                f"{tool}:mounted={mounted}:inventory={matching!r}"
                            )
                    cleanup_attachments(inventory)
                    if time.monotonic() >= settle_deadline:
                        break
                    time.sleep(0.05)
            finally:
                cleanup_attachments(attachment_inventory())

            remaining = attachment_inventory()
            for tool, (image_path, mount_path) in attachment_probes.items():
                self.assertFalse(mount_path.is_mount(), tool)
                self.assertFalse(matching_images(image_path, remaining), tool)
            for image_path, _ in attachment_probes.values():
                temporary = image_path.parent
                if temporary.exists():
                    shutil.rmtree(temporary)

            self.assertEqual(probe.returncode, 0, probe.stderr)
            create_status = re.search(
                r"(?m)^sandbox-hdiutil-create-status=(-?\d+)$",
                probe.stdout,
            )
            self.assertIsNotNone(create_status, probe.stdout)
            self.assertNotEqual(
                create_status.group(1),
                "0",
                "App-Sandboxed helper unexpectedly created an APFS work image",
            )
            self.assertIn(
                "sandbox-hdiutil-create-output-exists=false",
                probe.stdout,
            )
            attach_statuses: dict[str, str] = {}
            for tool in ("hdiutil", "diskutil"):
                attach_status = re.search(
                    rf"(?m)^sandbox-{tool}-attach-status=(-?\d+)$",
                    probe.stdout,
                )
                self.assertIsNotNone(attach_status, probe.stdout)
                self.assertNotEqual(
                    attach_status.group(1),
                    "0",
                    f"App-Sandboxed helper unexpectedly completed image attach with {tool}",
                )
                attach_statuses[tool] = attach_status.group(1)
            self.assertFalse(
                observed_mount,
                "App-Sandboxed disk image attach mounted a volume: "
                f"{observed_sources!r}; helper={probe.stdout!r}",
            )
            self.assertNotIn(
                "hdiutil",
                observed_image_tools,
                f"hdiutil registered an image under App Sandbox: {observed_images!r}",
            )
            mount_status = re.search(
                r"(?m)^sandbox-diskutil-mount-status=(.+)$",
                probe.stdout,
            )
            self.assertIsNotNone(mount_status, probe.stdout)
            self.assertTrue(
                mount_status.group(1) == "not-attempted"
                or re.fullmatch(r"-?\d+", mount_status.group(1)),
                probe.stdout,
            )
            self.assertNotEqual(
                mount_status.group(1),
                "0",
                f"App-Sandboxed helper unexpectedly mounted the APFS image; "
                f"partial-image-inventory={observed_images!r}; helper={probe.stdout!r}",
            )
            print(
                "App Sandbox image probe: "
                f"hdiutil-create={create_status.group(1)}, "
                f"hdiutil-attach={attach_statuses['hdiutil']}, "
                f"diskutil-attach={attach_statuses['diskutil']}, "
                f"diskutil-mount={mount_status.group(1)}, "
                f"partial-diskutil-image-observed={bool(observed_images)}"
            )

            token = secrets.token_hex(8)
            mount_path: Path | None = None
            try:
                prepared = subprocess.run(
                    [str(executable), "prepare", token],
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                self.assertEqual(prepared.returncode, 0, prepared.stderr)

                def output_path(label: str) -> Path:
                    match = re.search(
                        rf"(?m)^{re.escape(label)}=(.+)$", prepared.stdout
                    )
                    self.assertIsNotNone(match, prepared.stdout)
                    return Path(match.group(1)).resolve(strict=True)

                application_support = output_path("sandbox-application-support")
                probe_root = output_path("sandbox-mount-probe-root")
                mount_path = output_path("sandbox-mount-point")
                self.assertIn(bundle_id, str(application_support))
                self.assertEqual(
                    probe_root.parent,
                    application_support / "KhaosMountedImageProbe",
                )
                self.assertEqual(mount_path.parent, probe_root)

                external_attach = subprocess.run(
                    [
                        "/usr/bin/hdiutil",
                        "attach",
                        "-plist",
                        "-nobrowse",
                        "-mountpoint",
                        str(mount_path),
                        str(host_image),
                    ],
                    check=False,
                    capture_output=True,
                    timeout=120,
                )
                access_states: dict[str, bool] = {}
                try:
                    self.assertEqual(
                        external_attach.returncode,
                        0,
                        external_attach.stderr.decode(),
                    )
                    external_response = plistlib.loads(external_attach.stdout)
                    external_entities = external_response.get("system-entities", [])
                    self.assertTrue(
                        any(
                            entity.get("mount-point") == str(mount_path)
                            for entity in external_entities
                            if isinstance(entity, dict)
                        ),
                        external_response,
                    )
                    self.assertTrue(mount_path.is_mount())
                    host_canary = mount_path / "host-canary"
                    host_canary.write_text(
                        "host-mounted-volume-canary", encoding="utf-8"
                    )
                    self.assertEqual(
                        host_canary.read_text(encoding="utf-8"),
                        "host-mounted-volume-canary",
                    )

                    access = subprocess.run(
                        [str(executable), "access", token],
                        check=False,
                        capture_output=True,
                        text=True,
                        timeout=10,
                    )
                    self.assertEqual(access.returncode, 0, access.stderr)
                    for line in access.stdout.splitlines():
                        if line.startswith("sandbox-directory-"):
                            print(line)
                    self.assertRegex(
                        access.stdout,
                        r"(?m)^sandbox-directory-users-open=denied:(1|13)$",
                    )
                    for label in ("source", "mounted"):
                        for attribute in (
                            "open=allowed",
                            "fullpath=matches",
                            "mountpoint=allowed",
                            "mount-status=allowed",
                        ):
                            self.assertIn(
                                f"sandbox-directory-{label}-{attribute}",
                                access.stdout,
                            )
                    for operation in ("read", "write"):
                        result = re.search(
                            rf"(?m)^sandbox-mounted-volume-{operation}="
                            r"(allowed|denied:[^\n]+)$",
                            access.stdout,
                        )
                        self.assertIsNotNone(result, access.stdout)
                        access_states[operation] = result.group(1) == "allowed"
                    readback = re.search(
                        r"(?m)^sandbox-mounted-volume-write-readback="
                        r"(allowed|denied:[^\n]+)$",
                        access.stdout,
                    )
                    self.assertEqual(access_states["write"], readback is not None)
                    if readback is not None:
                        access_states["write-readback"] = (
                            readback.group(1) == "allowed"
                        )
                    print(
                        "App Sandbox mounted APFS volume: "
                        + ", ".join(
                            f"{operation}={'allowed' if allowed else 'denied'}"
                            for operation, allowed in access_states.items()
                        )
                    )
                finally:
                    if mount_path.is_mount():
                        detached = subprocess.run(
                            ["/usr/bin/hdiutil", "detach", str(mount_path)],
                            check=False,
                            capture_output=True,
                            text=True,
                            timeout=60,
                        )
                        if external_attach.returncode == 0:
                            self.assertEqual(
                                detached.returncode,
                                0,
                                detached.stdout + detached.stderr,
                            )

                verification_attach = subprocess.run(
                    [
                        "/usr/bin/hdiutil",
                        "attach",
                        "-plist",
                        "-nobrowse",
                        "-mountpoint",
                        str(host_mount_path),
                        str(host_image),
                    ],
                    check=False,
                    capture_output=True,
                    timeout=120,
                )
                try:
                    self.assertEqual(
                        verification_attach.returncode,
                        0,
                        verification_attach.stderr.decode(),
                    )
                    self.assertTrue(host_mount_path.is_mount())
                    self.assertEqual(
                        (host_mount_path / "host-canary").read_text(encoding="utf-8"),
                        "host-mounted-volume-canary",
                    )
                    writeback = host_mount_path / "sandbox-writeback"
                    self.assertEqual(writeback.exists(), access_states["write"])
                    if access_states["write"]:
                        self.assertEqual(
                            writeback.read_text(encoding="utf-8"),
                            "sandbox-mounted-volume-write",
                        )
                finally:
                    if host_mount_path.is_mount():
                        detached = subprocess.run(
                            ["/usr/bin/hdiutil", "detach", str(host_mount_path)],
                            check=False,
                            capture_output=True,
                            text=True,
                            timeout=60,
                        )
                        if verification_attach.returncode == 0:
                            self.assertEqual(
                                detached.returncode,
                                0,
                                detached.stdout + detached.stderr,
                            )
            finally:
                if mount_path is not None and mount_path.is_mount():
                    subprocess.run(
                        ["/usr/bin/hdiutil", "detach", str(mount_path)],
                        check=False,
                        capture_output=True,
                        timeout=60,
                    )
                cleanup = subprocess.run(
                    [str(executable), "cleanup", token],
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                self.assertEqual(cleanup.returncode, 0, cleanup.stderr)

    def test_xpc_sandbox_scope_peer_identity_and_service_container_identity(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory(prefix="khaos-xpc-sandbox-") as value:
            root = Path(value)
            signer_directory = tempfile.TemporaryDirectory(
                prefix="khaos-xpc-test-signer-"
            )
            self.addCleanup(
                self._cleanup_signing_identity,
                Path(signer_directory.name),
                signer_directory.cleanup,
            )
            signing_identity, signing_keychain = self._create_signing_identity(
                Path(signer_directory.name)
            )
            outside = root / "live-secret.txt"
            outside.write_text("outside-secret", encoding="utf-8")
            selected_workspace = root / "user-selected-workspace"
            execution_workspace = selected_workspace / "kernel-workspace"
            descriptor_workspace = selected_workspace / "kernel-descriptor-scope"
            execution_workspace.mkdir(parents=True)
            descriptor_workspace.mkdir()
            (execution_workspace / "input.txt").write_text(
                "xpc-input", encoding="utf-8"
            )
            (selected_workspace / "production-input.txt").write_text(
                "production-xpc-input", encoding="utf-8"
            )
            (selected_workspace / "production-hardlink-source.txt").write_text(
                "hardlink-source", encoding="utf-8"
            )
            (execution_workspace / "unscoped-secret.txt").write_text(
                "xpc-unscoped-secret", encoding="utf-8"
            )
            (descriptor_workspace / "input.txt").write_text(
                "xpc-input", encoding="utf-8"
            )
            sibling = selected_workspace / "sibling-secret.txt"
            sibling.write_text("sibling-secret", encoding="utf-8")
            (root / "sibling-secret.txt").write_text(
                "sibling-secret", encoding="utf-8"
            )
            (descriptor_workspace / "sibling-link").symlink_to(sibling)
            os.link(sibling, descriptor_workspace / "sibling-hardlink")
            listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            listener.bind(("127.0.0.1", 0))
            listener.listen(4)
            listener.settimeout(0.05)
            connection_seen = threading.Event()
            stop_server = threading.Event()

            def accept_connections() -> None:
                while not stop_server.is_set():
                    try:
                        connection, _ = listener.accept()
                    except TimeoutError:
                        continue
                    except OSError:
                        return
                    connection_seen.set()
                    connection.close()

            server = threading.Thread(target=accept_connections, daemon=True)
            server.start()

            def close_listener() -> None:
                stop_server.set()
                listener.close()
                server.join(timeout=1)

            self.addCleanup(close_listener)

            app = root / "XPCProbe.app"
            contents = app / "Contents"
            host_directory = contents / "MacOS"
            host_directory.mkdir(parents=True)
            host_binary = host_directory / "Host"
            workspace_grant_binary = root / "WorkspaceGrant"
            workspace_grant_host_binary = root / "WorkspaceGrantHost"
            runner_binary = root / "Runner"
            spoof_binary = root / "Spoof"
            python_executable = Path(sys.executable).resolve(strict=True)
            python_framework = next(
                (
                    parent
                    for parent in python_executable.parents
                    if parent.name == "Python.framework"
                ),
                None,
            )
            python_runtime_available = (
                sys.version_info >= (3, 10) and python_framework is not None
            )
            python_version = f"{sys.version_info.major}.{sys.version_info.minor}"
            install_name_tool = None
            if python_runtime_available:
                install_name_tool = subprocess.run(
                    ["xcrun", "--find", "install_name_tool"],
                    check=True,
                    capture_output=True,
                    text=True,
                ).stdout.strip()
            host_bundle_id = "org.khaos.SecurityProbe"
            host_client_service_id = f"{host_bundle_id}.HostClient"
            workspace_grant_bundle_id = f"{host_bundle_id}.WorkspaceGrant"
            host_client_binary = root / "HostClient"
            client_attack_binary = root / "XPCClientAttack"
            kernel_client_attack_binary = root / "KernelExecutionClientAttack"
            host_client_bundle = contents / "XPCServices" / "HostClient.xpc"
            host_client_executable = (
                host_client_bundle / "Contents" / "MacOS" / "HostClient"
            )
            workspace_grant_mode = os.environ.get("KHAOS_RUN_WORKSPACE_GRANT_UI")
            if workspace_grant_mode == "1":
                self.fail(
                    "the duplicate WorkspaceGrant Picker flow was retired; "
                    "use KHAOS_RUN_PRODUCT_WRITEBACK_UI=1"
                )
            if workspace_grant_mode not in (None, "build"):
                self.fail("KHAOS_RUN_WORKSPACE_GRANT_UI only supports build mode")
            prepare_workspace_grant = workspace_grant_mode == "build"
            service_ids = {
                name: f"{host_bundle_id}.{name}"
                for name in (
                    "Runner",
                    "PluginA",
                    "PluginB",
                    "Spoof",
                    "Kernel",
                    "KernelExecution",
                    "KernelProduction",
                )
            }
            service_bundles = {}
            service_binary_paths = {}
            for name in service_ids:
                bundle = contents / "XPCServices" / f"{name}.xpc"
                executable = (
                    name
                    if name in {
                        "Spoof", "Kernel", "KernelExecution", "KernelProduction"
                    }
                    else "Runner"
                )
                binary = bundle / "Contents" / "MacOS" / executable
                service_bundles[name] = bundle
                service_binary_paths[name] = binary

            sdk = subprocess.run(
                ["xcrun", "--sdk", "macosx", "--show-sdk-path"],
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
            swiftc = subprocess.run(
                ["xcrun", "--find", "swiftc"],
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
            workspace_xpc_abi = MACOS_TCB_SOURCES / "KernelWorkspaceXPC.swift"
            workspace_probe_request = PROBE_SOURCES / "WorkspaceProbeRequest.swift"
            for source, output in (
                (PROBE_SOURCES / "Host.swift", host_binary),
                (PROBE_SOURCES / "Spoof.swift", spoof_binary),
                (PROBE_SOURCES / "Runner.swift", runner_binary),
                (PROBE_SOURCES / "Kernel.swift", root / "Kernel"),
                (
                    MACOS_TCB_SOURCES / "KernelWorkspaceServiceMain.swift",
                    root / "KernelProduction",
                ),
                (PROBE_SOURCES / "WorkspaceGrant.swift", workspace_grant_binary),
            ):
                if source.name == "WorkspaceGrant.swift":
                    self._compile_workspace_grant_probe(swiftc, sdk, output)
                    continue
                command = [swiftc, "-sdk", sdk]
                if source.name in {
                    "Host.swift",
                    "Kernel.swift",
                    "KernelWorkspaceServiceMain.swift",
                    "Spoof.swift",
                }:
                    command.append("-parse-as-library")
                    if source.name == "Host.swift":
                        command.extend(
                            (
                                str(MACOS_TCB_SOURCES / "XPCPeerIdentity.swift"),
                                str(PROBE_SOURCES / "XPCPeerIdentityProbe.swift"),
                            )
                    )
                    if source.name == "Kernel.swift":
                        command.append(
                            str(MACOS_TCB_SOURCES / "KernelWorkspaceRoot.swift")
                        )
                        command.append(
                            str(MACOS_TCB_SOURCES / "KernelWorkspaceService.swift")
                        )
                        command.append(
                            str(MACOS_TCB_SOURCES / "XPCPeerIdentity.swift")
                        )
                        command.append(
                            str(MACOS_TCB_SOURCES / "KernelWorkspaceBootstrap.swift")
                        )
                    if source.name == "KernelWorkspaceServiceMain.swift":
                        command.extend(
                            (
                                str(MACOS_TCB_SOURCES / "KernelWorkspaceRoot.swift"),
                                str(MACOS_TCB_SOURCES / "KernelWorkspaceService.swift"),
                                str(MACOS_TCB_SOURCES / "XPCPeerIdentity.swift"),
                                str(MACOS_TCB_SOURCES / "KernelWorkspaceBootstrap.swift"),
                                str(MACOS_TCB_SOURCES / "KernelSnapshotBrokerXPC.swift"),
                                str(MACOS_TCB_SOURCES / "KernelSnapshotStoragePolicy.swift"),
                                str(MACOS_TCB_SOURCES / "KernelSnapshotBrokerClient.swift"),
                                str(MACOS_TCB_SOURCES / "KernelWorkspaceClient.swift"),
                                str(MACOS_TCB_SOURCES / "KernelCStringArray.swift"),
                                str(MACOS_TCB_SOURCES / "KernelWorkspacePythonExecutor.swift"),
                            )
                        )
                    if source.name in {"Host.swift", "Spoof.swift"}:
                        command.append(str(workspace_probe_request))
                    command.append(str(workspace_xpc_abi))
                command.extend((str(source), "-o", str(output)))
                compiled = subprocess.run(
                    command,
                    check=False,
                    capture_output=True,
                    text=True,
                )
                self.assertEqual(compiled.returncode, 0, compiled.stderr)
            unconfigured_service = subprocess.run(
                [str(root / "KernelProduction")],
                check=False,
                capture_output=True,
                text=True,
                timeout=3,
            )
            self.assertEqual(
                unconfigured_service.returncode,
                1,
                unconfigured_service.stdout + unconfigured_service.stderr,
            )
            self.assertEqual(
                unconfigured_service.stderr,
                "kernel-bootstrap=unavailable\n",
            )
            if prepare_workspace_grant:
                grant_host_compiled = subprocess.run(
                    [
                        swiftc,
                        "-sdk",
                        sdk,
                        "-target",
                        f"{platform.machine()}-apple-macosx{platform.mac_ver()[0]}",
                        "-parse-as-library",
                        str(workspace_xpc_abi),
                        str(PROBE_SOURCES / "KernelBootstrapPeerProbe.swift"),
                        str(MACOS_TCB_SOURCES / "XPCPeerIdentity.swift"),
                        str(PROBE_SOURCES / "WorkspaceGrantHostIPC.swift"),
                        str(PROBE_SOURCES / "WorkspaceGrantHost.swift"),
                        "-o",
                        str(workspace_grant_host_binary),
                    ],
                    check=False,
                    capture_output=True,
                    text=True,
                )
                self.assertEqual(
                    grant_host_compiled.returncode,
                    0,
                    grant_host_compiled.stderr,
                )
            for source, output in (
                (PROBE_SOURCES / "Host.swift", host_client_binary),
            ):
                compiled = subprocess.run(
                    [
                        swiftc,
                        "-sdk",
                        sdk,
                        "-parse-as-library",
                        "-D",
                        "KHAOS_XPC_CLIENT",
                        str(MACOS_TCB_SOURCES / "XPCPeerIdentity.swift"),
                        str(PROBE_SOURCES / "XPCPeerIdentityProbe.swift"),
                        str(workspace_probe_request),
                        str(workspace_xpc_abi),
                        str(source),
                        "-o",
                        str(output),
                    ],
                    check=False,
                    capture_output=True,
                    text=True,
                )
                self.assertEqual(compiled.returncode, 0, compiled.stderr)
            attack_compile = subprocess.run(
                [
                    swiftc,
                    "-sdk",
                    sdk,
                    "-parse-as-library",
                    str(PROBE_SOURCES / "XPCPeerIdentityProbe.swift"),
                    str(PROBE_SOURCES / "XPCClientAttack.swift"),
                    "-o",
                    str(client_attack_binary),
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(attack_compile.returncode, 0, attack_compile.stderr)
            kernel_attack_compile = subprocess.run(
                [
                    swiftc,
                    "-sdk",
                    sdk,
                    "-parse-as-library",
                    str(workspace_xpc_abi),
                    str(PROBE_SOURCES / "KernelBootstrapPeerProbe.swift"),
                    str(PROBE_SOURCES / "KernelXPCClientAttack.swift"),
                    "-o",
                    str(kernel_client_attack_binary),
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(
                kernel_attack_compile.returncode,
                0,
                kernel_attack_compile.stderr,
            )

            self._write_plist(
                contents / "Info.plist",
                {
                    "CFBundleIdentifier": host_bundle_id,
                    "CFBundleExecutable": "Host",
                    "CFBundlePackageType": "APPL",
                    "CFBundleName": "KhaosXPCProbe",
                    "CFBundleVersion": "1",
                    "LSMinimumSystemVersion": "13.0",
                },
            )
            entitlements = root / "entitlements.plist"
            self._write_plist(
                entitlements,
                {"com.apple.security.app-sandbox": True},
            )
            signed = subprocess.run(
                [
                    "codesign",
                    "--force",
                    "--keychain",
                    str(signing_keychain),
                    "--sign",
                    signing_identity,
                    "--entitlements",
                    str(entitlements),
                    str(app),
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(signed.returncode, 0, signed.stdout + signed.stderr)
            # The nested caller requirement is sealed into this bundle later;
            # pin its stable publisher identity instead of a self-referential cdhash.
            host_requirement = self._designated_code_requirement(
                host_binary, host_bundle_id
            )
            host_client_executable.parent.mkdir(parents=True)
            shutil.copy2(host_client_binary, host_client_executable)
            self._write_plist(
                host_client_bundle / "Contents" / "Info.plist",
                {
                    "CFBundleIdentifier": host_client_service_id,
                    "CFBundleExecutable": "HostClient",
                    "CFBundlePackageType": "XPC!",
                    "CFBundleName": "KhaosXPCProbeHostClient",
                    "CFBundleVersion": "1",
                    "KhaosCallerRequirement": host_requirement,
                    "XPCService": {
                        "ServiceType": "Application",
                        "RunLoopType": "NSRunLoop",
                    },
                },
            )
            subprocess.run(
                [
                    "codesign",
                    "--force",
                    "--sign",
                    "-",
                    "--entitlements",
                    str(entitlements),
                    str(host_client_bundle),
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            peer_requirement = self._code_hash_requirement(
                host_client_executable, host_client_service_id
            )
            client_requirement_check = subprocess.run(
                [
                    "codesign",
                    "--verify",
                    f"-R={peer_requirement}",
                    str(host_client_executable),
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(
                client_requirement_check.returncode,
                0,
                client_requirement_check.stderr,
            )
            # Only the trusted execution service attaches the bounded APFS image.
            kernel_execution_entitlements = root / "kernel-execution-entitlements.plist"
            self._write_plist(kernel_execution_entitlements, {})
            for name, bundle in service_bundles.items():
                service_binary_paths[name].parent.mkdir(parents=True, exist_ok=True)
                service_contents = bundle / "Contents"
                executable = (
                    name
                    if name in {
                        "Spoof", "Kernel", "KernelExecution", "KernelProduction"
                    }
                    else "Runner"
                )
                source = (
                    spoof_binary
                    if name == "Spoof"
                    else root / "KernelProduction"
                    if name == "KernelProduction"
                    else root / "Kernel"
                    if name in {"Kernel", "KernelExecution"}
                    else runner_binary
                )
                shutil.copy2(source, service_binary_paths[name])
                if name != "Spoof" and python_runtime_available:
                    bundled_framework = (
                        service_contents / "Frameworks" / "Python.framework"
                    )
                    bundled_framework.parent.mkdir(parents=True)
                    shutil.copytree(
                        python_framework,
                        bundled_framework,
                        symlinks=True,
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
                    )
                    site_packages = (
                        bundled_framework
                        / "Versions"
                        / python_version
                        / "lib"
                        / f"python{python_version}"
                        / "site-packages"
                    )
                    if site_packages.is_symlink():
                        site_packages.unlink()
                    elif site_packages.exists():
                        shutil.rmtree(site_packages)
                    bundled_python = (
                        bundled_framework
                        / "Versions"
                        / python_version
                        / "bin"
                        / f"python{python_version}"
                    )
                    python_app = (
                        bundled_framework
                        / "Versions"
                        / python_version
                        / "Resources"
                        / "Python.app"
                    )
                    python_app_executable = (
                        python_app / "Contents" / "MacOS" / "Python"
                    )
                    subprocess.run(
                        [
                            str(install_name_tool),
                            "-change",
                            str(python_executable.parents[1] / "Python"),
                            "@executable_path/../Python",
                            str(bundled_python),
                        ],
                        check=True,
                        capture_output=True,
                        text=True,
                    )
                    subprocess.run(
                        [
                            str(install_name_tool),
                            "-change",
                            str(python_executable.parents[1] / "Python"),
                            "@executable_path/../../../../Python",
                            str(python_app_executable),
                        ],
                        check=True,
                        capture_output=True,
                        text=True,
                    )
                    for code_path in (
                        bundled_framework / "Versions" / python_version / "Python",
                        bundled_python,
                        python_app_executable,
                    ):
                        subprocess.run(
                            ["codesign", "--force", "--sign", "-", str(code_path)],
                            check=True,
                            capture_output=True,
                            text=True,
                        )
                    subprocess.run(
                        ["codesign", "--force", "--sign", "-", str(python_app)],
                        check=True,
                        capture_output=True,
                        text=True,
                    )
                    subprocess.run(
                        ["codesign", "--force", "--sign", "-", str(bundled_framework)],
                        check=True,
                        capture_output=True,
                        text=True,
                    )
                    framework_signature = subprocess.run(
                        [
                            "codesign",
                            "--verify",
                            "--deep",
                            "--strict",
                            str(bundled_framework),
                        ],
                        check=False,
                        capture_output=True,
                        text=True,
                    )
                    self.assertEqual(
                        framework_signature.returncode,
                        0,
                        framework_signature.stderr,
                    )
                    resources = service_contents / "Resources"
                    resources.mkdir()
                    shutil.copytree(
                        Path(__file__).resolve().parents[1] / "khaos",
                        resources / "khaos",
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
                    )
                    shutil.copy2(
                        PROBE_SOURCES / "kernel_runner_probe.py",
                        resources / "kernel_runner_probe.py",
                    )
                    if name in {"Kernel", "KernelExecution", "KernelProduction"}:
                        shutil.copy2(
                            PROBE_SOURCES / "kernel_workspace_probe.py",
                            resources / "kernel_workspace_probe.py",
                        )
                        shutil.copy2(
                            PROBE_SOURCES / "kernel_workspace_descriptor_probe.py",
                            resources / "kernel_workspace_descriptor_probe.py",
                        )
                service_info = {
                    "CFBundleIdentifier": service_ids[name],
                    "CFBundleExecutable": executable,
                    "CFBundlePackageType": "XPC!",
                    "CFBundleName": f"KhaosXPCProbe{name}",
                    "CFBundleVersion": "1",
                    "KhaosPeerRequirement": peer_requirement,
                    "XPCService": {
                        "ServiceType": "Application",
                        "RunLoopType": "NSRunLoop",
                    },
                }
                if name in {"Kernel", "KernelExecution", "KernelProduction"}:
                    if name == "Kernel":
                        service_info["KhaosHostRequirement"] = peer_requirement
                        service_info["KhaosKernelServiceMode"] = "scope"
                    else:
                        service_info["KhaosWorkspaceCallerRequirement"] = (
                            peer_requirement
                        )
                        if name == "KernelProduction":
                            plugin_store = self._plugin_store_path_for_requirement(
                                peer_requirement
                            )
                            self.assertFalse(
                                plugin_store.exists(),
                                f"refusing to reuse Plugin state at {plugin_store}",
                            )
                            self.addCleanup(
                                self._remove_plugin_store,
                                plugin_store,
                            )
                        service_info["KhaosBootstrapRequirement"] = host_requirement
                        if name == "KernelExecution":
                            service_info["KhaosKernelServiceMode"] = "execution"
                if name != "Spoof" and python_runtime_available:
                    service_info["KhaosPythonVersion"] = python_version
                self._write_plist(service_contents / "Info.plist", service_info)
                service_entitlements = (
                    kernel_execution_entitlements
                    if name in {"KernelExecution", "KernelProduction"}
                    else entitlements
                )
                sign_command = ["codesign", "--force", "--sign", "-"]
                if name == "Spoof":
                    sign_command.extend(("--identifier", host_client_service_id))
                sign_command.extend(
                    (
                        "--entitlements",
                        str(service_entitlements),
                        str(bundle),
                    )
                )
                subprocess.run(
                    sign_command,
                    check=True,
                    capture_output=True,
                    text=True,
                )
                if name == "Spoof":
                    same_identifier = subprocess.run(
                        [
                            "codesign",
                            "--verify",
                            f'-R=identifier "{host_client_service_id}"',
                            str(service_binary_paths[name]),
                        ],
                        check=False,
                        capture_output=True,
                        text=True,
                    )
                    self.assertEqual(
                        same_identifier.returncode,
                        0,
                        same_identifier.stderr,
                    )
                    exact_host_code = subprocess.run(
                        [
                            "codesign",
                            "--verify",
                            f"-R={peer_requirement}",
                            str(service_binary_paths[name]),
                        ],
                        check=False,
                        capture_output=True,
                        text=True,
                    )
                    self.assertNotEqual(
                        exact_host_code.returncode,
                        0,
                        exact_host_code.stdout + exact_host_code.stderr,
                    )
            if prepare_workspace_grant:
                self.assertTrue(
                    python_runtime_available,
                    "the workspace XPC chain requires bundled Python 3.10+",
                )
                workspace_grant_app = root / "WorkspaceGrant.app"
                workspace_grant_contents = workspace_grant_app / "Contents"
                workspace_grant_executable = (
                    workspace_grant_contents / "MacOS" / "WorkspaceGrant"
                )
                workspace_grant_executable.parent.mkdir(parents=True)
                shutil.copy2(workspace_grant_binary, workspace_grant_executable)
                workspace_grant_entitlements = root / "workspace-grant-entitlements.plist"
                self._write_plist(
                    workspace_grant_entitlements,
                    {
                        "com.apple.security.app-sandbox": True,
                        # This negative case creates an app-container scoped bookmark
                        # without user selection.
                        "com.apple.security.files.bookmarks.app-scope": True,
                        "com.apple.security.files.user-selected.read-write": True,
                    },
                )
                self._write_plist(
                    workspace_grant_contents / "Info.plist",
                    {
                        "CFBundleIdentifier": workspace_grant_bundle_id,
                        "CFBundleExecutable": "WorkspaceGrant",
                        "CFBundleInfoDictionaryVersion": "6.0",
                        "CFBundlePackageType": "APPL",
                        "CFBundleName": "KhaosWorkspaceGrantProbe",
                        "CFBundleShortVersionString": "1.0",
                        "CFBundleVersion": "1",
                        "CFBundleSupportedPlatforms": ["MacOSX"],
                        "LSMinimumSystemVersion": "13.0",
                        "NSPrincipalClass": "NSApplication",
                    },
                )
                subprocess.run(
                    [
                        "codesign",
                        "--force",
                        "--keychain",
                        str(signing_keychain),
                        "--sign",
                        signing_identity,
                        "--entitlements",
                        str(workspace_grant_entitlements),
                        str(workspace_grant_app),
                    ],
                    check=True,
                    capture_output=True,
                    text=True,
                )
                # The embedded XPC service changes the containing app's resource seal.
                workspace_grant_requirement = self._designated_code_requirement(
                    workspace_grant_executable, workspace_grant_bundle_id
                )
                workspace_grant_service_requirements = {}
                for service_name in ("KernelExecution", "KernelProduction"):
                    grant_service = (
                        workspace_grant_contents
                        / "XPCServices"
                        / f"{service_name}.xpc"
                    )
                    shutil.copytree(
                        service_bundles[service_name], grant_service, symlinks=True
                    )
                    service_info = grant_service / "Contents" / "Info.plist"
                    with service_info.open("rb") as stream:
                        grant_info = plistlib.load(stream)
                    grant_info["CFBundleIdentifier"] = (
                        f"{workspace_grant_bundle_id}.{service_name}"
                    )
                    grant_info["KhaosWorkspaceCallerRequirement"] = (
                        workspace_grant_requirement
                    )
                    if service_name == "KernelProduction":
                        plugin_store = self._plugin_store_path_for_requirement(
                            workspace_grant_requirement
                        )
                        self.assertFalse(
                            plugin_store.exists(),
                            f"refusing to reuse Plugin state at {plugin_store}",
                        )
                        self.addCleanup(
                            self._remove_plugin_store,
                            plugin_store,
                        )
                    grant_info["KhaosBootstrapRequirement"] = (
                        workspace_grant_requirement
                    )
                    self._write_plist(service_info, grant_info)
                    subprocess.run(
                        [
                            "codesign",
                            "--force",
                            "--keychain",
                            str(signing_keychain),
                            "--sign",
                            signing_identity,
                            "--entitlements",
                            str(kernel_execution_entitlements),
                            str(grant_service),
                        ],
                        check=True,
                        capture_output=True,
                        text=True,
                    )
                    workspace_grant_service_requirements[service_name] = (
                        self._designated_code_requirement(
                            grant_service / "Contents" / "MacOS" / service_name,
                            f"{workspace_grant_bundle_id}.{service_name}",
                        )
                    )

                # This sibling XPC gets only a path; its sandbox has no user-selected scope.
                workspace_grant_host_service = (
                    workspace_grant_contents
                    / "XPCServices"
                    / "UntrustedHost.xpc"
                )
                host_service_executable = (
                    workspace_grant_host_service
                    / "Contents"
                    / "MacOS"
                    / "UntrustedHost"
                )
                host_service_executable.parent.mkdir(parents=True)
                shutil.copy2(workspace_grant_host_binary, host_service_executable)
                workspace_grant_host_entitlements = (
                    root / "workspace-grant-host-entitlements.plist"
                )
                self._write_plist(
                    workspace_grant_host_entitlements,
                    {"com.apple.security.app-sandbox": True},
                )
                self._write_plist(
                    workspace_grant_host_service / "Contents" / "Info.plist",
                    {
                        "CFBundleIdentifier": (
                            f"{workspace_grant_bundle_id}.UntrustedHost"
                        ),
                        "CFBundleExecutable": "UntrustedHost",
                        "CFBundlePackageType": "XPC!",
                        "CFBundleName": "KhaosUntrustedHostProbe",
                        "CFBundleVersion": "1",
                        "KhaosHostRequirement": workspace_grant_requirement,
                        "XPCService": {
                            "ServiceType": "Application",
                            "RunLoopType": "NSRunLoop",
                        },
                    },
                )
                subprocess.run(
                    [
                        "codesign",
                        "--force",
                        "--sign",
                        "-",
                        "--entitlements",
                        str(workspace_grant_host_entitlements),
                        str(workspace_grant_host_service),
                    ],
                    check=True,
                    capture_output=True,
                    text=True,
                )

                grant_app_info = workspace_grant_contents / "Info.plist"
                with grant_app_info.open("rb") as stream:
                    grant_info = plistlib.load(stream)
                for service_name, requirement in (
                    workspace_grant_service_requirements.items()
                ):
                    grant_info[f"Khaos{service_name}ServiceRequirement"] = requirement
                self._write_plist(grant_app_info, grant_info)

                subprocess.run(
                    [
                        "codesign",
                        "--force",
                        "--keychain",
                        str(signing_keychain),
                        "--sign",
                        signing_identity,
                        "--entitlements",
                        str(workspace_grant_entitlements),
                        str(workspace_grant_app),
                    ],
                    check=True,
                    capture_output=True,
                    text=True,
                )
                verified_workspace_grant = subprocess.run(
                    [
                        "codesign",
                        "--verify",
                        "--deep",
                        "--strict",
                        str(workspace_grant_app),
                    ],
                    check=False,
                    capture_output=True,
                    text=True,
                )
                self.assertEqual(
                    verified_workspace_grant.returncode,
                    0,
                    verified_workspace_grant.stderr,
                )
                self.assertEqual(
                    self._designated_code_requirement(
                        workspace_grant_executable, workspace_grant_bundle_id
                    ),
                    workspace_grant_requirement,
                    "signing the containing grant app changed its caller identity",
                )
                untrusted_host_bootstrap_result = subprocess.run(
                    [
                        str(workspace_grant_executable),
                        workspace_grant_bundle_id,
                        "--untrusted-host-bootstrap-check",
                        str(outside),
                    ],
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
                self.assertEqual(
                    untrusted_host_bootstrap_result.returncode,
                    0,
                    untrusted_host_bootstrap_result.stderr,
                )
                self.assertIn(
                    "untrusted-host-kernel-bootstrap=denied",
                    untrusted_host_bootstrap_result.stdout,
                )
                self.assertRegex(
                    untrusted_host_bootstrap_result.stdout,
                    r"(?m)^untrusted-xpc-workspace-write=denied:(?:1|13)$",
                )
                self.assertEqual(
                    outside.read_text(encoding="utf-8"),
                    "outside-secret",
                )
                client_peer_result = subprocess.run(
                    [
                        str(workspace_grant_executable),
                        workspace_grant_bundle_id,
                        "--client-peer-identity-check",
                        str(outside),
                    ],
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
                self.assertEqual(
                    client_peer_result.returncode,
                    0,
                    client_peer_result.stderr,
                )
                self.assertIn(
                    "xpc-kernel-client-peer-mismatch=rejected-by-os",
                    client_peer_result.stdout,
                )
                self.assertEqual(
                    outside.read_text(encoding="utf-8"),
                    "outside-secret",
                )
                relay_peer_result = subprocess.run(
                    [
                        str(workspace_grant_executable),
                        workspace_grant_bundle_id,
                        "--relay-peer-check",
                    ],
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
                self.assertEqual(
                    relay_peer_result.returncode,
                    0,
                    relay_peer_result.stderr,
                )
                self.assertIn(
                    "xpc-kernel-relay=peer-pid-mismatch-rejected-before-parse",
                    relay_peer_result.stdout,
                )
                production_bootstrap_result = subprocess.run(
                    [
                        str(workspace_grant_executable),
                        workspace_grant_bundle_id,
                        "--production-bootstrap-check",
                    ],
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
                self.assertEqual(
                    production_bootstrap_result.returncode,
                    0,
                    production_bootstrap_result.stderr,
                )
                self.assertIn(
                    "production-xpc-bootstrap=authenticated",
                    production_bootstrap_result.stdout,
                )
                app_container_result = subprocess.run(
                    [
                        str(workspace_grant_executable),
                        workspace_grant_bundle_id,
                        "--production-app-container-workspace-check",
                    ],
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=300,
                )
                self.assertEqual(
                    app_container_result.returncode,
                    0,
                    app_container_result.stderr,
                )
                for evidence in (
                    "production-xpc-app-container-bookmark=workspace_rejected",
                    "production-xpc-app-container-bookmark-no-writeback=verified",
                    "production-xpc-app-container-issued-scope=workspace_rejected",
                    "production-xpc-app-container-issued-scope-no-writeback=verified",
                ):
                    self.assertIn(evidence, app_container_result.stdout)
            subprocess.run(
                [
                    "codesign",
                    "--force",
                    "--keychain",
                    str(signing_keychain),
                    "--sign",
                    signing_identity,
                    "--entitlements",
                    str(entitlements),
                    str(app),
                ],
                check=True,
                capture_output=True,
                text=True,
            )

            verified = subprocess.run(
                ["codesign", "--verify", "--deep", "--strict", "--verbose=4", str(app)],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(verified.returncode, 0, verified.stderr)
            self.assertEqual(
                self._code_hash_requirement(
                    host_client_executable, host_client_service_id
                ),
                peer_requirement,
                "signing the containing probe app changed its pinned HostClient service",
            )
            self.assertEqual(
                self._designated_code_requirement(host_binary, host_bundle_id),
                host_requirement,
                "signing the containing probe app changed its caller identity",
            )

            protected_kernel_files = [
                (
                    "KernelExecution executable",
                    service_binary_paths["KernelExecution"],
                    service_bundles["KernelExecution"],
                ),
                (
                    "KernelProduction executable",
                    service_binary_paths["KernelProduction"],
                    service_bundles["KernelProduction"],
                ),
            ]
            if python_runtime_available:
                production_contents = (
                    service_bundles["KernelProduction"] / "Contents"
                )
                production_resources = production_contents / "Resources"
                production_python = (
                    production_contents
                    / "Frameworks"
                    / "Python.framework"
                    / "Versions"
                    / python_version
                    / "bin"
                    / f"python{python_version}"
                )
                protected_kernel_files.extend(
                    (
                        (
                            "KernelProduction Python bridge",
                            production_resources
                            / "khaos"
                            / "kernel"
                            / "workspace_xpc_bridge.py",
                            service_bundles["KernelProduction"],
                        ),
                        (
                            "KernelProduction changeset implementation",
                            production_resources
                            / "khaos"
                            / "kernel"
                            / "workspace_changes.py",
                            service_bundles["KernelProduction"],
                        ),
                        (
                            "KernelProduction Python interpreter",
                            production_python,
                            service_bundles["KernelProduction"],
                        ),
                    )
                )

            for label, protected_file, service_bundle in protected_kernel_files:
                with self.subTest(protected_file=label):
                    self.assertTrue(protected_file.is_file(), str(protected_file))
                    protected_digest = hashlib.sha256(
                        protected_file.read_bytes()
                    ).digest()
                    kernel_write_probe = subprocess.run(
                        [
                            str(host_binary),
                            "--verify-kernel-bundle-immutability",
                            str(protected_file),
                            str(service_bundle),
                        ],
                        check=False,
                        capture_output=True,
                        text=True,
                        timeout=10,
                    )
                    self.assertEqual(
                        kernel_write_probe.returncode,
                        0,
                        f"{label}: {kernel_write_probe.stderr}",
                    )
                    self.assertIn(
                        "app-container-write=allowed", kernel_write_probe.stdout
                    )
                    for operation in (
                        "kernel-helper-open-write",
                        "kernel-helper-create",
                        "kernel-helper-chmod",
                        "kernel-helper-hardlink",
                        "kernel-helper-swap",
                        "kernel-helper-rename",
                        "kernel-helper-symlink-replace",
                        "kernel-helper-unlink",
                        "kernel-bundle-swap",
                    ):
                        with self.subTest(protected_file=label, operation=operation):
                            self.assertRegex(
                                kernel_write_probe.stdout,
                                rf"{operation}=denied:(?:1|13)",
                            )
                    self.assertEqual(
                        hashlib.sha256(protected_file.read_bytes()).digest(),
                        protected_digest,
                    )
                    kernel_signature_check = subprocess.run(
                        [
                            "codesign",
                            "--verify",
                            "--deep",
                            "--strict",
                            str(service_bundle),
                        ],
                        check=False,
                        capture_output=True,
                        text=True,
                    )
                    self.assertEqual(
                        kernel_signature_check.returncode,
                        0,
                        f"{label}: {kernel_signature_check.stderr}",
                    )

            result = subprocess.run(
                [
                    str(host_binary),
                    host_bundle_id,
                    str(outside),
                    str(listener.getsockname()[1]),
                    str(execution_workspace / "input.txt"),
                    "yes" if python_runtime_available else "no",
                ],
                check=False,
                capture_output=True,
                text=True,
                timeout=200,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            report = json.loads(result.stdout)
            host_client_attack = root / "HostClientAttack"
            shutil.copy2(client_attack_binary, host_client_attack)
            self._assert_rejected_xpc_client(
                host_client_attack,
                host_bundle_id,
                host_requirement,
                f"{host_bundle_id}.HostClient",
            )
            self.assertTrue(
                report["selected_workspace_direct_read"].startswith("denied:"),
                report["selected_workspace_direct_read"],
            )
            self.assertIn(
                report["spoof_status"],
                {"peer=denied", "peer=no-response"},
                report["spoof_status"],
            )
            self.assertIn(
                report["spoof_kernel_status"],
                {"peer=denied", "peer=no-response"},
                report["spoof_kernel_status"],
            )
            self.assertIn(
                report["spoof_kernel_execution_status"],
                {"peer=denied", "peer=no-response"},
                report["spoof_kernel_execution_status"],
            )
            self.assertEqual(report["spoof_output"], "missing")
            self.assertEqual(report["snapshot_a_output"], "child")
            self.assertEqual(report["sibling"], "sibling-secret")
            self.assertEqual(outside.read_text(encoding="utf-8"), "outside-secret")
            self.assertFalse(Path(f"{outside}.runner-write").exists())
            self.assertFalse(Path(f"{outside}.plugin-write").exists())
            plugin_a = set(report["plugin_a"].splitlines())
            plugin_b = set(report["plugin_b"].splitlines())
            isolated_plugin_a = set(report["isolated_plugin_a"].splitlines())
            isolated_plugin_b = set(report["isolated_plugin_b"].splitlines())
            self.assertTrue(
                report["kernel_unscoped_read"].startswith("kernel-unscoped=denied:"),
                report["kernel_unscoped_read"],
            )
            kernel_read, bookmark_stale, bookmark_refreshed = report[
                "kernel_read"
            ].split(";", maxsplit=2)
            self.assertEqual(kernel_read, "kernel-read=plugin-a-secret")
            stale_value = bookmark_stale.removeprefix("bookmark-stale=")
            refreshed_value = bookmark_refreshed.removeprefix(
                "bookmark-refreshed="
            )
            self.assertIn(stale_value, {"true", "false"})
            self.assertIn(refreshed_value, {"true", "false"})
            self.assertEqual(stale_value, "true")
            self.assertEqual(refreshed_value, stale_value)
            if python_runtime_available:
                caller_crash = set(
                    report["kernel_workspace_caller_crash"].splitlines()
                )
                self.assertIn("xpc-kernel-caller-process=terminated", caller_crash)
                self.assertIn("xpc-kernel-caller-connection=interrupted", caller_crash)
                self.assertIn("xpc-kernel-after-caller-crash=healthy", caller_crash)
                self.assertIn("xpc-kernel-crash-no-writeback=verified", caller_crash)
                self.assertIn(
                    "xpc-kernel-disconnect=no-writeback",
                    report["kernel_workspace_disconnect"],
                )
                self.assertEqual(
                    report["kernel_workspace_disconnect_output"],
                    "missing",
                )
                kernel_execution = set(
                    report["kernel_workspace_execution"].splitlines()
                )
                self.assertIn(
                    "xpc-kernel-oversized-bookmark=rejected-before-buffer-allocation",
                    kernel_execution,
                )
                self.assertIn("xpc-kernel-abi=versioned-bounded", kernel_execution)
                self.assertIn("xpc-kernel-request-id=fixed-width", kernel_execution)
                self.assertIn(
                    "xpc-kernel-stream-peer=mismatch-rejected-before-parse",
                    kernel_execution,
                )
                self.assertIn(
                    "xpc-kernel-client-bookmark=bounded-before-copy",
                    kernel_execution,
                )
                self.assertIn(
                    "xpc-kernel-stalled-bookmark=bounded-deadline",
                    kernel_execution,
                )
                self.assertIn(
                    "xpc-kernel-workspace-child-symlink=denied-before-probe",
                    kernel_execution,
                )
                self.assertIn(
                    "xpc-kernel-descriptor-child-symlink=denied-before-probe",
                    kernel_execution,
                )
                kernel_cancellation = set(
                    report["kernel_workspace_cancellation"].splitlines()
                )
                self.assertIn(
                    "xpc-kernel-cancel=process_cancelled",
                    kernel_cancellation,
                )
                self.assertIn("xpc-kernel-cancel-scope=bound", kernel_cancellation)
                self.assertIn(
                    "xpc-kernel-cancel-connection=bound",
                    kernel_cancellation,
                )
                stale = next(
                    value
                    for value in kernel_execution
                    if value.startswith("kernel-workspace-bookmark-stale=")
                )
                refreshed = next(
                    value
                    for value in kernel_execution
                    if value.startswith("kernel-workspace-bookmark-refreshed=")
                )
                stale_value = stale.removeprefix("kernel-workspace-bookmark-stale=")
                refreshed_value = refreshed.removeprefix(
                    "kernel-workspace-bookmark-refreshed="
                )
                self.assertEqual(stale_value, "true")
                self.assertEqual(refreshed_value, stale_value)
                self.assertIn("kernel-workspace-descriptor-exit=0", kernel_execution)
                self.assertIn("kernel-workspace-exit=0", kernel_execution)
                source_volume = next(
                    value
                    for value in kernel_execution
                    if value.startswith("xpc-kernel-source-volume=")
                )
                self.assertTrue(
                    source_volume.startswith("xpc-kernel-source-volume=inspected:"),
                    source_volume,
                )
                apfs_probe = next(
                    value
                    for value in kernel_execution
                    if value.startswith("xpc-kernel-apfs-snapshot=")
                )
                self.assertEqual(apfs_probe, "xpc-kernel-apfs-snapshot=mounted")
                inherited_root_result = next(
                    value
                    for value in kernel_execution
                    if value.startswith("xpc-kernel-inherited-root=")
                )
                self.assertEqual(
                    inherited_root_result,
                    "xpc-kernel-inherited-root=read:xpc-input",
                )
                for label in (
                    "xpc-kernel-parent-escape",
                    "xpc-kernel-symlink-escape",
                ):
                    result = next(
                        value
                        for value in kernel_execution
                        if value.startswith(f"{label}=")
                    )
                    self.assertEqual(
                        result,
                        f"{label}=allowed:sibling-secret",
                    )
                hardlink_result = next(
                    value
                    for value in kernel_execution
                    if value.startswith("xpc-kernel-hardlink-alias=")
                )
                if report["kernel_descriptor_hardlink"] == "created":
                    self.assertEqual(
                        hardlink_result,
                        "xpc-kernel-hardlink-alias=allowed:sibling-secret",
                    )
                else:
                    self.assertTrue(
                        report["kernel_descriptor_hardlink"].startswith(
                            "unavailable:"
                        ),
                        report["kernel_descriptor_hardlink"],
                    )
                    self.assertEqual(
                        hardlink_result,
                        "xpc-kernel-hardlink-alias=denied:2",
                    )
                self.assertIn("xpc-kernel-runner=returncode:0", kernel_execution)
                self.assertIn("xpc-kernel-fs-scope=verified", kernel_execution)
                self.assertIn(
                    "xpc-kernel-commit=added:1,modified:0,deleted:0",
                    kernel_execution,
                )
                self.assertIn(
                    "xpc-kernel-unsafe-commit=commit_rejected",
                    kernel_execution,
                )
                for kind in ("symlink", "hardlink", "special"):
                    self.assertIn(
                        f"xpc-kernel-unsafe-{kind}=commit_rejected",
                        kernel_execution,
                    )
                self.assertIn("xpc-kernel-unsafe-output=absent", kernel_execution)
                self.assertIn("xpc-kernel-prior-output=preserved", kernel_execution)
                self.assertIn("xpc-kernel-outside-canary=unchanged", kernel_execution)
                self.assertEqual(
                    report["kernel_workspace_output"],
                    "committed:xpc-input",
                )
                self.assertEqual(report["kernel_workspace_bypass"], "missing")
            else:
                self.assertIn(
                    "kernel-workspace-python=unavailable",
                    report["kernel_workspace_execution"],
                )
            khaos_runner = set(report["khaos_runner"].splitlines())
            if python_runtime_available:
                self.assertIn("khaos-runner-exit=0", khaos_runner)
                for label in (
                    "plugin-snapshot-read=denied",
                    "plugin-sibling-read=denied",
                    "plugin-outside-read=denied",
                    "plugin-snapshot-write=denied",
                    "plugin-outside-write=denied",
                    "plugin-network=denied",
                    "plugin-fs-read=broker-mediated",
                    "plugin-fs-escape=denied",
                ):
                    self.assertIn(label, khaos_runner)
            else:
                self.assertIn("python-skip=no-supported-runtime", khaos_runner)
            self.assertIn("runner-snapshot-access-started=true", plugin_a)
            if python_runtime_available:
                self.assertIn(f"python-version={python_version}", plugin_a)
                self.assertIn("python-khaos-import=WorkspaceChangeSet", plugin_a)
                self.assertIn("python-snapshot-write=allowed", plugin_a)
                self.assertIn("python-sibling-read=denied", plugin_a)
                self.assertIn("python-outside-read=denied", plugin_a)
                self.assertIn("python-network=denied", plugin_a)
            else:
                self.assertIn("python-skip=no-supported-runtime", plugin_a)
            self.assertIn("runner-snapshot-write=allowed", plugin_a)
            self.assertIn("child-snapshot-write=allowed", plugin_a)
            runner_denials = (
                "runner-sibling-read",
                "runner-sibling-write",
                "runner-outside-read",
                "runner-outside-write",
                "runner-symlink-sibling-read",
                "runner-symlink-sibling-write",
                "runner-symlink-outside-read",
                "runner-symlink-outside-write",
                "runner-traversal-read",
                "runner-traversal-write",
                "runner-hardlink",
                "runner-network",
            )
            for label in runner_denials:
                denial = next(
                    value for value in plugin_a if value.startswith(f"{label}=")
                )
                self.assertRegex(denial, rf"^{label}=denied:(?:1|13)$", denial)
            for label in ("child-sibling-read", "child-outside-read", "child-network"):
                self.assertIn(f"{label}=denied", plugin_a, report["plugin_a"])
            self.assertIn("runner-container-state=stored", plugin_a)
            # Passing here records the shared-service leak; it is not an isolation check.
            self.assertIn("runner-container-state=plugin-a-secret", plugin_b)
            self.assertIn("runner-container-state=stored", isolated_plugin_a)
            self.assertIn("runner-container-state=missing", isolated_plugin_b)
            other_container_denial = next(
                value
                for value in isolated_plugin_b
                if value.startswith("runner-other-container-read=")
            )
            self.assertRegex(
                other_container_denial,
                r"^runner-other-container-read=denied:(?:1|13)$",
            )

            self.assertFalse(
                connection_seen.wait(timeout=0.2),
                "App Sandbox Runner reached the loopback listener",
            )

            if prepare_workspace_grant:
                self._assert_rejected_xpc_client(
                    kernel_client_attack_binary,
                    workspace_grant_bundle_id,
                    workspace_grant_requirement,
                    f"{workspace_grant_bundle_id}.KernelExecution",
                )
                self._assert_rejected_xpc_client(
                    kernel_client_attack_binary,
                    workspace_grant_bundle_id,
                    workspace_grant_requirement,
                    f"{workspace_grant_bundle_id}.KernelProduction",
                )


    @staticmethod
    def _code_hash_requirement(executable: Path, identifier: str) -> str:
        result = subprocess.run(
            ["codesign", "-dr-", str(executable)],
            check=True,
            capture_output=True,
            text=True,
        )
        requirement_output = f"{result.stdout}\n{result.stderr}"
        code_hashes = sorted(
            {
                value.lower()
                for value in re.findall(
                    r'cdhash H"([0-9a-f]+)"',
                    requirement_output,
                    flags=re.IGNORECASE,
                )
            }
        )
        if not code_hashes:
            raise AssertionError(
                f"codesign did not return any cdhash for {executable}"
            )
        pinned_hashes = " or ".join(
            f'cdhash H"{value}"' for value in code_hashes
        )
        return f'identifier "{identifier}" and ({pinned_hashes})'

    @staticmethod
    def _designated_code_requirement(executable: Path, identifier: str) -> str:
        result = subprocess.run(
            ["codesign", "-dr-", str(executable)],
            check=True,
            capture_output=True,
            text=True,
        )
        requirement_output = f"{result.stdout}\n{result.stderr}"
        requirements = sorted(
            {
                value.strip()
                for value in re.findall(
                    r"designated => (.+)", requirement_output
                )
            }
        )
        if len(requirements) != 1:
            raise AssertionError(
                f"codesign did not return one designated requirement for {executable}"
            )
        requirement = requirements[0]
        self_identity = f'identifier "{identifier}"'
        if self_identity not in requirement or "cdhash H" in requirement:
            raise AssertionError(
                f"designated requirement is not a stable publisher identity: {requirement}"
            )
        return requirement

    @staticmethod
    def _remove_plugin_store(path: Path) -> None:
        if not path.exists():
            return
        for directory, _, _ in os.walk(path):
            os.chmod(directory, 0o700)
        shutil.rmtree(path)

    @staticmethod
    def _plugin_store_path_for_requirement(requirement: str) -> Path:
        namespace = hashlib.sha256(requirement.encode("utf-8")).hexdigest()
        return (
            Path.home()
            / "Library"
            / "Application Support"
            / f"org.khaos.Seed.PluginStore-{namespace}"
        )

    @staticmethod
    def _compile_workspace_grant_probe(
        swiftc: str,
        sdk: str,
        output: Path,
    ) -> None:
        command = [
            swiftc,
            "-sdk",
            sdk,
            "-target",
            f"{platform.machine()}-apple-macosx{platform.mac_ver()[0]}",
            "-parse-as-library",
            str(MACOS_TCB_SOURCES / "KernelWorkspaceClient.swift"),
            str(MACOS_TCB_SOURCES / "KernelSnapshotBrokerBootstrapXPC.swift"),
            str(MACOS_TCB_SOURCES / "KernelSnapshotBrokerBootstrapClient.swift"),
            str(MACOS_TCB_SOURCES / "XPCPeerIdentity.swift"),
            str(PROBE_SOURCES / "WorkspaceGrantHostIPC.swift"),
            str(PROBE_SOURCES / "WorkspaceProbeRequest.swift"),
            str(MACOS_TCB_SOURCES / "KernelWorkspaceXPC.swift"),
            str(PROBE_SOURCES / "WorkspaceGrant.swift"),
            "-o",
            str(output),
        ]
        compiled = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
        )
        if compiled.returncode != 0:
            raise AssertionError(compiled.stderr)

    @staticmethod
    def _create_signing_identity(directory: Path) -> tuple[str, Path]:
        password = secrets.token_urlsafe(24)
        key = directory / "signing-key.pem"
        certificate = directory / "signing-certificate.pem"
        identity_file = directory / "signing-identity.p12"
        keychain = directory / "xpc-test.keychain"
        subprocess.run(
            [
                "openssl",
                "req",
                "-new",
                "-newkey",
                "rsa:2048",
                "-nodes",
                "-x509",
                "-days",
                "1",
                "-subj",
                "/CN=Khaos XPC Probe Test Identity",
                "-addext",
                "keyUsage=critical,digitalSignature",
                "-addext",
                "extendedKeyUsage=critical,codeSigning",
                "-keyout",
                str(key),
                "-out",
                str(certificate),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        subprocess.run(
            [
                "openssl",
                "pkcs12",
                "-legacy",
                "-export",
                "-inkey",
                str(key),
                "-in",
                str(certificate),
                "-out",
                str(identity_file),
                "-passout",
                f"pass:{password}",
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        subprocess.run(
            ["security", "create-keychain", "-p", password, str(keychain)],
            check=True,
            capture_output=True,
            text=True,
        )
        subprocess.run(
            ["security", "unlock-keychain", "-p", password, str(keychain)],
            check=True,
            capture_output=True,
            text=True,
        )
        subprocess.run(
            [
                "security",
                "import",
                str(identity_file),
                "-k",
                str(keychain),
                "-P",
                password,
                "-T",
                "/usr/bin/codesign",
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        subprocess.run(
            [
                "security",
                "set-key-partition-list",
                "-S",
                "apple-tool:,apple:,codesign:",
                "-s",
                "-k",
                password,
                str(keychain),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        search_list = subprocess.run(
            ["security", "list-keychains", "-d", "user"],
            check=True,
            capture_output=True,
            text=True,
        )
        original_keychains = shlex.split(search_list.stdout)
        (directory / "original-keychain-search-list.json").write_text(
            json.dumps(original_keychains), encoding="utf-8"
        )
        subprocess.run(
            [
                "security",
                "list-keychains",
                "-d",
                "user",
                "-s",
                *original_keychains,
                str(keychain),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        fingerprint = subprocess.run(
            [
                "openssl",
                "x509",
                "-in",
                str(certificate),
                "-noout",
                "-fingerprint",
                "-sha1",
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        identity = fingerprint.stdout.split("=", maxsplit=1)[-1].strip()
        identity = identity.replace(":", "").upper()
        if not re.fullmatch(r"[0-9A-F]{40}", identity):
            raise AssertionError(f"invalid test signing certificate fingerprint: {identity}")
        return identity, keychain

    @staticmethod
    def _cleanup_signing_identity(
        directory: Path, cleanup_directory: Callable[[], None]
    ) -> None:
        keychain = directory / "xpc-test.keychain"
        saved_search_list = directory / "original-keychain-search-list.json"
        if saved_search_list.exists():
            original_keychains = json.loads(
                saved_search_list.read_text(encoding="utf-8")
            )
            subprocess.run(
                [
                    "security",
                    "list-keychains",
                    "-d",
                    "user",
                    "-s",
                    *original_keychains,
                ],
                check=False,
                capture_output=True,
                text=True,
            )
        subprocess.run(
            ["security", "delete-keychain", str(keychain)],
            check=False,
            capture_output=True,
            text=True,
        )
        cleanup_directory()

    @staticmethod
    def _sign_bundle(
        bundle: Path,
        entitlements: Path,
        signing_identity: str,
        signing_keychain: Path,
    ) -> None:
        subprocess.run(
            [
                "codesign",
                "--force",
                "--keychain",
                str(signing_keychain),
                "--sign",
                signing_identity,
                "--entitlements",
                str(entitlements),
                str(bundle),
            ],
            check=True,
            capture_output=True,
            text=True,
        )

    def _assert_rejected_xpc_client(
        self,
        executable: Path,
        identifier: str,
        required_requirement: str,
        service_name: str,
    ) -> None:
        subprocess.run(
            [
                "codesign",
                "--force",
                "--sign",
                "-",
                "--identifier",
                identifier,
                str(executable),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        same_identifier = subprocess.run(
            [
                "codesign",
                "--verify",
                f'-R=identifier "{identifier}"',
                str(executable),
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(same_identifier.returncode, 0, same_identifier.stderr)
        pinned_identity = subprocess.run(
            [
                "codesign",
                "--verify",
                f"-R={required_requirement}",
                str(executable),
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertNotEqual(
            pinned_identity.returncode,
            0,
            pinned_identity.stdout + pinned_identity.stderr,
        )
        attempt = subprocess.run(
            [str(executable), service_name],
            check=False,
            capture_output=True,
            text=True,
            timeout=15,
        )
        self.assertEqual(attempt.returncode, 0, attempt.stderr + attempt.stdout)
        self.assertEqual(
            attempt.stdout.strip(),
            "peer=connection-invalidated",
            attempt.stderr + attempt.stdout,
        )

    def _assert_product_snapshot_broker_positive(
        self,
        *,
        product_app: Path,
        kernel_binary: Path,
        directory: Path,
        sdk: str,
        swiftc: str,
        signing_identity: str,
        signing_keychain: Path,
        launcher_entitlements: dict[str, object],
        service_entitlements: dict[str, object],
        kernel_requirement: str,
    ) -> None:
        executable = directory / "SnapshotBrokerProbeService"
        compiled = subprocess.run(
            [
                swiftc,
                "-sdk",
                sdk,
                "-parse-as-library",
                str(MACOS_TCB_SOURCES / "KernelWorkspaceXPC.swift"),
                str(MACOS_TCB_SOURCES / "KernelWorkspaceClient.swift"),
                str(MACOS_TCB_SOURCES / "KernelWorkspaceService.swift"),
                str(MACOS_TCB_SOURCES / "XPCPeerIdentity.swift"),
                str(MACOS_TCB_SOURCES / "KernelSnapshotBrokerXPC.swift"),
                str(MACOS_TCB_SOURCES / "KernelSnapshotStoragePolicy.swift"),
                str(MACOS_TCB_SOURCES / "KernelSnapshotBrokerClient.swift"),
                str(PROBE_SOURCES / "SnapshotBrokerProbeService.swift"),
                "-o",
                str(executable),
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(compiled.returncode, 0, compiled.stderr)

        def mounted_broker_images() -> list[str]:
            inventory = subprocess.run(
                ["/usr/bin/hdiutil", "info", "-plist"],
                check=False,
                capture_output=True,
                timeout=15,
            )
            self.assertEqual(
                inventory.returncode,
                0,
                inventory.stdout.decode(errors="replace")
                + inventory.stderr.decode(errors="replace"),
            )
            properties = plistlib.loads(inventory.stdout)
            images = properties.get("images", [])
            return sorted(
                entry["image-path"]
                for entry in images
                if isinstance(entry, dict)
                and isinstance(entry.get("image-path"), str)
                and "/khaos-snapshot-broker-" in entry["image-path"]
            )

        before_images = mounted_broker_images()
        service_bundle = kernel_binary.parents[2]
        backup = directory / "KernelProduction.original"
        shutil.copy2(kernel_binary, backup)
        service_entitlements_path = directory / "kernel-probe-entitlements.plist"
        app_entitlements_path = directory / "launcher-entitlements.plist"
        self._write_plist(service_entitlements_path, service_entitlements)
        self._write_plist(app_entitlements_path, launcher_entitlements)
        sign_bundle = partial(
            self._sign_bundle,
            signing_identity=signing_identity,
            signing_keychain=signing_keychain,
        )

        try:
            shutil.copy2(executable, kernel_binary)
            sign_bundle(service_bundle, service_entitlements_path)
            sign_bundle(product_app, app_entitlements_path)
            self.assertEqual(
                self._designated_code_requirement(
                    kernel_binary, "org.khaos.Seed.KernelProduction"
                ),
                kernel_requirement,
            )
            with tempfile.TemporaryDirectory(
                prefix="khaos-broker-product-check-"
            ) as value:
                output_root = Path(value)
                stdout_path = output_root / "launcher.stdout"
                stderr_path = output_root / "launcher.stderr"
                waiter = self._launch_product_app(
                    product_app,
                    stdout_path,
                    stderr_path,
                    "--bootstrap-check",
                )
                stdout, stderr = waiter.communicate(timeout=180)
                diagnostic = (
                    stderr_path.read_text(encoding="utf-8", errors="replace")
                    if stderr_path.exists()
                    else ""
                )
                self.assertEqual(
                    waiter.returncode,
                    0,
                    f"LaunchServices waiter failed: {stdout!r} {stderr!r}; "
                    f"diagnostics={diagnostic!r}",
                )
                self.assertEqual(
                    stdout_path.read_text(encoding="utf-8").strip(),
                    "kernel-and-snapshot-broker-peer-authentication=verified",
                    f"diagnostics={diagnostic!r}",
                )
                self.assertEqual(diagnostic, "")
        finally:
            self._terminate_product_executable(kernel_binary)
            shutil.copy2(backup, kernel_binary)
            sign_bundle(service_bundle, service_entitlements_path)
            sign_bundle(product_app, app_entitlements_path)
            signature = subprocess.run(
                ["codesign", "--verify", "--deep", "--strict", str(product_app)],
                check=False,
                capture_output=True,
                text=True,
                timeout=30,
            )
            self.assertEqual(signature.returncode, 0, signature.stderr)
            self.assertEqual(
                self._designated_code_requirement(
                    kernel_binary, "org.khaos.Seed.KernelProduction"
                ),
                kernel_requirement,
            )

        self.assertEqual(
            mounted_broker_images(),
            before_images,
            "the authenticated product Kernel broker lease must not remain mounted",
        )

    def _assert_snapshot_broker_xpc_os_restrictions(
        self,
        *,
        product_app: Path,
        broker_binary: Path,
        kernel_binary: Path,
        directory: Path,
        sdk: str,
        swiftc: str,
        signing_identity: str,
        signing_keychain: Path,
        launcher_entitlements: dict[str, object],
        broker_entitlements: dict[str, object],
        broker_requirement: str,
    ) -> None:
        target = f"{platform.machine()}-apple-macosx{platform.mac_ver()[0]}"
        probe_service = directory / "SnapshotBrokerSandboxProbeService"
        service_compile = subprocess.run(
            [
                swiftc,
                "-sdk",
                sdk,
                "-target",
                target,
                "-parse-as-library",
                str(PROBE_SOURCES / "SnapshotBrokerSandboxProbeXPC.swift"),
                str(MACOS_TCB_SOURCES / "KernelSnapshotStoragePolicy.swift"),
                str(MACOS_TCB_SOURCES / "KernelSnapshotBrokerSandbox.swift"),
                str(MACOS_TCB_SOURCES / "KernelCStringArray.swift"),
                str(MACOS_TCB_SOURCES / "KernelSnapshotBrokerToolRunner.swift"),
                str(PROBE_SOURCES / "SnapshotBrokerSandboxProbeService.swift"),
                "-o",
                str(probe_service),
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=60,
        )
        self.assertEqual(service_compile.returncode, 0, service_compile.stderr)

        sandbox_source = MACOS_TCB_SOURCES / "KernelSnapshotBrokerSandbox.swift"
        sandbox_source_text = sandbox_source.read_text(encoding="utf-8")
        self.assertEqual(sandbox_source_text.count("(version 1)"), 1)
        invalid_sandbox_source = directory / "KernelSnapshotBrokerSandboxInvalid.swift"
        invalid_sandbox_source.write_text(
            sandbox_source_text.replace("(version 1)", "(invalid-profile)", 1),
            encoding="utf-8",
        )
        broker_sources = (
            MACOS_TCB_SOURCES / "KernelSnapshotBrokerXPC.swift",
            MACOS_TCB_SOURCES / "KernelSnapshotBrokerBootstrapXPC.swift",
            MACOS_TCB_SOURCES / "KernelSnapshotStoragePolicy.swift",
            sandbox_source,
            MACOS_TCB_SOURCES / "XPCPeerIdentity.swift",
            MACOS_TCB_SOURCES / "KernelCStringArray.swift",
            MACOS_TCB_SOURCES / "KernelSnapshotBrokerToolRunner.swift",
            MACOS_TCB_SOURCES / "KernelSnapshotBrokerService.swift",
            MACOS_TCB_SOURCES / "KernelSnapshotBrokerServiceMain.swift",
        )
        invalid_broker = directory / "KernelSnapshotBrokerInvalidPolicy"
        invalid_compile = subprocess.run(
            [
                swiftc,
                "-sdk",
                sdk,
                "-target",
                target,
                "-parse-as-library",
                *(str(invalid_sandbox_source if source == sandbox_source else source)
                  for source in broker_sources),
                "-o",
                str(invalid_broker),
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=60,
        )
        self.assertEqual(invalid_compile.returncode, 0, invalid_compile.stderr)

        probe_client = directory / "SnapshotBrokerSandboxProbeClient"
        client_compile = subprocess.run(
            [
                swiftc,
                "-sdk",
                sdk,
                "-target",
                target,
                "-parse-as-library",
                str(PROBE_SOURCES / "SnapshotBrokerSandboxProbeXPC.swift"),
                str(PROBE_SOURCES / "SnapshotBrokerSandboxProbeClient.swift"),
                "-o",
                str(probe_client),
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=60,
        )
        self.assertEqual(client_compile.returncode, 0, client_compile.stderr)

        # /Users/Shared is host-readable and writable by the test user, but it
        # is outside the Broker's one permitted storage subtree.
        canary_root = (
            Path("/Users/Shared")
            / f"org.khaos.Seed.BrokerProbe.{uuid.uuid4().hex}"
            / "Data"
        )
        self.assertTrue(Path("/Users/Shared").is_dir())
        canary_root.mkdir(parents=True, mode=0o700)
        self.addCleanup(shutil.rmtree, canary_root.parent, True)
        read_canary = canary_root / "outside-read-canary"
        write_canary = canary_root / "outside-write-canary"
        shared_executable = canary_root / "outside-shared-executable"
        self.addCleanup(read_canary.unlink, missing_ok=True)
        self.addCleanup(write_canary.unlink, missing_ok=True)
        self.addCleanup(shared_executable.unlink, missing_ok=True)
        read_canary.write_bytes(b"host-only broker read canary")
        self.assertEqual(read_canary.read_bytes(), b"host-only broker read canary")
        self.assertFalse(write_canary.exists())
        directory_mode = canary_root.stat().st_mode & 0o777
        self.addCleanup(os.chmod, canary_root, directory_mode)
        os.chmod(canary_root, 0o711)
        self.assertEqual(canary_root.stat().st_mode & 0o777, 0o711)
        os.chmod(canary_root, directory_mode)
        alias_read_canary = Path("/System/Volumes/Data") / read_canary.relative_to("/")
        self.assertEqual(alias_read_canary.read_bytes(), b"host-only broker read canary")
        self.assertEqual(
            (alias_read_canary.stat().st_dev, alias_read_canary.stat().st_ino),
            (read_canary.stat().st_dev, read_canary.stat().st_ino),
        )
        control_descriptor = os.open(
            write_canary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC,
            0o600,
        )
        os.close(control_descriptor)
        write_canary.unlink()

        temporary_write_canary = (
            Path(tempfile.gettempdir()) / f"khaos-broker-temp-{uuid.uuid4().hex}"
        )
        private_temporary_write_canary = (
            Path("/var/tmp") / f"khaos-broker-vartmp-{uuid.uuid4().hex}"
        )
        self.assertTrue(private_temporary_write_canary.parent.lstat().st_mode)
        self.assertTrue(os.access(private_temporary_write_canary.parent, os.F_OK))
        tmp_alias_root = Path("/System/Volumes/Data/private/tmp")
        self.assertTrue(tmp_alias_root.is_dir())
        self.assertTrue(os.path.samefile(tmp_alias_root, "/tmp"))
        tmp_alias_write_canary = (
            tmp_alias_root / f"khaos-broker-tmp-{uuid.uuid4().hex}"
        )
        tmp_alias_executable = (
            tmp_alias_root / f"khaos-broker-exec-{uuid.uuid4().hex}"
        )
        self.addCleanup(tmp_alias_executable.unlink, missing_ok=True)
        for path in (
            temporary_write_canary,
            private_temporary_write_canary,
            tmp_alias_write_canary,
        ):
            self.assertFalse(path.exists())
            descriptor = os.open(
                path,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC,
                0o600,
            )
            os.close(descriptor)
            path.unlink()
            self.addCleanup(path.unlink, missing_ok=True)

        shared_executable.write_bytes(Path("/usr/bin/true").read_bytes())
        shared_executable.chmod(0o700)
        subprocess.run(
            [str(shared_executable)],
            check=True,
            capture_output=True,
            timeout=5,
        )
        shutil.copyfile("/usr/bin/true", tmp_alias_executable)
        tmp_alias_executable.chmod(0o700)
        subprocess.run(
            [str(tmp_alias_executable)],
            check=True,
            capture_output=True,
            timeout=5,
        )

        package_manager_temp_roots = (
            Path("/opt/homebrew/var/homebrew/tmp"),
            Path("/usr/local/var/homebrew/tmp"),
        )
        package_manager_temp_root = next(
            (
                path
                for path in package_manager_temp_roots
                if path.is_dir() and os.access(path, os.W_OK)
            ),
            None,
        )
        package_executable = ""
        package_alias_executable = ""
        package_write_path = ""
        package_alias_write_path = ""
        if package_manager_temp_root is not None:
            package_executable_path = package_manager_temp_root / (
                f"khaos-broker-exec-canary-{uuid.uuid4().hex}"
            )
            package_write_canary = package_manager_temp_root / (
                f"khaos-broker-write-canary-{uuid.uuid4().hex}"
            )
            self.addCleanup(package_executable_path.unlink, missing_ok=True)
            self.addCleanup(package_write_canary.unlink, missing_ok=True)
            shutil.copyfile("/usr/bin/true", package_executable_path)
            package_executable_path.chmod(0o700)
            subprocess.run(
                [str(package_executable_path)],
                check=True,
                capture_output=True,
                timeout=5,
            )
            package_executable = str(package_executable_path)
            package_alias_temp_root = (
                Path("/System/Volumes/Data")
                / package_manager_temp_root.relative_to("/")
            )
            if (
                package_alias_temp_root.is_dir()
                and os.path.samefile(package_manager_temp_root, package_alias_temp_root)
            ):
                package_alias_executable_path = (
                    package_alias_temp_root / package_executable_path.name
                )
                package_alias_write_canary = (
                    package_alias_temp_root / package_write_canary.name
                )
                self.assertFalse(package_alias_write_canary.exists())
                alias_control = os.open(
                    package_alias_write_canary,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC,
                    0o600,
                )
                os.close(alias_control)
                package_alias_write_canary.unlink()
                subprocess.run(
                    [str(package_alias_executable_path)],
                    check=True,
                    capture_output=True,
                    timeout=5,
                )
                package_alias_executable = str(package_alias_executable_path)
                package_alias_write_path = str(package_alias_write_canary)
                self.addCleanup(package_alias_write_canary.unlink, missing_ok=True)
            self.assertFalse(package_write_canary.exists())
            package_write_descriptor = os.open(
                package_write_canary,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC,
                0o600,
            )
            os.close(package_write_descriptor)
            package_write_canary.unlink()
            package_write_path = str(package_write_canary)

        kernel_digest = hashlib.sha256(kernel_binary.read_bytes()).digest()
        control_descriptor = os.open(kernel_binary, os.O_WRONLY | os.O_CLOEXEC)
        os.close(control_descriptor)

        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.addCleanup(listener.close)
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        port = listener.getsockname()[1]
        listener.settimeout(5)
        self.assertIsNone(os.kill(os.getpid(), 0), "host signal control must succeed")
        with socket.create_connection(("127.0.0.1", port), timeout=5):
            accepted, _ = listener.accept()
            accepted.close()

        broker_bundle = broker_binary.parents[2]
        product_launcher = product_app / "Contents" / "MacOS" / "KhaosSeed"
        broker_backup = directory / "KernelSnapshotBroker.original"
        launcher_backup = directory / "KhaosSeed.original"
        shutil.copy2(broker_binary, broker_backup)
        shutil.copy2(product_launcher, launcher_backup)
        broker_entitlements_path = directory / "broker-probe-entitlements.plist"
        launcher_entitlements_path = directory / "launcher-probe-entitlements.plist"
        self._write_plist(broker_entitlements_path, broker_entitlements)
        self._write_plist(launcher_entitlements_path, launcher_entitlements)
        sign_bundle = partial(
            self._sign_bundle,
            signing_identity=signing_identity,
            signing_keychain=signing_keychain,
        )

        try:
            self._terminate_product_executable(broker_binary)
            self._terminate_product_executable(product_launcher)
            shutil.copy2(invalid_broker, broker_binary)
            sign_bundle(broker_bundle, broker_entitlements_path)
            sign_bundle(product_app, launcher_entitlements_path)
            self.assertEqual(
                self._designated_code_requirement(
                    broker_binary, "org.khaos.Seed.KernelSnapshotBroker"
                ),
                broker_requirement,
            )
            with tempfile.TemporaryDirectory(
                prefix="khaos-broker-invalid-policy-"
            ) as value:
                output_root = Path(value)
                stdout_path = output_root / "launcher.stdout"
                stderr_path = output_root / "launcher.stderr"
                waiter = self._launch_product_app(
                    product_app,
                    stdout_path,
                    stderr_path,
                    "--bootstrap-check",
                )
                stdout, stderr = waiter.communicate(timeout=45)
                diagnostic = (
                    stderr_path.read_text(encoding="utf-8", errors="replace")
                    if stderr_path.exists()
                    else ""
                )
                self.assertEqual(
                    waiter.returncode,
                    0,
                    f"invalid-policy LaunchServices probe failed: "
                    f"{stdout!r} {stderr!r}; diagnostics={diagnostic!r}",
                )
                self.assertEqual(
                    stdout_path.read_text(encoding="utf-8").strip(),
                    "",
                    f"a rejected sandbox policy must not expose the Broker endpoint: "
                    f"{diagnostic!r}",
                )
                self.assertRegex(
                    diagnostic,
                    r"workspace-kernel-smoke=failed code=snapshot_broker_"
                    r"(?:connection_failed|timed_out)",
                )

            self._terminate_product_executable(broker_binary)
            shutil.copy2(probe_service, broker_binary)
            shutil.copy2(probe_client, product_launcher)
            sign_bundle(broker_bundle, broker_entitlements_path)
            sign_bundle(product_app, launcher_entitlements_path)
            self.assertEqual(
                self._designated_code_requirement(
                    broker_binary, "org.khaos.Seed.KernelSnapshotBroker"
                ),
                broker_requirement,
            )

            with tempfile.TemporaryDirectory(
                prefix="khaos-broker-sandbox-probe-"
            ) as value:
                output_root = Path(value)
                stdout_path = output_root / "launcher.stdout"
                stderr_path = output_root / "launcher.stderr"
                waiter = self._launch_product_app(
                    product_app,
                    stdout_path,
                    stderr_path,
                    str(read_canary),
                    str(alias_read_canary),
                    str(write_canary),
                    str(canary_root),
                    str(temporary_write_canary),
                    str(tmp_alias_executable),
                    str(private_temporary_write_canary),
                    str(tmp_alias_write_canary),
                    str(shared_executable),
                    package_executable,
                    package_alias_executable,
                    package_write_path,
                    package_alias_write_path,
                    str(kernel_binary),
                    str(os.getpid()),
                    str(port),
                )
                stdout, stderr = waiter.communicate(timeout=45)
                diagnostic = (
                    stderr_path.read_text(encoding="utf-8", errors="replace")
                    if stderr_path.exists()
                    else ""
                )
                self.assertEqual(
                    waiter.returncode,
                    0,
                    f"LaunchServices probe failed: {stdout!r} {stderr!r}; "
                    f"diagnostics={diagnostic!r}",
                )
                raw_result = stdout_path.read_text(encoding="utf-8").strip()
                self.assertTrue(
                    raw_result,
                    f"Broker sandbox probe returned no result; "
                    f"diagnostics={diagnostic!r}; "
                    f"launch_stdout={stdout!r}; launch_stderr={stderr!r}",
                )
                result = json.loads(raw_result)

            denied_errnos = {errno.EPERM, errno.EACCES}
            self.assertIn(result.get("external_read_errno"), denied_errnos, result)
            self.assertIn(result.get("external_alias_read_errno"), denied_errnos, result)
            self.assertIn(result.get("external_metadata_errno"), denied_errnos, result)
            self.assertIn(result.get("external_write_errno"), denied_errnos, result)
            self.assertIn(result.get("external_chmod_errno"), denied_errnos, result)
            self.assertIn(result.get("temporary_write_errno"), denied_errnos, result)
            self.assertIn(
                result.get("private_temporary_write_errno"), denied_errnos, result
            )
            self.assertIn(
                result.get("private_temporary_metadata_errno"), denied_errnos, result
            )
            self.assertIn(
                result.get("private_temporary_existence_errno"), denied_errnos, result
            )
            self.assertIn(result.get("tmp_alias_write_errno"), denied_errnos, result)
            self.assertIn(
                result.get("temporary_executable_spawn_errno"),
                denied_errnos,
                result,
            )
            self.assertIn(
                result.get("shared_root_executable_spawn_errno"),
                denied_errnos,
                result,
            )
            if package_executable:
                self.assertIn(
                    result.get("package_manager_executable_spawn_errno"),
                    denied_errnos,
                    result,
                )
                self.assertIn(
                    result.get("package_manager_write_errno"),
                    denied_errnos,
                    result,
                )
                self.assertFalse(
                    package_write_canary.exists(),
                    "XPC Broker wrote into a user-writable package-manager root",
                )
            if package_alias_executable:
                self.assertIn(
                    result.get("package_manager_alias_executable_spawn_errno"),
                    denied_errnos,
                    result,
                )
                self.assertIn(
                    result.get("package_manager_alias_write_errno"),
                    denied_errnos,
                    result,
                )
                self.assertFalse(
                    package_alias_write_canary.exists(),
                    "XPC Broker wrote through a package-manager firmlink alias",
                )
            self.assertIn(result.get("kernel_write_open_errno"), denied_errnos, result)
            self.assertIn(
                result.get("external_process_signal_zero_errno"), denied_errnos, result
            )
            self.assertEqual(result.get("same_sandbox_child_cancel_errno"), 0, result)
            self.assertIn(result.get("loopback_connect_errno"), denied_errnos, result)
            self.assertFalse(write_canary.exists(), "XPC Broker wrote outside its bundle")
            self.assertEqual(canary_root.stat().st_mode & 0o777, directory_mode)
            self.assertFalse(temporary_write_canary.exists())
            self.assertFalse(private_temporary_write_canary.exists())
            self.assertFalse(tmp_alias_write_canary.exists())
            listener.settimeout(0.2)
            with self.assertRaises(socket.timeout):
                listener.accept()
            self.assertEqual(
                hashlib.sha256(kernel_binary.read_bytes()).digest(), kernel_digest
            )
        finally:
            self._terminate_product_executable(broker_binary)
            self._terminate_product_executable(product_launcher)
            shutil.copy2(broker_backup, broker_binary)
            shutil.copy2(launcher_backup, product_launcher)
            sign_bundle(broker_bundle, broker_entitlements_path)
            sign_bundle(product_app, launcher_entitlements_path)
            signature = subprocess.run(
                ["codesign", "--verify", "--deep", "--strict", str(product_app)],
                check=False,
                capture_output=True,
                text=True,
                timeout=30,
            )
            self.assertEqual(signature.returncode, 0, signature.stderr)
            self.assertEqual(
                self._designated_code_requirement(
                    broker_binary, "org.khaos.Seed.KernelSnapshotBroker"
                ),
                broker_requirement,
            )

        self.assertFalse(write_canary.exists())
        self.assertEqual(hashlib.sha256(kernel_binary.read_bytes()).digest(), kernel_digest)
        listener.settimeout(0.2)
        with self.assertRaises(socket.timeout):
            listener.accept()

    @staticmethod
    def _signed_entitlements(bundle: Path) -> dict[str, object]:
        result = subprocess.run(
            ["codesign", "-d", "--entitlements", ":-", str(bundle)],
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise AssertionError(
                f"codesign could not read entitlements for {bundle}: {result.stderr}"
            )
        try:
            entitlements = plistlib.loads(result.stdout.encode("utf-8"))
        except plistlib.InvalidFileException as exc:
            raise AssertionError(
                f"codesign returned invalid entitlements for {bundle}"
            ) from exc
        if type(entitlements) is not dict:
            raise AssertionError(f"codesign returned no entitlement dictionary for {bundle}")
        return entitlements

    @staticmethod
    def _launch_product_app(
        product_app: Path,
        stdout_path: Path,
        stderr_path: Path,
        *arguments: str,
    ) -> subprocess.Popen[str]:
        return subprocess.Popen(
            [
                "/usr/bin/open",
                "-W",
                "-a",
                str(product_app),
                "--stdout",
                str(stdout_path),
                "--stderr",
                str(stderr_path),
                "--args",
                *arguments,
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

    def _assert_product_writeback_smoke(
        self,
        launcher: Path,
        product_app: Path,
        workspace: Path,
    ) -> None:
        acceptance_run_id = str(uuid.uuid4())
        fixture = workspace / "seed-picker-fixture.txt"
        fixture_contents = b"preserve this selected-workspace fixture\n"
        fixture.write_bytes(fixture_contents)
        fixture_digest = hashlib.sha256(fixture_contents).hexdigest()
        unscoped_fixture = workspace / "seed-picker-unscoped-fixture.txt"
        unscoped_fixture_contents = b"unscoped acceptance canary\n"
        unscoped_fixture.write_bytes(unscoped_fixture_contents)
        unscoped_fixture_digest = hashlib.sha256(unscoped_fixture_contents).hexdigest()
        print(
            "In the Khaos Seed Picker, press Command-Shift-G and enter this path; "
            "press Return, select the folder, and choose Open. Check that the "
            f"result alert shows acceptance run {acceptance_run_id}; dismiss it "
            "so the test can verify the workspace and signature:\n"
            f"{workspace}",
            flush=True,
        )

        with tempfile.TemporaryDirectory(prefix="khaos-seed-launch-") as value:
            diagnostic_path = Path(value) / "launcher.stderr"
            launch_started_at = time.strftime(
                "%Y-%m-%d %H:%M:%S", time.localtime()
            )
            process = self._launch_product_app(
                product_app,
                Path("/dev/null"),
                diagnostic_path,
                "--acceptance-workspace",
                str(workspace),
                "--acceptance-run-id",
                acceptance_run_id,
            )
            deadline = time.monotonic() + 300
            timed_out = False
            try:
                while process.poll() is None:
                    if time.monotonic() >= deadline:
                        timed_out = True
                        break
                    time.sleep(0.1)
            finally:
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=5)
                self._terminate_product_executable(launcher)

            open_stdout, open_stderr = process.communicate()
            diagnostic_output = (
                diagnostic_path.read_text(encoding="utf-8", errors="replace")
                if diagnostic_path.exists()
                else ""
            )

            def workspace_failure_context() -> str:
                entries = sorted(workspace.iterdir(), key=lambda item: item.name)
                metadata = [
                    (
                        item.name,
                        oct(item.lstat().st_mode & 0o170777),
                        item.lstat().st_size,
                        item.lstat().st_nlink,
                    )
                    for item in entries[:16]
                ]
                marker_count = sum(
                    item.name.startswith("khaos-seed-writeback-smoke-")
                    for item in entries
                )
                fixture_unchanged = (
                    fixture.exists()
                    and hashlib.sha256(fixture.read_bytes()).hexdigest()
                    == fixture_digest
                )
                unscoped_fixture_unchanged = (
                    unscoped_fixture.exists()
                    and hashlib.sha256(unscoped_fixture.read_bytes()).hexdigest()
                    == unscoped_fixture_digest
                )
                return (
                    f"entry_count={len(entries)}; marker_count={marker_count}; "
                    f"fixture_unchanged={fixture_unchanged}; "
                    f"unscoped_fixture_unchanged={unscoped_fixture_unchanged}; "
                    f"entry_metadata={metadata!r}; "
                    "executor_logs="
                    f"{self._product_executor_logs_since(launch_started_at)!r}; "
                    f"diagnostics={diagnostic_output!r}; "
                    f"launch_stdout={open_stdout!r}; launch_stderr={open_stderr!r}"
                )

            if timed_out or process.returncode != 0:
                result = (
                    "product writeback Picker did not complete within 300 seconds"
                    if timed_out
                    else f"LaunchServices open waiter exited {process.returncode}"
                )
                self.fail(f"{result}; {workspace_failure_context()}")
            try:
                self._assert_product_writeback_evidence(
                    diagnostic_output,
                    acceptance_run_id,
                )
            except AssertionError as exc:
                self.fail(
                    f"{exc}; LaunchServices open waiter exited {process.returncode}; "
                    f"{workspace_failure_context()}"
                )

        entries = list(workspace.iterdir())
        marker_files = [
            entry
            for entry in entries
            if entry.name.startswith("khaos-seed-writeback-smoke-")
        ]
        self.assertEqual(len(marker_files), 1, [entry.name for entry in entries])
        marker = marker_files[0]
        self.assertRegex(
            marker.name,
            r"^khaos-seed-writeback-smoke-[0-9a-f-]+\.txt$",
        )
        self.assertFalse(marker.is_symlink())
        self.assertTrue(marker.is_file())
        self.assertEqual(
            {entry.name for entry in entries},
            {fixture.name, unscoped_fixture.name, marker.name},
        )
        self.assertEqual(marker.read_text(encoding="utf-8"), "Khaos Seed Kernel writeback smoke")
        self.assertEqual(fixture.stat().st_nlink, 1)
        self.assertEqual(hashlib.sha256(fixture.read_bytes()).hexdigest(), fixture_digest)
        self.assertEqual(unscoped_fixture.stat().st_nlink, 1)
        self.assertEqual(
            hashlib.sha256(unscoped_fixture.read_bytes()).hexdigest(),
            unscoped_fixture_digest,
        )
        marker_info = marker.lstat()
        self.assertEqual(marker_info.st_nlink, 1)
        self.assertEqual(marker_info.st_mode & 0o777, 0o600)

        signature = subprocess.run(
            ["codesign", "--verify", "--deep", "--strict", str(product_app)],
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(signature.returncode, 0, signature.stderr)
        python_framework = (
            product_app
            / "Contents"
            / "XPCServices"
            / "KernelProduction.xpc"
            / "Contents"
            / "Frameworks"
            / "Python.framework"
        )
        self.assertFalse(
            list(python_framework.rglob("__pycache__")),
            "product writeback must not mutate the signed Python framework",
        )

    def _compile_agent_host_model_probe(self, scratch: Path) -> Path:
        swiftc = subprocess.run(
            ["xcrun", "--find", "swiftc"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        sdk = subprocess.run(
            ["xcrun", "--sdk", "macosx", "--show-sdk-path"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        probe = scratch / "AgentHostSandboxModelProbe"
        compiled = subprocess.run(
            [
                swiftc,
                "-sdk",
                sdk,
                "-target",
                f"{platform.machine()}-apple-macosx26.0",
                str(PROBE_SOURCES / "AgentHostSandboxModelProbe.swift"),
                "-o",
                str(probe),
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=60,
        )
        self.assertEqual(compiled.returncode, 0, compiled.stderr)
        return probe

    def _verify_agent_host_xpc_sandbox(
        self,
        *,
        product_app: Path,
        launcher_binary: Path,
        scratch: Path,
    ) -> None:
        canary = scratch / "agent-host-workspace-canary.txt"
        canary.write_text("parent can read and open for writing\n", encoding="utf-8")
        descriptor = os.open(canary, os.O_RDWR | os.O_CLOEXEC)
        os.close(descriptor)

        agent_run = subprocess.run(
            [str(launcher_binary), "--agent"],
            check=False,
            capture_output=True,
            text=True,
            input=f"CANARY_PATH={canary}\n/exit\n",
            timeout=180,
        )
        self.assertEqual(
            agent_run.returncode,
            0,
            agent_run.stdout + agent_run.stderr,
        )
        self.assertIn("read-denied=true write-denied=true", agent_run.stdout)
        self.assertEqual(canary.read_text(encoding="utf-8"), "parent can read and open for writing\n")
        signature = subprocess.run(
            ["codesign", "--verify", "--deep", "--strict", str(product_app)],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(signature.returncode, 0, signature.stderr)

    @staticmethod
    def _product_executor_logs_since(start_time: str) -> str:
        result = subprocess.run(
            [
                "/usr/bin/log",
                "show",
                "--start",
                start_time,
                "--style",
                "compact",
                "--predicate",
                'subsystem == "org.khaos.Seed.KernelProduction" '
                'AND category == "workspace-executor"',
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=20,
        )
        if result.returncode != 0:
            return f"log-show-exit={result.returncode}: {result.stderr[-2000:]}"
        return result.stdout[-12_000:]

    @staticmethod
    def _product_executable_process_ids(executable_path: Path) -> list[int]:
        if not executable_path.is_file():
            return []
        executable = str(executable_path.resolve(strict=True))
        listing = subprocess.run(
            ["/bin/ps", "-ww", "-axo", "pid=,command="],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
        if listing.returncode != 0:
            raise AssertionError(listing.stderr)
        process_ids = []
        for line in listing.stdout.splitlines():
            match = re.match(r"^\s*(\d+)\s+(.*)$", line)
            if not match:
                continue
            command = match.group(2).strip()
            if command == executable or command.startswith(f"{executable} "):
                process_ids.append(int(match.group(1)))
        return process_ids

    @classmethod
    def _terminate_product_executable(cls, executable_path: Path) -> None:
        process_ids = cls._product_executable_process_ids(executable_path)
        if not process_ids:
            return
        for process_id in process_ids:
            try:
                os.kill(process_id, signal.SIGTERM)
            except ProcessLookupError:
                pass
        deadline = time.monotonic() + 5
        while process_ids and time.monotonic() < deadline:
            time.sleep(0.05)
            process_ids = cls._product_executable_process_ids(executable_path)
        for process_id in process_ids:
            try:
                os.kill(process_id, signal.SIGKILL)
            except ProcessLookupError:
                pass

    def _assert_product_xpc_request_attacks(
        self,
        *,
        swiftc: str,
        sdk: str,
        launcher: Path,
        product_app: Path,
        product_bundle_id: str,
        product_requirement: str,
        signing_identity: str,
        signing_keychain: Path,
        verify_missing_broker: bool = False,
    ) -> None:
        driver = product_app.parent / "ProductXPCProbe"
        self._compile_workspace_grant_probe(swiftc, sdk, driver)
        entitlements = product_app.parent / "product-driver-entitlements.plist"
        self._write_plist(entitlements, self._signed_entitlements(product_app))
        shutil.copy2(driver, launcher)
        for target in (launcher, product_app):
            command = [
                "codesign",
                "--force",
                "--keychain",
                str(signing_keychain),
                "--sign",
                signing_identity,
                "--entitlements",
                str(entitlements),
            ]
            if target == launcher:
                command.extend(("--identifier", product_bundle_id))
            subprocess.run(
                [*command, str(target)],
                check=True,
                capture_output=True,
                text=True,
            )

        self.assertEqual(
            self._designated_code_requirement(launcher, product_bundle_id),
            product_requirement,
        )
        service_info_path = (
            product_app
            / "Contents"
            / "XPCServices"
            / "KernelProduction.xpc"
            / "Contents"
            / "Info.plist"
        )
        with service_info_path.open("rb") as stream:
            service_info = plistlib.load(stream)
        self.assertEqual(
            service_info.get("KhaosWorkspaceCallerRequirement"),
            product_requirement,
        )
        plugin_store = self._plugin_store_path_for_requirement(product_requirement)
        self.assertFalse(
            plugin_store.exists(),
            f"refusing to reuse Plugin state at {plugin_store}",
        )
        self.addCleanup(
            self._remove_plugin_store,
            plugin_store,
        )
        signature = subprocess.run(
            ["codesign", "--verify", "--deep", "--strict", str(product_app)],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(signature.returncode, 0, signature.stderr)
        authorized_launcher = subprocess.run(
            [
                "codesign",
                "--verify",
                f"-R={product_requirement}",
                str(launcher),
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(
            authorized_launcher.returncode,
            0,
            authorized_launcher.stderr,
        )

        bootstrap = subprocess.run(
            [str(launcher), product_bundle_id, "--production-bootstrap-check"],
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(
            bootstrap.returncode,
            0,
            bootstrap.stdout + bootstrap.stderr,
        )
        self.assertEqual(
            bootstrap.stdout.strip(),
            "production-xpc-bootstrap=authenticated\n"
            "production-xpc-runner-source-digest="
            "mismatch-rejected-before-bookmark\n"
            "production-xpc-json-duplicate-field="
            "exact-and-escaped-alias-rejected-before-bookmark\n"
            "production-xpc-json-nesting=over-limit-rejected\n"
            "production-xpc-workspace-scope="
            "malformed-and-over-budget-rejected-before-bookmark\n"
            "production-xpc-authority-fields="
            "approval-and-capability-claims-rejected-before-bookmark\n"
            "production-xpc-plugin-lifecycle="
            "admit-activate-stale-reject-rollback-persisted\n"
            "production-xpc-after-invalid-requests=responsive",
        )
        if verify_missing_broker:
            self._assert_product_xpc_missing_broker_rejected(
                launcher=launcher,
                product_bundle_id=product_bundle_id,
            )

    def _assert_product_xpc_missing_broker_rejected(
        self,
        *,
        launcher: Path,
        product_bundle_id: str,
    ) -> None:
        self.assertTrue(Path("/Users/Shared").is_dir())
        with tempfile.TemporaryDirectory(
            prefix="khaos-no-broker-canary-",
            dir="/Users/Shared",
        ) as value:
            canary_path = Path(value) / "runner-host-fallback.txt"
            subprocess.run(
                ["/usr/bin/touch", str(canary_path)],
                check=True,
                capture_output=True,
                text=True,
                timeout=10,
            )
            self.assertTrue(canary_path.is_file(), str(canary_path))
            canary_path.unlink()

            result = subprocess.run(
                [
                    str(launcher),
                    product_bundle_id,
                    "--production-missing-broker-check",
                    str(canary_path),
                ],
                check=False,
                capture_output=True,
                text=True,
                timeout=30,
            )
            output = result.stdout + result.stderr
            self.assertEqual(result.returncode, 0, output)
            self.assertEqual(
                result.stdout.strip(),
                "production-xpc-missing-broker=snapshot_broker_not_configured",
                output,
            )
            self.assertFalse(
                canary_path.exists(),
                "the Runner wrote its Host-fallback canary without a Broker",
            )

    def _build_sandboxed_app(
        self,
        root: Path,
        binary: Path,
        *,
        name: str,
        bundle_id: str,
        resources: dict[str, Path] | None = None,
    ) -> tuple[Path, Path]:
        app = root / f"{name}.app"
        contents = app / "Contents"
        executable = contents / "MacOS" / name
        executable.parent.mkdir(parents=True)
        shutil.copy2(binary, executable)
        if resources:
            resource_directory = contents / "Resources"
            for resource_name, source in resources.items():
                destination = resource_directory / resource_name
                if source.is_dir():
                    shutil.copytree(source, destination)
                else:
                    shutil.copy2(source, destination)
        self._write_plist(
            contents / "Info.plist",
            {
                "CFBundleIdentifier": bundle_id,
                "CFBundleExecutable": name,
                "CFBundleInfoDictionaryVersion": "6.0",
                "CFBundleName": name,
                "CFBundlePackageType": "APPL",
                "CFBundleVersion": "1",
            },
        )
        entitlements = root / f"{name}-entitlements.plist"
        self._write_plist(
            entitlements,
            {"com.apple.security.app-sandbox": True},
        )
        subprocess.run(
            [
                "codesign",
                "--force",
                "--sign",
                "-",
                "--entitlements",
                str(entitlements),
                str(app),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        signature = subprocess.run(
            ["codesign", "--verify", "--strict", str(app)],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(signature.returncode, 0, signature.stderr)
        self.assertIs(
            self._signed_entitlements(app).get("com.apple.security.app-sandbox"),
            True,
        )
        return app, executable

    @staticmethod
    def _write_plist(path: Path, values: dict[str, object]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("wb") as stream:
            plistlib.dump(values, stream)
