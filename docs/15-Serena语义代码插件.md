# Serena 语义代码插件

Serena 是一个第三方 MCP Server 插件，通过 LSP（Language Server Protocol）为 Claude Code / TreeCode 提供**符号级代码理解与编辑**能力。

> 项目地址：[github.com/oraios/serena](https://github.com/oraios/serena)
> 对应的 Claude Code 插件：`serena@claude-plugins-official`

---

## 定位：文本操作 vs 语义操作

Claude Code 内置工具以**文本**为粒度（Grep 搜字符串、Edit 替换文本行）；Serena 补充了**符号**粒度——它知道什么是类、方法、字段、参数，知道它们的边界和引用关系。

| 能力 | Claude Code 内置 | Serena |
|------|-----------------|--------|
| 代码搜索 | `Grep`（正则匹配文本） | `find_symbol`（按符号名/路径查找，支持子串匹配） |
| 文件结构 | `LSP:documentSymbol` | `get_symbols_overview`（分类展示，支持递归深度） |
| 引用查找 | `LSP:findReferences` | `find_referencing_symbols`（返回引用处代码片段 + 符号元信息） |
| 代码编辑 | `Edit`（精确文本替换） | `replace_symbol_body`（按符号边界替换）、`replace_content`（正则 + 通配符） |
| 重命名 | 手动多处 Edit | `rename_symbol`（全仓库 LSP rename） |
| 安全删除 | 手动确认无引用后删 | `safe_delete_symbol`（自动检查引用，无引用才删） |
| 代码插入 | `Edit` / `Write` | `insert_before_symbol` / `insert_after_symbol`（以符号为锚点插入） |

**核心优势**：重构场景下，Serena 的符号操作比文本操作更精确——不会因为同名字符串误匹配，也不需要手动计算行号范围。

---

## 架构

```
Claude Code / TreeCode (宿主进程)
  │
  ├── 插件系统 (plugins/)
  │     └── serena@claude-plugins-official (enabledPlugins)
  │           └── .mcp.json 定义 MCP Server 启动方式
  │
  └── MCP Client ──── stdio JSON-RPC ────► Serena MCP Server (uvx 子进程)
                                               │
                                               └── LSP 后端
                                                     ├── Pyright (Python)
                                                     ├── typescript-language-server (TS/JS)
                                                     └── ... (其他语言)
                                                           │
                                                           └── 代码仓库
```

### 启动方式

Serena 作为 MCP Server 通过 `uvx` 启动：

```json
// .mcp.json
{
  "serena": {
    "command": "uvx",
    "args": ["--from", "git+https://github.com/oraios/serena", "serena", "start-mcp-server"]
  }
}
```

Claude Code 启动时自动拉起该进程，通过 stdio 进行 JSON-RPC 通信。进程生命周期与 Claude Code 会话绑定。

---

## 安装与配置

### 安装

通过 Claude Code 插件市场安装：

```
/plugin install serena@claude-plugins-official
```

安装后的文件布局：

```
~/.claude/plugins/
├── installed_plugins.json                          # 全局安装记录
├── marketplaces/claude-plugins-official/
│   └── external_plugins/serena/
│       ├── .claude-plugin/plugin.json              # 插件元信息
│       └── .mcp.json                               # MCP Server 配置
└── cache/claude-plugins-official/serena/unknown/
    ├── .claude-plugin/plugin.json                  # 缓存副本
    └── .mcp.json                                   # 缓存副本
```

### 启用

在 `~/.claude/settings.json` 中：

```json
{
  "enabledPlugins": {
    "serena@claude-plugins-official": true
  }
}
```

### 项目注册

首次在某个仓库使用时，需要激活项目：

```
activate_project("/path/to/your/project")
```

Serena 会自动检测编程语言并启动对应的 LSP 后端。项目激活后会持久化记录，下次打开自动可用。

### Onboarding

Serena 有自己的 onboarding 机制（`check_onboarding_performed` → `onboarding`），用于让 LLM 生成项目结构记忆。这套记忆系统**独立于** Claude Code 的 `~/.claude/projects/.../memory/`。

---

## 工具清单

当前 Serena 1.1.2 在 `editing` + `interactive` 模式下提供 26 个活跃工具：

### 符号导航（只读）

| 工具 | 用途 | 典型用法 |
|------|------|----------|
| `get_symbols_overview` | 获取文件的符号结构（类、函数、变量） | 首次了解一个文件时调用，`depth=1` 可展开类成员 |
| `find_symbol` | 按 name_path 模式搜索符号 | `find_symbol("MyClass/my_method", include_body=True)` |
| `find_referencing_symbols` | 查找某符号的所有引用 | 重构前确认影响范围 |

**Name Path 规则**：
- 简单名 `"method"` — 匹配任意同名符号
- 相对路径 `"MyClass/method"` — 匹配 name path 后缀
- 绝对路径 `"/MyClass/method"` — 精确匹配完整路径
- 重载索引 `"MyClass/method[0]"` — 匹配第一个重载

### 符号编辑

| 工具 | 用途 |
|------|------|
| `replace_symbol_body` | 替换整个符号定义（含签名行） |
| `insert_before_symbol` | 在符号定义前插入内容（如新增 import） |
| `insert_after_symbol` | 在符号定义后插入内容（如新增方法） |
| `rename_symbol` | 全仓库重命名（LSP rename） |
| `safe_delete_symbol` | 检查无引用后删除，有引用则报告 |

### 文本级操作

| 工具 | 用途 |
|------|------|
| `replace_content` | 正则或字面量替换文件内容（支持 `allow_multiple_occurrences`） |
| `create_text_file` | 创建新文件 |
| `read_file` | 读取文件（支持行范围） |
| `search_for_pattern` | 正则搜索，支持 glob 过滤、上下文行、代码/非代码文件限定 |

### 文件系统

| 工具 | 用途 |
|------|------|
| `list_dir` | 列目录（支持递归） |
| `find_file` | 按文件名/通配符搜索 |
| `execute_shell_command` | 执行 shell 命令 |

### 项目与配置

| 工具 | 用途 |
|------|------|
| `activate_project` | 激活/切换项目 |
| `check_onboarding_performed` | 检查是否已完成 onboarding |
| `onboarding` | 执行项目 onboarding |
| `get_current_config` | 查看当前配置（版本、项目、模式、工具列表） |
| `initial_instructions` | 获取 Serena 使用手册 |

### 记忆系统

| 工具 | 用途 |
|------|------|
| `write_memory` | 写入项目记忆（md 格式，支持 `/` 分层） |
| `read_memory` | 读取记忆 |
| `list_memories` | 列出所有记忆（可按 topic 过滤） |
| `edit_memory` | 正则替换记忆内容 |
| `delete_memory` | 删除记忆 |
| `rename_memory` | 重命名/移动记忆 |

### 非活跃工具（按模式/后端切换）

Serena 还有一批 JetBrains IDE 专用工具（`jet_brains_*`）和行级编辑工具（`delete_lines`, `insert_at_line`, `replace_lines`），在当前 `desktop-app` 上下文中未激活。切换到 JetBrains 上下文时可用。

---

## 使用策略

Serena 的 Instructions Manual 推荐的工作流：

### 1. 渐进式信息获取

不要一上来就 `read_file` 读整个文件。推荐路径：

```
get_symbols_overview(depth=1)     # 看文件结构
    ↓
find_symbol(name, depth=1)        # 定位目标符号，看成员列表
    ↓
find_symbol(name, include_body=True)  # 只读需要的符号体
```

### 2. 重构安全检查

编辑符号前先检查引用：

```
find_referencing_symbols(name_path, relative_path)  # 确认影响范围
    ↓
rename_symbol / replace_symbol_body                  # 执行修改
```

### 3. 编辑方式选择

| 场景 | 推荐工具 |
|------|----------|
| 替换整个方法/类 | `replace_symbol_body` |
| 修改方法内几行 | `replace_content`（正则通配符） |
| 在文件开头加 import | `insert_before_symbol`（第一个顶层符号） |
| 在文件末尾加新函数 | `insert_after_symbol`（最后一个顶层符号） |
| 全仓库重命名 | `rename_symbol` |

### 4. `replace_content` 的正则技巧

Serena 文档特别强调：用 `.*?` 通配符避免写出完整的待替换文本，尤其是多行替换场景：

```python
# 好：用通配符跳过中间内容
needle: "def my_method.*?return result"  (mode="regex", DOTALL 已启用)

# 差：完整引用十几行代码
needle: "def my_method(self):\n    x = 1\n    y = 2\n    ..."
```

设置 `allow_multiple_occurrences=False`（默认）时，如果正则意外匹配多处会报错而非静默替换，安全性有保障。

---

## 与 TreeCode 插件系统的关系

Serena 通过 TreeCode 的插件系统加载（见 [docs/08-插件系统.md](08-插件系统.md)）：

1. Claude Code 插件市场下发 `.claude-plugin/plugin.json` + `.mcp.json`
2. TreeCode 的 `plugins/loader.py` 读取已启用插件的 `.mcp.json`
3. `mcp/client_manager.py` 根据配置启动 Serena MCP Server 进程
4. Serena 暴露的工具注册到 `ToolRegistry`，前缀为 `mcp__plugin_serena_serena__`

工具命名规则：`mcp__{plugin_scope}_{server_name}__{tool_name}`

---

## 注意事项

1. **两套记忆系统并存**：Serena 的 `write_memory` 和 Claude Code 的 `~/.claude/projects/.../memory/` 是独立的。Serena 记忆存储在 Serena 自己管理的路径中，不会出现在 Claude Code 的 MEMORY.md 里。

2. **LSP 启动延迟**：首次 `activate_project` 后，LSP 后端需要索引整个项目。大项目可能需要几秒到十几秒。

3. **符号操作的前提**：`replace_symbol_body`、`rename_symbol` 等工具依赖 LSP 的符号解析。如果 LSP 未启动或文件有语法错误，这些工具可能失败。

4. **与内置 LSP tool 的关系**：Claude Code 自身也有一个 `LSP` tool（支持 goToDefinition、findReferences 等）。两者底层可能连接不同的 LSP 实例。Serena 的符号工具通常更丰富（返回更多元信息和代码片段），但内置 LSP tool 更轻量。

5. **版本更新**：Serena 通过 `uvx --from git+https://github.com/oraios/serena` 拉取，每次启动都可能拉到最新版本。如需锁定版本，需修改 `.mcp.json` 中的 git ref。
