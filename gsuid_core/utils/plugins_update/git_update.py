"""
Git Update 工具模块

提供异步的 git 版本管理功能，支持：
- 获取远程 commit 列表
- 获取当前 commit 信息
- 回退到指定版本
- 强制更新（git reset --hard + git pull）

所有 git 操作均通过 asyncio.create_subprocess_shell 异步执行，避免阻塞事件循环。
"""

import asyncio
from typing import List, Optional, TypedDict
from pathlib import Path

from gsuid_core.logger import logger

from .api import CORE_PATH, PLUGINS_PATH


class CommitInfo(TypedDict):
    """Commit 信息"""

    hash: str
    short_hash: str
    author: str
    date: str
    message: str


class GitStatusInfo(TypedDict):
    """Git 仓库状态信息"""

    name: str
    path: str
    current_commit: CommitInfo
    is_git_repo: bool
    branch: str


async def _run_git(repo_path: Path, *args: str) -> tuple[int, str, str]:
    """
    在指定目录下异步执行 git 命令。

    使用 create_subprocess_exec 而非 create_subprocess_shell，
    避免 Windows cmd.exe 将 %an 等解释为环境变量。

    Args:
        repo_path: 仓库路径
        *args: git 子命令及参数

    Returns:
        (returncode, stdout, stderr)
    """
    import os

    env = os.environ.copy()
    env["GIT_TERMINAL_PROMPT"] = "0"
    process = await asyncio.create_subprocess_exec(
        "git",
        *args,
        cwd=repo_path,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
    )
    stdout, stderr = await process.communicate()
    return (
        process.returncode or 0,
        stdout.decode("utf-8", errors="replace").strip(),
        stderr.decode("utf-8", errors="replace").strip(),
    )


def _parse_commit_line(line: str) -> Optional[CommitInfo]:
    """
    解析 git log 格式的 commit 行。

    格式: hash|author|date|message

    Args:
        line: git log 输出行

    Returns:
        CommitInfo 字典，解析失败返回 None
    """
    parts = line.split("|", 3)
    if len(parts) < 4:
        return None

    hash_val, author, date, message = parts
    return CommitInfo(
        hash=hash_val.strip(),
        short_hash=hash_val.strip()[:7],
        author=author.strip(),
        date=date.strip(),
        message=message.strip(),
    )


async def get_current_commit(repo_path: Path) -> Optional[CommitInfo]:
    """
    获取仓库当前 HEAD 的 commit 信息。

    Args:
        repo_path: 仓库路径

    Returns:
        CommitInfo 字典，失败返回 None
    """
    if not (repo_path / ".git").exists():
        return None

    returncode, stdout, stderr = await _run_git(
        repo_path,
        "log",
        "-1",
        "--format=%H|%an|%ai|%s",
    )

    if returncode != 0 or not stdout:
        logger.warning(f"[Git Update] 获取当前 commit 失败: {stderr}")
        return None

    return _parse_commit_line(stdout)


async def get_current_branch(repo_path: Path) -> str:
    """
    获取仓库当前分支名称。

    在 detached HEAD 状态下，尝试获取默认分支名（main/master）。

    Args:
        repo_path: 仓库路径

    Returns:
        分支名称
    """
    returncode, stdout, _ = await _run_git(
        repo_path,
        "branch",
        "--show-current",
    )

    if returncode == 0 and stdout:
        return stdout

    # detached HEAD 状态，尝试获取远程默认分支
    returncode, stdout, _ = await _run_git(
        repo_path,
        "symbolic-ref",
        "refs/remotes/origin/HEAD",
        "--short",
    )

    if returncode == 0 and stdout and "/" in stdout:
        # 输出格式: origin/main
        return stdout.split("/", 1)[1]

    # fallback: 尝试 main 和 master
    for branch_name in ("main", "master"):
        returncode, _, _ = await _run_git(
            repo_path,
            "rev-parse",
            "--verify",
            f"origin/{branch_name}",
        )
        if returncode == 0:
            return branch_name

    return "main"


async def get_remote_commits(
    repo_path: Path,
    max_count: int = 50,
) -> List[CommitInfo]:
    """
    获取远程仓库的 commit 列表。

    先尝试 git fetch，如果失败（如认证问题）则使用本地缓存的 origin ref。
    然后获取 origin/{branch} 的 commit 历史。

    Args:
        repo_path: 仓库路径
        max_count: 最大返回数量

    Returns:
        CommitInfo 列表
    """
    if not (repo_path / ".git").exists():
        return []

    # 尝试 fetch 获取最新远程信息，失败则使用本地缓存
    returncode, _, stderr = await _run_git(repo_path, "fetch")
    if returncode != 0:
        logger.warning(f"[Git Update] git fetch 失败（将使用本地缓存的远程 ref）: {stderr}")

    # 获取当前分支
    branch = await get_current_branch(repo_path)

    # 获取远程 commit 列表
    returncode, stdout, stderr = await _run_git(
        repo_path,
        "log",
        f"origin/{branch}",
        f"-{max_count}",
        "--format=%H|%an|%ai|%s",
    )

    if returncode != 0 or not stdout:
        logger.warning(f"[Git Update] 获取远程 commit 列表失败: {stderr}")
        return []

    commits: List[CommitInfo] = []
    for line in stdout.split("\n"):
        line = line.strip()
        if not line:
            continue
        commit = _parse_commit_line(line)
        if commit:
            commits.append(commit)

    return commits


