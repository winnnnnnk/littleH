"""Local standard-library adapters."""

from __future__ import annotations

import hashlib
import os
import shutil
import stat
import subprocess
import tempfile
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Iterable, Iterator, Mapping, Optional, Sequence

from ..ports.protocols import ProcessResult

if os.name == "nt":
    import msvcrt
else:
    import fcntl


class LocalFileSystem:
    """Filesystem effects with atomic file writes and explicit paths."""

    def exists(self, path: Path) -> bool:
        return path.exists()

    def is_file(self, path: Path) -> bool:
        return path.is_file()

    def is_dir(self, path: Path) -> bool:
        return path.is_dir()

    def is_symlink(self, path: Path) -> bool:
        return path.is_symlink()

    def resolve(self, path: Path, strict: bool = False) -> Path:
        return path.expanduser().resolve(strict=strict)

    def read_bytes(self, path: Path) -> bytes:
        return path.read_bytes()

    def read_text(self, path: Path) -> str:
        return path.read_text(encoding="utf-8")

    def write_bytes_atomic(self, path: Path, content: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{path.name}.", dir=str(path.parent)
        )
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            if path.exists():
                temporary.chmod(path.stat().st_mode)
            os.replace(str(temporary), str(path))
        finally:
            temporary.unlink(missing_ok=True)

    def write_text_atomic(self, path: Path, content: str) -> None:
        self.write_bytes_atomic(path, content.encode("utf-8"))

    def mkdir(self, path: Path) -> None:
        path.mkdir(parents=True, exist_ok=True)

    def remove(self, path: Path) -> None:
        if path.is_symlink() or path.is_file():
            path.unlink(missing_ok=True)
        elif path.is_dir():
            shutil.rmtree(path)

    def copy(self, source: Path, target: Path) -> None:
        target.parent.mkdir(parents=True, exist_ok=True)
        if source.is_dir():
            shutil.copytree(
                source,
                target,
                dirs_exist_ok=True,
                ignore=_ignored_generated_files,
            )
        else:
            shutil.copy2(source, target)

    def replace(self, source: Path, target: Path) -> None:
        target.parent.mkdir(parents=True, exist_ok=True)
        os.replace(str(source), str(target))

    def iter_files(self, root: Path) -> Iterable[Path]:
        if not root.is_dir():
            return ()
        return tuple(
            path
            for path in root.rglob("*")
            if path.is_file()
            and "__pycache__" not in path.parts
            and path.name != ".DS_Store"
            and path.suffix not in {".pyc", ".pyo"}
        )

    def iter_children(self, root: Path) -> Iterable[Path]:
        if not root.is_dir():
            return ()
        return tuple(root.iterdir())

    def size(self, path: Path) -> int:
        if path.is_file():
            return path.stat().st_size
        return sum(item.stat().st_size for item in self.iter_files(path))

    def digest(self, path: Path) -> Optional[str]:
        if not path.exists() and not path.is_symlink():
            return None
        digest = hashlib.sha256()
        if path.is_file():
            digest.update(path.read_bytes().replace(b"\r\n", b"\n"))
            return digest.hexdigest()
        if path.is_dir():
            for item in sorted(self.iter_files(path), key=lambda value: value.relative_to(path).as_posix()):
                digest.update(item.relative_to(path).as_posix().encode("utf-8"))
                digest.update(b"\0")
                digest.update(item.read_bytes().replace(b"\r\n", b"\n"))
                digest.update(b"\0")
            return digest.hexdigest()
        return None

    def free_bytes(self, path: Path) -> int:
        existing = path
        while not existing.exists() and existing != existing.parent:
            existing = existing.parent
        return shutil.disk_usage(existing).free

    def chmod_executable(self, path: Path) -> None:
        path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

    @contextmanager
    def lock(self, path: Path) -> Iterator[None]:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a+b") as stream:
            if stream.tell() == 0:
                stream.write(b"\0")
                stream.flush()
            stream.seek(0)
            if os.name == "nt":
                msvcrt.locking(stream.fileno(), msvcrt.LK_LOCK, 1)
            else:
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                stream.seek(0)
                if os.name == "nt":
                    msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


class SystemClock:
    def now(self) -> datetime:
        return datetime.now().astimezone()


def _ignored_generated_files(directory: str, names: list[str]) -> set[str]:
    return {
        name
        for name in names
        if name in {"__pycache__", ".DS_Store"}
        or name.endswith((".pyc", ".pyo"))
    }


class SubprocessRunner:
    def run(
        self,
        command: Sequence[str],
        env: Optional[Mapping[str, str]] = None,
        cwd: Optional[Path] = None,
    ) -> ProcessResult:
        completed = subprocess.run(
            list(command),
            env=dict(env) if env is not None else None,
            cwd=str(cwd) if cwd is not None else None,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        return ProcessResult(completed.returncode, completed.stdout, completed.stderr)
