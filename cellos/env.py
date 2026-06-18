"""Environment variable loader for .env files.

Loads key=value pairs from a .env file in the config directory and injects
them into os.environ. Designed for secret management (API keys, tokens).

No external dependencies — trivial parser handles standard .env format:
- Blank lines skipped
- Lines starting with # are comments
- KEY=VALUE or KEY="VALUE" or KEY='VALUE'
"""

from __future__ import annotations

import os
from pathlib import Path


def load_env(env_path: str | None = None) -> dict[str, str]:
    """Load a .env file and inject keys into the process environment.

    Keys already set in the environment are NOT overwritten (environment
    variables take priority over .env file contents).

    Args:
        env_path: Path to .env file. Defaults to ~/.cellos/.env if None.

    Returns:
        Dictionary of loaded key=value pairs that were actually injected
        (i.e., not already present in the environment).
    """
    if env_path is None:
        env_path = str(Path.home() / ".cellos" / ".env")

    path = Path(env_path)
    if not path.exists():
        return {}

    text = path.read_text(encoding="utf-8").strip()
    if not text:
        return {}

    injected: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        # Skip blank lines and comments
        if not line or line.startswith("#"):
            continue

        # Split on first '=' only (values may contain '=')
        if "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        if not key:
            continue

        # Strip surrounding quotes (single or double)
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
            value = value[1:-1]

        # Only inject if not already set in environment
        if key not in os.environ:
            os.environ[key] = value
            injected[key] = value

    return injected


def get_required_env(key: str, hint: str | None = None) -> str:
    """Get an environment variable, raising a clear error if missing.

    Args:
        key: The environment variable name.
        hint: Optional hint message to show when the variable is missing.

    Returns:
        The value of the environment variable.

    Raises:
        EnvironmentError: If the variable is not set.
    """
    value = os.environ.get(key)
    if value is None:
        msg = f"Environment variable '{key}' is not set."
        if hint:
            msg += f" {hint}"
        raise EnvironmentError(msg)
    return value


def env_has(key: str) -> bool:
    """Check if an environment variable is set and non-empty.

    Args:
        key: The environment variable name.

    Returns:
        True if the variable exists and has a non-empty value.
    """
    return bool(os.environ.get(key, "").strip())


def get_trello_credentials() -> tuple[str, str]:
    """Get TRELLO_API_KEY and TRELLO_TOKEN from environment.

    Returns:
        Tuple of (api_key, token).

    Raises:
        EnvironmentError: If either credential is missing, with setup instructions.
    """
    hint = (
        "Create a Trello Power-Up at https://trello.com/power-ups/admin, "
        "generate an API key, then generate a user token with at least read,write scope, "
        "and add both to ~/.cellos/.env:"
    )
    api_key = get_required_env("TRELLO_API_KEY", hint)
    token = get_required_env("TRELLO_TOKEN", hint)
    return (api_key, token)