async def get_local_commits(
    repo_path: Path,
    max_count: int = 50,
) -> List[CommitInfo]:
    """
    获取本地仓库的 commit 历史。

    Args:
        repo_path: 仓库路径
        max_count: 最大返回数量

    Returns:
        CommitInfo 列表
    """
    if not (repo_path / ".git").exists():
        return []

    returncode, stdout, stderr = await _run_git(
        repo_path,
        "log",
        f"-{max_count}",
        "--format=%H|%an|%ai|%s",
    )

    if returncode != 0 or not stdout:
        logger.warning(f"[Git Update] 获取本地 commit 列表失败: {stderr}")
        return []

    commits: List[CommitInfo] = []
    for line in stdout.split("\n"):
        line = line.strip()
        if not line:
            continue
        commit = _parse_commit_line(line)
        if commit:
            commits.append(commit)

    return commits


async def get_git_status(repo_path: Path) -> Optional[GitStatusInfo]:
    """
    获取仓库的完整状态信息。

    Args:
        repo_path: 仓库路径

    Returns:
        GitStatusInfo 字典，失败返回 None
    """
    if not (repo_path / ".git").exists():
        return None

    current_commit = await get_current_commit(repo_path)
    if not current_commit:
        return None

    branch = await get_current_branch(repo_path)

    return GitStatusInfo(
        name=repo_path.name,
        path=str(repo_path),
        current_commit=current_commit,
        is_git_repo=True,
        branch=branch,
    )


async def checkout_commit(repo_path: Path, commit_hash: str) -> tuple[bool, str]:
    """
    回退到指定 commit。

    执行 git reset --hard {commit_hash}，将仓库切换到指定版本。
    使用 reset --hard 而非 checkout，避免进入 detached HEAD 状态，
    也不会触发 git 凭证请求。

    Args:
        repo_path: 仓库路径
        commit_hash: 目标 commit hash（支持短 hash）

    Returns:
        (success, message)
    """
    if not (repo_path / ".git").exists():
        return False, "不是有效的 git 仓库"

    # 验证 commit hash 是否存在
    returncode, _, stderr = await _run_git(
        repo_path,
        "cat-file",
        "-t",
        commit_hash,
    )

    if returncode != 0:
        return False, f"无效的 commit hash: {commit_hash}"

    # 执行 reset --hard
    returncode, _, stderr = await _run_git(
        repo_path,
        "reset",
        "--hard",
        commit_hash,
    )

    if returncode != 0:
        logger.warning(f"[Git Update] reset --hard 失败: {stderr}")
        return False, f"reset --hard 失败: {stderr}"

    logger.info(f"[Git Update] 已回退到 commit: {commit_hash}")
    return True, f"已回退到 commit: {commit_hash[:7]}"


async def force_update(repo_path: Path) -> tuple[bool, str]:
    """
    强制更新仓库。

    执行 git reset --hard origin/{branch}，然后 git pull。

    Args:
        repo_path: 仓库路径

    Returns:
        (success, message)
    """
    if not (repo_path / ".git").exists():
        return False, "不是有效的 git 仓库"

    # 获取当前分支
    branch = await get_current_branch(repo_path)
    if branch == "unknown":
        return False, "无法获取当前分支信息"

    # 先 fetch
    returncode, _, stderr = await _run_git(repo_path, "fetch")
    if returncode != 0:
        return False, f"git fetch 失败: {stderr}"

    # git reset --hard origin/{branch}
    returncode, stdout, stderr = await _run_git(
        repo_path,
        "reset",
        "--hard",
        f"origin/{branch}",
    )

    if returncode != 0:
        logger.warning(f"[Git Update] git reset --hard 失败: {stderr}")
        return False, f"git reset --hard 失败: {stderr}"

    # git pull
    returncode, stdout, stderr = await _run_git(repo_path, "pull")
    if returncode != 0:
        logger.warning(f"[Git Update] git pull 失败: {stderr}")
        return False, f"git pull 失败: {stderr}"

    # 获取更新后的 commit 信息
    current_commit = await get_current_commit(repo_path)
    if current_commit:
        message = f"强制更新成功，当前版本: {current_commit['short_hash']}"
    else:
        message = "强制更新成功"

    logger.info(f"[Git Update] {message}")
    return True, message


async def get_all_plugins_status() -> List[GitStatusInfo]:
    """
    获取所有插件（包括 core 本体）的 git 状态信息。

    Returns:
        GitStatusInfo 列表
    """
    result: List[GitStatusInfo] = []

    # core 本体
    core_status = await get_git_status(CORE_PATH)
    if core_status:
        result.append(core_status)

    # 所有插件
    if PLUGINS_PATH.exists():
        for plugin_dir in sorted(PLUGINS_PATH.iterdir()):
            if plugin_dir.is_dir() and plugin_dir.name != "__pycache__":
                plugin_status = await get_git_status(plugin_dir)
                if plugin_status:
                    result.append(plugin_status)

    return result


def _resolve_plugin_path(plugin_name: str) -> Optional[Path]:
    """
    解析插件名称到实际路径。

    Args:
        plugin_name: 插件名称

    Returns:
        插件路径，不存在返回 None
    """
    if plugin_name.lower() == "gsuid_core":
        return CORE_PATH

    # 尝试精确匹配
    plugin_path = PLUGINS_PATH / plugin_name
    if plugin_path.exists():
        return plugin_path

    # 尝试大小写不敏感匹配
    for d in PLUGINS_PATH.iterdir():
        if d.is_dir() and d.name.lower() == plugin_name.lower():
            return d

    return None
