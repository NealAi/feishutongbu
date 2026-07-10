#!/usr/bin/env python3
"""
同步脚本 — 两阶段：preview（预览变更）→ apply（执行同步）

用法:
  python3 sync.py preview                       扫描变更（不修改文件）
  python3 sync.py apply                         应用所有待处理变更
  python3 sync.py apply --approve new           仅批准新增
  python3 sync.py apply --approve new --approve modified
  python3 sync.py apply --skip token1,token2
  python3 sync.py apply --only token1,token2
"""

import json
import os
import sys
from datetime import datetime, timezone

# 允许从项目根或 scripts/ 目录运行
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from scripts.common import (
    VAULT_PATH, STATE_FILE, PENDING_FILE,
    sanitize_filename, lark_cli,
)


# ========================
#  DRIVE SCAN
# ========================

def list_folder(folder_token=""):
    """列出文件夹内容（自动分页）"""
    all_files = []
    page_token = ""
    params = {}
    if folder_token:
        params["folder_token"] = folder_token
    while True:
        req = {**params}
        if page_token:
            req["page_token"] = page_token
        result = lark_cli("drive", "files", "list", "--as", "user",
                         "--params", json.dumps(req))
        if not result.get("ok"):
            break
        files = result.get("data", {}).get("files", [])
        all_files.extend(files)
        if not result.get("data", {}).get("has_more"):
            break
        page_token = result.get("data", {}).get("page_token", "")
        if not page_token:
            break
    return all_files


def build_drive_tree(folder_token="", folder_path=""):
    """递归构建云盘文件树"""
    files = list_folder(folder_token)
    tree = []
    for f in files:
        item = {
            "name": f["name"],
            "token": f["token"],
            "type": f["type"],
            "modified_time": f.get("modified_time", f.get("created_time", "0")),
            "created_time": f.get("created_time", "0"),
            "url": f.get("url", ""),
            "path": os.path.join(folder_path, sanitize_filename(f["name"])),
            "drive_path": folder_path,
        }
        tree.append(item)
        if f["type"] == "folder":
            tree.extend(build_drive_tree(f["token"], item["path"]))
    return tree


# ========================
#  STATE MANAGEMENT
# ========================

def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE) as f:
            return json.load(f)
    return {"files": {}, "last_sync": None}


def save_state(state):
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)


# ========================
#  EXPORT
# ========================

def export_docx(token, rel_path):
    """导出 docx → Markdown（cwd 必须是 VAULT_PATH）"""
    output_dir = os.path.dirname(rel_path)
    if output_dir:
        os.makedirs(os.path.join(VAULT_PATH, output_dir), exist_ok=True)
    filename = os.path.basename(rel_path)
    base_name = filename[:-3] if filename.endswith(".md") else filename

    result = lark_cli("drive", "+export", "--as", "user",
                     "--doc-type", "docx",
                     "--file-extension", "markdown",
                     "--token", token,
                     "--output-dir", output_dir or ".",
                     "--file-name", base_name,
                     "--overwrite", cwd=VAULT_PATH)

    if result.get("ok"):
        exported = os.path.join(VAULT_PATH, rel_path)
        if os.path.exists(exported):
            return True
        search_dir = os.path.join(VAULT_PATH, output_dir) if output_dir else VAULT_PATH
        if os.path.isdir(search_dir):
            for f in os.listdir(search_dir):
                if f.endswith(".md") and (base_name.lower() in f.lower() or
                                          f.lower().startswith(base_name[:10].lower())):
                    actual = os.path.join(search_dir, f)
                    if actual != exported:
                        os.rename(actual, exported)
                    return True
        return False
    else:
        err = result.get("error", {}).get("message", "Unknown")
        print(f"    ⚠️  Export failed: {err}", file=sys.stderr)
        return False


