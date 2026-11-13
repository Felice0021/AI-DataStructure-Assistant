"""Offline regression checks for the public audit exports; no paid or backend calls."""
import contextlib
import csv
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('course_audit_review', HERE / 'review.py')
review = importlib.util.module_from_spec(spec)
spec.loader.exec_module(review)


class ReviewChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = {r['chunk_id']: r for r in map(json.loads, review.SOURCE.read_text(encoding='utf8').splitlines())}
        cls.notes = json.loads((HERE / 'content_notes.json').read_text(encoding='utf8'))
        with (review.OUT / 'review.csv').open(encoding='utf-8-sig', newline='') as handle:
            cls.rows = list(csv.DictReader(handle))
        with (review.OUT / 'candidates_100.csv').open(encoding='utf-8-sig', newline='') as handle:
            cls.candidates = list(csv.DictReader(handle))

    def test_candidate_count_ids_and_ai_coverage(self):
        self.assertEqual(len(self.rows), 1010)
        self.assertEqual(len(self.candidates), 100)
        self.assertEqual(len({r['legacy_chunk_id'] for r in self.rows}), 1010)
        self.assertEqual(len({r['legacy_chunk_id'] for r in self.candidates}), 100)
        review.require_candidate_reviews([{'chunk_id':r['legacy_chunk_id']} for r in self.candidates], self.notes)

    def test_missing_blank_or_flagged_ai_review_is_rejected(self):
        candidate = [{'chunk_id':self.candidates[0]['legacy_chunk_id']}]
        cid = candidate[0]['chunk_id']
        for notes in ({}, {cid:{'note':' '}}, {cid:{'note':'review','issue':'open issue'}}):
            with self.subTest(notes=notes), self.assertRaisesRegex(ValueError, 'explicit AI content review'):
                review.require_candidate_reviews(candidate, notes)

    def test_source_metadata_and_separate_states(self):
        for row in self.rows:
            source = self.source[row['legacy_chunk_id']]
            for key in ('chapter','section','source_file','content_type'):
                self.assertEqual(row[key], source[key])
            self.assertEqual(row['page'], '' if source['page'] is None else str(source['page']))
            self.assertEqual(row['人工复核状态'], '未复核')
            self.assertEqual(row['最终批准状态'], '未批准')
            self.assertIn('规则筛查', row['自动初审状态'])
            self.assertIn('未独立核验', row['来源授权确认状态'])
        exported = json.loads((review.OUT / 'review_data.json').read_text(encoding='utf8'))
        self.assertEqual(len(exported),1010)
        self.assertTrue(all('text' not in row for row in exported))
        summary = json.loads((review.OUT / 'summary.json').read_text(encoding='utf8'))
        self.assertFalse(summary['authorization']['public_distribution_confirmed'])
        self.assertEqual(summary['review_states']['finally_approved'], 0)

    def test_public_artifacts_have_no_full_source_body_or_workbook(self):
        # Scan every current public textual deliverable, including notes and scripts.
        paths = [p for folder in (review.OUT, HERE) for p in folder.iterdir()
                 if p.suffix in {'.csv','.json','.md','.py'} and p.is_file()]
        bodies = {''.join(row['text'].split()) for row in self.source.values()}
        for path in paths:
            text = path.read_text(encoding='utf-8-sig')
            if path.suffix == '.csv':
                with path.open(encoding='utf-8-sig', newline='') as handle:
                    self.assertNotIn('text', csv.DictReader(handle).fieldnames)
            normalized = ''.join(text.split())
            # JSON escaped newlines must also be checked after decoding.
            if path.suffix == '.json':
                def strings(value):
                    if isinstance(value,str): yield value
                    elif isinstance(value,list):
                        for item in value: yield from strings(item)
                    elif isinstance(value,dict):
                        for item in value.values(): yield from strings(item)
                normalized += ''.join(''.join(s.split()) for s in strings(json.loads(text)))
            self.assertFalse(any(body in normalized for body in bodies),path.name)
        workbook = (HERE / 'course_review.xlsx').relative_to(review.ROOT).as_posix()
        tracked = subprocess.run(['git','ls-files','--',workbook],
                                 cwd=review.ROOT,capture_output=True,text=True,check=True).stdout
        self.assertEqual(tracked.strip(),'','Source-containing workbook must not remain tracked')

    def test_regeneration_is_stable_and_protects_human_edits(self):
        # TemporaryDirectory checks use only this explicitly named test directory.
        with tempfile.TemporaryDirectory(prefix='audit-review-test-') as temporary:
            out = Path(temporary).resolve()
            self.assertEqual(out.parent, Path(tempfile.gettempdir()).resolve())
            self.assertTrue(out.name.startswith('audit-review-test-'))
            with patch.object(review,'OUT',out), contextlib.redirect_stdout(io.StringIO()):
                review.main()
                before = {p.name:p.read_bytes() for p in out.iterdir()}
                review.main()
                self.assertEqual(before,{p.name:p.read_bytes() for p in out.iterdir()})
                crlf_source = out / 'input-crlf.jsonl'
                crlf_source.write_bytes(review.SOURCE.read_bytes().replace(b'\r\n',b'\n').replace(b'\n',b'\r\n'))
                with patch.object(review,'SOURCE',crlf_source):
                    review.main()
                self.assertTrue(all((out/name).read_bytes()==data for name,data in before.items()))
                crlf_source.unlink()
                path = out / 'review.csv'
                with path.open(encoding='utf-8-sig',newline='') as handle:
                    edited = list(csv.DictReader(handle))
                edited[0]['负责人复核结论'] = '已由负责人复核'
                with path.open('w',encoding='utf-8-sig',newline='') as handle:
                    writer=csv.DictWriter(handle,fieldnames=list(edited[0]),lineterminator='\n')
                    writer.writeheader();writer.writerows(edited)
                preserved = {p.name:p.read_bytes() for p in out.iterdir()}
                with self.assertRaisesRegex(ValueError,'human-edited'):
                    review.main()
                self.assertEqual(preserved,{p.name:p.read_bytes() for p in out.iterdir()})


if __name__ == '__main__':
    unittest.main(verbosity=2)
