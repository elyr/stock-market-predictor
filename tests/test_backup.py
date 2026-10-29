"""
Backup and restore: consistent copies of live databases, folders, checks
against the manifest, retention, and a full round trip of the app's data.
"""

import os
import sqlite3
import tarfile

import pytest

from api.store import NotificationStore, Store
from scripts import backup


def make_store(path) -> Store:
    store = Store(str(path))
    for day, ic in (('2026-01-05', 0.1), ('2026-01-12', -0.04)):
        run_id = store.save_run('crypto', day, 5, 1, {'note': day},
                                [{'symbol': 'BTC-USD', 'rank': 1, 'composite_score': 1.0, 'entry_price': 1.0,
                                  'payload': {'symbol': 'BTC-USD'}}])
        store.record_outcome(run_id, day, {'BTC-USD': 0.01}, 0.01, 0.0, ic)
    return store


def snapshot(store: Store):
    return [(r['id'], r['data_date'], r['rank_ic']) for r in store.list_runs('crypto')]


def make_folder(path):
    (path / 'day1').mkdir(parents=True)
    (path / 'day1' / 'report.md').write_text('# Report')
    (path / 'model.joblib').write_bytes(os.urandom(2048))
    os.symlink('day1', path / 'latest')


def test_round_trip_restores_identical_data(tmp_path):
    store = make_store(tmp_path / 'live' / 'app.db')
    make_folder(tmp_path / 'live' / 'results')
    before = snapshot(store)

    path, manifest = backup.create(str(tmp_path / 'backups'), {'app': str(tmp_path / 'live' / 'app.db')},
                                   {'results': str(tmp_path / 'live' / 'results')}, label='test')
    assert os.path.basename(path).startswith('ledger-backup-') and path.endswith('.tar.gz')
    app = next(i for i in manifest['items'] if i['name'] == 'app')
    assert app['tables']['runs'] == 2 and app['tables']['predictions'] == 2
    results = next(i for i in manifest['items'] if i['name'] == 'results')
    assert {f['path'] for f in results['files']} == {'day1/report.md', 'model.joblib'}
    assert results['links'] == {'latest': 'day1'}

    # Disaster: everything is lost, then restored to a new place
    lines = backup.restore(path, {'app': str(tmp_path / 'new' / 'app.db')},
                           {'results': str(tmp_path / 'new' / 'results')})
    assert len(lines) == 2
    assert snapshot(Store(str(tmp_path / 'new' / 'app.db'))) == before
    assert (tmp_path / 'new' / 'results' / 'day1' / 'report.md').read_text() == '# Report'
    assert (tmp_path / 'new' / 'results' / 'model.joblib').read_bytes() == \
        (tmp_path / 'live' / 'results' / 'model.joblib').read_bytes()
    assert os.readlink(tmp_path / 'new' / 'results' / 'latest') == 'day1'


def test_restore_replaces_existing_data(tmp_path):
    store = make_store(tmp_path / 'app.db')
    path, _ = backup.create(str(tmp_path / 'backups'), {'app': str(tmp_path / 'app.db')}, {})
    store.save_run('crypto', '2026-02-01', 5, 1, {}, [])  # made after the backup
    (tmp_path / 'app.db-wal').write_text('stale')          # leftovers of the old database
    backup.restore(path, {'app': str(tmp_path / 'app.db')}, {})
    assert len(Store(str(tmp_path / 'app.db')).list_runs('crypto')) == 2
    assert not (tmp_path / 'app.db-wal').exists()


def test_backup_while_a_writer_holds_a_transaction(tmp_path):
    make_store(tmp_path / 'app.db')
    writer = sqlite3.connect(tmp_path / 'app.db')
    writer.execute('BEGIN')
    writer.execute("INSERT INTO runs (id, universe, created_at, data_date, horizon, top_n, summary_json) "
                   "VALUES ('x', 'crypto', 'now', '2026-03-01', 5, 1, '{}')")
    # Uncommitted rows are not in the copy, and the copy is consistent
    path, manifest = backup.create(str(tmp_path / 'b'), {'app': str(tmp_path / 'app.db')}, {})
    writer.rollback()
    writer.close()
    assert next(i for i in manifest['items'] if i['name'] == 'app')['tables']['runs'] == 2
    backup.verify(path)


def test_missing_items_are_recorded_and_skipped(tmp_path):
    make_store(tmp_path / 'app.db')
    path, manifest = backup.create(str(tmp_path / 'b'), {'app': str(tmp_path / 'app.db'),
                                                         'mlflow': str(tmp_path / 'none.db')},
                                   {'results': str(tmp_path / 'nothing-yet')})
    skipped = {i['name'] for i in manifest['items'] if i.get('skipped')}
    assert skipped == {'mlflow', 'results'}
    lines = backup.restore(path, {'mlflow': str(tmp_path / 'restored.db')}, {})
    assert 'left as is' in lines[0] and not (tmp_path / 'restored.db').exists()


