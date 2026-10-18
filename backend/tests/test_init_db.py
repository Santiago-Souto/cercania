from sqlalchemy import create_engine, inspect, text

from app import models


def test_init_db_adds_new_nullable_columns(monkeypatch):
    engine = create_engine("sqlite://")
    with engine.begin() as conn:
        # A person table from before `email` existed.
        conn.execute(text(
            "CREATE TABLE person (id VARCHAR(32) PRIMARY KEY, phone VARCHAR(20) NOT NULL, "
            "display_name VARCHAR(120) NOT NULL, created_at DATETIME NOT NULL)"
        ))
    monkeypatch.setattr(models, "engine", engine)
    models.init_db()
    models.init_db()  # second run is a no-op
    cols = {c["name"] for c in inspect(engine).get_columns("person")}
    assert "email" in cols
    assert "location" in {c["name"] for c in inspect(engine).get_columns("patient")}


def test_init_db_adds_indexes_to_existing_tables(monkeypatch):
    engine = create_engine("sqlite://")
    models.Base.metadata.create_all(engine)
    with engine.begin() as conn:
        conn.execute(text("DROP INDEX uq_invite_pending"))  # an invite table from before the index
    monkeypatch.setattr(models, "engine", engine)
    models.init_db()
    models.init_db()
    assert "uq_invite_pending" in {i["name"] for i in inspect(engine).get_indexes("invite")}
