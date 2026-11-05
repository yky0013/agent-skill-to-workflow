"""Read-only skill discovery and reconciliation with an earlier audit atlas."""

from dataclasses import asdict, dataclass, field
import hashlib
import json
import os
from pathlib import Path
import re
from urllib.parse import unquote

import yaml

MAX_SOURCE_BYTES = 2 * 1024 * 1024
MAX_JSON_BYTES = 32 * 1024 * 1024
EXCLUDED = {".git", "node_modules", ".venv", "venv", "__pycache__", "target", "dist", ".tox"}


@dataclass
class Issue:
    severity: str
    code: str
    message: str
    path: str = ""
    line: int | None = None


@dataclass
class Skill:
    id: str
    path: str
    name: str
    description: str = ""
    sha256: str = ""
    issues: list[Issue] = field(default_factory=list)
    historical: dict = field(default_factory=dict)
    evidence_matches: bool | None = None
    enabled: bool | None = None
    references: list[dict] = field(default_factory=list)
    captured_at: str = ""


@dataclass
class Catalog:
    skills: list[Skill] = field(default_factory=list)
    issues: list[Issue] = field(default_factory=list)

    def to_dict(self):
        return {"schemaVersion": 1, **asdict(self)}


def digest_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read_limited(path: Path, limit: int) -> bytes:
    with path.open("rb") as stream:
        data = stream.read(limit + 1)
    if len(data) > limit:
        raise ValueError(f"文件超过 {limit} 字节限制：{path}")
    return data


def load_json(path: str | Path):
    return json.loads(read_limited(Path(path), MAX_JSON_BYTES).decode("utf-8-sig"))


def is_link(path: Path) -> bool:
    return path.is_symlink() or (hasattr(path, "is_junction") and path.is_junction())


def inspect_skill(path: str | Path) -> Skill:
    path = Path(path).expanduser().absolute()
    key = os.path.normcase(str(path.resolve()))
    skill = Skill(digest_bytes(key.encode("utf-8"))[:16], str(path), path.parent.name)
    try:
        data = read_limited(path, MAX_SOURCE_BYTES)
        text = data.decode("utf-8-sig")
        skill.sha256 = digest_bytes(data)
    except (OSError, ValueError, UnicodeError) as exc:
        skill.issues.append(Issue("error", "unreadable", str(exc), str(path)))
        return skill
    lines = text.splitlines()
    body_start = 0
    try:
        if not lines or lines[0].strip() != "---":
            raise ValueError("缺少 YAML frontmatter")
        end = next(i for i in range(1, len(lines)) if lines[i].strip() == "---")
        metadata = yaml.safe_load("\n".join(lines[1:end]))
        if not isinstance(metadata, dict):
            raise ValueError("frontmatter 必须是映射")
        for key in ("name", "description"):
            if not isinstance(metadata.get(key), str) or not metadata[key].strip():
                raise ValueError(f"frontmatter 缺少有效字符串：{key}")
        skill.name = metadata["name"].strip()
        skill.description = metadata["description"].strip()
        body_start = end + 1
    except (ValueError, StopIteration, yaml.YAMLError, RecursionError) as exc:
        skill.issues.append(Issue("error", "frontmatter", f"无效技能元数据：{exc}", str(path), 1))
    # Only explicit Markdown links are checked; mentions are not inferred as calls.
    fenced = False
    for number, line in enumerate(lines[body_start:], body_start + 1):
        if line.lstrip().startswith(("```", "~~~")):
            fenced = not fenced
            continue
        if fenced:
            continue
        for match in re.finditer(r"\[[^\]\n]*\]\((<[^>]+>|[^)\n]+)\)", line):
            target = match.group(1).strip()
            target = target[1:-1] if target.startswith("<") else target.split(' "', 1)[0]
            if not target or target.startswith("#") or re.match(r"^[a-zA-Z][\w+.-]+://|^(mailto|data|skill|plugin):", target):
                continue
            if any(token in target for token in ("*", "{", "}", "$")):
                continue
            target = unquote(target.split("#", 1)[0].split("?", 1)[0])
            candidate = Path(target)
            if not candidate.is_absolute():
                candidate = path.parent / candidate
            try:
                exists = candidate.exists()
            except OSError:
                exists = False
            if not exists:
                skill.issues.append(Issue("warning", "missing_resource", f"未找到链接资源：{target}", str(path), number))
    return skill


def _mark_duplicates(catalog: Catalog) -> Catalog:
    names: dict[str, list[Skill]] = {}
    for skill in catalog.skills:
        names.setdefault(skill.name.casefold(), []).append(skill)
    for matches in names.values():
        if len(matches) > 1:
            for skill in matches:
                skill.issues.append(Issue("warning", "duplicate_name", f"存在 {len(matches)} 个同名入口，请按路径区分", skill.path))
    catalog.skills.sort(key=lambda s: (s.name.casefold(), s.path))
    return catalog


def scan_roots(roots) -> Catalog:
    catalog = Catalog()
    seen = set()
    for root in roots:
        root = Path(root).expanduser().absolute()
        if not root.is_dir():
            catalog.issues.append(Issue("error", "missing_root", f"技能根目录不存在：{root}", str(root)))
            continue
        def onerror(exc):
            catalog.issues.append(Issue("warning", "scan_error", str(exc), str(root)))
        for directory, dirs, files in os.walk(root, followlinks=False, onerror=onerror):
            dirs[:] = sorted(d for d in dirs if d not in EXCLUDED and not is_link(Path(directory) / d))
            for name in sorted(files):
                if name.casefold() != "skill.md":
                    continue
                path = Path(directory) / name
                if is_link(path):
                    catalog.issues.append(Issue("warning", "linked_source", "跳过链接文件", str(path)))
                    continue
                skill = inspect_skill(path)
                if skill.id not in seen:
                    catalog.skills.append(skill)
                    seen.add(skill.id)
    return _mark_duplicates(catalog)


def import_atlas(path: str | Path) -> Catalog:
    atlas = load_json(path)
    if not isinstance(atlas, dict) or type(atlas.get("schemaVersion")) is not int or atlas["schemaVersion"] != 1 or not isinstance(atlas.get("skills"), list):
        raise ValueError("不支持的 atlas 格式，需要 schemaVersion=1 和 skills 数组")
    catalog = Catalog()
    seen = set()
    for record in atlas["skills"]:
        if not isinstance(record, dict) or not isinstance(record.get("path"), str) or not Path(record["path"]).is_absolute():
            raise ValueError("atlas 每个技能必须包含本机绝对 path")
        skill = inspect_skill(record["path"])
        if skill.id in seen:
            continue
        seen.add(skill.id)
        historical = record.get("historical")
        skill.historical = historical.copy() if isinstance(historical, dict) else {}
        skill.enabled = record.get("enabled") if isinstance(record.get("enabled"), bool) else None
        skill.captured_at = str(atlas.get("capturedAt", ""))
        skill.evidence_matches = bool(skill.sha256 and skill.sha256 == record.get("sha256"))
        if skill.evidence_matches:
            refs = record.get("references", [])
            skill.references = [r.copy() for r in refs if isinstance(r, dict)] if isinstance(refs, list) else []
        else:
            skill.issues.append(Issue("warning", "source_changed", "源文件与筛查快照不同或未找到；历史证据不可用于当前验证", skill.path))
        if skill.enabled is False:
            skill.issues.append(Issue("warning", "disabled_snapshot", "筛查快照记录此入口为禁用；需核实后重新扫描再选择", skill.path))
        catalog.skills.append(skill)
    return _mark_duplicates(catalog)
