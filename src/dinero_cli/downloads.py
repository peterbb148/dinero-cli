"""Atomic, no-clobber publication of downloaded documents on Windows and Linux."""

import os
import tempfile
from pathlib import Path
from types import TracebackType
from typing import BinaryIO
from urllib.parse import quote, quote_plus

from dinero_cli.errors import CLIError


class DownloadFile:
    """Keep incomplete bytes private and publish only after a complete successful response."""

    def __init__(self, output: Path) -> None:
        self.output = output
        self.temporary: Path | None = None
        self.stream: BinaryIO | None = None
        self.size = 0
        self.secrets: tuple[bytes, ...] = ()
        self.tail = b""
        self.overlap = 0

    def __enter__(self) -> "DownloadFile":
        """Validate the explicit destination and create a private sibling temporary file."""
        if str(self.output) == "-":
            raise CLIError("Download requires a destination file; stdout is not supported.")
        if self.output.exists() or self.output.is_symlink():
            raise CLIError("Download destination already exists; choose a new file.")
        try:
            descriptor, filename = tempfile.mkstemp(
                prefix=".dinero-download-", dir=self.output.parent
            )
            self.temporary = Path(filename)
            try:
                self.stream = os.fdopen(descriptor, "wb")
            except OSError:
                os.close(descriptor)
                self.temporary.unlink()
                raise
        except OSError as error:
            raise CLIError(
                "Unable to create the download file; check its parent directory.", code=5
            ) from error
        return self

    def set_secrets(self, secrets: tuple[str, ...]) -> None:
        """Detect raw and URL-encoded active credentials even across stream chunk boundaries."""
        self.secrets = tuple(
            variant.encode("utf-8")
            for secret in secrets
            if secret
            for variant in (secret, quote(secret, safe=""), quote_plus(secret))
        )
        self.overlap = max((len(value) for value in self.secrets), default=1) - 1

    def write(self, chunk: bytes) -> None:
        """Preserve bytes, refusing responses that echo the active credentials."""
        sample = self.tail + chunk
        if any(secret in sample for secret in self.secrets):
            raise CLIError("Download contains credential data and cannot be saved.", code=5)
        self.tail = sample[-self.overlap :] if self.overlap else b""
        assert self.stream is not None
        try:
            self.stream.write(chunk)
        except OSError as error:
            raise CLIError("Unable to write the download file.", code=5) from error
        self.size += len(chunk)

    def publish(self) -> dict[str, str | int]:
        """Atomically link the complete file without clobbering a concurrent destination."""
        assert self.stream is not None and self.temporary is not None
        try:
            self.stream.flush()
            os.fsync(self.stream.fileno())
            self.stream.close()
        except OSError as error:
            raise CLIError("Unable to finalize the download file.", code=5) from error
        try:
            # A hard link publishes a complete sibling file and atomically refuses an
            # existing target. Filesystems without hard links fail; never copy/overwrite.
            os.link(self.temporary, self.output)
        except FileExistsError as error:
            raise CLIError("Download destination already exists; choose a new file.") from error
        except OSError as error:
            raise CLIError(
                "Unable to publish download; check directory permissions and hard-link support.",
                code=5,
            ) from error
        return {"path": str(self.output), "bytes": self.size}

    def __exit__(
        self,
        kind: type[BaseException] | None,
        value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Remove temporary bytes after success, API failure, local failure or interruption."""
        try:
            if self.stream is not None:
                self.stream.close()
        finally:
            if self.temporary is not None:
                self.temporary.unlink(missing_ok=True)
