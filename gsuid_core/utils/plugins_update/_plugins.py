import os
import shutil
import asyncio
import subprocess
from typing import Dict, List, Union, Optional
from pathlib import Path

import aiohttp

from gsuid_core.gss import gss
from gsuid_core.logger import logger
from gsuid_core.utils.plugins_config.gs_config import core_plugins_config

from .api import CORE_PATH, PLUGINS_PATH, plugins_lib
from .utils import check_start_tool
from .git_async import (
    run_git,
    git_pull,
    git_clone,
    git_fetch,
    git_clean_xdf,
    git_reset_hard,
    git_diff_commits,
    git_is_valid_repo,
    git_get_current_branch,
)
from .reload_plugin import reload_plugin

plugins_list: Dict[str, Dict[str, str]] = {}


def _parse_git_error(message: str, plugin_name: str, operation: str = "pull") -> List[str]:
    """
    解析 git 错误信息，返回用户友好的提示和解决方案。

    Args:
        message: git 命令返回的原始错误信息
        plugin_name: 插件名称
        operation: 操作类型，"pull" 或 "fetch"

    Returns:
        包含错误描述和解决方案的字符串列表
    """
    msg_lower = message.lower()
    prefix = f"更新插件 {plugin_name} 失败"

    # 合并冲突
    if any(kw in msg_lower for kw in ["conflict", "merge", "automatic merge failed", "cannot be resolved"]):
        return [
            f"❌ {prefix}",
            "📋 原因：本地代码与远程代码存在合并冲突",
            "💡 解决：使用「强制更新」或「强行强制更新」覆盖本地修改",
        ]

    # 本地有未提交的修改
    if any(
        kw in msg_lower
        for kw in [
            "your local changes to the following files would be overwritten",
            "please commit your changes or stash them",
            "entry '.*' not uptodate",
            "dirty",
        ]
    ):
        return [
            f"❌ {prefix}",
            "📋 原因：本地存在未提交的修改，无法自动合并",
            "💡 解决：使用「强制更新」丢弃本地修改，或手动 stash 后重试",
        ]

    # 分支分叉
    if any(kw in msg_lower for kw in ["diverged", "need to specify how to reconcile", "refusing to merge unrelated"]):
        return [
            f"❌ {prefix}",
            "📋 原因：本地与远程分支历史分叉，无法自动合并",
            "💡 解决：使用「强制更新」重置到远程版本",
        ]

    # 网络错误
    if any(
        kw in msg_lower
        for kw in [
            "could not resolve host",
            "connection refused",
            "network is unreachable",
            "connection timed out",
            "failed to connect",
            "couldn't connect to server",
        ]
    ):
        return [
            f"❌ {prefix}",
            "📋 原因：网络连接失败，无法访问远程仓库",
            "💡 解决：检查网络连接，或配置 Git 镜像源加速访问",
        ]

    # SSL / 证书错误
    if any(kw in msg_lower for kw in ["ssl", "certificate", "cert"]):
        return [
            f"❌ {prefix}",
            "📋 原因：SSL 证书验证失败",
            "💡 解决：检查系统时间是否正确，或尝试更新 CA 证书",
        ]

    # 远程仓库不存在 / URL 错误
    if any(
        kw in msg_lower
        for kw in [
            "repository not found",
            "does not appear to be a git repository",
            "not found",
            "404",
        ]
    ):
        return [
            f"❌ {prefix}",
            "📋 原因：远程仓库地址无效或仓库已被删除",
            "💡 解决：检查插件仓库地址是否正确，可能需要重新安装插件",
        ]

    # 认证 / 权限错误
    if any(
        kw in msg_lower
        for kw in [
            "permission denied",
            "authentication failed",
            "403",
            "401",
            "credential",
            "fatal: could not read",
            "username",
        ]
    ):
        return [
            f"❌ {prefix}",
            "📋 原因：仓库认证失败，可能是私有仓库需要登录凭证",
            "💡 解决：检查 Git 凭证配置，或确认仓库访问权限",
        ]

    # 超时
    if "timeout" in msg_lower:
        return [
            f"⏭️ 跳过更新插件 {plugin_name}",
            "⚠️ git 操作超时，可能需要 git 凭证或网络不稳定",
        ]

    # 磁盘空间不足
    if any(kw in msg_lower for kw in ["no space left", "disk full", "not enough space"]):
        return [
            f"❌ {prefix}",
            "📋 原因：磁盘空间不足",
            "💡 解决：清理磁盘空间后重试",
        ]

    # 通用兜底
    return [
        f"❌ {prefix}",
        f"📋 原因：{message[:100]}",
        "💡 解决：尝试「强制更新」，若仍失败请检查控制台日志",
    ]


