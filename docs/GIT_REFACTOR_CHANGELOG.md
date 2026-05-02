# Git 操作重构：移除 gitpython，全面使用异步命令执行

> 变更日期：2026-05-02

## 背景

原有代码中 `_plugins.py` 使用 `gitpython` 库（`from git.repo import Repo`）执行 git 操作（clone、pull、fetch 等），存在以下问题：

1. **凭证卡死**：当某个插件仓库需要 git 凭证（如私有仓库）时，`gitpython` 的 `fetch()`/`pull()` 会永久阻塞，导致「全部更新」命令卡死无法返回。
2. **依赖冗余**：`git_mirror.py` 和 `git_update.py` 已经使用 `asyncio.create_subprocess_exec` 异步执行 git 命令，但各自维护独立的 `_run_git` 实现，代码重复。
3. **平台兼容性**：`gitpython` 在某些 Windows 环境下存在路径编码问题。

## 变更内容

### 1. 新增共享异步 git 工具模块

**新增文件**：[`gsuid_core/utils/plugins_update/git_async.py`](gsuid_core/utils/plugins_update/git_async.py)

统一的异步 git 命令执行基础设施，提供以下功能：

| 函数 | 用途 |
|------|------|
| [`run_git()`](gsuid_core/utils/plugins_update/git_async.py:35) | 统一的异步 git 命令执行入口 |
| [`git_clone()`](gsuid_core/utils/plugins_update/git_async.py:87) | 异步克隆仓库 |
| [`git_fetch()`](gsuid_core/utils/plugins_update/git_async.py:126) | 异步 fetch |
| [`git_pull()`](gsuid_core/utils/plugins_update/git_async.py:147) | 异步 pull |
| [`git_reset_hard()`](gsuid_core/utils/plugins_update/git_async.py:168) | 异步 reset --hard |
| [`git_clean_xdf()`](gsuid_core/utils/plugins_update/git_async.py:189) | 异步 clean -xdf |
| [`git_get_remote_url()`](gsuid_core/utils/plugins_update/git_async.py:210) | 获取 remote URL |
| [`git_set_remote_url()`](gsuid_core/utils/plugins_update/git_async.py:231) | 设置 remote URL |
| [`git_get_current_branch()`](gsuid_core/utils/plugins_update/git_async.py:252) | 获取当前分支 |
| [`git_get_log()`](gsuid_core/utils/plugins_update/git_async.py:295) | 获取 commit log |
| [`git_diff_commits()`](gsuid_core/utils/plugins_update/git_async.py:322) | 获取两个 ref 之间的差异 |
| [`git_is_valid_repo()`](gsuid_core/utils/plugins_update/git_async.py:351) | 检查是否是有效 git 仓库 |

**关键设计**：

- 使用 `asyncio.create_subprocess_exec` 而非 `create_subprocess_shell`，避免 Windows `cmd.exe` 将 `%an` 等解释为环境变量
- 设置 `GIT_TERMINAL_PROMPT=0` 环境变量，防止 git 在需要凭证时弹出交互式提示
- 所有命令均有超时机制（默认 30 秒，clone 120 秒），超时自动 kill 进程并返回错误
- 超时返回 `(-999, "", "timeout")`，调用方可据此判断是否需要跳过

### 2. 重写 `_plugins.py` — 移除 gitpython

**修改文件**：[`gsuid_core/utils/plugins_update/_plugins.py`](gsuid_core/utils/plugins_update/_plugins.py)

- 移除 `from git.exc import GitCommandError, NoSuchPathError, InvalidGitRepositoryError`
- 移除 `from git.repo import Repo`
- [`install_plugins()`](gsuid_core/utils/plugins_update/_plugins.py:238) 改为 `async def`，使用 [`git_clone()`](gsuid_core/utils/plugins_update/git_async.py:87) 替代 `Repo.clone_from()`
- [`install_plugin()`](gsuid_core/utils/plugins_update/_plugins.py:280) 改为 `async def`
- [`check_plugins()`](gsuid_core/utils/plugins_update/_plugins.py:291) 改为 `async def`，使用 [`git_is_valid_repo()`](gsuid_core/utils/plugins_update/git_async.py:351) 替代 `Repo()`
- [`check_can_update()`](gsuid_core/utils/plugins_update/_plugins.py:301) 改为 `async def`，使用 `run_git` + `git_fetch` 替代 `repo.remote().fetch()`
- 新增 [`update_from_git_async()`](gsuid_core/utils/plugins_update/_plugins.py:373) 替代原来的 `update_from_git()` + `update_from_git_in_tread()`，完全异步执行
- **凭证超时处理**：当 `git fetch` 或 `git pull` 超时时，跳过该插件并报告「可能需要 git 凭证」

