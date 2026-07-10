#!/usr/bin/env python3
"""
feishutongbu 公共模块 — 配置加载、lark-cli 封装、文件名处理
"""

import json
import os
import subprocess
import sys
import time

# === 配置 ===
CONFIG_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "config.json")


def load_config():
    """加载 config.json，展开 ~ 路径"""
    if not os.path.exists(CONFIG_PATH):
        print(f"❌ 配置文件不存在: {CONFIG_PATH}", file=sys.stderr)
        print("   请复制 config.example.json → config.json 并修改配置", file=sys.stderr)
        sys.exit(1)
    with open(CONFIG_PATH, "r") as f:
        cfg = json.load(f)
    # 展开 ~
    for key in ("lark_cli_path", "obsidian_vault_path"):
        cfg[key] = os.path.expanduser(cfg[key])
    return cfg


CFG = load_config()
LARK_CLI = CFG["lark_cli_path"]
VAULT_PATH = CFG["obsidian_vault_path"]
USER_OPEN_ID = CFG["feishu_user_open_id"]
STATE_FILE = os.path.join(VAULT_PATH, ".feishu-sync-state.json")
PENDING_FILE = os.path.join(VAULT_PATH, ".feishu-sync-pending.json")
MAX_RETRIES = 3


def sanitize_filename(name: str) -> str:
    """替换文件名中的非法字符"""
    for ch in ('/', ':', '*', '?', '"', '<', '>', '|', '\\'):
        name = name.replace(ch, '_')
    name = name.strip().rstrip('.')
    while '  ' in name:
        name = name.replace('  ', ' ')
    return name


def lark_cli(*args, **kwargs):
    """调用 lark-cli，返回解析后的 JSON dict"""
    cmd = [LARK_CLI] + list(args)
    cwd = kwargs.pop("cwd", None)
    for attempt in range(MAX_RETRIES):
        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=120, cwd=cwd,
                env={**os.environ,
                     "LARKSUITE_CLI_NO_UPDATE_NOTIFIER": "1",
                     "LARKSUITE_CLI_NO_SKILLS_NOTIFIER": "1"}
            )
            stdout = result.stdout.strip()
            if not stdout:
                stderr = result.stderr.strip()
                if stderr:
                    first = stderr.find("{")
                    if first >= 0:
                        return json.loads(stderr[first:stderr.rfind("}") + 1])
                return {"ok": False, "error": {"message": "empty output"}}
            first = stdout.find("{")
            if first >= 0:
                return json.loads(stdout[first:stdout.rfind("}") + 1])
            return {"ok": False, "error": {"message": "no JSON"}}
        except (json.JSONDecodeError, ValueError):
            if attempt < MAX_RETRIES - 1:
                time.sleep(2 ** attempt)
                continue
            return {"ok": False, "error": {"message": "JSON parse error"}}
        except subprocess.TimeoutExpired:
            if attempt < MAX_RETRIES - 1:
                time.sleep(2 ** attempt)
                continue
            return {"ok": False, "error": {"message": "timeout"}}
    return {"ok": False}
