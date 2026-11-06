"""Versioned JSON persistence with backups, diff previews and atomic replacement."""

from contextlib import contextmanager
import difflib
import json
import os
from pathlib import Path
import tempfile
import uuid

from .catalog import digest_bytes, is_link, load_json, read_limited, MAX_JSON_BYTES


def json_bytes(data) -> bytes:
    return (json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")


def ensure_plain_path(path: Path):
    for part in (path, *path.parents):
        if is_link(part):
            raise ValueError(f"写入路径不能经过符号链接或目录联接：{part}")


def read_json_versioned(path):
    data = read_limited(Path(path), MAX_JSON_BYTES)
    return json.loads(data.decode("utf-8-sig")), digest_bytes(data)


def preview_json(path, data) -> str:
    path = Path(path)
    before = read_limited(path, MAX_JSON_BYTES).decode("utf-8-sig") if path.exists() else ""
    after = json_bytes(data).decode("utf-8")
    return "".join(difflib.unified_diff(before.splitlines(True), after.splitlines(True), fromfile=str(path), tofile=str(path) + " (proposed)")) or "无内容变化\n"


@contextmanager
def exclusive_destination(path: Path):
    ensure_plain_path(path)
    lock = path.with_name(f".{path.name}.workflow-lock")
    try:
        descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as exc:
        raise ValueError(f"文件正在被操作，或留有中断的锁文件：{lock}") from exc
    try:
        os.close(descriptor)
        yield
    finally:
        lock.unlink(missing_ok=True)


def save_json(path, data, *, expected_digest: str | None) -> str:
    """None means create-only. Existing files require the digest observed by the caller."""
    path = Path(path).expanduser().absolute()
    payload = json_bytes(data)
    if len(payload) > MAX_JSON_BYTES:
        raise ValueError("JSON 文件过大")
    ensure_plain_path(path)
    if not path.parent.is_dir():
        raise ValueError(f"目标父目录不存在：{path.parent}")
    with exclusive_destination(path):
        previous = read_limited(path, MAX_JSON_BYTES) if path.exists() else None
        actual = digest_bytes(previous) if previous is not None else None
        if actual != expected_digest:
            raise ValueError("文件已在其他位置修改或目标已存在，请重新载入后再保存")
        if previous == payload:
            return actual
        if previous is not None:
            backup_dir = path.parent / ".workflow-backups"
            ensure_plain_path(backup_dir)
            backup_dir.mkdir(exist_ok=True)
            backup = backup_dir / f"{path.name}.{uuid.uuid4().hex}.json"
            with backup.open("xb") as stream:
                stream.write(previous)
        descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            json.loads(Path(temporary).read_text(encoding="utf-8"))
            os.replace(temporary, path)
            if path.read_bytes() != payload:
                raise OSError("原子写入后校验失败")
        finally:
            Path(temporary).unlink(missing_ok=True)
    return digest_bytes(payload)
