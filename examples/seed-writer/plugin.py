from khaos.runner_sdk import fs_write, process_exec, workspace_commit


def run():
    fs_write("seed-plugin-output.txt", b"Khaos Seed plugin ran\n")
    result = process_exec(("/bin/bash", "-c", ":"))
    if result["returncode"] == 0:
        workspace_commit()
    return result["returncode"]
