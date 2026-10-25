"""Stand-ins for ffmpeg/arecord and Feishu so tests never touch real devices or the network."""
import os
import sys
import tempfile
import textwrap

FAKE_FFMPEG = textwrap.dedent(r'''
    import os, sys, time
    fd = int(sys.argv[1])
    exit_after = float(sys.argv[2]) if len(sys.argv) > 2 else 0
    jpeg = b"\xff\xd8" + b"\x00" * 500 + b"\xff\xd9"
    t0 = time.time(); i = 0
    while True:
        sys.stdout.buffer.write(jpeg); sys.stdout.buffer.flush()
        if i % 10 == 0:
            os.write(fd, bytes([(i * 7) % 256]) * (64 * 36))
        i += 1
        time.sleep(0.1)
        if exit_after and time.time() - t0 > exit_after:
            sys.exit(3)
''')

# 0.5 s loud, 1 s silence, repeated; 16 kHz s16le mono
FAKE_ARECORD = textwrap.dedent(r'''
    import sys, time, struct
    loud = struct.pack("<h", 12000) * 8000 + struct.pack("<h", -12000) * 0
    loud = b"".join(struct.pack("<h", 12000 if (i // 20) % 2 else -12000) for i in range(8000))
    quiet = b"\x00\x00" * 16000
    while True:
        for chunk in (loud, quiet):
            for j in range(0, len(chunk), 1024):
                sys.stdout.buffer.write(chunk[j:j+1024]); sys.stdout.buffer.flush()
                time.sleep(0.032 / 4)
''')


def write_script(body: str) -> str:
    fd, path = tempfile.mkstemp(suffix=".py")
    with os.fdopen(fd, "w") as f:
        f.write(body)
    return path


class FakeNotifier:
    configured = True

    def __init__(self):
        self.messages = []
        self.sent = 0
        self.last_error = None

    def start(self):
        pass

    def send(self, text):
        self.messages.append(text)
        self.sent += 1


def pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    # a zombie still answers kill(0); treat it as gone
    try:
        with open(f"/proc/{pid}/stat") as f:
            return f.read().split(")")[-1].split()[0] != "Z"
    except OSError:
        return False


PY = sys.executable
