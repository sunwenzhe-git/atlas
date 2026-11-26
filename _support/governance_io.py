"""Safe project paths and atomic generation publication for RFC-20261125-01.

Writes never edit legacy assets. A generation is completed under a temporary
sibling directory and exposed by one temp+rename manifest pointer update.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
from pathlib import Path, PurePosixPath

from _support.governance_schema import canonical_bytes, canonical_digest

_DIGEST = re.compile(r"^[0-9a-f]{64}$")


class GovernancePathError(ValueError):
    """A path is unsafe or resolves outside the project."""


def safe_path(root: str | Path, rel: str | Path) -> Path:
    """Resolve a project-relative path, rejecting traversal and every symlink.

    Both lexical validation and resolved containment are required: lexical
    checks catch portable path spellings, containment catches links in any
    parent component. Missing leaf paths are allowed for future writes.
    """
    if not isinstance(rel, (str, Path)) or not str(rel):
        raise GovernancePathError("路径必须是非空项目相对路径")
    text = str(rel).replace("\\", "/")
    pure = PurePosixPath(text)
    if pure.is_absolute() or re.match(r"^[A-Za-z]:", text) or text.startswith("//"):
        raise GovernancePathError(f"拒绝绝对路径：{rel}")
    if any(part == ".." for part in pure.parts):
        raise GovernancePathError(f"拒绝路径逃逸：{rel}")
    base = Path(root).absolute()
    if base.is_symlink():
        raise GovernancePathError(f"项目根不得为符号链接：{base}")
    resolved_root = base.resolve()
    candidate = base.joinpath(*pure.parts)
    current = base
    for part in pure.parts:
        current = current / part
        if current.is_symlink():
            raise GovernancePathError(f"拒绝符号链接路径：{rel}")
    try:
        resolved = candidate.resolve()
    except (OSError, RuntimeError) as exc:
        raise GovernancePathError(f"路径无法解析：{rel}: {exc}") from exc
    if not resolved.is_relative_to(resolved_root):
        raise GovernancePathError(f"路径逃逸项目根：{rel}")
    return candidate


def atomic_write_bytes(path: str | Path, data: bytes) -> None:
    """Write bytes via fsync + temp file + same-directory atomic rename."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp",
                                     dir=str(target.parent))
    temp = Path(temporary)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, target)
    finally:
        if temp.exists():
            temp.unlink()


def atomic_write_json(path: str | Path, value) -> None:
    atomic_write_bytes(path, canonical_bytes(value) + b"\n")


def load_json(path: str | Path) -> dict:
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"JSON 重复键：{key}")
            result[key] = value
        return result

    return json.loads(Path(path).read_text(encoding="utf-8"), object_pairs_hook=unique)


