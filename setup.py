#!/usr/bin/env python3
"""
feishutongbu 安装向导
帮助新用户配置 config.json
"""

import json
import os
import subprocess
import sys

CONFIG_TEMPLATE = {
    "lark_cli_path": "~/bin/lark-cli",
    "obsidian_vault_path": "",
    "feishu_user_open_id": "",
    "feishu_user_name": "",
    "check_interval_minutes": 10,
}


def find_lark_cli():
    """尝试找 lark-cli 路径"""
    candidates = [
        os.path.expanduser("~/bin/lark-cli"),
        "/usr/local/bin/lark-cli",
        "/opt/homebrew/bin/lark-cli",
    ]
    for p in candidates:
        if os.path.exists(p):
            return p
    # try which
    try:
        result = subprocess.run(["which", "lark-cli"], capture_output=True, text=True)
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass
    return None


def find_obsidian_vaults():
    """尝试查找 Obsidian 仓库"""
    vaults = []
    # iCloud 路径
    icloud = os.path.expanduser("~/Library/Mobile Documents/iCloud~md~obsidian/Documents")
    if os.path.isdir(icloud):
        for d in os.listdir(icloud):
            full = os.path.join(icloud, d)
            if os.path.isdir(full) and os.path.isdir(os.path.join(full, ".obsidian")):
                vaults.append(full)
    return vaults


def get_open_id(lark_cli_path):
    """通过 auth status 获取当前用户 open_id"""
    try:
        env = os.environ.copy()
        env["LARKSUITE_CLI_NO_UPDATE_NOTIFIER"] = "1"
        env["LARKSUITE_CLI_NO_SKILLS_NOTIFIER"] = "1"
        result = subprocess.run(
            [lark_cli_path, "auth", "status", "--json", "--verify"],
            capture_output=True, text=True, timeout=30, env=env,
        )
        data = json.loads(result.stdout)
        user = data.get("identities", {}).get("user", {})
        return user.get("openId", ""), user.get("userName", "")
    except Exception:
        return "", ""


def main():
    print("=" * 50)
    print("  🚀 feishutongbu 安装向导")
    print("=" * 50)
    print()

    # 1. lark-cli
    lark_path = find_lark_cli()
    print(f"1️⃣  lark-cli 路径")
    if lark_path:
        print(f"   已检测到: {lark_path}")
    else:
        lark_path = input("   请输入 lark-cli 完整路径: ").strip()
        if not lark_path:
            print("   ❌ 必须先安装 lark-cli")
            sys.exit(1)

    # 2. Obsidian vault
    print(f"\n2️⃣  Obsidian 仓库路径")
    vaults = find_obsidian_vaults()
    if vaults:
        print("   找到以下仓库:")
        for i, v in enumerate(vaults):
            print(f"     [{i+1}] {v}")
        choice = input(f"   选择 (1-{len(vaults)}) 或输入自定义路径: ").strip()
        if choice.isdigit() and 1 <= int(choice) <= len(vaults):
            vault_path = vaults[int(choice) - 1]
        else:
            vault_path = choice or vaults[0]
    else:
        vault_path = input("   请输入 Obsidian 仓库完整路径: ").strip()
        if not vault_path:
            print("   ❌ 必须指定仓库路径")
            sys.exit(1)
    vault_path = os.path.expanduser(vault_path)

    # 3. User open_id
    print(f"\n3️⃣  飞书用户 Open ID")
    open_id, user_name = get_open_id(lark_path)
    if open_id:
        print(f"   已检测到: {user_name} ({open_id})")
    else:
        open_id = input("   请输入你的飞书 user open_id (ou_xxx): ").strip()
    if not open_id:
        print("   ⚠️  稍后可手动编辑 config.json")

    # 4. Interval
    print(f"\n4️⃣  检查间隔（分钟）")
    interval = input("   (默认 10): ").strip()
    interval = int(interval) if interval.isdigit() else 10

    # --- 写 config ---
    config = {
        "lark_cli_path": lark_path,
        "obsidian_vault_path": vault_path,
        "feishu_user_open_id": open_id,
        "feishu_user_name": user_name,
        "check_interval_minutes": interval,
    }

    config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")
    with open(config_path, "w") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)

    print(f"\n✅ 配置已保存到 config.json")
    print()
    print("下一步:")
    print("  1. 确认飞书 bot 有 im:message 权限")
    print("  2. 运行 python3 scripts/notify.py 测试通知")
    print("  3. 设置定时任务（每 10 分钟）:")
    print("     python3 scripts/check_and_act.py")
    print()
    print("  📖 详细文档: README.md")


if __name__ == "__main__":
    main()