def test_damaged_backups_are_refused_before_anything_changes(tmp_path):
    make_store(tmp_path / 'app.db')
    path, _ = backup.create(str(tmp_path / 'b'), {'app': str(tmp_path / 'app.db')}, {})
    # Swap the database inside the archive for another one
    other = tmp_path / 'other.db'
    sqlite3.connect(other).execute('CREATE TABLE t (x)').connection.commit()
    damaged = tmp_path / 'damaged.tar.gz'
    with tarfile.open(path) as src, tarfile.open(damaged, 'w:gz') as dst:
        for member in src.getmembers():
            if member.name == 'sqlite/app.db':
                dst.add(other, arcname='sqlite/app.db')
            else:
                dst.addfile(member, src.extractfile(member))
    target = tmp_path / 'target.db'
    target.write_text('untouched')
    with pytest.raises(RuntimeError, match='damaged'):
        backup.restore(str(damaged), {'app': str(target)}, {})
    assert target.read_text() == 'untouched'
    with pytest.raises(RuntimeError, match='manifest.json is missing'):
        with tarfile.open(tmp_path / 'empty.tar.gz', 'w:gz'):
            pass
        backup.verify(str(tmp_path / 'empty.tar.gz'))


def test_unknown_names_are_refused(tmp_path):
    make_store(tmp_path / 'app.db')
    path, _ = backup.create(str(tmp_path / 'b'), {'app': str(tmp_path / 'app.db')}, {})
    with pytest.raises(RuntimeError, match="no database named 'appp'"):
        backup.restore(path, {'appp': str(tmp_path / 'x.db')}, {})


def test_retention_keeps_the_newest(tmp_path, monkeypatch):
    make_store(tmp_path / 'app.db')
    stamps = iter(f'20260101T00000{i}Z' for i in range(5))
    monkeypatch.setattr(backup, 'now_stamp', lambda: next(stamps))
    for _ in range(5):
        _, manifest = backup.create(str(tmp_path / 'b'), {'app': str(tmp_path / 'app.db')}, {}, keep=3)
    names = [os.path.basename(p) for p in backup.archives(str(tmp_path / 'b'))]
    assert names == [f'ledger-backup-20260101T00000{i}Z.tar.gz' for i in (2, 3, 4)]
    assert len(manifest['removed']) == 1


def test_command_line(tmp_path, capsys):
    make_store(tmp_path / 'app.db')
    out = str(tmp_path / 'b')
    assert backup.main(['create', '--output', out, '--sqlite', f'app={tmp_path / "app.db"}', '--keep', '2']) == 0
    assert 'Backup written' in capsys.readouterr().out
    assert backup.main(['list', '--output', out]) == 0
    assert 'app (' in capsys.readouterr().out
    assert backup.main(['restore', 'latest', '--from', out, '--sqlite', f'app={tmp_path / "restored.db"}']) == 0
    assert len(Store(str(tmp_path / 'restored.db')).list_runs('crypto')) == 2
    assert backup.main(['verify', str(tmp_path / 'missing.tar.gz')]) == 1
    with pytest.raises(SystemExit):
        backup.main(['create', '--output', out, '--sqlite', 'no-equals-sign'])


# ------------------------------------------------- database URLs (PostgreSQL)

def test_database_round_trip_and_moving_between_backends(database, tmp_path):
    """
    A database given by URL is copied table by table; a restore can load it
    into PostgreSQL or SQLite, and a SQLite backup can be loaded into PostgreSQL.
    """
    url = database if '://' in database else f'sqlite:///{database}'
    store = make_store_at(url)
    notes = NotificationStore(store)
    first = notes.add('crypto', {'type': 'gap', 'severity': 'info', 'symbol': 'BTC-USD', 'title': 't', 'body': 'b',
                                 'event_date': '2026-01-05'}, 'k1')
    before = snapshot(store)

    path, manifest = backup.create(str(tmp_path / 'b'), {}, {}, database_items={'app': url})
    item = manifest['items'][0]
    assert item['kind'] == 'database' and item['tables']['runs'] == 2 and item['tables']['notifications'] == 1
    backup.verify(path)

    # Into a fresh SQLite file, then back into the original database after wiping it
    lines = backup.restore(path, {'app': str(tmp_path / 'copy.db')}, {})
    assert '-> ' in lines[0]
    copy = Store(str(tmp_path / 'copy.db'))
    assert snapshot(copy) == before and NotificationStore(copy).get(first)['title'] == 't'
    store.save_run('crypto', '2026-03-01', 5, 1, {}, [])
    backup.restore(path, {}, {}, database_items={'app': url})
    assert snapshot(store) == before
    # New notifications get new ids after a restore (the id counter moved past the restored rows)
    assert notes.add('crypto', {'type': 'gap', 'severity': 'critical', 'symbol': 'ETH-USD', 'title': 't2',
                                'body': 'b', 'event_date': '2026-01-06'}, 'k2') > first

    # A SQLite backup moved into this database
    sqlite_store = make_store(tmp_path / 'legacy.db')
    sqlite_backup, _ = backup.create(str(tmp_path / 'b2'), {'app': str(tmp_path / 'legacy.db')}, {})
    backup.restore(sqlite_backup, {}, {}, database_items={'app': url})
    assert snapshot(store) == snapshot(sqlite_store)


def make_store_at(url) -> Store:
    store = Store(url)
    for day, ic in (('2026-01-05', 0.1), ('2026-01-12', -0.04)):
        run_id = store.save_run('crypto', day, 5, 1, {'note': day},
                                [{'symbol': 'BTC-USD', 'rank': 1, 'composite_score': 1.0, 'entry_price': 1.0,
                                  'payload': {'symbol': 'BTC-USD'}}])
        store.record_outcome(run_id, day, {'BTC-USD': 0.01}, 0.01, 0.0, ic)
    return store