class GenerationStore:
    """Publish immutable migration generations and atomically switch pointers."""

    def __init__(self, root: str | Path):
        self.root = Path(root).absolute()
        self.base = safe_path(self.root, ".adapter-out/migration")
        self.generations = safe_path(self.root, ".adapter-out/migration/generations")
        self.pointer_path = safe_path(self.root, ".adapter-out/migration/manifest.json")

    def read_pointer(self) -> dict:
        return load_json(self.pointer_path)

    def verify_generation(self, pointer: dict) -> dict[str, object]:
        if not isinstance(pointer, dict):
            raise ValueError("代际 pointer 必须为对象")
        generation = pointer.get("generation")
        if not isinstance(generation, str) or not _DIGEST.fullmatch(generation) \
                or pointer.get("business_digest") != generation \
                or pointer.get("path") != f"generations/{generation}":
            raise ValueError("代际 pointer generation/path 非法")
        files = pointer.get("files")
        if not isinstance(files, dict) or not files:
            raise ValueError("代际 pointer files 清单缺失")
        directory = safe_path(self.root, f".adapter-out/migration/generations/{generation}")
        if not directory.is_dir() or directory.is_symlink():
            raise FileNotFoundError(f"代际目录不存在或不是普通目录：{generation}")
        entries = list(directory.iterdir())
        if {entry.name for entry in entries} != set(files) \
                or any(not entry.is_file() or entry.is_symlink() for entry in entries):
            raise ValueError("代际目录文件清单不完整或含非普通文件")
        artifacts = {}
        for name, expected in files.items():
            path = safe_path(self.root, f".adapter-out/migration/generations/{generation}/{name}")
            raw = path.read_bytes()
            if hashlib.sha256(raw).hexdigest() != expected:
                raise ValueError(f"代际产物哈希不符：{name}")
            artifacts[name] = json.loads(raw.decode("utf-8"))
        if canonical_digest(artifacts) != generation:
            raise ValueError("代际 canonical digest 与 generation 不符")
        return artifacts

    def _previous(self, generation: str, mode: str) -> tuple[str | None, dict | None]:
        if not self.pointer_path.exists():
            return None, None
        current = self.read_pointer()
        old = current.get("generation")
        if old == generation and current.get("mode", "enforce") == mode:
            return current.get("previous_generation"), current.get("previous_pointer")
        return old, current

    def publish(self, business_digest: str, artifacts: dict[str, object], mode: str = "enforce") -> dict:
        if not _DIGEST.fullmatch(business_digest):
            raise ValueError("business_digest 必须为 64 位小写 SHA-256")
        if mode not in ("shadow", "enforce", "off"):
            raise ValueError("mode 必须为 shadow/enforce/off")
        if any(not name or Path(name).name != name or "\\" in name for name in artifacts):
            raise ValueError("代际产物名必须是普通文件名")
        if canonical_digest(artifacts) != business_digest:
            raise ValueError("business_digest 必须等于 artifacts canonical digest")
        payload = {name: canonical_bytes(value) + b"\n" for name, value in artifacts.items()}
        if self.pointer_path.exists():
            self.verify_generation(self.read_pointer())
        self.generations.mkdir(parents=True, exist_ok=True)
        final = safe_path(self.root, f".adapter-out/migration/generations/{business_digest}")
        if final.exists():
            if not final.is_dir() or final.is_symlink():
                raise GovernancePathError(f"代际路径不是普通目录：{final}")
            entries = list(final.iterdir())
            if {entry.name for entry in entries} != set(payload) \
                    or any(not entry.is_file() or entry.is_symlink() for entry in entries):
                raise GovernancePathError(f"代际目录含额外或非普通文件，拒绝覆盖 last-known-good：{final}")
            damaged = False
            for name, expected in payload.items():
                path = safe_path(self.root, f".adapter-out/migration/generations/{business_digest}/{name}")
                if not path.is_file() or path.is_symlink() or path.read_bytes() != expected:
                    damaged = True
                    break
            if damaged:
                raise GovernancePathError(f"代际内容损坏，拒绝替换 last-known-good：{final}")
        else:
            temporary = Path(tempfile.mkdtemp(prefix=f".{business_digest}.", dir=str(self.generations)))
            try:
                for name, data in payload.items():
                    atomic_write_bytes(temporary / name, data)
                os.rename(temporary, final)
            finally:
                if temporary.exists():
                    for child in temporary.iterdir():
                        child.unlink()
                    temporary.rmdir()
        previous_generation, previous_pointer = self._previous(business_digest, mode)
        manifest = {
            "schema_version": 1,
            "module": "migration",
            "mode": mode,
            "generation": business_digest,
            "business_digest": business_digest,
            "path": f"generations/{business_digest}",
            "previous_generation": previous_generation,
            "previous_pointer": previous_pointer,
            "files": {name: __import__("hashlib").sha256(data).hexdigest()
                      for name, data in sorted(payload.items())},
        }
        # Pointer is the commit point. Any failure leaves the previous pointer.
        atomic_write_json(self.pointer_path, manifest)
        return manifest

    def rollback(self) -> dict:
        """Only switch the pointer to its predecessor; never delete generations."""
        current = self.read_pointer()
        if not isinstance(current, dict):
            raise ValueError("当前 migration pointer 必须为对象")
        previous = current.get("previous_generation")
        if not previous:
            raise ValueError("没有可回滚的上一代")
        if not _DIGEST.fullmatch(str(previous)):
            raise ValueError("previous_generation 非法")
        directory = safe_path(self.root, f".adapter-out/migration/generations/{previous}")
        if not directory.is_dir() or directory.is_symlink():
            raise FileNotFoundError(f"上一代不存在或不是普通目录：{previous}")
        restored = current.get("previous_pointer")
        if not isinstance(restored, dict) or restored.get("generation") != previous \
                or restored.get("business_digest") != previous \
                or restored.get("path") != f"generations/{previous}":
            raise ValueError("previous_pointer 与上一代不一致")
        bound_files = restored.get("files")
        if not isinstance(bound_files, dict) or not bound_files:
            raise ValueError("previous_pointer 缺完整文件清单")
        entries = list(directory.iterdir())
        if {entry.name for entry in entries} != set(bound_files) \
                or any(not entry.is_file() or entry.is_symlink() for entry in entries):
            raise ValueError("上一代文件清单不完整或含非普通文件条目")
        artifacts = {}
        for name, expected in bound_files.items():
            path = safe_path(self.root, f".adapter-out/migration/generations/{previous}/{name}")
            if not path.is_file() or path.is_symlink() or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
                raise ValueError(f"上一代产物校验失败：{name}")
            artifacts[name] = json.loads(path.read_text(encoding="utf-8"))
        if canonical_digest(artifacts) != previous:
            raise ValueError("上一代 canonical digest 与 generation 不符")
        atomic_write_json(self.pointer_path, restored)
        return restored