def create_stub_markdown(name, url, doc_type, rel_path):
    """为非 docx 文件创建飞书链接快捷方式"""
    abs_path = os.path.join(VAULT_PATH, rel_path)
    os.makedirs(os.path.dirname(abs_path), exist_ok=True)
    labels = {"sheet": "📊 飞书电子表格", "bitable": "📋 飞书多维表格"}
    label = labels.get(doc_type, f"📎 飞书{doc_type}")
    content = f"""---
feishu_type: {doc_type}
feishu_url: {url}
feishu_synced: {datetime.now(timezone.utc).isoformat()}
---

# {name}

> **{label}** — 此文件为飞书在线文档的快捷方式。
>
> 🔗 [在飞书中打开]({url})
>
> *此文档为在线文档类型，无法直接导出为 Markdown。请点击链接在飞书中查看。*
"""
    with open(abs_path, "w", encoding="utf-8") as f:
        f.write(content)
    return True


def delete_empty_dirs():
    """清理空目录"""
    preserved = {".obsidian", ".claude", ".claudian",
                 ".feishu-sync-state.json", ".feishu-sync-pending.json"}
    for root, dirs, files in os.walk(VAULT_PATH, topdown=False):
        if root == VAULT_PATH:
            continue
        contents = [c for c in os.listdir(root)
                    if c not in preserved and c != ".DS_Store"]
        if len(contents) == 0:
            try:
                os.rmdir(root)
                print(f"  🧹 清理空目录: {os.path.relpath(root, VAULT_PATH)}")
            except OSError:
                pass


# ========================
#  PREVIEW
# ========================

def cmd_preview():
    """扫描变更，生成报告 → pending 文件，不修改任何本地文件"""
    print("🔍 正在扫描飞书云盘变更...", file=sys.stderr)

    old_state = load_state()
    old_files = old_state.get("files", {})
    current_tree = build_drive_tree("", "")
    current_files = {item["token"]: item for item in current_tree
                     if item["type"] != "folder"}

    report = {
        "last_sync": old_state.get("last_sync"),
        "unchanged": 0,
        "new": [], "modified": [], "deleted": [],
    }

    for token, item in current_files.items():
        if token not in old_files:
            report["new"].append({
                "token": token, "name": item["name"], "type": item["type"],
                "path": item["path"] + ".md", "drive_path": item["drive_path"],
                "modified_time": item["modified_time"], "url": item.get("url", ""),
            })
        elif old_files[token].get("modified_time") != item["modified_time"]:
            old = old_files[token]
            report["modified"].append({
                "token": token, "name": item["name"], "type": item["type"],
                "path": item["path"] + ".md", "drive_path": item["drive_path"],
                "old_modified_time": old["modified_time"],
                "new_modified_time": item["modified_time"],
                "url": item.get("url", ""),
            })
        else:
            report["unchanged"] += 1

    for token, info in old_files.items():
        if token not in current_files:
            report["deleted"].append({
                "token": token, "name": info["name"], "type": info["type"],
                "path": info["path"],
            })

    for key in ("new", "modified", "deleted"):
        report[key].sort(key=lambda x: x["path"])

    # --- 打印可读摘要 ---
    print("\n" + "=" * 55, file=sys.stderr)
    print("  📊 飞书云盘变更报告", file=sys.stderr)
    print("=" * 55, file=sys.stderr)
    print(f"  上次同步: {report['last_sync'] or '从未'}", file=sys.stderr)
    print(f"  未变化:   {report['unchanged']} 个", file=sys.stderr)
    print(f"  🆕 新增:   {len(report['new'])} 个", file=sys.stderr)
    print(f"  ✏️  修改:   {len(report['modified'])} 个", file=sys.stderr)
    print(f"  🗑️  删除:   {len(report['deleted'])} 个", file=sys.stderr)

    if report["new"]:
        print(f"\n  🆕 新增文件:", file=sys.stderr)
        for f in report["new"]:
            e = {"docx": "📄", "sheet": "📊", "bitable": "📋"}.get(f["type"], "📎")
            print(f"    {e} {f['name']}", file=sys.stderr)
            print(f"       → {f['path']}", file=sys.stderr)

    if report["modified"]:
        print(f"\n  ✏️  修改文件:", file=sys.stderr)
        for f in report["modified"]:
            print(f"    📄 {f['name']} → {f['path']}", file=sys.stderr)

    if report["deleted"]:
        print(f"\n  🗑️  飞书已删文件:", file=sys.stderr)
        for f in report["deleted"]:
            print(f"    ❌ {f['name']} → {f['path']}", file=sys.stderr)

    total = len(report["new"]) + len(report["modified"]) + len(report["deleted"])
    if total == 0:
        print("\n  ✨ 无变更，已是最新状态。", file=sys.stderr)

    # --- 写 pending 文件 ---
    approved_new = [f["token"] for f in report["new"]]
    approved_modified = [f["token"] for f in report["modified"]]
    approved_deleted = [f["token"] for f in report["deleted"]]

    # 收集文件夹
    folders = sorted({f["path"] for f in current_tree if f["type"] == "folder"})

    # 收集当前文件信息
    drive_files = {}
    for token, item in current_files.items():
        if item["type"] == "folder":
            continue
        drive_files[token] = {
            "name": item["name"], "type": item["type"],
            "modified_time": item["modified_time"],
            "path": item["path"] + ".md",
            "drive_path": item["drive_path"], "url": item.get("url", ""),
        }

    pending = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "report": report,
        "approved_new": approved_new,
        "approved_modified": approved_modified,
        "approved_deleted": approved_deleted,
        "folders": folders,
        "drive_files": drive_files,
    }
    os.makedirs(os.path.dirname(PENDING_FILE), exist_ok=True)
    with open(PENDING_FILE, "w") as f:
        json.dump(pending, f, indent=2, ensure_ascii=False)

    # stdout 输出 JSON（供程序化消费）
    print(json.dumps(report, indent=2, ensure_ascii=False))


