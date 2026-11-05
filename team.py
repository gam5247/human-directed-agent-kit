#!/usr/bin/env python3
"""Local task/result mailbox for independent CLI sessions. No agent launcher."""
import argparse
import json
from pathlib import Path, PurePosixPath
import sqlite3
import time
import uuid


def connect(root):
    folder = Path(root).resolve() / '.agent-team'
    if folder.is_symlink():
        raise ValueError('Refusing a symlink mailbox directory')
    folder.mkdir(exist_ok=True)
    try:
        with (folder / '.gitignore').open('x', encoding='utf-8') as handle:
            handle.write('*\n')
    except FileExistsError:
        pass
    path = folder / 'queue.sqlite3'
    if path.is_symlink():
        raise ValueError('Refusing a symlink database')
    db = sqlite3.connect(str(path), timeout=10)
    db.row_factory = sqlite3.Row
    db.execute('CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY, worker TEXT NOT NULL, task TEXT NOT NULL, scope TEXT NOT NULL, status TEXT NOT NULL, token TEXT, result TEXT)')
    db.execute('CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)')
    db.commit()
    return db


def dispatch(db, worker, task, scope):
    raw = [p.strip().replace('\\', '/') for p in scope.split(',') if p.strip()]
    if not raw or any(p.startswith('/') or '..' in p.split('/') or ':' in p or any(c in p for c in '*?[]') for p in raw):
        raise ValueError('Use explicit project-relative file/directory scopes')
    paths = [str(PurePosixPath(p)) for p in raw]
    if any(p == '.' or p.split('/')[0] in ('.git', '.agent-team', '.codex') for p in paths):
        raise ValueError('Do not assign the project root or coordination/configuration paths')
    db.execute('BEGIN IMMEDIATE')
    try:
        if db.execute("SELECT 1 FROM settings WHERE key='stopped' AND value='1'").fetchone():
            raise ValueError('Team is stopped; initialize before dispatch')
        for row in db.execute("SELECT worker,scope FROM jobs WHERE status IN ('queued','running')"):
            for old in json.loads(row['scope']):
                old = old.casefold()
                if any(p.casefold() == old or p.casefold().startswith(old + '/') or old.startswith(p.casefold() + '/') for p in paths):
                    raise ValueError(f'Active scope overlap with {row["worker"]}: {old}')
        job = uuid.uuid4().hex
        db.execute('INSERT INTO jobs VALUES (?,?,?,?,?,?,?)', (job, worker, task, json.dumps(paths), 'queued', None, None))
        db.commit()
        return {'id': job, 'worker': worker, 'status': 'queued'}
    except Exception:
        db.rollback()
        raise


def take(db, worker):
    db.execute('BEGIN IMMEDIATE')
    try:
        if db.execute("SELECT 1 FROM settings WHERE key='stopped' AND value='1'").fetchone():
            db.commit()
            return {'stopped': True}
        if db.execute("SELECT 1 FROM jobs WHERE worker=? AND status='running'", (worker,)).fetchone():
            db.commit()
            return {'busy': True, 'worker': worker}
        row = db.execute("SELECT * FROM jobs WHERE worker=? AND status='queued' ORDER BY rowid LIMIT 1", (worker,)).fetchone()
        if row is None:
            db.commit()
            return {'idle': True}
        token = uuid.uuid4().hex
        db.execute("UPDATE jobs SET status='running',token=? WHERE id=?", (token, row['id']))
        db.commit()
        return {**dict(row), 'status': 'running', 'token': token, 'scope': json.loads(row['scope'])}
    except Exception:
        db.rollback()
        raise


def finish(db, job, token, result, blocked=False):
    with db:
        changed = db.execute("UPDATE jobs SET status=?,result=? WHERE id=? AND token=? AND status='running'", ('blocked' if blocked else 'done', result, job, token)).rowcount
        if changed != 1:
            raise ValueError('Job is not running or claim token does not match')
    return {'id': job, 'status': 'blocked' if blocked else 'done'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', default='.')
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('init')
    send = commands.add_parser('send')
    send.add_argument('--worker', required=True)
    task_input = send.add_mutually_exclusive_group(required=True)
    task_input.add_argument('--task')
    task_input.add_argument('--task-file', type=Path)
    send.add_argument('--scope', required=True)
    wait = commands.add_parser('wait')
    wait.add_argument('--worker', required=True)
    wait.add_argument('--seconds', type=int, default=15, choices=range(1, 31))
    done = commands.add_parser('finish')
    done.add_argument('--id', required=True)
    done.add_argument('--token', required=True)
    result_input = done.add_mutually_exclusive_group(required=True)
    result_input.add_argument('--result')
    result_input.add_argument('--result-file', type=Path)
    done.add_argument('--blocked', action='store_true')
    cancel = commands.add_parser('cancel')
    cancel.add_argument('--id', required=True)
    cancel.add_argument('--reason', required=True)
    commands.add_parser('status')
    commands.add_parser('stop')
    args = parser.parse_args()
    db = connect(args.root)
    try:
        if args.command in ('init', 'stop'):
            with db:
                db.execute("INSERT OR REPLACE INTO settings VALUES ('stopped',?)", ('1' if args.command == 'stop' else '0',))
            result = {'stopped': args.command == 'stop'}
        elif args.command == 'send':
            task = args.task_file.read_text(encoding='utf-8') if args.task_file else args.task
            result = dispatch(db, args.worker, task, args.scope)
        elif args.command == 'wait':
            end = time.monotonic() + args.seconds
            while True:
                result = take(db, args.worker)
                if not result.get('idle') or time.monotonic() >= end:
                    break
                time.sleep(0.5)
        elif args.command == 'finish':
            content = args.result_file.read_text(encoding='utf-8') if args.result_file else args.result
            result = finish(db, args.id, args.token, content, args.blocked)
        elif args.command == 'cancel':
            with db:
                changed = db.execute("UPDATE jobs SET status='cancelled',token=NULL,result=? WHERE id=? AND status IN ('queued','running','blocked')", (args.reason, args.id)).rowcount
                if changed != 1:
                    raise ValueError('No cancellable task found')
            result = {'id': args.id, 'status': 'cancelled'}
        else:
            result = [{**dict(row), 'scope': json.loads(row['scope'])} for row in db.execute('SELECT id,worker,task,scope,status,result FROM jobs ORDER BY rowid')]
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except (ValueError, sqlite3.Error, OSError) as exc:
        parser.exit(1, f'Team operation stopped: {exc}\n')
    finally:
        db.close()


if __name__ == '__main__':
    main()