is_install_dep = core_plugins_config.get_config("AutoInstallDep").data
is_reload: bool = core_plugins_config.get_config("AutoReloadPlugins").data


async def check_plugin_exist(name: str):
    name = name.lower()

    if name in ["core_command", "gs_test"]:
        return "❌ 内置插件不可删除！"

    for i in PLUGINS_PATH.iterdir():
        if i.stem.lower().strip("_") == name:
            return i
    else:
        for i in PLUGINS_PATH.iterdir():
            if name in i.name.lower():
                return i


async def uninstall_plugin(path: Path):
    if not path.exists():
        return f"❌ 插件 {path.name} 不存在!"
    if path.is_dir():
        # Windows下处理被锁定的文件
        def onerror(func, path, exc):
            """处理删除文件时的权限错误"""
            import stat

            # 检查文件是否只读
            if not os.access(path, os.W_OK):
                # 尝试移除只读属性
                try:
                    os.chmod(path, stat.S_IWUSR)
                    func(path)
                except Exception:
                    pass  # 忽略二次错误
            else:
                raise exc

        try:
            shutil.rmtree(path)
            return f"✅ 插件目录 {path.name} 删除成功!"
        except PermissionError:
            # 尝试使用onerror回调处理被锁定的文件
            try:
                shutil.rmtree(path, onexc=onerror)
                if path.exists():
                    # 仍存在则尝试手动删除
                    _try_manual_delete(path)
                return f"✅ 插件目录 {path.name} 删除成功!"
            except Exception:
                return f"⚠️ 插件目录 {path.name} 部分文件被锁定,请手动删除或重启后重试!"
    else:
        path.unlink()
        return f"✅ 插件文件 {path.name} 删除成功!"


def _try_manual_delete(path: Path):
    """手动尝试删除目录内容"""
    import stat

    for item in path.rglob("*"):
        try:
            if item.is_file():
                os.chmod(item, stat.S_IWUSR)
                item.unlink()
            elif item.is_dir():
                os.chmod(item, stat.S_IWUSR)
                shutil.rmtree(item, ignore_errors=True)
        except Exception:
            pass
    # 最后尝试删除根目录
    try:
        os.chmod(path, stat.S_IWUSR)
        path.rmdir()
    except Exception:
        pass


# 传入一个path对象
def run_install(path: Optional[Path] = None) -> int:
    tools = check_start_tool()
    if tools == "python":
        logger.warning("你使用的是PIP环境, 无需进行 PDM/Poetry install!")
        return -200

    if path is None:
        path = CORE_PATH

    # 检测path是否是一个目录
    if not path.is_dir():
        raise ValueError(f"{path} is not a directory")

    # 异步执行poetry install命令，并返回返回码
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf8"

    if tools == "uv":
        CMD = "uv sync --inexact"
    else:
        CMD = f"{tools} install"

    proc = subprocess.run(
        CMD,
        cwd=path,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        shell=True,
        env=env,
        encoding="utf-8",
        text=True,
    )

    output = proc.stdout  # 获取输出
    error = proc.stderr  # 获取错误信息

    logger.info(output)
    if error:
        logger.error(error)

    retcode = -1 if proc.returncode is None else proc.returncode
    if "No dependencies to install or update" in output:
        retcode = 200
    return retcode