# ========================
#  APPLY
# ========================

def cmd_apply(approve_categories=None, skip_tokens=None, only_tokens=None):
    """应用批准的变更"""
    if not os.path.exists(PENDING_FILE):
        print("❌ 没有待处理的变更。请先运行 preview。", file=sys.stderr)
        sys.exit(1)

    with open(PENDING_FILE) as f:
        pending = json.load(f)

    report = pending["report"]

    # 确定批准的 token
    if only_tokens:
        only_set = set(only_tokens)
        approved_new = [t for t in pending["approved_new"] if t in only_set]
        approved_modified = [t for t in pending["approved_modified"] if t in only_set]
        approved_deleted = [t for t in pending["approved_deleted"] if t in only_set]
    elif approve_categories:
        approved_new = pending["approved_new"] if "new" in approve_categories else []
        approved_modified = pending["approved_modified"] if "modified" in approve_categories else []
        approved_deleted = pending["approved_deleted"] if "deleted" in approve_categories else []
    else:
        approved_new = pending["approved_new"]
        approved_modified = pending["approved_modified"]
        approved_deleted = pending["approved_deleted"]

    if skip_tokens:
        skip_set = set(skip_tokens)
        approved_new = [t for t in approved_new if t not in skip_set]
        approved_modified = [t for t in approved_modified if t not in skip_set]
        approved_deleted = [t for t in approved_deleted if t not in skip_set]

    total = len(approved_new) + len(approved_modified) + len(approved_deleted)
    if total == 0:
        print("✨ 没有需要执行的操作。")
        return

    print(f"\n📥 执行 {total} 项变更...", file=sys.stderr)

    # 1) 创建目录
    for fp in pending.get("folders", []):
        os.makedirs(os.path.join(VAULT_PATH, fp), exist_ok=True)

    # 2) 删除
    for token in approved_deleted:
        info = next((d for d in report["deleted"] if d["token"] == token), None)
        if not info:
            continue
        fp = os.path.join(VAULT_PATH, info["path"])
        if os.path.exists(fp):
            os.remove(fp)
            print(f"  🗑️  已删除: {info['path']}", file=sys.stderr)

    # 3) 新增+修改
    sync_tokens = approved_new + approved_modified
    drive_files = pending.get("drive_files", {})
    success = stub = fail = 0

    for i, token in enumerate(sync_tokens):
        item = drive_files.get(token)
        if not item:
            continue
        dt = item["type"]
        rp = item["path"]

        print(f"  [{i+1}/{len(sync_tokens)}] {item['name'][:60]}", end=" ", file=sys.stderr)
        sys.stderr.flush()

        if dt == "docx":
            if export_docx(token, rp):
                print("✅", file=sys.stderr)
                success += 1
            else:
                url = item.get("url", "")
                if create_stub_markdown(item["name"], url, dt, rp):
                    print("📎(stub)", file=sys.stderr)
                    stub += 1
                else:
                    print("❌", file=sys.stderr)
                    fail += 1
        elif dt in ("sheet", "bitable"):
            if create_stub_markdown(item["name"], item.get("url", ""), dt, rp):
                print("📎", file=sys.stderr)
                stub += 1
            else:
                print("❌", file=sys.stderr)
                fail += 1

    print(f"\n  ✅ 导出: {success}  📎 快捷方式: {stub}  ❌ 失败: {fail}", file=sys.stderr)

    # 4) 清理
    delete_empty_dirs()

    # 5) 更新状态文件
    old_state = load_state()
    new_state_files = dict(old_state.get("files", {}))
    for token in approved_deleted:
        new_state_files.pop(token, None)
    for token in approved_new + approved_modified:
        item = drive_files.get(token)
        if item:
            new_state_files[token] = {
                "name": item["name"], "type": item["type"],
                "modified_time": item["modified_time"],
                "path": item["path"], "drive_path": item["drive_path"],
            }
    new_state = {
        "files": new_state_files,
        "last_sync": datetime.now(timezone.utc).isoformat(),
        "stats": {
            "total": len(new_state_files),
            "docx": sum(1 for v in new_state_files.values() if v["type"] == "docx"),
            "sheet": sum(1 for v in new_state_files.values() if v["type"] == "sheet"),
            "bitable": sum(1 for v in new_state_files.values() if v["type"] == "bitable"),
        },
    }
    save_state(new_state)
    os.remove(PENDING_FILE)

    print(f"\n✨ 同步完成! 总文件: {new_state['stats']['total']}", file=sys.stderr)
    print(f"  💾 状态已更新", file=sys.stderr)


