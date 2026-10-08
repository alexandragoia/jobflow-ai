from sqlalchemy import inspect, text

def backup_database(engine):
    if not engine.url.database:
        return
    import sqlite3
    from pathlib import Path
    database = Path(engine.url.database)
    backup = database.with_suffix(".db.bak")
    if database.is_file() and not backup.exists():
        source = sqlite3.connect(f"file:{database.as_posix()}?mode=ro", uri=True)
        destination = sqlite3.connect(backup)
        try:
            source.backup(destination)
        finally:
            source.close()
            destination.close()

def migrate(engine):
    """Additive SQLite migrations preserve existing jobs and feedback."""
    additions = {
        "jobs": {"possible_repost": "BOOLEAN NOT NULL DEFAULT 0"},
        "searches": {"params_json": "TEXT NOT NULL DEFAULT '{}'", "messages_json": "TEXT NOT NULL DEFAULT '[]'"},
        "search_results": {"score": "INTEGER NOT NULL DEFAULT 40", "score_confidence": "TEXT NOT NULL DEFAULT 'baja'",
                           "score_factors_json": "TEXT NOT NULL DEFAULT '[]'", "result_json": "TEXT NOT NULL DEFAULT '{}'"},
        "job_feedback": {"disposition": "TEXT NOT NULL DEFAULT 'none'", "saved": "BOOLEAN NOT NULL DEFAULT 0", "reason": "TEXT", "note": "TEXT",
                         "interest_note": "TEXT", "interest_conditional": "BOOLEAN NOT NULL DEFAULT 0"},
    }
    with engine.begin() as connection:
        for table, columns in additions.items():
            existing = {c["name"] for c in inspect(connection).get_columns(table)}
            for name, declaration in columns.items():
                if name not in existing:
                    connection.execute(text(f'ALTER TABLE "{table}" ADD COLUMN "{name}" {declaration}'))
                    if table == "job_feedback" and name == "disposition":
                        connection.execute(text("UPDATE job_feedback SET disposition = CASE WHEN liked = 1 THEN 'interested' ELSE 'rejected' END"))
