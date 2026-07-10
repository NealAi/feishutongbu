# feishutongbu（飞书同步）

**飞书云盘 → Obsidian 知识库自动同步工具**

飞书机器人定时扫描云盘变更 → 推送通知 → 你在飞书中回复指令 → 自动同步到 Obsidian。

## 工作原理

```
飞书云盘文档有变动（新增/修改/删除）
        ↓  每 10 分钟自动检查
飞书机器人发通知给你
        ↓  你在飞书中回复
  "全部同步" → 新增 + 修改 + 删除 全同步
  "仅新增"   → 只同步新文件
  "跳过"     → 什么都不做
        ↓
自动执行 → 机器人回复结果
```

## 前置条件

1. **[lark-cli](https://github.com/larksuite/lark-cli)** — 飞书命令行工具（需已配置 `lark-cli config init`）
2. **飞书应用** — 需开通以下权限：
   - `drive:drive.metadata:readonly` — 读取云盘文件列表
   - `docx:document:readonly` — 导出文档
   - `im:message` — 发送消息（bot）
   - `im:message.p2p_msg:get_as_user` — 读取 P2P 回复
   - `space:document:retrieve` — 读取云盘根目录
3. **Python 3.9+**
4. **Obsidian** — 本地仓库

## 安装

```bash
git clone https://github.com/Zhuanz2/feishutongbu.git
cd feishutongbu
python3 setup.py
```

`setup.py` 会引导你配置：
- lark-cli 路径
- Obsidian 仓库路径
- 飞书用户 Open ID
- 检查间隔

## 使用

### 手动同步

```bash
# 预览变更（不修改任何文件）
python3 scripts/sync.py preview

# 执行同步（全部变更）
python3 scripts/sync.py apply

# 只同步新增
python3 scripts/sync.py apply --approve new

# 只同步新增和修改，不删除
python3 scripts/sync.py apply --approve new --approve modified
```

### 自动化（定时 + 飞书回复确认）

```bash
# 单次检测 + 通知 + 读回复 + 执行
python3 scripts/check_and_act.py
```

**设置定时任务（推荐）：**

```bash
# 方法 1: crontab（每 10 分钟）
crontab -e
# 添加:
*/10 * * * * cd /path/to/feishutongbu && python3 scripts/check_and_act.py >> /tmp/feishutongbu.log 2>&1

# 方法 2: Claude Code 内置定时器
# 在 Claude Code 中输入:
/loop 10m python3 scripts/check_and_act.py
```

### 作为 Claude Code Skill

将 `SKILL.md` 复制到 `~/.claude/skills/feishutongbu/SKILL.md`，
然后在 Claude Code 中输入 `/feishutongbu` 即可手动触发。

## 文件结构

```
feishutongbu/
├── config.example.json      # 配置模板
├── config.json              # 个人配置（gitignore）
├── setup.py                 # 安装向导
├── SKILL.md                 # Claude Code skill 定义
├── scripts/
│   ├── common.py            # 公共模块（配置、lark-cli 封装）
│   ├── sync.py              # 同步引擎（preview + apply）
│   ├── notify.py            # 变更检测 + 飞书通知
│   └── check_and_act.py     # 主入口（定时任务调用）
└── README.md
```

## 同步规则

| 飞书类型 | Obsidian 处理 |
|---------|-------------|
| 📄 飞书文档 (docx) | 导出为 `.md` Markdown |
| 📊 电子表格 (sheet) | 创建带飞书链接的快捷方式 |
| 📋 多维表格 (bitable) | 创建带飞书链接的快捷方式 |

- 修改过的文档 → 重新导出，覆盖旧版本
- 飞书已删除的文档 → 删除 Obsidian 中对应文件

## License

MIT
