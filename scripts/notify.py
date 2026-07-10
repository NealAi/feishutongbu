#!/usr/bin/env python3
"""
飞书云盘变更通知脚本
检测变更 → 飞书机器人推送通知给用户
"""

import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from scripts.common import (
    VAULT_PATH, USER_OPEN_ID, PENDING_FILE, lark_cli,
)
from scripts.sync import build_drive_tree, load_state


def send_feishu_message(markdown_text):
    """发送飞书 Markdown 消息。成功返回 {chat_id, message_id}，失败返回 None"""
    result = lark_cli("im", "+messages-send", "--as", "bot",
                     "--user-id", USER_OPEN_ID, "--markdown", markdown_text)
    if result.get("ok"):
        return {
            "chat_id": result["data"].get("chat_id", ""),
            "message_id": result["data"].get("message_id", ""),
        }
    # fallback: plain text
    plain = markdown_text.replace("**", "").replace("`", "").replace("*", "")
    result = lark_cli("im", "+messages-send", "--as", "bot",
                     "--user-id", USER_OPEN_ID, "--text", plain)
    if result.get("ok"):
        return {
            "chat_id": result["data"].get("chat_id", ""),
            "message_id": result["data"].get("message_id", ""),
        }
    return None


def build_change_message(report):
    """构建 Markdown 通知消息"""
    n_new = len(report["new"])
    n_mod = len(report["modified"])
    n_del = len(report["deleted"])
    total = n_new + n_mod + n_del

    now = datetime.now().strftime("%m/%d %H:%M")
    lines = [f"📊 **飞书云盘变更提醒** ({now})", ""]
    if total == 0:
        lines.append("✅ 暂无变更，已是最新状态。")
        return "\n".join(lines)

    lines.append(f"发现 **{total}** 项变更：")
    lines.append("")

    if report["new"]:
        lines.append(f"🆕 **新增 ({n_new})**")
        for f in report["new"][:10]:
            e = {"docx": "📄", "sheet": "📊", "bitable": "📋"}.get(f["type"], "📎")
            lines.append(f"  {e} {f['name']}")
            lines.append(f"    _{f['path']}_")
        if n_new > 10:
            lines.append(f"  ... 还有 {n_new - 10} 个")
        lines.append("")

    if report["modified"]:
        lines.append(f"✏️ **修改 ({n_mod})**")
        for f in report["modified"][:5]:
            lines.append(f"  📄 {f['name']}")
            lines.append(f"    _{f['path']}_")
        if n_mod > 5:
            lines.append(f"  ... 还有 {n_mod - 5} 个")
        lines.append("")

    if report["deleted"]:
        lines.append(f"🗑️ **已删除 ({n_del})**")
        for f in report["deleted"][:5]:
            lines.append(f"  ❌ {f['name']}")
            lines.append(f"    _{f['path']}_")
        if n_del > 5:
            lines.append(f"  ... 还有 {n_del - 5} 个")
        lines.append("")

    lines.append("---")
    lines.append("**回复此消息即可确认同步：**")
    lines.append("• 回复 `全部同步` → 同步所有变更")
    lines.append("• 回复 `仅新增` → 只同步新增文件")
    lines.append("• 回复 `跳过` → 本次不同步")
    return "\n".join(lines)


def scan_changes():
    """对比状态文件，返回变更报告 dict"""
    old_state = load_state()
    old_files = old_state.get("files", {})
    current_tree = build_drive_tree("", "")
    current_files = {item["token"]: item for item in current_tree
                     if item["type"] != "folder"}

    report = {"last_sync": old_state.get("last_sync"),
              "new": [], "modified": [], "deleted": []}

    for token, item in current_files.items():
        if token not in old_files:
            report["new"].append({
                "token": token, "name": item["name"], "type": item["type"],
                "path": item["path"] + ".md", "drive_path": item["drive_path"],
                "url": item.get("url", ""),
            })
        elif old_files[token].get("modified_time") != item.get("modified_time"):
            report["modified"].append({
                "token": token, "name": item["name"], "type": item["type"],
                "path": item["path"] + ".md", "url": item.get("url", ""),
            })

    for token, info in old_files.items():
        if token not in current_files:
            report["deleted"].append({
                "token": token, "name": info["name"], "type": info["type"],
                "path": info["path"],
            })
    return report


def main():
    print("🔍 检测飞书云盘变更...", file=sys.stderr)
    report = scan_changes()
    total = len(report["new"]) + len(report["modified"]) + len(report["deleted"])

    if total == 0:
        print("  ✅ 无变更", file=sys.stderr)
        return

    print(f"  📊 变更: 新增{len(report['new'])} 修改{len(report['modified'])} "
          f"删除{len(report['deleted'])}", file=sys.stderr)

    # 去重：相同变更不重复发
    if os.path.exists(PENDING_FILE):
        with open(PENDING_FILE) as f:
            existing = json.load(f)
        existing_rep = existing.get("report", {})
        same = (
            {f["token"] for f in existing_rep.get("new", [])} == {f["token"] for f in report["new"]}
            and {f["token"] for f in existing_rep.get("modified", [])} == {f["token"] for f in report["modified"]}
            and {f["token"] for f in existing_rep.get("deleted", [])} == {f["token"] for f in report["deleted"]}
        )
        if existing.get("notified") and same and not existing.get("confirmed"):
            print("  ⏭️  已有相同待确认通知，跳过", file=sys.stderr)
            return

    message = build_change_message(report)
    print("  📤 发送飞书通知...", file=sys.stderr)

    sent = send_feishu_message(message)
    if sent:
        print("  ✅ 通知已发送", file=sys.stderr)
        pending = {
            "created_at": datetime.now(timezone.utc).isoformat(),
            "report": report,
            "notified": True, "confirmed": False,
            "chat_id": sent["chat_id"],
            "notify_message_id": sent["message_id"],
        }
        os.makedirs(os.path.dirname(PENDING_FILE), exist_ok=True)
        with open(PENDING_FILE, "w") as f:
            json.dump(pending, f, indent=2, ensure_ascii=False)
    else:
        print("  ❌ 通知发送失败", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
