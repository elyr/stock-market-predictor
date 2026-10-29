#!/usr/bin/env python3
"""
Back up and restore Ledger's data: SQLite databases (copied consistently while
the app runs) and folders (model files, prediction results).

    # A backup of the app database, MLflow's database and its model files
    python scripts/backup.py create --output backups \\
        --sqlite app=data/demo.db --sqlite mlflow=data/mlflow-demo.db \\
        --dir mlflow-artifacts=data/mlartifacts-demo --keep 14

    python scripts/backup.py list --output backups
    python scripts/backup.py verify backups/ledger-backup-20261029T023000Z.tar.gz

    # Restore (stop the app first): each item goes back to the path given
    python scripts/backup.py restore backups/ledger-backup-20261029T023000Z.tar.gz \\
        --sqlite app=data/demo.db --sqlite mlflow=data/mlflow-demo.db \\
        --dir mlflow-artifacts=data/mlartifacts-demo

    # With PostgreSQL: a logical copy of every table of the app's schema
    python scripts/backup.py create --output backups --database app="$DATABASE_URL"
    # ... restored into PostgreSQL, or a SQLite backup moved into PostgreSQL
    python scripts/backup.py restore latest --from backups --database app="$DATABASE_URL"

Each backup is one ``.tar.gz`` with a ``manifest.json`` listing every file
with its size and SHA-256, plus the row count of each database table. A
restore checks all of them before it changes anything. Items missing at
backup time (for example a folder not created yet) are skipped and recorded
as such. SQLite files and folders need only the standard library; database
URLs (``--database``) use the app's own schema and SQLAlchemy (api/db.py).

Exit codes: 0 success, 1 failure, 2 bad arguments.
"""

import argparse
import hashlib
import io
import json
import os
import shutil
import sqlite3
import sys
import tarfile
import tempfile
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

FORMAT = 1
PREFIX = 'ledger-backup-'
SUFFIX = '.tar.gz'


# ----------------------------------------------------------------- helpers

def parse_items(values: Optional[List[str]], kind: str) -> Dict[str, str]:
    """``NAME=PATH`` pairs from the command line."""
    items: Dict[str, str] = {}
    for value in values or []:
        name, sep, path = value.partition('=')
        if not sep or not name or not path:
            raise SystemExit(f'--{kind} needs NAME=PATH, got {value!r}')
        if not name.replace('-', '').replace('_', '').isalnum():
            raise SystemExit(f'--{kind}: the name {name!r} may only contain letters, digits, - and _')
        if name in items:
            raise SystemExit(f'--{kind}: {name!r} is given twice')
        items[name] = path
    return items


def sha256(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            digest.update(chunk)
    return digest.hexdigest()


def table_counts(path: str) -> Dict[str, int]:
    conn = sqlite3.connect(f'file:{path}?mode=ro', uri=True)
    try:
        tables = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
        return {t: conn.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0] for t in tables}
    finally:
        conn.close()


def snapshot_sqlite(source: str, destination: str) -> None:
    """A consistent copy of a live database (SQLite's online backup, safe while the app writes)."""
    src = sqlite3.connect(f'file:{source}?mode=ro', uri=True, timeout=60)
    dst = sqlite3.connect(destination)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()
    check = sqlite3.connect(destination)
    try:
        result = check.execute('PRAGMA integrity_check').fetchone()[0]
    finally:
        check.close()
    if result != 'ok':
        raise RuntimeError(f'The copy of {source} failed its integrity check: {result}')


# --------------------------------------------------------- database URLs

def _app_db():
    """api.db, importable when the script runs from the repository or the image."""
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if root not in sys.path:
        sys.path.insert(0, root)
    from api import db
    return db


