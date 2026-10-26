"""Export contract without loading any real configuration or connecting to a database."""
import json
from pathlib import Path
from backend.v2.core.config import Settings, REPOSITORY_ROOT
from backend.v2.main import create_app


def schema():
    return create_app(Settings(_env_file=None, db_password='synthetic-schema-only')).openapi()


def main():
    target = REPOSITORY_ROOT / 'docs/v2/openapi.json'
    target.write_text(json.dumps(schema(), ensure_ascii=False, indent=2) + '\n', encoding='utf8')
    print('Exported docs/v2/openapi.json without real credentials')


if __name__ == '__main__':
    main()
