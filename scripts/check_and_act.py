#!/usr/bin/env python3
"""
飞书同步主入口 — 定时任务运行此脚本
逻辑: 检查待处理通知 → 读用户飞书回复 → 执行确认的操作
      若无待处理通知 → 运行 notify 检测变更
"""

import json
import os
import subprocess
import sys
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from scripts.common import VAULT_PATH, PENDING_FILE, lark_cli

SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
NOTIFY_SCRIPT = os.path.join(SCRIPTS_DIR, "notify.py")
SYNC_SCRIPT = os.path.join(SCRIPTS_DIR, "sync.py")


def read_user_replies(chat_id, after_time):
    """读取 P2P 对话中的用户回复（排除 bot 消息）。
    往前多取 120 秒防止时钟偏差。"""
    try:
        pending_dt = datetime.fromisoformat(after_time)
        start_dt = pending_dt - timedelta(seconds=120)
        start_time = start_dt.isoformat()
    except (ValueError, TypeError):
        start_time = after_time

    result = lark_cli("im", "+chat-messages-list", "--as", "bot",
                     "--chat-id", chat_id, "--start", start_time, "--order", "asc")
    if not result.get("ok"):
        return []

    messages = result.get("data", {}).get("messages", [])
    user_msgs = []
    for msg in messages:
        sender = msg.get("sender", {})
        if sender.get("sender_type") == "app":
            continue  # 跳过 bot 消息

        content = msg.get("content", "")
        text = ""
        try:
            parsed = json.loads(content) if isinstance(content, str) else content
            if isinstance(parsed, str):
                text = parsed                   # text 类型消息
            elif isinstance(parsed, dict):
                text = (parsed.get("text") or
                        parsed.get("title") or "")
            elif isinstance(parsed, list):
                for block in parsed:
                    if isinstance(block, dict):
                        text += str(block.get("text_run", {}).get("content", ""))
        except (json.JSONDecodeError, TypeError, AttributeError):
            text = str(content)

        text = text.strip()
        if text:
            user_msgs.append({
                "message_id": msg.get("message_id", ""),
                "text": text,
                "create_time": msg.get("create_time", ""),
            })
    return user_msgs


def parse_user_intent(text):
    """解析用户回复 → 'all' | 'new_only' | 'skip' | 'unknown'"""
    text = text.strip().lower()
    if text in ("跳过", "skip", "忽略", "不要", "no", "不", "取消", "cancel"):
        return "skip"
    if text in ("仅新增", "只新增", "new only", "only new", "仅同步新增"):
        return "new_only"
    if text in ("全部同步", "同步", "sync", "全部", "all", "确认", "ok",
                "好的", "行", "可以", "同意", "yes", "y", "好", "1"):
        return "all"
    if "全部" in text and ("同步" in text or "更新" in text):
        return "all"
    if "仅新增" in text or "只同步新增" in text:
        return "new_only"
    if "跳过" in text or "先不" in text or "忽略" in text:
        return "skip"
    return "unknown"


def send_reply(chat_id, markdown_text):
    """在同一个聊天中发送回复消息"""
    lark_cli("im", "+messages-send", "--as", "bot",
             "--chat-id", chat_id, "--markdown", markdown_text)


def run_sync(approve_categories):
    """先跑 preview 生成完整 pending，再跑 apply"""
    subprocess.run(["python3", SYNC_SCRIPT, "preview"],
                   capture_output=True, text=True, timeout=300, cwd=VAULT_PATH)

    if os.path.exists(PENDING_FILE):
        with open(PENDING_FILE) as f:
            prefilled = json.load(f)
        # 按用户选择的类别过滤
        prefilled["approved_new"] = (prefilled.get("approved_new", [])
                                     if "new" in approve_categories else [])
        prefilled["approved_modified"] = (prefilled.get("approved_modified", [])
                                          if "modified" in approve_categories else [])
        prefilled["approved_deleted"] = (prefilled.get("approved_deleted", [])
                                         if "deleted" in approve_categories else [])
        with open(PENDING_FILE, "w") as f:
            json.dump(prefilled, f, indent=2, ensure_ascii=False)

    cmd = ["python3", SYNC_SCRIPT, "apply"]
    for cat in approve_categories:
        cmd.extend(["--approve", cat])
    result = subprocess.run(cmd, capture_output=True, text=True,
                            timeout=600, cwd=VAULT_PATH)
    return result.returncode == 0


