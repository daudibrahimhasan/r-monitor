from __future__ import annotations

import re
from pathlib import Path
from typing import Any


_BOOLS = {"true": True, "false": False, "yes": True, "no": False, "on": True, "off": False}
_NULLS = {"null": None, "none": None, "~": None}


def load_simple_yaml(path: Path) -> dict[str, Any]:
    """
    Minimal YAML loader (subset) to avoid external deps.

    Supports:
    - key: value mappings
    - nested mappings via indentation
    - lists using "- item"
    - strings (quoted/unquoted), ints, floats, bools, null

    Not a full YAML parser.
    """
    lines = path.read_text(encoding="utf-8").splitlines()
    # Strip comments (but keep indentation).
    processed: list[tuple[int, str]] = []
    for raw in lines:
        if not raw.strip():
            continue
        if raw.lstrip().startswith("#"):
            continue
        # Remove inline comment if preceded by whitespace.
        line = re.sub(r"\s+#.*$", "", raw).rstrip()
        if not line.strip():
            continue
        indent = len(line) - len(line.lstrip(" "))
        processed.append((indent, line.lstrip(" ")))

    root: dict[str, Any] = {}
    stack: list[tuple[int, Any]] = [(0, root)]

    def parse_scalar(token: str) -> Any:
        t = token.strip()
        if (t.startswith('"') and t.endswith('"')) or (t.startswith("'") and t.endswith("'")):
            return t[1:-1]
        low = t.lower()
        if low in _BOOLS:
            return _BOOLS[low]
        if low in _NULLS:
            return None
        if re.fullmatch(r"-?\d+", t):
            try:
                return int(t)
            except Exception:
                return t
        if re.fullmatch(r"-?\d+\.\d+", t):
            try:
                return float(t)
            except Exception:
                return t
        return t

    i = 0
    while i < len(processed):
        indent, content = processed[i]
        while stack and indent < stack[-1][0]:
            stack.pop()
        if not stack:
            raise ValueError("Invalid indentation in YAML")

        parent = stack[-1][1]

        if content.startswith("- "):
            item_value = parse_scalar(content[2:])
            if not isinstance(parent, list):
                raise ValueError("List item without list parent")
            parent.append(item_value)
            i += 1
            continue

        if ":" not in content:
            raise ValueError(f"Unsupported YAML line: {content}")

        key, rest = content.split(":", 1)
        key = key.strip()
        rest = rest.strip()

        if isinstance(parent, list):
            raise ValueError("Mapping entry inside list without object support")
        if not isinstance(parent, dict):
            raise ValueError("Invalid YAML structure")

        if rest == "":
            # Determine whether this becomes dict or list by lookahead.
            next_container: Any = {}
            if i + 1 < len(processed):
                next_indent, next_content = processed[i + 1]
                if next_indent > indent and next_content.startswith("- "):
                    next_container = []
            parent[key] = next_container
            stack.append((indent + 1, next_container))
        else:
            parent[key] = parse_scalar(rest)

        i += 1

    return root