### 3. 更新 `git_mirror.py` — 使用共享 `run_git`

**修改文件**：[`gsuid_core/utils/plugins_update/git_mirror.py`](gsuid_core/utils/plugins_update/git_mirror.py)

- 移除独立的 `_run_git()` 实现
- [`get_remote_url()`](gsuid_core/utils/plugins_update/git_mirror.py:58) 改为调用 [`git_get_remote_url()`](gsuid_core/utils/plugins_update/git_async.py:210)
- [`set_plugin_mirror()`](gsuid_core/utils/plugins_update/git_mirror.py:359) 中的 `git remote set-url` 改为调用 [`git_set_remote_url()`](gsuid_core/utils/plugins_update/git_async.py:231)

### 4. 更新 `git_update.py` — 使用共享 `run_git`

**修改文件**：[`gsuid_core/utils/plugins_update/git_update.py`](gsuid_core/utils/plugins_update/git_update.py)

- 移除独立的 `_run_git()` 实现
- 所有 git 命令调用改为使用 [`run_git()`](gsuid_core/utils/plugins_update/git_async.py:35)
- [`get_current_branch()`](gsuid_core/utils/plugins_update/git_update.py:94) 改为调用 [`git_get_current_branch()`](gsuid_core/utils/plugins_update/git_async.py:252)
- [`force_update()`](gsuid_core/utils/plugins_update/git_update.py:307) 改为调用 [`git_fetch()`](gsuid_core/utils/plugins_update/git_async.py:126)、[`git_reset_hard()`](gsuid_core/utils/plugins_update/git_async.py:168)、[`git_pull()`](gsuid_core/utils/plugins_update/git_async.py:147)

### 5. 更新调用方

| 文件 | 变更 |
|------|------|
| [`core_update/__init__.py`](gsuid_core/buildin_plugins/core_command/core_update/__init__.py) | `update_from_git_in_tread` → `update_from_git_async` |
| [`auto_update/auto_task.py`](gsuid_core/buildin_plugins/core_command/auto_update/auto_task.py) | `update_from_git_in_tread` → `update_from_git_async` |
| [`install_plugins/__init__.py`](gsuid_core/buildin_plugins/core_command/install_plugins/__init__.py) | `install_plugins(plugins)` → `await install_plugins(plugins)` |

### 6. 移除 gitpython 依赖

**修改文件**：[`pyproject.toml`](pyproject.toml)

移除 `"gitpython>=3.1.27"` 依赖项。

### 7. WebConsole API 影响

经检查，以下 WebConsole API **无需修改**：

- [`plugins_api.py`](gsuid_core/webconsole/plugins_api.py)：通过 `from _plugins import install_plugin, update_plugins, uninstall_plugin` 调用，函数签名未变
- [`git_mirror_api.py`](gsuid_core/webconsole/git_mirror_api.py)：通过 `from git_mirror import ...` 调用，函数签名未变
- [`git_update_api.py`](gsuid_core/webconsole/git_update_api.py)：通过 `from git_update import ...` 调用，函数签名未变

## 凭证超时处理机制

当「全部更新」命令执行时，如果某个插件仓库需要 git 凭证：

1. `run_git()` 设置 `GIT_TERMINAL_PROMPT=0`，git 不会弹出交互式提示
2. git 命令会在 30 秒内超时（由 `asyncio.wait_for` 控制）
3. 超时后进程被 kill，返回 `(-999, "", "timeout")`
4. `update_from_git_async()` 检测到超时，跳过该插件并返回提示信息：
   ```
   ⏭️ 跳过更新插件 xxx
   ⚠️ git fetch 失败，可能需要 git 凭证，请检查仓库配置
   ```
5. 继续更新下一个插件，不会阻塞

## 注意事项

- `gsuid_core/plugins/_GenshinUID/GenshinUID/genshinuid_update/update.py` 中仍使用 `import git`，这是 GenshinUID 插件自身的代码，不在本次重构范围内
- 所有 git 命令使用 `asyncio.create_subprocess_exec` 执行，兼容 Windows/Linux/macOS
