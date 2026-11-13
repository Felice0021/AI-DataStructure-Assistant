"""Offline Issue #5 review. Reads frozen assets; writes only its own output directory."""
import ast
from collections import Counter, defaultdict
import csv
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import sys
import subprocess

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'docs/v2/course_audit/2026-11-04'
SOURCE = ROOT / 'knowledge_base/ds_chunks.jsonl'

def digest(data):
    return hashlib.sha256(data).hexdigest()

def save(name, obj):
    (OUT / name).write_text(json.dumps(obj, ensure_ascii=False, indent=2) + '\n', encoding='utf-8', newline='\n')

def require_candidate_reviews(candidates, notes):
    missing = [r['chunk_id'] for r in candidates
               if not isinstance(notes.get(r['chunk_id']), dict)
               or not isinstance(notes[r['chunk_id']].get('note'), str)
               or not notes[r['chunk_id']]['note'].strip()
               or notes[r['chunk_id']].get('issue')]
    if missing:
        raise ValueError('Final candidates require explicit AI content review without open issues: ' + ', '.join(missing))

def protect_human_records(fieldnames):
    """Fail closed instead of replacing edits in any existing generated review view."""
    defaults = {
        '人工复核状态': {'未复核', ''}, '最终批准状态': {'未批准', ''},
        '负责人复核结论': {'待复核', ''},
        '授权凭据': {'用户会话确认；见authorization.md', '组员陈述；见authorization.md'},
        '允许对外展示': {'否（公开展示/分发未确认）'},
    }
    existing = []
    for name in ('review.csv', 'candidates_100.csv', 'issues.csv'):
        path = OUT / name
        if path.exists():
            with path.open(encoding='utf-8-sig', newline='') as handle:
                reader = csv.DictReader(handle)
                if set(reader.fieldnames or ()) - set(fieldnames) - {'text'}:
                    raise ValueError(f'{name}: unknown columns; preserve and merge manually')
                existing.extend((name, row) for row in reader)
    path = OUT / 'review_data.json'
    if path.exists():
        existing.extend((path.name, row) for row in json.loads(path.read_text(encoding='utf-8')))
    for name, row in existing:
        if set(row) - set(fieldnames) - {'text'}:
            raise ValueError(f'{name}: unknown columns; preserve and merge manually')
        for key, allowed in defaults.items():
            if key in row and row[key] not in allowed:
                raise ValueError(f'{name}: human-edited {key} at {row.get("legacy_chunk_id")}; generation stopped')

