"""Optional, locally supplied source labels for a verified course import."""
import json
import re


def read_mapping(path):
    if path is None:
        return {}
    try:
        with path.open('rb') as source:
            raw = source.read(2_000_001)
        if len(raw) > 2_000_000:
            return {}
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError, UnicodeError):
        return {}


def source_label(row, mapping):
    """Use only the entry pinned to this authorized, unchanged database chunk."""
    entry = mapping.get(str(row['chunk_id']))
    if not isinstance(entry, dict):
        return {}
    if any(entry.get(key) != str(row[key]) for key in ('knowledge_base_id', 'document_id', 'content_hash')):
        return {}
    name, chapter, section, page = (entry.get(k) for k in ('source_file', 'chapter', 'section', 'page'))
    if not all(isinstance(x, str) and len(x) <= 300 for x in (name, chapter, section)) or not name.strip():
        return {}
    if any(re.search(r'[\x00-\x1f\x7f]', x) for x in (name, chapter, section)):
        return {}
    title = ' · '.join(dict.fromkeys(x.strip() for x in (chapter, section) if x.strip())) or None
    return {'source_filename': name, 'section_title': title, 'page_number': page if type(page) is int and page > 0 else None}
