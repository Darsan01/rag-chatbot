"""Fixed Ollama starter: plain subprocess, no asyncio recursion bug.

What was wrong in the original:
- pipe() called asyncio.gather(pipe(stdout), pipe(stderr)) INSIDE
  itself, after its loop finished - so every finished pipe spawned
  two more pipes, forever.
- The thread was non-daemon and never joined, and the Ollama
  process was never stopped on exit.
- is_port_open() only caught ConnectionRefusedError.
"""
import socket
import subprocess
import threading


def run_ollama_server():
    """Start `ollama serve` in a daemon thread. Returns the process."""
    process = subprocess.Popen(
        ["ollama", "serve"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )

    def _drain():
        assert process.stdout is not None
        for line in process.stdout:
            print(line.rstrip())

    thread = threading.Thread(target=_drain, daemon=True)
    thread.start()
    return process


def is_port_open(port: int, host: str = "localhost") -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(1)
        try:
            s.connect((host, port))
            return True
        except OSError:
            return False
