import os
import sys
import tempfile
import threading
from pathlib import Path
from typing import Dict

if sys.platform == "win32":
    import msvcrt

    OPEN_MODE = os.O_RDWR | os.O_CREAT | os.O_TRUNC
else:
    import fcntl

    NON_BLOCKING = fcntl.LOCK_EX | fcntl.LOCK_NB
    BLOCKING = fcntl.LOCK_EX

_locks: Dict[str, "_ProcessLock"] = {}
_base_lock = threading.Lock()


def get_process_lock(lock_id: str) -> "_ProcessLock":
    with _base_lock:
        if lock_id not in _locks:
            if sys.platform == "win32":
                _locks[lock_id] = WindowsLock(lock_id)
            else:
                _locks[lock_id] = UnixLock(lock_id)
        return _locks[lock_id]


class _ProcessLock:
    def __init__(self, lock_id: str) -> None:
        self._lock = threading.Lock()
        self._lock_path = Path(tempfile.gettempdir()).joinpath(f".solcx-lock-{lock_id}")
        self._lock_file = self._lock_path.open("w")

    def acquire(self, blocking: bool) -> bool:
        raise NotImplementedError("Method not implemented by child class")

    def release(self) -> None:
        raise NotImplementedError("Method not implemented by child class")

    def wait(self) -> None:
        self.acquire(True)
        self.release()


class UnixLock(_ProcessLock):
    def acquire(self, blocking: bool) -> bool:
        if not self._lock.acquire(blocking):
            return False
        try:
            fcntl.flock(self._lock_file, BLOCKING if blocking else NON_BLOCKING)
        except BlockingIOError:
            self._lock.release()
            return False
        return True

    def release(self) -> None:
        fcntl.flock(self._lock_file, fcntl.LOCK_UN)
        self._lock.release()


class WindowsLock(_ProcessLock):
    def acquire(self, blocking: bool) -> bool:
        if not self._lock.acquire(blocking):
            return False
        while True:
            try:
                fd = os.open(self._lock_path, OPEN_MODE)  # type: ignore
                msvcrt.locking(  # type: ignore
                    fd, msvcrt.LK_LOCK if blocking else msvcrt.LK_NBLCK, 1  # type: ignore
                )
                self._fd = fd
                return True
            except OSError:
                if not blocking:
                    self._lock.release()
                    return False

    def release(self) -> None:
        msvcrt.locking(self._fd, msvcrt.LK_UNLCK, 1)  # type: ignore
        self._lock.release()
