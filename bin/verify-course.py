"""逐章真跑一遍两门课的代码，确认讲义里的每一格都能运行。"""
import json, sys, urllib.request

BASE = "http://127.0.0.1:9188/api/v1"

def get(path):
    with urllib.request.urlopen(BASE + path, timeout=60) as r:
        return json.load(r)

def post(path, body, timeout=300):
    req = urllib.request.Request(
        BASE + path, data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)

def run_course(book_id, label):
    print(f"\n{'='*66}\n{label}\n{'='*66}")
    spine = get(f"/book/books/{book_id}/spine")
    spine = spine.get("spine", spine)
    total = ok = 0
    for ch in spine["chapters"]:
        for page_id in ch["page_ids"]:
            page = get(f"/book/books/{book_id}/pages/{page_id}")
            page = page.get("page", page)
            blocks = [b for b in page["blocks"]
                      if b["type"] == "code" and (b["payload"] or {}).get("notebook", {}).get("runnable")]
            if not blocks:
                continue
            post("/ext/notebook/reset", {"book_id": book_id, "page_id": page_id})
            print(f"\n── {page['title']}（{len(blocks)} 段代码）")
            for i, b in enumerate(blocks, 1):
                total += 1
                head = b["payload"]["code"].strip().splitlines()[0][:46]
                try:
                    r = post("/ext/notebook/run",
                             {"book_id": book_id, "page_id": page_id, "block_id": b["id"],
                              "through": True, "timeout_s": 240}, timeout=320)
                except Exception as exc:
                    print(f"  ✗ 第{i}段 请求失败 {type(exc).__name__}  {head}")
                    continue
                stderr = (r.get("stderr") or "").strip()
                # Go 的编译错误是子进程的 stderr，内核本身没报错，所以状态仍是 ok。
                # 只看 status 会把编译失败当成通过。
                compile_failed = "go 退出码" in stderr or "cannot find" in stderr or ": undefined" in stderr
                if r["status"] == "ok" and not r.get("error") and not compile_failed:
                    ok += 1
                    extra = ""
                    if r["stdout"].strip():
                        extra = "→ " + r["stdout"].strip().splitlines()[0][:40]
                    print(f"  ✓ 第{i}段 {r['elapsed_s']:5.2f}s {head} {extra}")
                else:
                    err = (r.get("error") or {})
                    detail = f"{err.get('ename','')}: {err.get('evalue','')}" if err else (
                        stderr.splitlines()[0][:120] if stderr else r["status"])
                    print(f"  ✗ 第{i}段 {head}")
                    print(f"      {detail[:200]}")
                    if r["stderr"].strip():
                        print(f"      stderr: {r['stderr'].strip().splitlines()[0][:160]}")
    print(f"\n{label}：{ok}/{total} 段通过")
    return ok, total

a = run_course("bk_course_agent-from-scratch-python", "Python 版")
b = run_course("bk_course_agent-from-scratch-go", "Go 版")
print(f"\n{'='*66}\n合计 {a[0]+b[0]}/{a[1]+b[1]} 段通过")
sys.exit(0 if a[0] == a[1] and b[0] == b[1] else 1)
