from __future__ import annotations

import argparse
import csv
import html
import os
import shutil
import threading
import webbrowser
from collections import defaultdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse


PROJECT_ROOT = Path(__file__).resolve().parents[1]

SOURCE = PROJECT_ROOT / "tests/heldout_annotation_blind_v1.csv"
FACETS = PROJECT_ROOT / "tests/heldout_annotation_facets_v1.csv"
WORKING = PROJECT_ROOT / "tests/heldout_annotation_working_v1.csv"
BACKUP = PROJECT_ROOT / "tests/heldout_annotation_working_v1.last.bak"

LOCK = threading.Lock()


def read_csv(path: Path):
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        return list(reader), list(reader.fieldnames or [])


def write_csv_atomic(path: Path, rows, fieldnames):
    tmp = path.with_suffix(path.suffix + ".tmp")

    if path.exists():
        shutil.copy2(path, BACKUP)

    with tmp.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    os.replace(tmp, path)


def prepare_working_file():
    if not SOURCE.exists():
        raise RuntimeError(f"source file not found: {SOURCE}")

    if not FACETS.exists():
        raise RuntimeError(f"facet file not found: {FACETS}")

    if not WORKING.exists():
        shutil.copy2(SOURCE, WORKING)


def load_state():
    rows, fields = read_csv(WORKING)

    required = {
        "question_id",
        "candidate_id",
        "question",
        "reference_answer",
        "chunk_id",
        "chapter",
        "section",
        "content_type",
        "source_file",
        "chunk_text",
        "relevance_label",
        "supported_facets",
        "annotation_note",
    }

    missing = required - set(fields)
    if missing:
        raise RuntimeError(
            f"working CSV missing columns: {sorted(missing)}"
        )

    facet_rows, _ = read_csv(FACETS)
    facets = defaultdict(list)

    for r in facet_rows:
        facets[r["question_id"]].append(
            (r["facet_id"], r["facet_text"])
        )

    def facet_num(item):
        fid = item[0]
        try:
            return int(fid[1:])
        except Exception:
            return 9999

    for qid in facets:
        facets[qid].sort(key=facet_num)

    return rows, fields, facets


def normalized_selected(raw_values):
    result = []
    seen = set()

    for value in raw_values:
        value = value.strip()
        if value and value not in seen:
            result.append(value)
            seen.add(value)

    return result


def auto_label(selected, all_facet_ids):
    selected_set = set(selected)
    all_set = set(all_facet_ids)

    if not selected_set:
        return "0"

    if all_set and selected_set == all_set:
        return "2"

    return "1"


def status_text(row):
    label = (row.get("relevance_label") or "").strip()
    if label == "":
        return "未标注"
    return "已保存"


def next_unlabeled(rows, current):
    n = len(rows)

    for j in range(current + 1, n):
        if not (rows[j].get("relevance_label") or "").strip():
            return j

    for j in range(0, current):
        if not (rows[j].get("relevance_label") or "").strip():
            return j

    return current


def page_html(index: int, message: str = ""):
    rows, _, facets_map = load_state()

    n = len(rows)
    if n == 0:
        return "<h1>No annotation rows.</h1>"

    index = max(0, min(index, n - 1))
    row = rows[index]

    qid = row["question_id"]
    facets = facets_map.get(qid, [])
    selected = {
        x.strip()
        for x in (row.get("supported_facets") or "").split("|")
        if x.strip()
    }

    completed = sum(
        bool((r.get("relevance_label") or "").strip())
        for r in rows
    )

    prev_i = max(0, index - 1)
    next_i = min(n - 1, index + 1)
    unlabeled_i = next_unlabeled(rows, index)

    facet_html = []

    for fid, text in facets:
        checked = " checked" if fid in selected else ""
        facet_html.append(
            f"""
            <label class="facet">
              <input type="checkbox"
                     name="facet"
                     value="{html.escape(fid)}"{checked}>
              <span class="fid">{html.escape(fid)}</span>
              <span>{html.escape(text)}</span>
            </label>
            """
        )

    current_label = (row.get("relevance_label") or "").strip()
    if current_label:
        label_display = f"自动标签：{html.escape(current_label)}"
    else:
        label_display = "自动标签：尚未保存"

    msg_html = (
        f'<div class="message">{html.escape(message)}</div>'
        if message
        else ""
    )

    return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>Held-out Facet Annotation</title>
<style>
body {{
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI",
                 "PingFang SC", "Microsoft YaHei", sans-serif;
    margin: 0;
    background: #f5f5f7;
    color: #1d1d1f;
}}

.container {{
    width: min(1180px, 94vw);
    margin: 24px auto 60px;
}}

.topbar {{
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: 16px;
    background: white;
    padding: 14px 18px;
    border-radius: 12px;
    position: sticky;
    top: 8px;
    z-index: 10;
    box-shadow: 0 1px 8px rgba(0,0,0,.07);
}}