# ========================
#  CLI
# ========================

def usage():
    print("用法:", file=sys.stderr)
    print("  python3 sync.py preview", file=sys.stderr)
    print("  python3 sync.py apply [--approve new|modified|deleted] [--skip tok1,tok2] [--only tok1,tok2]", file=sys.stderr)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        usage()
        sys.exit(1)
    cmd = sys.argv[1]
    if cmd == "preview":
        cmd_preview()
    elif cmd == "apply":
        approve_categories = []
        skip_tokens = []
        only_tokens = []
        i = 2
        while i < len(sys.argv):
            if sys.argv[i] == "--approve" and i + 1 < len(sys.argv):
                approve_categories.append(sys.argv[i + 1])
                i += 2
            elif sys.argv[i] == "--skip" and i + 1 < len(sys.argv):
                skip_tokens = sys.argv[i + 1].split(",")
                i += 2
            elif sys.argv[i] == "--only" and i + 1 < len(sys.argv):
                only_tokens = sys.argv[i + 1].split(",")
                i += 2
            else:
                print(f"未知参数: {sys.argv[i]}", file=sys.stderr)
                usage()
                sys.exit(1)
        cmd_apply(approve_categories=approve_categories or None,
                  skip_tokens=skip_tokens or None,
                  only_tokens=only_tokens or None)
    else:
        usage()
        sys.exit(1)