def main():
    print("🔄 飞书同步检查...", file=sys.stderr)

    # 无待处理 → 检测变更
    if not os.path.exists(PENDING_FILE):
        print("  📋 无待处理通知，检查是否有新变更...", file=sys.stderr)
        subprocess.run(["python3", NOTIFY_SCRIPT], timeout=300)
        return

    with open(PENDING_FILE) as f:
        pending = json.load(f)

    # 已确认执行过的 → 跳过
    if pending.get("confirmed"):
        print("  ✅ 已完成确认的变更，清理中...", file=sys.stderr)
        try:
            os.remove(PENDING_FILE)
        except FileNotFoundError:
            pass
        return

    chat_id = pending.get("chat_id", "")
    created_at = pending.get("created_at", "")
    if not chat_id or not created_at:
        print("  ⚠️  旧版待处理文件，重新扫描...", file=sys.stderr)
        os.remove(PENDING_FILE)
        subprocess.run(["python3", NOTIFY_SCRIPT], timeout=300)
        return

    # 读取用户回复
    print(f"  📩 检查用户回复...", file=sys.stderr)
    replies = read_user_replies(chat_id, created_at)
    if not replies:
        print("  ⏳ 用户尚未回复", file=sys.stderr)
        return

    latest = replies[-1]
    intent = parse_user_intent(latest["text"])

    if intent == "unknown":
        print(f"  ❓ 无法识别回复: \"{latest['text']}\"", file=sys.stderr)
        send_reply(chat_id,
                   "❓ 未识别的指令。请回复：\n"
                   "• `全部同步` — 同步所有变更\n"
                   "• `仅新增` — 只同步新增文件\n"
                   "• `跳过` — 本次不同步")
        return

    # 执行
    if intent == "skip":
        print("  ⏭️  用户选择跳过", file=sys.stderr)
        send_reply(chat_id, "👌 已跳过本次同步，需要时手动运行同步。")
        # 记录跳过，避免 notify 重复通知同一批变更
        from scripts.sync import load_state, save_state, STATE_FILE
        state = load_state()
        skipped = state.get("skipped_tokens", [])
        for key in ("new", "modified", "deleted"):
            for f in pending.get("report", {}).get(key, []):
                if f.get("token") and f["token"] not in skipped:
                    skipped.append(f["token"])
        state["skipped_tokens"] = skipped[-200:]  # 保留最近 200 个
        save_state(state)
        try:
            os.remove(PENDING_FILE)
        except FileNotFoundError:
            pass

    elif intent == "all":
        print("  🚀 用户确认全部同步", file=sys.stderr)
        send_reply(chat_id, "🔄 正在同步所有变更到 Obsidian...")
        success = run_sync(["new", "modified", "deleted"])
        if success:
            send_reply(chat_id, "✅ 同步完成！所有变更已更新到 Obsidian 知识库。")
        else:
            send_reply(chat_id, "⚠️ 同步出现问题，请手动检查。")

    elif intent == "new_only":
        print("  🚀 用户确认仅同步新增", file=sys.stderr)
        send_reply(chat_id, "🔄 正在同步新增文件到 Obsidian...")
        success = run_sync(["new"])
        if success:
            send_reply(chat_id, "✅ 新增文件已同步到 Obsidian 知识库。")

    # 清理（run_sync 内部可能已删除 pending）
    try:
        os.remove(PENDING_FILE)
    except FileNotFoundError:
        pass

    print(f"  ✅ 处理完成 (intent={intent})", file=sys.stderr)


if __name__ == "__main__":
    main()