def dump_database(url: str, destination: str) -> Tuple[Dict[str, int], List[dict]]:
    """Every table of the app's schema as JSON lines, one file per table."""
    db = _app_db()
    from sqlalchemy import inspect, select

    engine = db.make_engine(db.database_url('', url))
    counts, files = {}, []
    os.makedirs(destination, exist_ok=True)
    try:
        options = {}
        if engine.dialect.name == 'postgresql':
            # One consistent snapshot of every table, while the app keeps writing
            options = {'isolation_level': 'REPEATABLE READ', 'postgresql_readonly': True}
        with engine.connect().execution_options(**options) as conn:
            existing = set(inspect(conn).get_table_names())
            for table in db.TABLES:
                if table.name not in existing:
                    continue
                path = os.path.join(destination, f'{table.name}.jsonl')
                n = 0
                with open(path, 'w') as f:
                    for row in conn.execute(select(table).order_by(*table.primary_key.columns)).mappings():
                        f.write(json.dumps(dict(row)) + '\n')
                        n += 1
                counts[table.name] = n
                files.append({'path': f'{table.name}.jsonl', 'size': os.path.getsize(path), 'sha256': sha256(path)})
    finally:
        engine.dispose()
    return counts, files


def _rows_from_jsonl(directory: str, table: str):
    path = os.path.join(directory, f'{table}.jsonl')
    if not os.path.exists(path):
        return []
    with open(path) as f:
        return [json.loads(line) for line in f if line.strip()]


def _rows_from_sqlite(path: str, table: str):
    conn = sqlite3.connect(f'file:{path}?mode=ro', uri=True)
    conn.row_factory = sqlite3.Row
    try:
        if not conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)).fetchone():
            return []
        return [dict(r) for r in conn.execute(f'SELECT * FROM "{table}"')]
    finally:
        conn.close()


def load_database(url: str, rows_for) -> Dict[str, int]:
    """
    Replace every table of the app's schema at ``url`` with the given rows, in
    one transaction. The schema is brought up to date first.
    """
    db = _app_db()
    from sqlalchemy import delete, func, insert, select, text

    engine = db.make_engine(db.database_url('', url))
    counts = {}
    try:
        db.migrate(engine)
        with engine.begin() as conn:
            for table in reversed(db.TABLES):
                conn.execute(delete(table))
            for table in db.TABLES:
                columns = set(table.c.keys())
                rows = [{k: v for k, v in r.items() if k in columns} for r in rows_for(table.name)]
                for start in range(0, len(rows), 500):
                    conn.execute(insert(table), rows[start:start + 500])
                counts[table.name] = len(rows)
            if engine.dialect.name == 'postgresql':
                # Rows came with their ids: move the id sequence past them
                top = conn.execute(select(func.max(db.notifications.c.id))).scalar()
                conn.execute(text("SELECT setval(pg_get_serial_sequence('notifications', 'id'), :v, :called)"),
                             {'v': top or 1, 'called': top is not None})
    finally:
        engine.dispose()
    return counts


def now_stamp() -> str:
    return datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')


def archives(directory: str) -> List[str]:
    """Backups in a folder, oldest first (names sort by time)."""
    if not os.path.isdir(directory):
        return []
    return sorted(os.path.join(directory, f) for f in os.listdir(directory)
                  if f.startswith(PREFIX) and f.endswith(SUFFIX))


# ------------------------------------------------------------------ create

