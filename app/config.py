from pathlib import Path
import os
import shutil

import yaml
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")


def mutable_config_path(name, root=None):
    root = root or ROOT
    data_dir = os.getenv('JOBFLOW_DATA_DIR')
    if data_dir and name in ('preferences.yaml', 'qualifications.yaml'):
        directory = Path(data_dir) / 'config'
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / name
        if name == 'preferences.yaml' and not path.exists():
            shutil.copyfile(root / 'config' / name, path)
        return path
    return root / 'config' / name


def load_yaml(name: str) -> dict:
    path = mutable_config_path(name)
    if name == "qualifications.yaml" and not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as file:
        return yaml.safe_load(file) or {}


PREFERENCES = load_yaml("preferences.yaml")
SYNONYMS = load_yaml("synonyms.yaml")
