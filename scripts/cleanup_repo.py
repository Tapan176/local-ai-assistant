"""
Repository cleanup automation for TAPAN_AI.

Usage:
  python scripts/cleanup_repo.py --apply
  python scripts/cleanup_repo.py            # dry-run
"""
from __future__ import annotations

import argparse
import shutil
from pathlib import Path
from typing import Iterable, List


ROOT = Path(__file__).resolve().parents[1]


def _move(path: Path, target: Path, apply: bool, ops: List[str]) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    ops.append(f"MOVE {path} -> {target}")
    if apply:
        if target.exists():
            stem = target.stem
            suffix = target.suffix
            idx = 1
            while target.exists():
                target = target.with_name(f"{stem}_{idx}{suffix}")
                idx += 1
        shutil.move(str(path), str(target))


def _delete(path: Path, apply: bool, ops: List[str]) -> None:
    ops.append(f"DELETE {path}")
    if not apply:
        return
    if path.is_dir():
        shutil.rmtree(path, ignore_errors=True)
    elif path.exists():
        path.unlink()


def move_docs(root: Path, apply: bool, ops: List[str]) -> None:
    docs_dir = root / "docs"
    docs_dir.mkdir(exist_ok=True)
    candidates: List[Path] = []

    candidates.extend([p for p in root.glob("*.pdf") if p.is_file()])
    candidates.extend([p for p in root.glob("tapan_ai_report*.md") if p.is_file()])
    candidates.extend([p for p in root.glob("*phase*report*.md") if p.is_file()])
    candidates.extend([p for p in root.glob("*deep*research*.md") if p.is_file()])
    candidates.extend([p for p in root.glob("*deep*research*.txt") if p.is_file()])

    for path in sorted(set(candidates)):
        if path.parent == docs_dir:
            continue
        _move(path, docs_dir / path.name, apply, ops)


def keep_only_runtime_src(root: Path, apply: bool, ops: List[str]) -> None:
    src_dir = root / "src"
    if not src_dir.exists():
        return
    allowed = {"agent", "tools", "core", "memory", "tests", "__init__.py"}
    quarantine = root / "backup" / "cleanup_quarantine" / "src"
    quarantine.mkdir(parents=True, exist_ok=True)

    for item in src_dir.iterdir():
        if item.name in allowed:
            continue
        _move(item, quarantine / item.name, apply, ops)


def delete_clutter(root: Path, apply: bool, ops: List[str]) -> None:
    # Directories
    for name in ("experiments", "notebooks", "old_prompts", "prompts_old"):
        path = root / name
        if path.exists():
            _delete(path, apply, ops)

    # Files
    for pattern in ("*.ipynb", "*old_prompt*.md", "*deprecated_prompt*.md"):
        for path in root.rglob(pattern):
            if ".venv" in path.parts or ".git" in path.parts:
                continue
            _delete(path, apply, ops)

    # Duplicate tests (common naming patterns)
    for pattern in ("*copy*.py", "*duplicate*.py", "*_old.py", "*_backup.py"):
        for path in (root / "tests").rglob(pattern) if (root / "tests").exists() else []:
            _delete(path, apply, ops)


def _tree_lines(path: Path, prefix: str = "", max_depth: int = 3, depth: int = 0) -> List[str]:
    if depth > max_depth or not path.exists():
        return []
    lines: List[str] = []
    children = sorted(path.iterdir(), key=lambda p: (p.is_file(), p.name.lower()))
    for idx, child in enumerate(children):
        branch = "└── " if idx == len(children) - 1 else "├── "
        lines.append(f"{prefix}{branch}{child.name}")
        if child.is_dir():
            ext = "    " if idx == len(children) - 1 else "│   "
            lines.extend(_tree_lines(child, prefix + ext, max_depth, depth + 1))
    return lines


def generate_clean_tree(root: Path, apply: bool, ops: List[str]) -> Path:
    docs_dir = root / "docs"
    docs_dir.mkdir(exist_ok=True)
    tree_path = docs_dir / "CLEAN_TREE.txt"
    lines = [root.name]
    lines.extend(_tree_lines(root, max_depth=3))
    ops.append(f"WRITE {tree_path}")
    if apply:
        tree_path.write_text("\n".join(lines), encoding="utf-8")
    else:
        # Dry-run still writes to make inspection easier.
        tree_path.write_text("\n".join(lines), encoding="utf-8")
    return tree_path


def main() -> None:
    parser = argparse.ArgumentParser(description="TAPAN_AI cleanup automation")
    parser.add_argument("--apply", action="store_true", help="Apply changes (default is dry-run)")
    args = parser.parse_args()

    ops: List[str] = []
    apply = bool(args.apply)

    move_docs(ROOT, apply, ops)
    keep_only_runtime_src(ROOT, apply, ops)
    delete_clutter(ROOT, apply, ops)
    tree_path = generate_clean_tree(ROOT, apply, ops)

    mode = "APPLY" if apply else "DRY-RUN"
    print(f"[{mode}] cleanup operations: {len(ops)}")
    for op in ops:
        print(op)
    print(f"CLEAN TREE: {tree_path}")


if __name__ == "__main__":
    main()