def create(output: str, sqlite_items: Dict[str, str], dir_items: Dict[str, str], keep: int = 0,
           label: str = '', database_items: Optional[Dict[str, str]] = None) -> Tuple[str, dict]:
    """Write a backup archive to ``output``; returns its path and manifest."""
    database_items = database_items or {}
    if not sqlite_items and not dir_items and not database_items:
        raise SystemExit('Nothing to back up: give at least one --sqlite, --database or --dir')
    os.makedirs(output, exist_ok=True)
    stamp = now_stamp()
    manifest = {'format': FORMAT, 'created_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
                'label': label, 'items': []}
    with tempfile.TemporaryDirectory(prefix='ledger-backup-') as tmp:
        staged: List[Tuple[str, str]] = []  # (path on disk, name in the archive)
        for name, path in sqlite_items.items():
            entry = {'name': name, 'kind': 'sqlite', 'source': path}
            if not os.path.isfile(path):
                manifest['items'].append({**entry, 'skipped': 'not found'})
                continue
            copy = os.path.join(tmp, f'{name}.db')
            snapshot_sqlite(path, copy)
            arcname = f'sqlite/{name}.db'
            manifest['items'].append({**entry, 'file': arcname, 'size': os.path.getsize(copy),
                                      'sha256': sha256(copy), 'tables': table_counts(copy)})
            staged.append((copy, arcname))
        for name, url in database_items.items():
            folder = os.path.join(tmp, 'database', name)
            counts, files = dump_database(url, folder)
            manifest['items'].append({'name': name, 'kind': 'database', 'source': _app_db().safe_url(url),
                                      'tables': counts, 'files': files})
            staged += [(os.path.join(folder, f['path']), f"database/{name}/{f['path']}") for f in files]
        for name, path in dir_items.items():
            entry = {'name': name, 'kind': 'dir', 'source': path}
            if not os.path.isdir(path):
                manifest['items'].append({**entry, 'skipped': 'not found'})
                continue
            files = []
            for root, _, names in os.walk(path):
                for filename in sorted(names):
                    full = os.path.join(root, filename)
                    if os.path.islink(full) or not os.path.isfile(full):
                        continue  # links (e.g. "latest") are recreated by the app; only real files are kept
                    relative = os.path.relpath(full, path)
                    files.append({'path': relative, 'size': os.path.getsize(full), 'sha256': sha256(full)})
                    staged.append((full, f'dirs/{name}/{relative}'))
            links = {os.path.relpath(os.path.join(root, n), path): os.readlink(os.path.join(root, n))
                     for root, dirs, names in os.walk(path) for n in names + dirs
                     if os.path.islink(os.path.join(root, n))}
            manifest['items'].append({**entry, 'files': files, 'links': links})

        name = f'{PREFIX}{stamp}{SUFFIX}'
        final = os.path.join(output, name)
        partial = final + '.partial'
        with tarfile.open(partial, 'w:gz') as tar:
            data = json.dumps(manifest, indent=2).encode()
            info = tarfile.TarInfo('manifest.json')
            info.size = len(data)
            info.mtime = int(datetime.now(timezone.utc).timestamp())
            tar.addfile(info, io.BytesIO(data))
            for path, arcname in staged:
                tar.add(path, arcname=arcname, recursive=False)
        os.replace(partial, final)  # never leave a half-written backup under a backup's name

    removed = prune(output, keep) if keep else []
    manifest['archive'] = final
    manifest['removed'] = removed
    return final, manifest


def prune(directory: str, keep: int) -> List[str]:
    """Delete all but the newest ``keep`` backups."""
    existing = archives(directory)
    old = existing[:-keep] if keep > 0 else []
    for path in old:
        os.remove(path)
    return old


# ------------------------------------------------------------ read, verify

def read_manifest(tar: tarfile.TarFile) -> dict:
    try:
        member = tar.getmember('manifest.json')
    except KeyError:
        raise RuntimeError('Not a Ledger backup: manifest.json is missing')
    manifest = json.load(tar.extractfile(member))
    if manifest.get('format') != FORMAT:
        raise RuntimeError(f"Unsupported backup format {manifest.get('format')!r}")
    return manifest


def _safe_member(name: str) -> bool:
    return not (name.startswith('/') or '..' in name.split('/'))


def extract_verified(archive: str, destination: str) -> dict:
    """Unpack into ``destination`` and check every file against the manifest."""
    with tarfile.open(archive, 'r:gz') as tar:
        manifest = read_manifest(tar)
        for member in tar.getmembers():
            if not _safe_member(member.name) or not (member.isfile() or member.isdir()):
                raise RuntimeError(f'Refusing unexpected entry in the archive: {member.name}')
        if hasattr(tarfile, 'data_filter'):
            tar.extractall(destination, filter='data')
        else:  # Python before 3.11.4 (and 3.10.12): the entries were checked above
            tar.extractall(destination)
    problems = []
    for item in manifest['items']:
        if item.get('skipped'):
            continue
        if item['kind'] == 'database':
            for f in item['files']:
                path = os.path.join(destination, 'database', item['name'], f['path'])
                if not os.path.isfile(path) or sha256(path) != f['sha256']:
                    problems.append(f"{item['name']}/{f['path']}: missing or changed")
            continue
        if item['kind'] == 'sqlite':
            path = os.path.join(destination, item['file'])
            if not os.path.isfile(path) or sha256(path) != item['sha256']:
                problems.append(f"{item['name']}: database file missing or changed")
                continue
            if table_counts(path) != item['tables']:
                problems.append(f"{item['name']}: table row counts differ from the manifest")
        else:
            for f in item['files']:
                path = os.path.join(destination, 'dirs', item['name'], f['path'])
                if not os.path.isfile(path) or sha256(path) != f['sha256']:
                    problems.append(f"{item['name']}/{f['path']}: missing or changed")
    if problems:
        raise RuntimeError('The backup is damaged:\n  ' + '\n  '.join(problems[:20]))
    return manifest


