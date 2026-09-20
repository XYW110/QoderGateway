import os
import sys
from pathlib import Path


def project_root() -> Path:
    """运行时根目录：冻结(exe)时为 exe 所在目录，源码运行为项目根。"""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent.parent


def load_dotenv() -> None:
    candidates = [
        Path.cwd() / ".env",
        project_root() / ".env",
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


def registrar_proxy() -> str | None:
    """注册机（DrissionPage 浏览器）使用的 HTTP 代理。

    - QODER_REGISTRAR_PROXY=1/true 开启；关闭时注册机一律直连
    - 地址取 QODER_REGISTRAR_PROXY_URL；未设置则回退 QODER_PROXY
    - 开启了但两边都为空 → 返回 None（直连），由调用方记警告日志
    """
    if not env_bool("QODER_REGISTRAR_PROXY", False):
        return None
    url = (os.getenv("QODER_REGISTRAR_PROXY_URL") or os.getenv("QODER_PROXY") or "").strip()
    return url or None


def mail_proxy() -> str | None:
    """临时邮箱客户端（Emailnator/YYDS）使用的 HTTP 代理。

    - QODER_MAIL_PROXY=1/true 开启（默认开，保持旧行为）；关闭则邮箱直连
    - 地址优先级：QODER_MAIL_PROXY_URL → LOCAL_PROXY → QODER_PROXY
    - 开启了但都为空 → None（直连）
    """
    if not env_bool("QODER_MAIL_PROXY", True):
        return None
    url = (os.getenv("QODER_MAIL_PROXY_URL") or os.getenv("LOCAL_PROXY") or os.getenv("QODER_PROXY") or "").strip()
    return url or None


def httpx_client_kwargs() -> dict:
    proxy = proxy_url()
    return {"proxy": proxy} if proxy else {}
