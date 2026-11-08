import subprocess
import sys
import time

from mediaforge.core import procctl


def _state(pid):
    with open(f"/proc/{pid}/stat") as f:
        return f.read().rsplit(")", 1)[1].split()[0]


def test_suspend_and_resume_a_real_process():
    p = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        time.sleep(0.3)
        assert procctl.suspend(p.pid) is True
        if sys.platform.startswith("linux"):
            time.sleep(0.2)
            assert _state(p.pid) == "T"          # stopped
        assert procctl.resume(p.pid) is True
        if sys.platform.startswith("linux"):
            time.sleep(0.2)
            assert _state(p.pid) in ("S", "R")   # running again
    finally:
        p.kill()
        p.wait()


def test_bad_pids_return_false():
    assert procctl.suspend(0) is False and procctl.resume(-5) is False
    assert procctl.suspend(2_000_000_000) is False