def main():
    OUT.mkdir(parents=True, exist_ok=True)
    raw = SOURCE.read_bytes().replace(b'\r\n', b'\n')
    rows = [json.loads(s) for s in raw.decode('utf-8').splitlines() if s.strip()]
    # Run existing validator without changing its historical report.
    path = ROOT / 'knowledge_base/validate_chunks.py'
    spec = importlib.util.spec_from_file_location('course_validator', path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    chunks, issues = mod.load_and_validate(SOURCE)
    stats = mod.build_statistics(chunks, issues)
    # Execute ONLY the unchanged pure prepare() AST from the checked-in tool.
    # This is an offline fallback, explicitly not a successful V2 CLI run.
    tool = ROOT / 'backend/v2/tools/import_course.py'
    tree = ast.parse(tool.read_text(encoding='utf-8'))
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'prepare')
    scope = {'Path': Path, 'hashlib': hashlib, 'json': json, 're': re}
    exec(compile(ast.Module(body=[fn], type_ignores=[]), str(tool), 'exec'), scope)
    data, manifest = scope['prepare'](SOURCE)
    flags = defaultdict(list)
    for issue in issues:
        if issue.chunk_id:
            flags[issue.chunk_id].append((issue.code, issue.message))
    normalized = [''.join(r['text'].split()).lower() for r in rows]
    grams = [{s[i:i+3] for i in range(len(s)-2)} for s in normalized]
    pairs = []
    for i, a in enumerate(rows):
        cid, text = a['chunk_id'], a['text']
        if a['page'] is None:
            flags[cid].append(('PAGE_UNKNOWN', '页码为 null；格式允许，引用位置待核对'))
        if not (ROOT / 'knowledge_base' / a['source_file']).is_file():
            flags[cid].append(('SOURCE_NOT_LOCAL', 'knowledge_base 中无同名源文件；不能据此认定来源不存在'))
        if '\ufffd' in text or re.search(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', text):
            flags[cid].append(('ENCODING_SUSPECT', '发现替换字符或控制字符'))
        chapter = re.match(r'ds_ch(\d+)_', cid)
        section = re.match(r'(\d+)\.', a['section'])
        if chapter and section and int(chapter[1]) != int(section[1]):
            flags[cid].append(('SECTION_ID_MISMATCH', 'section 数字前缀与 ID 章节不同；需对照目录'))
        if a['content_type'] == 'code' and (text.count('{') != text.count('}') or text.count('/*') != text.count('*/')):
            flags[cid].append(('CODE_DELIMITER', '代码花括号或注释界符数量不平衡；启发式疑点'))
        if text.count('$$') % 2 or re.search(r'\.\.\.|…|略去|省略', text):
            flags[cid].append(('INCOMPLETE_SUSPECT', '省略标记或公式界符疑点；可能为正常节选'))
        for j in range(i):
            if a['chapter'] != rows[j]['chapter'] or min(len(normalized[i]),len(normalized[j])) < 25:
                continue
            if min(len(normalized[i]),len(normalized[j])) / max(len(normalized[i]),len(normalized[j])) < .7:
                continue
            sim = len(grams[i] & grams[j]) / max(1, len(grams[i] | grams[j]))
            if sim >= .72:
                pairs.append({'id_a':rows[j]['chunk_id'], 'id_b':cid, 'trigram_jaccard':round(sim,4)})
                for x,y in [(cid, rows[j]['chunk_id']), (rows[j]['chunk_id'],cid)]:
                    flags[x].append(('NEAR_DUPLICATE', f'与 {y} 字符三元组 Jaccard={sim:.4f}；不自动合并'))
    notes_path = Path(__file__).with_name('content_notes.json')
    notes = json.loads(notes_path.read_text(encoding='utf-8')) if notes_path.exists() else {}
    for cid, note in notes.items():
        if note.get('issue'):
            flags[cid].append(('CONTENT_REVIEW',note['issue']))
    # Diversity by chapter, type and section, with deterministic source-order ties.
    quotas = {1:6,2:12,3:12,4:8,5:8,6:16,7:16,9:12,10:8,11:2}
    candidates = []
    for ch, quota in quotas.items():
        pool = [r for r in rows if r['chunk_id'].startswith(f'ds_ch{ch:02d}_') and not flags[r['chunk_id']] and r['content_type'] != 'exercise']
        chosen = []
        uses = Counter()
        types = Counter()
        while len(chosen) < quota:
            available = [r for r in pool if r not in chosen]
            if not available:
                raise ValueError(f'Not enough candidates in chapter {ch}')
            r = min(available,key=lambda r:(uses[r['section']],types[r['content_type']],-min(len(r['text']),160)))
            chosen.append(r)
            uses[r['section']] += 1
            types[r['content_type']] += 1
        candidates.extend(chosen)
    candidate_ids = {r['chunk_id'] for r in candidates}
    # Review notes are maintained separately by stable ID after actual AI reading.
    if any(flags[cid] for cid in candidate_ids):
        raise ValueError('Candidate now has review issues: revise selection explicitly')
    require_candidate_reviews(candidates, notes)
    table = []
    for r in rows:
        cid = r['chunk_id']
        fs = flags[cid]
        note = notes.get(cid, {})
        table.append({'legacy_chunk_id':cid, **{k:r[k] for k in ('chapter','section','source_file','page','content_type')},
            '质量状态':'有疑点待复核' if fs else '自动规则未命中异常；待复核',
            '异常类型':'; '.join(sorted({x[0] for x in fs})),
            '审查说明':'；'.join(x[1] for x in fs) or '自动规则未命中；不代表内容或页码正确',
            '建议处理':'对照原资料复核后决定保留/补充/合并' if fs else '负责人核对原文、页码及授权',
            '是否首批候选':'是（限非商用研究试验；待内容复核）' if cid in candidate_ids else '否',
            '来源授权确认状态':'组员陈述：限非商用研究试验；未独立核验',
            '自动初审状态':'规则筛查完成；AI内容初审已记录' if note else '仅规则筛查；未做AI内容初审',
            '人工复核状态':'未复核', '最终批准状态':'未批准',
            '复核方式':'自动检查 + AI辅助内容初审' if note else '自动检查；未做逐条内容初审',
            '内容初审说明':note.get('note',''),
            '用途': {'concept':'概念问答','algorithm':'算法步骤讲解','code':'代码分析','exercise':'习题讲解'}[r['content_type']] if cid in candidate_ids else '',
            '筛选理由': ('章节/小节及类型覆盖；自动规则未命中异常；' + notes[cid]['note']) if cid in candidate_ids else '',
            '负责人复核结论':'待复核',
            '授权凭据':'组员陈述；见authorization.md',
            '允许对外展示':'否（公开展示/分发未确认）'})
    protect_human_records(list(table[0]))
    # All review/overwrite checks happen before writing any report.
    save('validation_current.json', {'input_file': 'knowledge_base/ds_chunks.jsonl',
         'statistics': stats, 'issues': [vars(i) for i in issues]})
    save('prepare_offline.json', {'mode': 'offline AST of unchanged prepare(); NOT V2 CLI acceptance',
         'hash_byte_convention':'UTF-8 with LF line endings',
         'tool_sha256': digest(tool.read_bytes().replace(b'\r\n', b'\n')),
         'source_jsonl': {'records':len(rows), 'bytes':len(raw), 'sha256':digest(raw)},
         'derived_txt': {k:v for k,v in manifest.items() if k != 'mapping'}, 'validation_errors': []})
    save('preview_mapping.json', manifest['mapping'])
    save('near_duplicates.json', pairs)
    for name, selected in [('review.csv',table),('candidates_100.csv',[r for r in table if r['legacy_chunk_id'] in candidate_ids]),
                           ('issues.csv',[r for r in table if r['异常类型']])]:
        with (OUT/name).open('w',encoding='utf-8-sig',newline='') as f:
            writer=csv.DictWriter(f,fieldnames=list(table[0]),lineterminator='\n');writer.writeheader();writer.writerows(selected)
    save('review_data.json', table)
    blob = subprocess.run(['git','show','HEAD:knowledge_base/ds_chunks.jsonl'],cwd=ROOT,check=True,capture_output=True).stdout
    save('summary.json', {'source_sha256':digest(raw), 'source_bytes':len(raw),
        'hash_byte_convention':'UTF-8 with LF line endings',
        'git_blob_bytes':len(blob),'git_blob_sha256':digest(blob),'lf_normalized_matches_git_blob':raw == blob,
        'statistics':stats,
        'flag_counts': dict(Counter(code for fs in flags.values() for code in sorted({x[0] for x in fs}))),
        'flagged_records':sum(bool(flags[r['chunk_id']]) for r in rows), 'candidate_count':len(candidates),
        'ai_content_review_count':len(notes),
        'authorization': {'status':'member-reported; not independently verified', 'scope':'noncommercial research experiments',
                          'records':len(rows), 'written_evidence_attached':False, 'public_distribution_confirmed':False},
        'review_states': {'ai_content_reviewed':len(notes), 'human_reviewed':0, 'finally_approved':0},
        'public_exports_include_source_text':False, 'public_workbook_tracked':False,
        'candidate_types':dict(Counter(r['content_type'] for r in candidates)),
        'candidate_chapters':dict(Counter(r['chapter'] for r in candidates)),
        'unknown_page_ids':[r['chunk_id'] for r in rows if r['page'] is None]})
    print(json.dumps({'records':len(rows),'candidates':len(candidates),'flags':sum(bool(flags[r['chunk_id']]) for r in rows),
                      'source_sha256':digest(raw)},ensure_ascii=False))

if __name__ == '__main__':
    main()
