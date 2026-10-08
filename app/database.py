from pathlib import Path
import os

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

ROOT = Path(__file__).resolve().parents[1]
data_dir = Path(os.getenv('JOBFLOW_DATA_DIR', str(ROOT)))
database_path = Path(os.getenv('JOBFLOW_DATABASE_PATH', str(data_dir / 'jobflow.db')))
database_path.parent.mkdir(parents=True, exist_ok=True)
DATABASE_URL = f"sqlite:///{database_path.as_posix()}"
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


class Base(DeclarativeBase):
    pass


def get_session():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