def check_retcode(retcode: int) -> str:
    if retcode == 200:
        return "无需更新依赖！"
    elif retcode == 0:
        return "新增/更新依赖成功!"
    else:
        return f"更新失败, 错误码{retcode}"


async def update_all_plugins(level: int = 0) -> List[str]:
    log_list = []
    for plugin in PLUGINS_PATH.iterdir():
        if _is_plugin(plugin):
            log_list.extend(await update_from_git_async(level, plugin))
    return log_list


def _is_plugin(plugin: Path) -> bool:
    if plugin.is_dir() and plugin.name != "__pycache__" and plugin.name != "core_command":
        return True
    return False


async def set_proxy_all_plugins(proxy: Optional[str] = None) -> List[str]:
    log_list = []
    for plugin in PLUGINS_PATH.iterdir():
        if _is_plugin(plugin):
            log_list.append(await set_proxy(plugin, proxy))
    log_list.append(await set_proxy(CORE_PATH, proxy))
    return log_list


async def refresh_list() -> List[str]:
    refresh_list = []
    async with aiohttp.ClientSession() as session:
        logger.trace(f"稍等...开始刷新插件列表, 地址: {plugins_lib}")
        async with session.get(plugins_lib) as resp:
            _plugins_list: Dict[str, Dict[str, Dict[str, str]]] = await resp.json()
            for i in _plugins_list["plugins"]:
                if i.lower() not in plugins_list:
                    refresh_list.append(i)
                    logger.debug(f"[刷新插件列表] 列表新增插件 {i}")
                plugins_list[i.lower()] = _plugins_list["plugins"][i]
    return refresh_list


async def get_plugins_list() -> Dict[str, Dict[str, str]]:
    if not plugins_list:
        await refresh_list()
    return plugins_list


async def get_local_plugins_list() -> Dict[str, Dict[str, str]]:
    """获取本地已安装的插件列表"""
    local_plugins: Dict[str, Dict[str, str]] = {}
    for plugin_dir in PLUGINS_PATH.iterdir():
        if _is_plugin(plugin_dir):
            plugin_name = plugin_dir.name
            local_plugins[plugin_name.lower()] = {
                "name": plugin_name,
                "link": str(plugin_dir),
                "info": f"本地插件：{plugin_name}",
                "branch": "main",
            }
    return local_plugins


async def get_plugins_url(name: str) -> Optional[Dict[str, str]]:
    if not plugins_list:
        await refresh_list()

    if name in plugins_list:
        return plugins_list[name]
    else:
        for _n in plugins_list:
            if name.lower() in _n:
                return plugins_list[_n]
        else:
            return None


async def install_plugins(plugins: Dict[str, str]) -> str:
    from .git_mirror import SSH_GITHUB_TEMPLATE, _is_ssh_mode, _is_proxy_prefix

    git_mirror: str = core_plugins_config.get_config("GitMirror").data

    plugin_name = plugins["link"].split("/")[-1]

    # 使用 GitMirror 镜像源/代理/SSH
    if git_mirror:
        if _is_ssh_mode(git_mirror):
            # SSH 模式：ssh://git@ssh.github.com:443/{owner}/{repo}.git
            link = plugins["link"].rstrip("/")
            parts = link.split("/")
            if len(parts) >= 2:
                owner, repo = parts[-2], parts[-1]
                git_path = SSH_GITHUB_TEMPLATE.format(owner=owner, repo=repo)
            else:
                git_path = f"{plugins['link']}.git"
        elif _is_proxy_prefix(git_mirror):
            # 代理前缀模式：{proxy_prefix}{full_github_url}
            proxy_prefix = git_mirror.rstrip("/") + "/"
            git_path = f"{proxy_prefix}{plugins['link']}.git"
        else:
            # 镜像模式：{mirror_prefix}/{repo_name}
            mirror_prefix = git_mirror.rstrip("/")
            git_path = f"{mirror_prefix}/{plugin_name}"
    else:
        git_path = f"{plugins['link']}.git"
    logger.info(f"稍等...开始安装插件, 地址: {git_path}")
    path = PLUGINS_PATH / plugin_name
    if path.exists():
        return "该插件已经安装过了!"

    branch = plugins["branch"] if plugins["branch"] != "main" else None

    success, message = await git_clone(git_path, path, branch=branch, depth=1)
    if not success:
        return f"❌ 插件{plugin_name}安装失败: {message}"

    logger.info(f"插件{plugin_name}安装成功!")
    if is_reload:
        gss.load_plugin(path)
    return f"插件{plugin_name}安装成功!发送[gs重启]以应用! (如已开启自动重载插件则无需重启)"


