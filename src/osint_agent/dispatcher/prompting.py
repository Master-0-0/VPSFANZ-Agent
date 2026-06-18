import os
from pathlib import Path
from typing import Dict, Optional


def _get_prompts_dir() -> Path:
    return Path(__file__).parent / "prompts"


def list_prompt_groups() -> list:
    prompts_dir = _get_prompts_dir()
    groups = set()
    for f in prompts_dir.iterdir():
        if f.is_dir():
            groups.add(f.name)
    return sorted(groups)


def load_prompt(template_name: str, group: str = "default") -> Optional[str]:
    prompts_dir = _get_prompts_dir()
    candidates = [
        prompts_dir / group / template_name,
        prompts_dir / template_name,
    ]
    for path in candidates:
        if path.exists():
            with open(path, encoding="utf-8") as f:
                return f.read()
    return None


def render_prompt(template: str, variables: Dict[str, str]) -> str:
    result = template
    for key, value in variables.items():
        placeholder = "{%s}" % key
        result = result.replace(placeholder, str(value))
    return result


def get_prompt(task_type: str, variables: Dict[str, str], group: str = "default") -> Optional[str]:
    filenames = {
        "bootstrap": "bootstrap.md",
        "reason": "reason.md",
        "explore": "explore.md",
    }
    filename = filenames.get(task_type)
    if not filename:
        return None
    template = load_prompt(filename, group)
    if template is None:
        return None
    return render_prompt(template, variables)
