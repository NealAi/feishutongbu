---
name: feishutongbu
version: 1.0.0
description: "飞书云盘 → Obsidian 知识库同步。飞书机器人推送变更通知 → 用户在飞书中回复确认同步。"
---

# 飞书云盘 → Obsidian 同步

## 快速使用

用户输入 `/feishutongbu` 时，运行预览检测并展示变更详情，询问用户是否同步：

```bash
python3 scripts/sync.py preview
```

然后将输出中的变更信息清晰地展示给用户（新增/修改/删除），
用 AskUserQuestion 或直接询问确认后执行：

```bash
# 全部同步
python3 scripts/sync.py apply

# 仅新增
python3 scripts/sync.py apply --approve new
```

## 定时自动化

定时运行此命令即可自动检测 + 飞书通知 + 用户飞书回复确认：

```bash
python3 scripts/check_and_act.py
```

建议用 crontab 或 Claude Code `/loop` 每 10 分钟跑一次。
