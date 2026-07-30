from __future__ import annotations

from pathlib import Path


def save_env_values(env_path: Path, values: dict[str, str], *, keep_blank: bool = True) -> None:
    env_path.parent.mkdir(parents=True, exist_ok=True)
    existing = env_path.read_text(encoding="utf-8").splitlines() if env_path.exists() else []
    remaining = dict(values)
    output: list[str] = []

    for line in existing:
        key = env_key(line)
        if key and key in remaining:
            value = remaining.pop(key)
            if value or keep_blank:
                output.append(f"{key}={quote_env_value(value)}")
            else:
                output.append(line)
        else:
            output.append(line)

    if remaining:
        if output and output[-1].strip():
            output.append("")
        for key, value in remaining.items():
            if value or keep_blank:
                output.append(f"{key}={quote_env_value(value)}")

    env_path.write_text("\n".join(output).rstrip() + "\n", encoding="utf-8")


def env_key(line: str) -> str:
    stripped = line.strip()
    if not stripped or stripped.startswith("#") or "=" not in stripped:
        return ""
    key = stripped.split("=", 1)[0].strip()
    return key if key.replace("_", "").isalnum() else ""


def quote_env_value(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if any(char.isspace() for char in text) or "#" in text:
        return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return text
