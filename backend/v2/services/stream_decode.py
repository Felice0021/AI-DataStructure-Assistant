"""Bounded SSE framing and JSON answer-prefix decoding. No raw JSON reaches the UI."""
import codecs
import json


class StreamDecodeError(ValueError):
    pass


def strict_json(value):
    def pairs(items):
        result={}
        for key,item in items:
            if key in result:raise StreamDecodeError('duplicate_field')
            result[key]=item
        return result
    def constant(_):raise StreamDecodeError('invalid_number')
    return json.loads(value,object_pairs_hook=pairs,parse_constant=constant)


class SSEDecoder:
    def __init__(self):
        self.decoder=codecs.getincrementaldecoder('utf-8-sig')('strict')
        self.line='';self.data=[];self.event_bytes=0;self.wire_bytes=0;self.events=0;self.cr=False

    def feed(self,raw,*,final=False):
        self.wire_bytes+=len(raw)
        if self.wire_bytes>4*1024*1024:raise StreamDecodeError('wire_limit')
        text=self.decoder.decode(raw,final=final);result=[]
        for char in text:
            if self.cr:
                self.cr=False
                if char=='\n':continue
            if char in '\r\n':
                if char=='\r':self.cr=True
                line=self.line;self.line=''
                if not line:
                    if self.data:
                        self.events+=1
                        if self.events>8192:raise StreamDecodeError('event_limit')
                        result.append('\n'.join(self.data))
                    self.data=[];self.event_bytes=0
                elif line.startswith('data:'):
                    self.data.append(line[5:].removeprefix(' '))
                # Other SSE fields and comments do not become model content.
            else:
                self.line+=char;self.event_bytes+=len(char.encode('utf8'))
                if self.event_bytes>65536:raise StreamDecodeError('event_size_limit')
        if final and (self.line or self.data):raise StreamDecodeError('incomplete_event')
        return result


class AnswerPrefix:
    """Only decodes a top-level JSON string named answer; other values use stdlib JSON.

    This is a preview lexer, never the answer validator. Final AnswerDraft parsing remains
    mandatory, including duplicate keys, exact fields, citations and source validation.
    """
    def __init__(self,limit):
        self.raw='';self.pos=0;self.state='start';self.key=None;self.seen=set();self.status=None
        self.answer='';self.sent=0;self.limit=limit;self.raw_bytes=0;self.answer_bytes=0
        self.escape=False;self.hex=None;self.high=None;self.expect_low=0
        self.decoder=json.JSONDecoder(object_pairs_hook=self._pairs,parse_constant=self._constant)

    @staticmethod
    def _constant(_):raise StreamDecodeError('invalid_number')
    @staticmethod
    def _pairs(items):
        result={}
        for key,value in items:
            if key in result:raise StreamDecodeError('duplicate_field')
            result[key]=value
        return result

    def _append(self,char):
        if ord(char)<32 and char not in '\n\r\t':raise StreamDecodeError('invalid_control')
        self.answer_bytes+=len(char.encode('utf8'))
        if self.answer_bytes>self.limit:raise StreamDecodeError('answer_limit')
        self.answer+=char

    def _string_char(self,char):
        if self.expect_low:
            expected='\\' if self.expect_low==1 else 'u'
            if char!=expected:raise StreamDecodeError('invalid_surrogate')
            self.expect_low+=1
            if self.expect_low==3:self.expect_low=0;self.hex=''
        elif self.hex is not None:
            if char not in '0123456789abcdefABCDEF':raise StreamDecodeError('invalid_escape')
            self.hex+=char
            if len(self.hex)==4:
                code=int(self.hex,16);self.hex=None
                if self.high is not None:
                    if not 0xdc00<=code<=0xdfff:raise StreamDecodeError('invalid_surrogate')
                    self._append(chr(0x10000+((self.high-0xd800)<<10)+code-0xdc00));self.high=None
                elif 0xd800<=code<=0xdbff:self.high=code;self.expect_low=1
                elif 0xdc00<=code<=0xdfff:raise StreamDecodeError('invalid_surrogate')
                else:self._append(chr(code))
        elif self.escape:
            self.escape=False
            if char=='u':self.hex=''
            elif char in '"\\/bfnrt':self._append({'b':'\b','f':'\f','n':'\n','r':'\r','t':'\t'}.get(char,char))
            else:raise StreamDecodeError('invalid_escape')
        elif char=='\\':self.escape=True
        elif char=='"':self.state='comma'
        elif ord(char)<32:raise StreamDecodeError('invalid_string')
        else:self._append(char)

    def feed(self,part):
        self.raw_bytes+=len(part.encode('utf8'))
        if self.raw_bytes>self.limit:raise StreamDecodeError('completion_limit')
        self.raw+=part
        while self.pos<len(self.raw):
            char=self.raw[self.pos]
            if self.state=='answer':
                self.pos+=1;self._string_char(char);continue
            if char.isspace():self.pos+=1;continue
            if self.state=='start':
                if char!='{':raise StreamDecodeError('expected_object')
                self.pos+=1;self.state='key'
            elif self.state=='key':
                if char=='}':self.pos+=1;self.state='done';continue
                try:value,end=self.decoder.raw_decode(self.raw,self.pos)
                except json.JSONDecodeError:break
                if not isinstance(value,str) or value in self.seen:raise StreamDecodeError('invalid_key')
                self.key=value;self.seen.add(value);self.pos=end;self.state='colon'
            elif self.state=='colon':
                if char!=':':raise StreamDecodeError('expected_colon')
                self.pos+=1;self.state='value'
            elif self.state=='value':
                if self.key=='answer':
                    if char!='"':raise StreamDecodeError('expected_answer_string')
                    self.pos+=1;self.state='answer'
                else:
                    try:value,end=self.decoder.raw_decode(self.raw,self.pos)
                    except json.JSONDecodeError:break
                    if end==len(self.raw):break # a scalar may continue in the next chunk
                    if self.key=='status':self.status=value
                    self.pos=end;self.state='comma'
            elif self.state=='comma':
                if char==',':self.pos+=1;self.state='key'
                elif char=='}':self.pos+=1;self.state='done'
                else:raise StreamDecodeError('expected_separator')
            else:raise StreamDecodeError('trailing_json')
        if self.status=='answered':
            delta=self.answer[self.sent:];self.sent=len(self.answer);return delta
        return ''
