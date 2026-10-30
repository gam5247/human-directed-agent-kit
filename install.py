#!/usr/bin/env python3
"""Install only this kit's skills; optionally append a managed AGENTS block."""
import argparse
from pathlib import Path

BEGIN = '<!-- BEGIN human-directed-agent-kit -->'
END = '<!-- END human-directed-agent-kit -->'
SKILLS = ('decision-brief', 'scoped-build', 'explain-implementation')


def inside(root, path):
    resolved = path.resolve()
    if not resolved.is_relative_to(root):
        raise ValueError(f'Path leaves the target project: {path}')
    if path.is_symlink():
        raise ValueError(f'Refusing a symlink target: {path}')
    return path


def agents_content(existing, guidance):
    newline = '\r\n' if '\r\n' in existing else '\n'
    block = BEGIN + '\n' + guidance.rstrip() + '\n' + END
    block = block.replace('\n', newline)
    if BEGIN not in existing and END not in existing:
        gap = '' if not existing else (newline if existing.endswith(newline) else newline * 2)
        return existing + gap + block + newline
    if existing.count(BEGIN) != 1 or existing.count(END) != 1:
        raise ValueError('Malformed or duplicate kit markers in AGENTS.md')
    start, finish = existing.index(BEGIN), existing.index(END)
    if finish < start:
        raise ValueError('Reversed kit markers in AGENTS.md')
    return existing[:start] + block + existing[finish + len(END):]


def plan_install(target, with_agents):
    root = target.resolve(strict=True)
    if not root.is_dir():
        raise ValueError('Target must be an existing project directory')
    source = Path(__file__).resolve().parent
    changes = []
    for name in SKILLS:
        path = inside(root, root / '.agents' / 'skills' / name / 'SKILL.md')
        data = (source / '.agents' / 'skills' / name / 'SKILL.md').read_bytes()
        if path.exists():
            if path.read_bytes() != data:
                raise ValueError(f'Existing skill differs; review manually: {path}')
        else:
            changes.append((path, data))
    if with_agents:
        if (root / 'AGENTS.override.md').exists():
            raise ValueError('AGENTS.override.md exists; keep it and follow project guidance manually')
        path = inside(root, root / 'AGENTS.md')
        old = path.read_bytes() if path.exists() else b''
        # utf-8 retains an existing BOM and all unrelated bytes/newlines.
        text = old.decode('utf-8')
        guide = (source / 'AGENTS.md').read_text(encoding='utf-8')
        new = agents_content(text, guide).encode('utf-8')
        if old != new:
            changes.append((path, new))
    return changes


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--target', required=True, type=Path)
    parser.add_argument('--with-agents', action='store_true', help='Append kit guidance; keep existing instructions')
    parser.add_argument('--dry-run', action='store_true', help='Show changes without writing')
    args = parser.parse_args()
    try:
        changes = plan_install(args.target, args.with_agents)
        for path, data in changes:
            print(('WOULD WRITE ' if args.dry_run else 'WRITE ') + str(path))
            if not args.dry_run:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(data)
        if not changes:
            print('UNCHANGED: kit already installed')
    except (ValueError, OSError, UnicodeError) as exc:
        parser.exit(1, f'Installation stopped: {exc}\n')


if __name__ == '__main__':
    main()
