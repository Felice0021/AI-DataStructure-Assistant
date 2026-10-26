"""Private local storage. No user filename is used in a filesystem operation."""
from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import re
import secrets
import stat
from typing import BinaryIO

from backend.v2.core.errors import AuthError


def storage_unavailable():
    return AuthError(503, "storage_unavailable", "File storage temporarily unavailable")


@dataclass(frozen=True)
class StoredFile:
    key: str
    size: int
    sha256: str
    mime: str


class LocalFileStorage:
    def __init__(self, root: Path):
        if not root.is_absolute() or ".." in root.parts:
            raise OSError("Invalid storage root")
        self.root = root

    @contextmanager
    def directory(self):
        # Walk anchored descriptors; reject symlinks in every component, including root.
        fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY)
        try:
            for part in self.root.parts[1:]:
                if part in {".", ".."}:
                    raise OSError("Invalid storage root")
                try:
                    os.mkdir(part, 0o700, dir_fd=fd)
                except FileExistsError:
                    pass
                child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                os.close(fd)
                fd = child
            info = os.fstat(fd)
            if info.st_uid != os.getuid() or info.st_mode & 0o077:
                raise OSError("Storage root must be private and owned by the service user")
            yield fd
        finally:
            os.close(fd)

    @staticmethod
    def check_key(key):
        if not re.fullmatch(r"[0-9a-f]{64}", key):
            raise OSError("Invalid storage key")

    def save(self, source: BinaryIO, limit: int, filename: str, declared_type: str) -> StoredFile:
        from backend.v2.services.file_validation import detect_file
        key, temporary = secrets.token_hex(32), "." + secrets.token_hex(32) + ".tmp"
        with self.directory() as directory:
            published = False
            try:
                fd = os.open(temporary, os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=directory)
                with os.fdopen(fd, "w+b") as target:
                    digest, size = hashlib.sha256(), 0
                    while chunk := source.read(64 * 1024):
                        size += len(chunk)
                        if size > limit:
                            raise AuthError(413, "file_too_large", "File exceeds upload limit")
                        digest.update(chunk)
                        target.write(chunk)
                    if not size:
                        raise AuthError(422, "invalid_file", "File must not be empty")
                    target.flush()
                    target.seek(0)
                    mime = detect_file(target, filename, declared_type)
                    os.fsync(target.fileno())
                os.rename(temporary, key, src_dir_fd=directory, dst_dir_fd=directory)
                published = True
                os.fsync(directory)
                return StoredFile(key, size, digest.hexdigest(), mime)
            except BaseException:
                for name in (key,) if published else (temporary,):
                    try:
                        os.unlink(name, dir_fd=directory)
                    except FileNotFoundError:
                        pass
                raise

    def open(self, key: str, expected_size: int):
        self.check_key(key)
        with self.directory() as directory:
            fd = os.open(key, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077 or info.st_size != expected_size:
                raise OSError("Invalid stored object")
            return os.fdopen(fd, "rb")
        except BaseException:
            os.close(fd)
            raise

    def remove(self, key: str):
        self.check_key(key)
        with self.directory() as directory:
            try:
                os.unlink(key, dir_fd=directory)  # unlink does not follow a replaced symlink
            except FileNotFoundError:
                pass
            os.fsync(directory)
