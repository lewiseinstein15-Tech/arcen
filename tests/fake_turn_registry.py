"""Deterministic in-memory fake for server pipeline tests; never executes commands."""
import time


class FakeTurnRegistry:
    supports_host_diff = False

    def __init__(self):
        self.calls = []
        self.closed = False

    def dispatch(self, name, args):
        self.calls.append((name, args))
        cmd = args.get("cmd", "")
        if cmd.startswith("sleep "):
            time.sleep(0.6)
        if cmd.startswith("exit "):
            code = int(cmd.split()[1])
            return {"ok": False, "error": f"exit {code}: ", "result": {"exit": code}}
        if name != "bash":
            return {"ok": False, "error": "unsupported in fake", "result": None}
        return {"ok": True, "error": None,
                "result": {"stdout": cmd[5:] + "\n" if cmd.startswith("echo ") else "",
                           "stderr": "", "exit": 0}}

    def close(self):
        self.closed = True
