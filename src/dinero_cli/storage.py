"""Private local state with atomic replacement and cross-process serialization."""

import os
import stat
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from filelock import FileLock, Timeout

from dinero_cli.errors import CLIError


def check_private(path: Path, *, directory: bool = False) -> None:
    """Reject links, wrong owners/types and non-private POSIX state."""
    if path.is_symlink():
        raise CLIError("State paths must not be symbolic links.")
    info = path.stat()
    expected = stat.S_ISDIR if directory else stat.S_ISREG
    if not expected(info.st_mode):
        raise CLIError("State path has an unsupported file type.")
    if os.name != "nt" and (info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o077):
        raise CLIError("State permissions must be private: directory 0700, files 0600.")


def ensure_directory(directory: Path) -> None:
    """Create only application state; never repair permissions silently."""
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    check_private(directory, directory=True)


@contextmanager
def locked(directory: Path, *, timeout: float = 10) -> Iterator[None]:
    """Serialize config and credential transactions across processes on both platforms."""
    ensure_directory(directory)
    path = directory / "state.lock"
    if path.exists() or path.is_symlink():
        check_private(path)
    try:
        with FileLock(path, timeout=timeout, mode=0o600):
            yield
    except Timeout as error:
        raise CLIError("Local state is busy; retry after the other command finishes.") from error


def read_private(path: Path) -> bytes:
    """Read state only from the intended private directory and regular file."""
    check_private(path.parent, directory=True)
    check_private(path)
    return path.read_bytes()


def atomic_write(path: Path, content: bytes) -> None:
    """Replace a complete record only after flushing a private temporary file."""
    ensure_directory(path.parent)
    if path.exists() or path.is_symlink():
        check_private(path)
    descriptor, temporary = tempfile.mkstemp(prefix=".dinero-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        if os.name != "nt":
            directory_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
