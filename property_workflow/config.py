from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


def _strip_line_comment(line: str, marker: str) -> str:
    cleaned: list[str] = []
    in_single = False
    in_double = False
    escaped = False
    i = 0
    length = len(line)
    while i < length:
        char = line[i]
        if in_double:
            cleaned.append(char)
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_double = False
            i += 1
            continue
        if in_single:
            cleaned.append(char)
            if char == "'" and i + 1 < length and line[i + 1] == "'":
                cleaned.append("'")
                i += 2
                continue
            if char == "'":
                in_single = False
            i += 1
            continue
        if marker == "//" and char == "/" and i + 1 < length and line[i + 1] == "/":
            break
        if marker == "#" and char == "#":
            break
        if char == '"':
            in_double = True
        elif char == "'":
            in_single = True
        cleaned.append(char)
        i += 1
    return "".join(cleaned).rstrip()


def _strip_jsonc_line_comments(raw_text: str) -> str:
    return "\n".join(_strip_line_comment(line, "//") for line in raw_text.splitlines())


def _strip_yaml_comments(raw_text: str) -> str:
    return "\n".join(_strip_line_comment(line, "#") for line in raw_text.splitlines())


def _parse_scalar(value: str) -> Any:
    if value == "":
        return ""
    if value == "{}":
        return {}
    if value == "[]":
        return []
    if value in {"null", "~"}:
        return None
    lower = value.lower()
    if lower == "true":
        return True
    if lower == "false":
        return False
    if re.fullmatch(r"-?\d+", value):
        return int(value)
    if re.fullmatch(r"-?\d+\.\d+", value):
        return float(value)
    if value.startswith('"') and value.endswith('"'):
        return json.loads(value)
    if value.startswith("'") and value.endswith("'"):
        return value[1:-1].replace("''", "'")
    return value


def _split_key_value(line: str) -> tuple[str, str | None]:
    in_single = False
    in_double = False
    escaped = False
    for index, char in enumerate(line):
        if in_double:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_double = False
            continue
        if in_single:
            if char == "'" and index + 1 < len(line) and line[index + 1] == "'":
                continue
            if char == "'":
                in_single = False
            continue
        if char == '"':
            in_double = True
            continue
        if char == "'":
            in_single = True
            continue
        if char == ":":
            return line[:index].strip(), line[index + 1 :].strip()
    return line.strip(), None


def _indent_of(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def _parse_simple_yaml_text(raw_text: str) -> dict[str, Any]:
    lines = [
        _strip_yaml_comments(line)
        for line in raw_text.splitlines()
    ]
    lines = [line for line in lines if line.strip()]

    def parse_block(index: int, indent: int) -> tuple[Any, int]:
        if index >= len(lines):
            return {}, index
        current_indent = _indent_of(lines[index])
        if current_indent < indent:
            return {}, index
        if lines[index].lstrip().startswith("- "):
            items: list[Any] = []
            while index < len(lines):
                line = lines[index]
                line_indent = _indent_of(line)
                if line_indent < indent:
                    break
                if line_indent != indent:
                    raise ValueError(f"配置文件缩进错误: {line}")
                stripped = line[indent:]
                if not stripped.startswith("- "):
                    break
                item_text = stripped[2:].strip()
                index += 1
                if not item_text:
                    if index >= len(lines) or _indent_of(lines[index]) <= indent:
                        items.append(None)
                    else:
                        child, index = parse_block(index, _indent_of(lines[index]))
                        items.append(child)
                    continue
                key, value = _split_key_value(item_text)
                if value is None:
                    items.append(_parse_scalar(item_text))
                    continue
                item: dict[str, Any] = {key: _parse_scalar(value)}
                if index < len(lines) and _indent_of(lines[index]) > indent:
                    child, index = parse_block(index, _indent_of(lines[index]))
                    if isinstance(child, dict):
                        item.update(child)
                    else:
                        item[key] = child
                items.append(item)
            return items, index

        mapping: dict[str, Any] = {}
        while index < len(lines):
            line = lines[index]
            line_indent = _indent_of(line)
            if line_indent < indent:
                break
            if line_indent != indent:
                raise ValueError(f"配置文件缩进错误: {line}")
            stripped = line[indent:]
            if stripped.startswith("- "):
                break
            key, value = _split_key_value(stripped)
            if value is None:
                raise ValueError(f"配置文件缺少值: {line}")
            index += 1
            if value == "":
                if index >= len(lines) or _indent_of(lines[index]) <= indent:
                    mapping[key] = {}
                else:
                    child, index = parse_block(index, _indent_of(lines[index]))
                    mapping[key] = child
            else:
                mapping[key] = _parse_scalar(value)
        return mapping, index

    parsed, consumed = parse_block(0, 0)
    if consumed != len(lines):
        remaining = lines[consumed] if consumed < len(lines) else "<eof>"
        raise ValueError(f"配置文件无法完全解析: {remaining}")
    if not isinstance(parsed, dict):
        raise ValueError("配置文件顶层必须是映射")
    return parsed


def _resolve_config_path(path: Path) -> Path:
    if path.exists():
        return path
    candidates: list[Path] = []
    if path.suffix.lower() == ".yaml":
        candidates.append(path.with_suffix(".yml"))
    elif path.suffix.lower() == ".yml":
        candidates.append(path.with_suffix(".yaml"))
    else:
        candidates.extend([path.with_suffix(".yml"), path.with_suffix(".yaml")])
    for candidate in candidates:
        if candidate.exists():
            return candidate
    raise FileNotFoundError(f"配置文件不存在: {path}")


def _load_with_yaml(path: Path) -> dict[str, Any]:
    import yaml  # type: ignore

    with path.open("r", encoding="utf-8-sig") as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict):
        raise ValueError(f"配置文件格式错误: {path}")
    return data


def _load_with_simple_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8-sig") as f:
        return _parse_simple_yaml_text(f.read())


def _load_with_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8-sig") as f:
        raw_text = f.read()
    data = json.loads(_strip_jsonc_line_comments(raw_text))
    if not isinstance(data, dict):
        raise ValueError(f"配置文件格式错误: {path}")
    return data


def load_config(path: str | Path) -> dict[str, Any]:
    config_path = _resolve_config_path(Path(path))
    yaml_failure: Exception | None = None
    try:
        return _load_with_yaml(config_path)
    except ModuleNotFoundError:
        pass
    except Exception as yaml_error:
        yaml_failure = yaml_error
    try:
        return _load_with_simple_yaml(config_path)
    except Exception as simple_yaml_error:
        try:
            return _load_with_json(config_path)
        except Exception:
            if yaml_failure is not None:
                raise yaml_failure
            raise simple_yaml_error


def resolve_base_path(
    config: dict[str, Any],
    key: str,
    default: str | Path,
    *,
    anchor: str | Path | None = None,
) -> Path:
    base_paths = config.get("base_paths")
    raw_value = ""
    if isinstance(base_paths, dict):
        raw_value = str(base_paths.get(key, "")).strip()
    candidate = Path(raw_value or default)
    if candidate.is_absolute():
        return candidate.resolve()
    base_anchor = Path(anchor) if anchor is not None else Path.cwd()
    return (base_anchor / candidate).resolve()