def verify(archive: str) -> dict:
    with tempfile.TemporaryDirectory(prefix='ledger-verify-') as tmp:
        return extract_verified(archive, tmp)


# ----------------------------------------------------------------- restore

def restore(archive: str, sqlite_items: Dict[str, str], dir_items: Dict[str, str],
            database_items: Optional[Dict[str, str]] = None) -> List[str]:
    """
    Put each named item back at the path given. Everything is checked before
    anything is replaced; each database and folder is replaced in one step.

    A database (``--database NAME=URL``) can be restored from a database item
    or from a SQLite item of the same name, and a SQLite file from a database
    item: that is how data moves between SQLite and PostgreSQL.
    """
    database_items = database_items or {}
    if not sqlite_items and not dir_items and not database_items:
        raise SystemExit('Nothing to restore: give at least one --sqlite, --database or --dir')
    done: List[str] = []
    with tempfile.TemporaryDirectory(prefix='ledger-restore-') as tmp:
        manifest = extract_verified(archive, tmp)
        by_name = {(i['kind'], i['name']): i for i in manifest['items']}
        for name in [*sqlite_items, *database_items]:
            if ('sqlite', name) not in by_name and ('database', name) not in by_name:
                raise RuntimeError(f"The backup has no database named {name!r} "
                                   f"(it has: {', '.join(i['name'] for i in manifest['items'])})")
        for name in dir_items:
            if ('dir', name) not in by_name:
                raise RuntimeError(f"The backup has no folder named {name!r}")

        def rows_from(item):
            if item['kind'] == 'database':
                folder = os.path.join(tmp, 'database', item['name'])
                return lambda table: _rows_from_jsonl(folder, table)
            path = os.path.join(tmp, item['file'])
            return lambda table: _rows_from_sqlite(path, table)

        for name, url in database_items.items():
            item = by_name.get(('database', name)) or by_name[('sqlite', name)]
            if item.get('skipped'):
                done.append(f'{name}: not in the backup ({item["skipped"]} when it was made), left as is')
                continue
            counts = load_database(url, rows_from(item))
            done.append(f"{name}: {sum(counts.values())} rows in {len(counts)} tables -> "
                        f"{_app_db().safe_url(url)}")

        for name, target in list(sqlite_items.items()):
            if ('sqlite', name) not in by_name:  # a database item restored into a SQLite file
                item = by_name[('database', name)]
                counts = load_database(f'sqlite:///{os.path.abspath(target)}', rows_from(item))
                done.append(f"{name}: {sum(counts.values())} rows in {len(counts)} tables -> {target}")
                continue
            item = by_name[('sqlite', name)]
            if item.get('skipped'):
                done.append(f'{name}: not in the backup ({item["skipped"]} when it was made), left as is')
                continue
            os.makedirs(os.path.dirname(os.path.abspath(target)), exist_ok=True)
            staged = f'{target}.restoring'
            shutil.copyfile(os.path.join(tmp, item['file']), staged)
            for suffix in ('-wal', '-shm', '-journal'):  # leftovers of the old database would corrupt the new one
                if os.path.exists(target + suffix):
                    os.remove(target + suffix)
            os.replace(staged, target)
            done.append(f"{name}: {sum(item['tables'].values())} rows in {len(item['tables'])} tables -> {target}")

        for name, target in dir_items.items():
            item = by_name[('dir', name)]
            if item.get('skipped'):
                done.append(f'{name}: not in the backup ({item["skipped"]} when it was made), left as is')
                continue
            source = os.path.join(tmp, 'dirs', name)
            os.makedirs(source, exist_ok=True)
            for link, points_to in item.get('links', {}).items():
                path = os.path.join(source, link)
                os.makedirs(os.path.dirname(path), exist_ok=True)
                os.symlink(points_to, path)
            target = target.rstrip('/')
            os.makedirs(target, exist_ok=True)
            # Replace the folder's contents (not the folder: it may be a mounted volume)
            for entry in os.listdir(target):
                path = os.path.join(target, entry)
                if os.path.isdir(path) and not os.path.islink(path):
                    shutil.rmtree(path)
                else:
                    os.remove(path)
            for entry in os.listdir(source):
                shutil.move(os.path.join(source, entry), os.path.join(target, entry))
            done.append(f"{name}: {len(item['files'])} files -> {target}")
    return done


