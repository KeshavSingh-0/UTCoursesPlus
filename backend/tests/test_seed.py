import sqlite3

import pytest
from helpers import mk  # noqa: F401  (keeps the tests directory on the path)

from utcoursesplus import demo, seed
from utcoursesplus.cli import main
from utcoursesplus.db import connect


def private_db(path):
    demo.build(path)
    con = connect(path)
    con.execute("CREATE TABLE IF NOT EXISTS kv(key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    con.execute("INSERT INTO kv(key, value) VALUES('requirements', '{\"secret\": 1}')")
    con.commit()
    con.close()


def tables(path):
    con = sqlite3.connect(path)
    try:
        return {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    finally:
        con.close()


def test_export_keeps_schedule_facts_and_drops_everything_personal(tmp_path):
    src, dest = tmp_path / "mine.sqlite", tmp_path / "seed" / "s.sqlite"
    private_db(src)
    assert {"kv", "rating", "grade", "syllabus"} <= tables(src)
    out, n = seed.export_seed(src, dest)
    assert out == dest and n == seed.sections_in(src) > 0
    assert tables(dest) == set(seed.SEED_TABLES)
    assert seed.sections_in(dest) == n


def test_export_refuses_an_empty_database(tmp_path):
    connect(tmp_path / "empty.sqlite").close()
    with pytest.raises(ValueError, match="no sections"):
        seed.export_seed(tmp_path / "empty.sqlite", tmp_path / "s.sqlite")


def test_bootstrap_fills_an_empty_database_but_never_overwrites_real_data(tmp_path):
    src, s = tmp_path / "src.sqlite", tmp_path / "seed.sqlite"
    demo.build(src)
    seed.export_seed(src, s)
    db = tmp_path / "data" / "mine.sqlite"
    assert seed.bootstrap(db, s) == seed.sections_in(s)
    con = connect(db)
    con.execute("DELETE FROM section WHERE unique_no != (SELECT MIN(unique_no) FROM section)")
    con.commit()
    con.close()
    assert seed.bootstrap(db, s) == 0 and seed.sections_in(db) == 1  # existing data is left alone
    assert seed.bootstrap(tmp_path / "x.sqlite", tmp_path / "missing.sqlite") == 0  # no seed, nothing to do


def test_bootstrapped_database_opens_in_the_app(tmp_path):
    from fastapi.testclient import TestClient

    from utcoursesplus.api import create_app

    src, s = tmp_path / "src.sqlite", tmp_path / "seed.sqlite"
    demo.build(src)
    seed.export_seed(src, s)
    db = tmp_path / "db.sqlite"
    seed.bootstrap(db, s)
    c = TestClient(create_app(db, demo=True))
    st = c.get("/api/status").json()
    assert st["has_data"] and st["demo"] is True and st["sections"] == seed.sections_in(s)
    assert c.get("/api/courses", params={"q": "C S"}).json()["total"] > 0
    assert c.get("/api/requirements").status_code == 200


def test_export_seed_command(tmp_path, monkeypatch, capsys):
    from utcoursesplus import config

    src = tmp_path / "mine.sqlite"
    demo.build(src)
    monkeypatch.setattr(config, "SEED_DB", tmp_path / "seed" / "spring2027.sqlite")
    assert main(["export-seed", "--db", str(src)]) == 0
    assert "schedule facts only" in capsys.readouterr().out
    assert main(["export-seed", "--db", str(tmp_path / "nothing.sqlite")]) == 2
