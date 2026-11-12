import json

import pytest

from backend.v2.schemas.rag import AnswerDraft
from backend.v2.services.answer_validation import AnswerValidationError, validate_answer
from backend.v2.services.generation_provider import DeterministicProvider


def test_course_metadata_is_not_emitted_as_source_claim():
    blocks = [{'citation_id': '[S1]', 'content': 'V1 来源 course.pdf 第 12 页\n数据结构课程内容'}]
    messages = [{'content': ''}, {'content': ''}, {'content': json.dumps({'blocks': blocks})}]
    result = DeterministicProvider().generate(messages, before_attempt=lambda: None)
    draft = AnswerDraft.model_validate_json(result.content)
    assert validate_answer(draft, blocks) == ['[S1]']
    assert '数据结构课程内容' in draft.answer
    assert 'course.pdf' not in draft.answer and '第 12 页' not in draft.answer


@pytest.mark.parametrize('text', ['虚构.pdf [S1]', '第 99 页 [S1]'])
def test_source_claims_remain_rejected(text):
    draft = AnswerDraft(status='answered', answer=text, used_source_ids=['[S1]'])
    with pytest.raises(AnswerValidationError, match='unsupported_source_metadata'):
        validate_answer(draft, [{'citation_id': '[S1]'}])


def test_empty_evidence_refuses():
    messages = [{'content': ''}, {'content': ''}, {'content': '{"blocks": []}'}]
    draft = AnswerDraft.model_validate_json(DeterministicProvider().generate(messages, before_attempt=lambda: None).content)
    assert draft.status == 'insufficient_evidence' and draft.used_source_ids == []