async def install_plugin(plugin_name: str) -> int:
    url = await get_plugins_url(plugin_name)
    if url is None:
        return -1
    await install_plugins(url)
    return 0


async def check_plugins(plugin_name: str) -> Optional[Path]:
    path = PLUGINS_PATH / plugin_name
    if path.exists():
        if await git_is_valid_repo(path):
            return path
        return None
    else:
        return None


async def check_can_update(repo_path: Path) -> bool:
    """检查仓库是否有可用更新"""
    success, _ = await git_fetch(repo_path)
    if not success:
        return False

    branch = await git_get_current_branch(repo_path)

    # 比较本地和远程的 commit hash
    returncode_local, local_hash, _ = await run_git(repo_path, "rev-parse", "HEAD")
    returncode_remote, remote_hash, _ = await run_git(repo_path, "rev-parse", f"origin/{branch}")

    if returncode_local != 0 or returncode_remote != 0:
        return False

    return local_hash != remote_hash


async def async_check_plugins(plugin_name: str):
    path = PLUGINS_PATH / plugin_name
    if path.exists():
        try:
            success, _ = await git_fetch(path, timeout=10)
            if not success:
                return 0

            returncode, stdout, _ = await run_git(path, "status")
            if returncode != 0:
                return 0

            if "Your branch is up to date" in stdout:
                return 4
            elif "not a git repository" in stdout:
                return 3
            else:
                return 1
        except Exception as e:
            logger.warning(f"检查插件 {plugin_name} 状态异常: {str(e)}")
            return 0
    return 3


async def check_status(plugin_name: str) -> int:
    return await async_check_plugins(plugin_name)


def extract_last_url(text: str):
    if "/http" in text:
        parts = text.split("/http")
        url = "http" + parts[-1]
        return url
    elif text.startswith("https://github.com/"):
        return text
    else:
        return None


async def set_proxy(repo: Path, proxy: Optional[str] = None) -> str:
    """设置单个仓库的 git remote URL（使用 GitMirror 镜像源）"""
    from .git_mirror import set_plugin_mirror

    mirror_prefix = proxy if proxy is not None else core_plugins_config.get_config("GitMirror").data
    success, message = await set_plugin_mirror(repo, mirror_prefix)
    return message


