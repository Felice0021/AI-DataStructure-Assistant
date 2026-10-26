"""Create V2-only local credentials without touching the repository root .env."""
import os
from pathlib import Path
import secrets


def main() -> None:
    path = Path(__file__).with_name(".env")
    content = (
        "DS_V2_DB_NAME=ds_assistant_v2\n"
        "DS_V2_DB_USER=ds_assistant_v2\n"
        f"DS_V2_DB_PASSWORD={secrets.token_urlsafe(40)}\n"
        "DS_V2_DB_HOST=127.0.0.1\n"
        "DS_V2_DB_PORT=5433\n"
    )
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        print("V2 .env already exists; left unchanged.")
        return
    with os.fdopen(fd, "w") as stream:
        stream.write(content)
    print("Created V2 .env with a random password (mode 0600); do not commit it.")


if __name__ == "__main__":
    main()
