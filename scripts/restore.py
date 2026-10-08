"""Recreate Python dependencies after extracting a JobFlow backup."""
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def main():
    if sys.version_info < (3, 11):
        raise SystemExit('Necesitas Python 3.11 o posterior para restaurar JobFlow.')
    environment = ROOT / '.venv'
    if not (environment / 'Scripts' / 'python.exe').exists():
        subprocess.run([sys.executable, '-m', 'venv', str(environment)], check=True)
    python = environment / 'Scripts' / 'python.exe'
    subprocess.run([str(python), '-m', 'pip', 'install', '-r', str(ROOT / 'requirements.txt')], cwd=ROOT, check=True)
    print('\nPreparado. Abre Abrir JobFlow.cmd para usar tus ofertas y preferencias.')


if __name__ == '__main__':
    main()
