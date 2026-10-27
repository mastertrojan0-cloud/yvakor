"""Carrega config/settings.yaml + variáveis de ambiente (.env)."""
from pathlib import Path
import os

try:
    import yaml
except ImportError:
    yaml = None

ROOT = Path(__file__).resolve().parent.parent


def _load_dotenv():
    env_file = ROOT / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


def load_settings() -> dict:
    _load_dotenv()
    cfg_path = ROOT / "config" / "settings.yaml"
    if yaml is None:
        raise RuntimeError("Instale pyyaml: pip install -r requirements.txt")
    with open(cfg_path, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    try:
        from yvakor.ajustes import aplicar_ao_settings
        return aplicar_ao_settings(cfg)
    except Exception:
        return cfg