# --------------------------------------------------------------------- CLI

def describe(path: str) -> str:
    with tarfile.open(path, 'r:gz') as tar:
        m = read_manifest(tar)
    parts = []
    for item in m['items']:
        if item.get('skipped'):
            parts.append(f"{item['name']} (skipped)")
        elif item['kind'] in ('sqlite', 'database'):
            parts.append(f"{item['name']} ({sum(item['tables'].values())} rows)")
        else:
            parts.append(f"{item['name']} ({len(item['files'])} files)")
    size = os.path.getsize(path) / 1e6
    return f"{os.path.basename(path)}  {size:.1f} MB  {m['created_at']}  {', '.join(parts)}"


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0],
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest='command', required=True)

    c = sub.add_parser('create', help='Write a new backup')
    c.add_argument('--output', required=True, help='Folder for the backups')
    c.add_argument('--sqlite', action='append', metavar='NAME=PATH', help='A SQLite database (repeatable)')
    c.add_argument('--database', action='append', metavar='NAME=URL',
                   help='A database URL, e.g. PostgreSQL (repeatable)')
    c.add_argument('--dir', action='append', metavar='NAME=PATH', help='A folder (repeatable)')
    c.add_argument('--keep', type=int, default=0, help='Keep only the newest N backups (0: keep all)')
    c.add_argument('--label', default='', help='Free text stored in the manifest')

    r = sub.add_parser('restore', help='Restore from a backup (stop the app first)')
    r.add_argument('archive', help="A backup file, or 'latest' with --from")
    r.add_argument('--from', dest='source', help="Folder to pick 'latest' from")
    r.add_argument('--sqlite', action='append', metavar='NAME=PATH')
    r.add_argument('--database', action='append', metavar='NAME=URL')
    r.add_argument('--dir', action='append', metavar='NAME=PATH')

    v = sub.add_parser('verify', help='Check a backup without restoring it')
    v.add_argument('archive')

    l = sub.add_parser('list', help='List the backups in a folder')
    l.add_argument('--output', required=True)

    args = parser.parse_args(argv)
    try:
        if args.command == 'create':
            path, manifest = create(args.output, parse_items(args.sqlite, 'sqlite'), parse_items(args.dir, 'dir'),
                                    keep=args.keep, label=args.label,
                                    database_items=parse_items(args.database, 'database'))
            print(f'Backup written: {describe(path)}')
            for old in manifest['removed']:
                print(f'Removed old backup {os.path.basename(old)}')
        elif args.command == 'restore':
            archive = args.archive
            if archive == 'latest':
                found = archives(args.source or '.')
                if not found:
                    print(f"No backups in {args.source or '.'}", file=sys.stderr)
                    return 1
                archive = found[-1]
            print(f'Restoring {describe(archive)}')
            for line in restore(archive, parse_items(args.sqlite, 'sqlite'), parse_items(args.dir, 'dir'),
                                database_items=parse_items(args.database, 'database')):
                print(f'  {line}')
        elif args.command == 'verify':
            verify(args.archive)
            print(f'OK: {describe(args.archive)}')
        elif args.command == 'list':
            found = archives(args.output)
            for path in reversed(found):
                print(describe(path))
            if not found:
                print(f'No backups in {args.output}')
    except Exception as e:  # reported plainly; the traceback is not useful to someone restoring
        print(f'Error: {e}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