async def update_from_git_async(
    level: int = 0,
    repo_like: Union[str, Path, None] = None,
    log_key: List[str] = [],
    log_limit: int = 5,
) -> List[str]:
    """
    异步更新 git 仓库（替代原来的 update_from_git + update_from_git_in_tread）。

    Args:
        level: 更新等级 0=普通, 1=强制(reset --hard), 2=强行强制(clean -xdf + reset)
        repo_like: 仓库路径/名称，None 表示更新 core 本体
        log_key: 过滤 commit message 的关键字
        log_limit: 最大返回日志条数

    Returns:
        日志列表
    """
    # 解析仓库路径
    if repo_like is None:
        repo_path = CORE_PATH
        plugin_name = "早柚核心"
        if is_install_dep:
            run_install(CORE_PATH)
    elif isinstance(repo_like, Path):
        repo_path = repo_like
        plugin_name = repo_like.name
    else:
        checked = await check_plugins(repo_like)
        plugin_name = repo_like
        if not checked:
            logger.warning("[更新] 更新失败, 该插件不存在!")
            return ["更新失败, 不存在该插件!"]
        repo_path = checked

    # 验证是否是有效的 git 仓库
    if not await git_is_valid_repo(repo_path):
        logger.warning("[更新] 更新失败, 非有效Repo路径!")
        return ["更新失败, 该路径并不是一个有效的GitRepo路径, 请使用`git clone`安装插件..."]

    logger.info(f"[更新] 准备更新 [{plugin_name}], 更新等级为{level}")

    # 先执行 git fetch
    logger.info(f"[更新][{plugin_name}] 正在执行 git fetch")
    success, message = await git_fetch(repo_path)
    if not success:
        logger.warning(f"[更新] 执行 git fetch 失败...{message}!")
        return _parse_git_error(message, plugin_name, operation="fetch")

    # 获取当前分支
    default_branch = await git_get_current_branch(repo_path)

    # 获取更新前的 commit log 用于差异比较
    commits_diff = await git_diff_commits(
        repo_path,
        "HEAD",
        f"origin/{default_branch}",
        max_count=40,
    )

    # level >= 2: 强行强制更新 - clean -xdf
    if level >= 2:
        logger.warning(f"[更新][{plugin_name}] 正在执行 git clean --xdf")
        logger.warning("[更新] 你有 2 秒钟的时间中断该操作...")
        if plugin_name == "早柚核心":
            return ["更新失败, 禁止强行强制更新核心..."]
        await asyncio.sleep(2)
        await git_clean_xdf(repo_path)

    # level >= 1: 强制更新 - reset --hard
    if level >= 1:
        logger.warning(f"[更新][{plugin_name}] 正在执行 git reset --hard")
        await git_reset_hard(repo_path)

    # 执行 git pull
    success, pull_message = await git_pull(repo_path)
    if not success:
        logger.warning(f"[更新] 更新失败...{pull_message}!")
        return _parse_git_error(pull_message, plugin_name, operation="pull")

    logger.info(f"[更新][{plugin_name}] {pull_message}")

    # 构建更新日志
    log_list: List[str] = []
    if commits_diff:
        log_list.append(f"✅本次插件 {plugin_name} , 更新内容如下：")
        for commit_msg in commits_diff:
            if log_key:
                for key in log_key:
                    if key in commit_msg:
                        log_list.append(commit_msg)
                        if len(log_list) >= log_limit:
                            break
            else:
                log_list.append(commit_msg)
                if len(log_list) >= log_limit:
                    break
    else:
        log_list.append(f"✅插件 {plugin_name} 本次无更新内容！")

    if plugin_name != "早柚核心" and is_reload:
        reload_plugin(plugin_name)
    return log_list


async def update_plugins(
    plugin_name: str,
    level: int = 0,
    log_key: List[str] = [],
    log_limit: int = 10,
) -> Union[str, List]:
    if not plugin_name:
        return "请后跟有效的插件名称！\n例如：core更新插件genshinuid"

    if not plugins_list:
        await refresh_list()

    pn = plugin_name.lower()
    for _n in plugins_list:
        plugin = plugins_list[_n]
        if "alias" in plugin:
            for alias in plugin["alias"]:
                if pn == alias.lower():
                    pn = _n.lower()
                    break

    for _n in PLUGINS_PATH.iterdir():
        if pn == _n.name.lower():
            plugin_name = _n.name
            break

    log_list = await update_from_git_async(
        level,
        plugin_name,
        log_key,
        log_limit,
    )
    return log_list
