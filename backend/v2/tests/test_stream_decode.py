import json
import pytest
from backend.v2.services.stream_decode import SSEDecoder,AnswerPrefix,StreamDecodeError


@pytest.mark.parametrize('step',[1,2,3,7,64])
def test_sse_multibyte_boundaries_comments_crlf_and_multiline(step):
    wire=': keepalive\r\ndata: 中文😀\r\ndata: second\r\n\r\ndata: [DONE]\r\r'.encode()
    parser=SSEDecoder();events=[]
    for i in range(0,len(wire),step):events+=parser.feed(wire[i:i+step])
    events+=parser.feed(b'',final=True)
    assert events==['中文😀\nsecond','[DONE]']


@pytest.mark.parametrize('step',[1,2,3,11,64])
@pytest.mark.parametrize('answer',['中文😀 **加粗** [S1]','quote " and \\ newline\n\tcode', '<script>not executed</script>', 'a\u2028b'])
def test_answer_prefix_decodes_only_top_level_answer_and_all_escapes(step,answer):
    raw=json.dumps({'status':'answered','answer':answer,'used_source_ids':['[S1]']},ensure_ascii=True)
    parser=AnswerPrefix(32000);parts=[]
    for i in range(0,len(raw),step):parts.append(parser.feed(raw[i:i+step]))
    assert ''.join(parts)==answer and parser.raw==raw
    if step==1:assert sum(bool(p) for p in parts)>1


def test_answer_must_not_be_emitted_until_status_is_answered():
    p=AnswerPrefix(1000)
    assert p.feed('{"answer":"secret","status":')==''
    assert p.feed('"answered","used_source_ids":["[S1]"]}')=='secret'
    p=AnswerPrefix(1000)
    assert p.feed('{"status":"insufficient_evidence","answer":"ignore","used_source_ids":[]}')==''
    p=AnswerPrefix(1000)
    assert p.feed('{"metadata":{"answer":"not the top level"},"status":"answered","answer":"real"}')=='real'


@pytest.mark.parametrize('raw',[
    '{"status":"answered","answer":"bad\\q"}',
    '{"status":"answered","answer":"bad\\ud800x"}',
    '{"status":"answered","answer":"bad\\udc00"}',
    '{"status":"answered","answer":"bad\\u0000"}',
    '{"status":"answered","answer":"one","answer":"two"}',
    '[{"answer":"not object"}]',
    '{"status":"answered","answer":99}',
])
def test_malformed_json_strings_and_duplicates_fail_closed(raw):
    p=AnswerPrefix(1000)
    with pytest.raises((ValueError,UnicodeError)):p.feed(raw)


def test_limits_incomplete_utf8_and_frames():
    with pytest.raises(StreamDecodeError):SSEDecoder().feed(b'data:'+b'a'*65537)
    with pytest.raises(UnicodeError):SSEDecoder().feed(b'\xff')
    with pytest.raises(UnicodeError):SSEDecoder().feed(b'\xe4',final=True)
    with pytest.raises(StreamDecodeError):SSEDecoder().feed(b'data: incomplete',final=True)
    with pytest.raises(StreamDecodeError):AnswerPrefix(4).feed('12345')


def test_optional_utf8_bom_is_supported_across_byte_boundaries():
    parser=SSEDecoder();events=[]
    for byte in b'\xef\xbb\xbfdata: hello\n\n':events+=parser.feed(bytes([byte]))
    assert events==['hello']
