"""Turn draft citations [R:A1] into [1], [2], … in order of first appearance, and append the cited references.

Card P6 (refactoring plan v6, paper rule 5). Drafts cite with the P6 list IDs behind an "R:" prefix,
e.g. [R:D1] or [R:A1, R:B3]; brackets without that prefix ([[N01]], [B1], [1]) are left alone, and so
is anything inside a fenced code block. References that are never cited are left out of the list.

Run from the repository root:
  python scripts/paper/renumber_refs.py                     # every paper/*.md except references.md
  python scripts/paper/renumber_refs.py paper/blind.md --out-dir paper/build
Each draft is written to <out-dir>/<same name>, with the reference list under "## 참고문헌".
An unknown or malformed citation stops the run with every offending one listed.
"""
import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_REFS = ROOT / "paper" / "references.md"
DEFAULT_OUT = ROOT / "paper" / "build"
HEADING = "## 참고문헌"

ENTRY = re.compile(r"^\[([A-Z]+\d+)\]\s+(.+)$")
COMMENT = re.compile(r"<!--.*?-->")
GROUP = re.compile(r"\[R:[^\]]*\]")                 # any bracket that starts with "R:"
ITEM = re.compile(r"^R:([A-Z]+\d+)$")
FENCE = re.compile(r"^\s*(```|~~~)")


def parse_references(text):
    """{id: entry} in file order. Only lines "[ID] text" count; <!-- notes --> are removed."""
    refs = {}
    for line in text.splitlines():
        m = ENTRY.match(COMMENT.sub("", line).strip())
        if m:
            if m.group(1) in refs:
                raise ValueError(f"duplicate reference id {m.group(1)}")
            refs[m.group(1)] = m.group(2).strip()
    return refs


def _ids(group):
    """IDs of one "[R:…]" group, or None if it is malformed."""
    ids = []
    for part in group[1:-1].split(","):
        m = ITEM.match(part.strip())
        if not m:
            return None
        ids.append(m.group(1))
    return ids


def renumber(text, refs):
    """(text with [n] citations, cited IDs in order of first appearance)."""
    numbers = {}
    problems = []

    def replace(match):
        ids = _ids(match.group(0))
        if ids is None:
            problems.append(f"malformed citation {match.group(0)}")
            return match.group(0)
        unknown = [i for i in ids if i not in refs]
        if unknown:
            problems.append(f"unknown reference {', '.join(unknown)} in {match.group(0)}")
            return match.group(0)
        for i in ids:
            numbers.setdefault(i, len(numbers) + 1)
        return "[" + ", ".join(str(n) for n in sorted({numbers[i] for i in ids})) + "]"

    out = []
    in_fence = False
    for line in text.splitlines(keepends=True):
        if FENCE.match(line):
            in_fence = not in_fence
            out.append(line)
        elif in_fence:
            out.append(line)
        else:
            out.append(GROUP.sub(replace, line))
    if problems:
        raise ValueError("; ".join(problems))
    return "".join(out), list(numbers)


def reference_list(cited, refs):
    return "\n".join(f"[{n}] {refs[i]}" for n, i in enumerate(cited, start=1))


def build(draft_text, refs):
    body, cited = renumber(draft_text, refs)
    if not cited:
        return body
    return body.rstrip("\n") + f"\n\n{HEADING}\n\n" + reference_list(cited, refs) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("drafts", nargs="*", type=Path, help="draft files (default: paper/*.md except references.md)")
    ap.add_argument("--refs", type=Path, default=DEFAULT_REFS)
    ap.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    args = ap.parse_args(argv)

    refs = parse_references(args.refs.read_text(encoding="utf-8"))
    drafts = args.drafts or sorted(p for p in (ROOT / "paper").glob("*.md") if p.resolve() != args.refs.resolve())
    if not drafts:
        print("no drafts found", file=sys.stderr)
        return 1
    args.out_dir.mkdir(parents=True, exist_ok=True)
    failed = False
    for draft in drafts:
        try:
            text = build(draft.read_text(encoding="utf-8"), refs)
        except ValueError as e:
            print(f"{draft}: {e}", file=sys.stderr)
            failed = True
            continue
        target = args.out_dir / draft.name
        target.write_text(text, encoding="utf-8")
        print(f"{draft} -> {target}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
