"""HTTPS UI regression. A synthetic response tests Markdown; the Qwen request is real."""
import json
import os
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT=Path('/var/lib/ds-v2-parser/qwen-demo')

def main():
    data=json.loads((ROOT/'credentials.json').read_text())
    course=json.loads((ROOT/'course-import-state.json').read_text())
    origin='https://qwen.dsassistant.cn'
    checks={};api_origins=set()
    with sync_playwright() as playwright:
        browser=playwright.chromium.launch(headless=True)
        context=browser.new_context(viewport={'width':1280,'height':900})
        page=context.new_page()
        def collect(request):
            from urllib.parse import urlsplit
            u=urlsplit(request.url)
            if u.path.startswith('/api/v2/'):api_origins.add(u.scheme+'://'+u.netloc)
        page.on('request',collect)
        page.goto(origin,wait_until='networkidle')
        page.locator('input[type=email]').fill(data['accounts'][0]['email'])
        page.locator('input[type=password]').fill(data['accounts'][0]['password'])
        page.locator('button[type=submit]').click()
        page.get_by_text('V1 课程知识库 Qwen 演示',exact=True).wait_for(timeout=20000)
        page.get_by_text('V1 课程知识库 Qwen 演示',exact=True).click()
        checks['no_cloud_checkboxes']=page.get_by_text('本次请求的云端用途',exact=False).count()==0
        page.locator('#ask-query').fill('栈和队列有什么区别？')
        page.get_by_role('button',name='提问',exact=True).click()
        page.locator('[data-testid=answer-success]').wait_for(timeout=90000)
        answer=page.locator('[data-testid=answer-success]')
        checks['real_qwen']='qwen3.8-flash' in answer.inner_text()
        checks['sources_initially_folded']=not page.locator('.sources').evaluate('(e) => e.open')
        page.locator('button.cite').first.click()
        checks['citation_expands']=page.locator('.sources').evaluate('(e) => e.open') and page.locator('.source-item.is-active').count()==1
        checks['source_labels']=all('v1-course-' not in name for name in page.locator('.source-name').all_text_contents())
        screenshot=ROOT/'ux-qwen-answer.png';answer.screenshot(path=str(screenshot));os.chmod(screenshot,0o600)
        # Intercept only this synthetic answer to exercise rendering cases the model may not emit.
        def fixture(route):
            payload=route.request.post_data_json
            if payload.get('query')!='markdown-rendering-fixture': return route.continue_()
            response={'status':'answered','reason':None,'answer':'# 标题\n\n**粗体** 与 *斜体* [S1]\n\n- 列表\n\n`[S1]`\n\n```python\nprint("[S1]")\n```\n\n| A | B |\n|---|---|\n| 1 | 2 |\n\n<img src=x onerror=alert(1)>',
                'sources':[{'citation_id':'[S1]','chunk_id':'11111111-1111-4111-8111-111111111111','document_id':'22222222-2222-4222-8222-222222222222','knowledge_base_id':course['kb'],'source_filename':'fixture.pdf','page_number':None,'section_title':'示例','chunk_index':0,'content_hash':'0'*64,'generation':1,'index_revision':1,'embedding_space_id':'fixture'}],
                'retrieval_mode':'hybrid','answer_mode':'qa','rerank_applied':False,'generation_model':'fixture','execution_performed':False,'latency_ms':1}
            route.fulfill(status=200,content_type='application/json',body=json.dumps(response,ensure_ascii=False))
        page.route('**/api/v2/rag/ask',fixture)
        page.locator('#ask-query').fill('markdown-rendering-fixture')
        page.get_by_role('button',name='提问',exact=True).click()
        page.locator('.answer-text h1').wait_for(timeout=30000)
        area=page.locator('.answer-text')
        checks['fixture_markdown']=area.locator('strong').count()==1 and area.locator('li').count()==1 and area.locator('table').count()==1 and area.locator('pre code.language-python').count()==1
        checks['fixture_code_citations_inert']=area.locator('button.cite').count()==1 and area.locator('code button').count()==0
        checks['fixture_html_safe']=area.locator('img').count()==0
        page.unroute('**/api/v2/rag/ask',fixture)
        page.locator('summary').filter(has_text='高级选项').click()
        page.locator('#ask-retrieval-mode').select_option('bm25')
        page.locator('#ask-query').fill('unmatchedzzzzz')
        page.get_by_role('button',name='提问',exact=True).click()
        page.locator('[data-testid=answer-refused]').wait_for(timeout=30000);checks['refusal']=True
        checks['same_origin_api']=api_origins=={origin}
        checks['mock_off']=page.locator('.mock-hint').count()==0
        cookies=context.cookies(origin)
        checks['secure_httponly']=any(c['name']=='__Host-ds_v2_session' and c['secure'] and c['httpOnly'] for c in cookies)
        page.get_by_role('button',name='退出',exact=True).click()
        page.locator('input[type=email]').wait_for(timeout=20000);checks['logout']=True
        page.locator('input[type=email]').fill(data['accounts'][1]['email'])
        page.locator('input[type=password]').fill(data['accounts'][1]['password'])
        page.locator('button[type=submit]').click();page.get_by_role('button',name='退出',exact=True).wait_for(timeout=20000)
        checks['cross_user_404']=page.evaluate("async (id) => (await fetch('/api/v2/knowledge-bases/'+id,{credentials:'include'})).status",course['kb'])==404
        page.get_by_role('button',name='退出',exact=True).click();browser.close()
    print('UX_BROWSER_CHECKS',json.dumps(checks,sort_keys=True),flush=True)
    return 0 if all(checks.values()) else 1

if __name__=='__main__':
    try:raise SystemExit(main())
    except Exception as error:
        print('UX_BROWSER_FAILED',type(error).__name__,flush=True)
        raise SystemExit(1) from None
