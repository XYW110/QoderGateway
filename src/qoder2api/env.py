import os
from pathlib import Path


def load_dotenv() -> None:
    candidates = [
        Path.cwd() / ".env",
        Path(__file__).resolve().parent.parent.parent / ".env",  # 项目根
    ]
    seen: set[Path] = set()
    for env_path in candidates:
        try:
            env_path = env_path.resolve()
        except Exception:
            continue
        if env_path in seen or not env_path.exists():
            continue
        seen.add(env_path)
        for raw_line in env_path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value


load_dotenv()


def env_bool(name: str, default: bool = True) -> bool:
    value = os.getenv(name)
    if value is None or value.strip() == "":
        return default
    return value.strip().lower() not in {"0", "false", "no", "off"}


def admin_password() -> str | None:
    value = os.getenv("QODER_ADMIN_PASSWORD", "").strip()
    return value or None


def proxy_url() -> str | None:
    value = os.getenv("QODER_PROXY", "").strip()
    return value or None


def httpx_client_kwargs() -> dict:
    proxy = proxy_url()
    return {"proxy": proxy} if proxy else {}
