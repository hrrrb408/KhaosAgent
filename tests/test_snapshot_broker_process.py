from __future__ import annotations

from pathlib import Path
import platform
import signal
import subprocess
import sys
import tempfile
import time
import unittest


ROOT = Path(__file__).resolve().parents[1]
MACOS_TCB = ROOT / "khaos" / "macos"
PROBE = ROOT / "tests" / "macos_xpc_probe" / "KernelSnapshotBrokerToolRunnerProbe.swift"


@unittest.skipUnless(sys.platform == "darwin", "macOS process groups are required")
class SnapshotBrokerToolProcessTests(unittest.TestCase):
    def test_exit_cancellation_and_timeout_kill_only_the_tool_process_group(self) -> None:
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
        target = f"{platform.machine()}-apple-macosx{platform.mac_ver()[0]}"

        with tempfile.TemporaryDirectory(prefix="khaos-broker-tool-") as value:
            root = Path(value)
            executable = root / "KernelSnapshotBrokerToolRunnerProbe"
            compiled = subprocess.run(
                [
                    swiftc,
                    "-sdk",
                    sdk,
                    "-target",
                    target,
                    "-parse-as-library",
                    str(MACOS_TCB / "KernelCStringArray.swift"),
                    str(MACOS_TCB / "KernelSnapshotBrokerToolRunner.swift"),
                    str(PROBE),
                    "-o",
                    str(executable),
                ],
                check=False,
                capture_output=True,
                text=True,
                timeout=60,
            )
            self.assertEqual(compiled.returncode, 0, compiled.stderr)

            inventory = subprocess.run(
                [str(executable), "inventory", str(root / "unused")],
                check=False,
                capture_output=True,
                text=True,
                timeout=15,
            )
            self.assertEqual(inventory.returncode, 0, inventory.stderr)
            self.assertRegex(
                inventory.stdout.strip(),
                r"^broker-tool-inventory=valid-plist bytes=[1-9][0-9]*$",
            )

            unrelated = subprocess.Popen(
                ["/bin/sleep", "60"],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            try:
                expected_results = {
                    "orphaned": "broker-tool-process-group=orphaned-child-stopped",
                    "cancelled": "broker-tool-process-group=cancelled",
                    "timed-out": "broker-tool-process-group=timed-out",
                    "wait-error": "broker-tool-process-group=wait-error-child-stopped",
                }
                for mode, expected_result in expected_results.items():
                    with self.subTest(mode=mode):
                        pid_file = root / f"{mode}.pid"
                        result = subprocess.run(
                            [str(executable), mode, str(pid_file)],
                            check=False,
                            capture_output=True,
                            text=True,
                            timeout=10,
                        )
                        self.assertEqual(result.returncode, 0, result.stderr)
                        self.assertEqual(
                            result.stdout.strip(),
                            expected_result,
                        )
                        self.assertTrue(pid_file.is_file())
                        child_pid = int(pid_file.read_text(encoding="ascii"))
                        self.assertTrue(
                            self._wait_until_process_stops(child_pid),
                            f"tool descendant {child_pid} survived {mode}",
                        )
                        self.assertIsNone(
                            unrelated.poll(),
                            "terminating the Broker tool group killed an unrelated process",
                        )
            finally:
                if unrelated.poll() is None:
                    unrelated.send_signal(signal.SIGTERM)
                    try:
                        unrelated.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        unrelated.kill()
                        unrelated.wait(timeout=3)

    @staticmethod
    def _wait_until_process_stops(process_id: int) -> bool:
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            status = subprocess.run(
                ["/bin/ps", "-o", "stat=", "-p", str(process_id)],
                check=False,
                capture_output=True,
                text=True,
                timeout=2,
            ).stdout.strip()
            if not status or status.startswith("Z"):
                return True
            time.sleep(0.02)
        return False


if __name__ == "__main__":
    unittest.main()
