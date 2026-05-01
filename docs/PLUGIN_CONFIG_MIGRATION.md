# 插件配置存储重构：从 config.json 拆分为独立文件

> **Breaking Change** — 本文档记录 GsCore 插件配置存储的重大架构变更。

---

## 一、变更概述

原先所有插件的配置都存储在 `data/config.json` 的 `"plugins"` key 下，形成一个巨大的嵌套字典。随着插件数量增长，这带来了以下问题：

1. **配置膨胀**：所有插件配置挤在一个 JSON 文件中，文件越来越大
2. **写入冲突**：修改任意一个插件的配置都需要重写整个 `plugins` 字典
3. **可读性差**：手动排查配置问题时需要在大 JSON 中定位
4. **迁移困难**：无法单独备份或迁移某个插件的配置

**新方案**：每个插件的配置独立存储为 `data/plugins_configs/<plugin_name>.json`。

---

## 二、目录结构变化

### 变更前

```
data/
└── config.json          # 包含 "plugins": { "plugin_a": {...}, "plugin_b": {...} }
```

### 变更后

```
data/
├── config.json          # 不再包含 "plugins" key
└── plugins_configs/     # 新增目录
    ├── plugin_a.json    # 插件 A 的独立配置
    ├── plugin_b.json    # 插件 B 的独立配置
    └── ...
```

---

## 三、涉及的文件变更

### 3.1 `gsuid_core/data_store.py`

新增 `PLUGINS_CONFIGS_PATH` 常量，指向 `data/plugins_configs/` 目录。

```python
PLUGINS_CONFIGS_PATH = get_res_path("plugins_configs")
```

### 3.2 `gsuid_core/config.py`

- 从 `CONFIG_DEFAULT` 中移除 `"plugins": {}`
- 从 `DICT_CONFIG` 类型字面量中移除 `"plugins"`
- 新增 `PluginConfigStore` 类，提供以下能力：
  - `_migrate_from_config()`: 启动时自动迁移旧配置
  - `_load_all()`: 从 `plugins_configs/` 目录加载所有配置到内存
  - `get_all()`: 返回所有插件配置的引用（兼容旧 `config_plugins` 接口）
  - `save(plugin_name)`: 持久化单个插件配置到独立 JSON 文件
  - `save_all()`: 持久化所有插件配置
- 新增全局实例 `plugin_config_store`

### 3.3 `gsuid_core/sv.py`

- 导入从 `core_config.get_config("plugins")` 改为 `plugin_config_store.get_all()`
- `Plugins.set()` 和 `SV.set()` 中的写入逻辑从 `core_config.set_config("plugins", ...)` 改为 `plugin_config_store.save(plugin_name)`
- 内存中的 `config_plugins` 变量仍然保留，但现在指向 `PluginConfigStore` 的内部缓存

### 3.4 `gsuid_core/server.py`

- 插件加载完成后调用 `plugin_config_store.save_all()` 确保所有配置持久化

### 3.5 `gsuid_core/webconsole/core_config_api.py`

- 移除对 `"plugins"` key 的跳过逻辑（因为已不在 `CONFIG_DEFAULT` 中）

---

## 四、启动时自动迁移

当 GsCore 启动时，`PluginConfigStore.__init__()` 会自动执行迁移：

1. 检查 `config.json` 中是否存在 `"plugins"` key
2. 如果存在且非空，先备份 `config.json` 为 `data/config_backup.json`（仅当备份文件不存在时）
3. 遍历每个插件配置，写入 `data/plugins_configs/<name>.json`（仅当目标文件不存在时）
4. 从 `config.json` 中移除 `"plugins"` key 并写回

**注意**：
- 迁移是幂等的，重复执行不会覆盖已存在的独立配置文件
- 备份文件 `config_backup.json` 不会被覆盖，确保首次迁移前的完整快照保留

---

## 五、兼容性说明

| 组件 | 是否需要修改 | 说明 |
|------|-------------|------|
| WebConsole API | ❌ 无需修改 | 读取 `SL.plugins`（内存单例），不直接读取 `config_plugins` |
| buildin_plugins | ❌ 无需修改 | 通过 `sv.set()` 间接操作，已兼容 |
| 第三方插件 | ❌ 无需修改 | 通过 `SV` / `Plugins` 类操作，接口不变 |
| 手动编辑配置 | ⚠️ 路径变化 | 需要编辑 `data/plugins_configs/<name>.json` 而非 `config.json` |

---

## 六、配置文件格式

每个插件的独立 JSON 文件格式与原先 `config.json["plugins"][name]` 完全一致：

```json
{
    "name": "my_plugin",
    "pm": 6,
    "priority": 5,
    "enabled": true,
    "area": "SV",
    "black_list": [],
    "white_list": [],
    "prefix": [],
    "force_prefix": [],
    "disable_force_prefix": false,
    "allow_empty_prefix": false,
    "sv": {
        "帮助": {
            "priority": 5,
            "enabled": true,
            "pm": 6,
            "black_list": [],
            "area": "ALL",
            "white_list": []
        }
    }
}
```

---

## 七、回滚方案

如需回滚到旧版本：

1. 将 `data/plugins_configs/` 下所有 JSON 文件合并为一个字典
2. 在 `data/config.json` 中添加 `"plugins"` key，值为合并后的字典
3. 删除 `data/plugins_configs/` 目录
4. 回退代码版本