.progress {{
    font-weight: 600;
}}

.meta {{
    font-size: 14px;
    color: #666;
}}

.card {{
    background: white;
    margin-top: 16px;
    padding: 20px 22px;
    border-radius: 12px;
    box-shadow: 0 1px 5px rgba(0,0,0,.05);
}}

h2 {{
    font-size: 18px;
    margin-top: 0;
}}

.question {{
    font-size: 19px;
    line-height: 1.7;
    font-weight: 600;
}}

.answer {{
    line-height: 1.7;
    white-space: pre-wrap;
}}

.chunk {{
    line-height: 1.8;
    white-space: pre-wrap;
    background: #f7f7f9;
    padding: 15px;
    border-radius: 8px;
}}

.facet {{
    display: flex;
    gap: 10px;
    align-items: flex-start;
    padding: 11px 12px;
    margin: 8px 0;
    border: 1px solid #ddd;
    border-radius: 8px;
    cursor: pointer;
    line-height: 1.55;
}}

.facet:hover {{
    background: #f5f7fa;
}}

.facet input {{
    margin-top: 5px;
    transform: scale(1.25);
}}

.fid {{
    font-weight: 700;
    min-width: 30px;
}}

textarea {{
    width: 100%;
    min-height: 72px;
    box-sizing: border-box;
    padding: 10px;
    font: inherit;
}}

.buttons {{
    display: flex;
    flex-wrap: wrap;
    gap: 10px;
    margin-top: 18px;
}}

button, .button {{
    border: 0;
    border-radius: 8px;
    padding: 10px 16px;
    font-size: 15px;
    cursor: pointer;
    text-decoration: none;
    display: inline-block;
}}

.primary {{
    background: #1668dc;
    color: white;
}}

.zero {{
    background: #444;
    color: white;
}}

.secondary {{
    background: #e9e9ed;
    color: #222;
}}

.message {{
    margin-top: 14px;
    padding: 10px 12px;
    background: #eaf6ea;
    border-radius: 8px;
}}

.rule {{
    color: #555;
    line-height: 1.65;
    font-size: 14px;
}}

.status {{
    font-size: 14px;
    color: #555;
}}

.jump {{
    display: flex;
    gap: 6px;
    align-items: center;
}}

.jump input {{
    width: 70px;
    padding: 7px;
}}
</style>
</head>

<body>
<div class="container">

<div class="topbar">
  <div>
    <div class="progress">
      已完成 {completed} / {n}
    </div>
    <div class="meta">
      当前 {index + 1} / {n}
      · {html.escape(qid)}
      · {html.escape(row["candidate_id"])}
      · {html.escape(status_text(row))}
    </div>
  </div>

  <div class="jump">
    <form method="get" action="/">
      <span>跳到第</span>
      <input name="i" type="number"
             min="1" max="{n}" value="{index + 1}">
      <button class="secondary" type="submit">跳转</button>
    </form>
  </div>
</div>

{msg_html}

<div class="card">
  <h2>Question</h2>
  <div class="question">
    {html.escape(row["question"])}
  </div>
</div>

<div class="card">
  <h2>Reference answer</h2>
  <div class="answer">
    {html.escape(row["reference_answer"])}
  </div>
</div>

<form method="post" action="/save">

<input type="hidden" name="index" value="{index}">

<div class="card">
  <h2>Core facets</h2>

  <div class="rule">
    只勾选当前 chunk 能直接支持，或结合问题即可一步明确推导出的要点。
    不要使用外部知识补全。
  </div>

  {''.join(facet_html)}

  <div class="status">
    {label_display}
  </div>
</div>

<div class="card">
  <h2>Candidate chunk</h2>

  <div class="meta">
    chunk_id: {html.escape(row["chunk_id"])}
    · {html.escape(row["chapter"])}
    · {html.escape(row["section"])}
    · {html.escape(row["content_type"])}
  </div>

  <div class="chunk">
    {html.escape(row["chunk_text"])}
  </div>
</div>

<div class="card">
  <h2>Annotation note（可选）</h2>
  <textarea name="note"
    placeholder="只有歧义、边界情况或需要复核时填写">{html.escape(row.get("annotation_note") or "")}</textarea>

  <div class="buttons">
    <button type="submit"
            name="action"
            value="save_next"
            class="primary">
      保存并下一条
    </button>

    <button type="submit"
            name="action"
            value="zero_next"
            class="zero">
      0：无任何 facet，并下一条
    </button>

    <button type="submit"
            name="action"
            value="save_stay"
            class="secondary">
      仅保存
    </button>

    <a class="button secondary" href="/?i={prev_i + 1}">
      上一条
    </a>

    <a class="button secondary" href="/?i={next_i + 1}">
      下一条
    </a>

    <a class="button secondary" href="/?i={unlabeled_i + 1}">
      下一个未标
    </a>
  </div>
</div>

</form>

