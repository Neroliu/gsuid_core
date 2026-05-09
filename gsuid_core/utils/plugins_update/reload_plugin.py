import sys

from gsuid_core.sv import SL
from gsuid_core.gss import gss
from gsuid_core.logger import logger
from gsuid_core.server import _module_cache


def reload_plugin(plugin_name: str) -> str:
    logger.info(f"🔔 正在重载插件 {plugin_name}...")

    # ──────────────────────────────────────────
    # 第一步：收集该插件下所有 SV 和 Plugins 对象
    # ──────────────────────────────────────────
    sv_names_to_del = [sv_name for sv_name, sv in SL.lst.items() if sv.self_plugin_name == plugin_name]
    plugins_to_del = {sv.plugins for sv in SL.lst.values() if sv.self_plugin_name == plugin_name}

    # ──────────────────────────────────────────
    # 第二步：清理 SL 三张表
    # ──────────────────────────────────────────
    for sv_name in sv_names_to_del:
        sv = SL.lst.pop(sv_name)
        # 清除 is_initialized，否则 SV.__init__ 重载时会被跳过
        sv.is_initialized = False

    for plugins in plugins_to_del:
        SL.detail_lst.pop(plugins, None)

    SL.plugins.pop(plugin_name, None)

    # ──────────────────────────────────────────
    # 第三步：清理 sys.modules 和 _module_cache
    # 必须覆盖所有子模块，不能只清入口
    # ──────────────────────────────────────────
    stale_modules = [
        k
        for k in sys.modules
        if k == plugin_name  # 顶层包名
        or k.startswith(f"{plugin_name}.")  # 子模块
        or f".{plugin_name}." in k  # plugins.MajsoulUID.xxx 形式
        or k.endswith(f".{plugin_name}")
    ]
    for k in stale_modules:
        sys.modules.pop(k, None)

    stale_cache = [k for k in list(_module_cache) if plugin_name in k]
    for k in stale_cache:
        _module_cache.pop(k, None)

    # ──────────────────────────────────────────
    # 第四步：重新加载
    # ──────────────────────────────────────────
    module_list = gss.load_plugin(plugin_name)

    if module_list is None:
        return f"❌ 未知的插件类型 {plugin_name}"
    if isinstance(module_list, str):
        return module_list  # load_plugin 已经返回了错误信息

    for module_name, filepath, _type in module_list:
        try:
            gss.cached_import(module_name, filepath, _type)
        except Exception as e:
            logger.exception(f"❌ 重载模块 {module_name} 失败: {e}")
            return f"❌ 重载失败: {e}"

    logger.success(f"✨ 已重载插件 {plugin_name}")
    return f"✨ 已重载插件 {plugin_name}!"
