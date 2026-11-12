"""Headless HTTPS smoke for the isolated synthetic QA account; no secret output."""
import json
from pathlib import Path
from playwright.sync_api import sync_playwright


def main():
    data=json.loads(Path('/var/lib/ds-v2-parser/qwen-demo/credentials.json').read_text())
    origin='https://qwen.dsassistant.cn'
    with sync_playwright() as playwright:
        browser=playwright.chromium.launch(headless=True)
        context=browser.new_context()
        page=context.new_page()
        api_origins=set()
        def collect(request):
            from urllib.parse import urlsplit
            url=urlsplit(request.url)
            if url.path.startswith('/api/v2/'):api_origins.add(url.scheme+'://'+url.netloc)
        page.on('request',collect)
        page.goto(origin,wait_until='networkidle')
        page.locator('input[type=email]').fill(data['accounts'][0]['email'])
        page.locator('input[type=password]').fill(data['accounts'][0]['password'])
        page.locator('button[type=submit]').click()
        page.get_by_text('Synthetic Qwen Demo',exact=True).wait_for(timeout=20000)
        page.get_by_text('Synthetic Qwen Demo',exact=True).click()
        page.locator('#ask-retrieval-mode').select_option('hybrid')
        page.get_by_label('查询向量').check()
        page.get_by_label('重排序',exact=True).check()
        page.get_by_label('生成回答',exact=True).check()
        page.locator('#ask-query').fill('AVL树的平衡条件是什么？')
        page.get_by_role('button',name='提问',exact=True).click()
        page.locator('[data-testid=answer-success]').wait_for(timeout=65000)
        answer=page.locator('[data-testid=answer-success]').inner_text()
        cookie=context.cookies(origin)
        checks={'model': 'qwen3.8-flash' in answer,'citation':'[S1]' in answer,
                'source':page.locator('.source-item').count()>0,
                'no_import_metadata':'chunk_id' not in answer and 'source_file' not in answer,
                'same_origin_api':api_origins=={origin},'mock_off':page.locator('.mock-hint').count()==0,
                'secure_httponly':any(c['name']=='__Host-ds_v2_session' and c['secure'] and c['httpOnly'] for c in cookie)}
        page.locator('#ask-retrieval-mode').select_option('bm25')
        page.locator('#ask-query').fill('unmatchedzzzzz')
        page.get_by_role('button',name='提问',exact=True).click()
        page.locator('[data-testid=answer-refused]').wait_for(timeout=30000)
        checks['refusal']=True
        page.get_by_role('button',name='退出',exact=True).click()
        page.locator('input[type=email]').wait_for(timeout=20000);checks['logout']=True
        page.locator('input[type=email]').fill(data['accounts'][1]['email'])
        page.locator('input[type=password]').fill(data['accounts'][1]['password'])
        page.locator('button[type=submit]').click()
        page.get_by_role('button',name='退出',exact=True).wait_for(timeout=20000)
        page.get_by_text('还没有可用的知识库',exact=False).wait_for(timeout=20000)
        checks['private_hidden']=page.get_by_text('Synthetic Qwen Demo',exact=True).count()==0
        status=page.evaluate("async (id) => (await fetch('/api/v2/knowledge-bases/'+id,{credentials:'include'})).status",data['knowledge_base_id'])
        checks['cross_user_404']=status==404
        page.get_by_role('button',name='退出',exact=True).click()
        browser.close()
    print('BROWSER_CHECKS',json.dumps(checks,sort_keys=True),flush=True)
    return 0 if all(checks.values()) else 1


if __name__=='__main__':
    try:raise SystemExit(main())
    except Exception as error:
        print('BROWSER_FAILED',type(error).__name__,flush=True)
        raise SystemExit(1) from None