<div class="card rule">
  <b>自动标签规则</b><br>
  不勾任何 facet → 0<br>
  勾选部分 facet → 1<br>
  勾选全部 facet → 2<br><br>

  快捷键：<br>
  Ctrl/Cmd + Enter：保存并下一条<br>
  Ctrl/Cmd + 0：标 0 并下一条<br>
  Alt + ← / →：上一条 / 下一条
</div>

</div>

<script>
document.addEventListener("keydown", function(e) {{
    const tag = document.activeElement.tagName.toLowerCase();

    if ((e.ctrlKey || e.metaKey) && e.key === "Enter") {{
        e.preventDefault();
        document.querySelector(
            'button[value="save_next"]'
        ).click();
    }}

    if ((e.ctrlKey || e.metaKey) && e.key === "0") {{
        e.preventDefault();
        document.querySelector(
            'button[value="zero_next"]'
        ).click();
    }}

    if (tag !== "textarea" && e.altKey && e.key === "ArrowLeft") {{
        window.location.href = "/?i={prev_i + 1}";
    }}

    if (tag !== "textarea" && e.altKey && e.key === "ArrowRight") {{
        window.location.href = "/?i={next_i + 1}";
    }}
}});
</script>

</body>
</html>
"""


class Handler(BaseHTTPRequestHandler):

    def send_html(self, text, status=200):
        data = text.encode("utf-8")
        self.send_response(status)
        self.send_header(
            "Content-Type",
            "text/html; charset=utf-8",
        )
        self.send_header(
            "Content-Length",
            str(len(data)),
        )
        self.end_headers()
        self.wfile.write(data)

    def redirect(self, index, message=""):
        query = {"i": index + 1}
        if message:
            query["msg"] = message

        self.send_response(303)
        self.send_header(
            "Location",
            "/?" + urlencode(query),
        )
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)

        if parsed.path != "/":
            self.send_error(404)
            return

        params = parse_qs(parsed.query)

        try:
            requested = int(params.get("i", ["1"])[0])
        except ValueError:
            requested = 1

        index = max(0, requested - 1)
        message = params.get("msg", [""])[0]

        self.send_html(page_html(index, message))

    def do_POST(self):
        parsed = urlparse(self.path)

        if parsed.path != "/save":
            self.send_error(404)
            return

        length = int(
            self.headers.get("Content-Length", "0")
        )
        body = self.rfile.read(length).decode("utf-8")
        params = parse_qs(body, keep_blank_values=True)

        try:
            index = int(params["index"][0])
        except Exception:
            self.send_error(400, "invalid index")
            return

        action = params.get(
            "action", ["save_next"]
        )[0]

        note = params.get("note", [""])[0].strip()

        with LOCK:
            rows, fields, facets_map = load_state()

            if not 0 <= index < len(rows):
                self.send_error(400, "index out of range")
                return

            row = rows[index]
            qid = row["question_id"]

            allowed = [
                fid for fid, _ in facets_map.get(qid, [])
            ]

            if action == "zero_next":
                selected = []
            else:
                selected = normalized_selected(
                    params.get("facet", [])
                )

            invalid = set(selected) - set(allowed)

            if invalid:
                self.send_error(
                    400,
                    f"invalid facets: {sorted(invalid)}",
                )
                return

            label = auto_label(
                selected,
                allowed,
            )

            row["supported_facets"] = "|".join(
                fid for fid in allowed
                if fid in set(selected)
            )
            row["relevance_label"] = label
            row["annotation_note"] = note

            write_csv_atomic(
                WORKING,
                rows,
                fields,
            )

            if action in {"save_next", "zero_next"}:
                target = min(index + 1, len(rows) - 1)
            else:
                target = index

        self.redirect(
            target,
            f"已保存 {qid} / {row['candidate_id']}，自动标签={label}",
        )

    def log_message(self, fmt, *args):
        return


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--port",
        type=int,
        default=8765,
    )
    parser.add_argument(
        "--no-browser",
        action="store_true",
    )
    args = parser.parse_args()

    prepare_working_file()

    rows, _, _ = load_state()

    print("===== HELD-OUT FACET ANNOTATOR =====")
    print("source =", SOURCE.relative_to(PROJECT_ROOT))
    print("working =", WORKING.relative_to(PROJECT_ROOT))
    print("rows =", len(rows))
    print(f"url = http://127.0.0.1:{args.port}")
    print()
    print("自动规则：")
    print("  no facets -> label 0")
    print("  partial facets -> label 1")
    print("  all facets -> label 2")
    print()
    print("Ctrl+C 可停止服务，进度已实时写入 CSV。")

    server = ThreadingHTTPServer(
        ("127.0.0.1", args.port),
        Handler,
    )

    if not args.no_browser:
        threading.Timer(
            0.6,
            lambda: webbrowser.open(
                f"http://127.0.0.1:{args.port}"
            ),
        ).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nserver stopped")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
