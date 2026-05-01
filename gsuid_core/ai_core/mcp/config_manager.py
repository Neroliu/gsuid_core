"""
MCP 配置管理器模块

管理用户自定义的 MCP 服务器配置，支持增删改查。
每个 MCP 配置以独立 JSON 文件存储在 data/ai_core/mcp_configs/ 目录下。

配置文件格式 (JSON):
{
    "name": "MiniMax",
    "command": "uvx",
    "args": ["minimax-coding-plan-mcp"],
    "env": {"MINIMAX_API_KEY": "your_key"},
    "enabled": true
}
"""

import json
from typing import Any
from pathlib import Path
from dataclasses import dataclass

from gsuid_core.logger import logger
from gsuid_core.ai_core.resource import MCP_CONFIGS_PATH


@dataclass
class MCPConfig:
    """MCP 服务器配置数据类"""

    name: str
    command: str
    args: list[str]
    env: dict[str, str]
    enabled: bool = True

    def to_dict(self) -> dict[str, Any]:
        """转换为字典"""
        return {
            "name": self.name,
            "command": self.command,
            "args": self.args,
            "env": self.env,
            "enabled": self.enabled,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "MCPConfig":
        """从字典创建配置"""
        return cls(
            name=data["name"],
            command=data["command"],
            args=data.get("args", []),
            env=data.get("env", {}),
            enabled=data.get("enabled", True),
        )


class MCPConfigManager:
    """
    MCP 配置管理器

    管理 data/ai_core/mcp_configs/ 目录下的 MCP 服务器配置文件。
    每个配置文件对应一个 MCP 服务器，文件名为 {config_id}.json。
    """

    def __init__(self) -> None:
        self._base_path: Path = MCP_CONFIGS_PATH
        self._cache: dict[str, MCPConfig] = {}
        self._load_all()

    def _get_config_path(self, config_id: str) -> Path:
        """获取配置文件的完整路径"""
        return self._base_path / f"{config_id}.json"

    def _load_all(self) -> None:
        """加载所有配置文件到缓存"""
        self._cache.clear()
        for config_file in self._base_path.glob("*.json"):
            config_id = config_file.stem
            try:
                with open(config_file, "r", encoding="UTF-8") as f:
                    data = json.load(f)
                self._cache[config_id] = MCPConfig.from_dict(data)
            except Exception as e:
                logger.error(f"🔌 [MCP Config] 加载配置文件失败: {config_file}, 错误: {e}")

    def list_configs(self) -> list[dict[str, Any]]:
        """
        列出所有 MCP 配置

        Returns:
            配置列表，每个元素包含 config_id 和配置详情
        """
        result: list[dict[str, Any]] = []
        for config_id, config in self._cache.items():
            item = config.to_dict()
            item["config_id"] = config_id
            result.append(item)
        return result

    def get_config(self, config_id: str) -> MCPConfig | None:
        """
        获取指定的 MCP 配置

        Args:
            config_id: 配置 ID（文件名不含扩展名）

        Returns:
            MCPConfig 实例，不存在则返回 None
        """
        return self._cache.get(config_id)

    def get_enabled_configs(self) -> list[tuple[str, MCPConfig]]:
        """
        获取所有启用的 MCP 配置

        Returns:
            (config_id, MCPConfig) 列表
        """
        return [(cid, cfg) for cid, cfg in self._cache.items() if cfg.enabled]

    def create_config(self, config_id: str, config: MCPConfig) -> tuple[bool, str]:
        """
        创建新的 MCP 配置

        Args:
            config_id: 配置 ID（文件名不含扩展名）
            config: MCP 配置对象

        Returns:
            (是否成功, 消息)
        """
        if config_id in self._cache:
            return False, f"配置 '{config_id}' 已存在"

        config_path = self._get_config_path(config_id)
        try:
            with open(config_path, "w", encoding="UTF-8") as f:
                json.dump(config.to_dict(), f, indent=4, ensure_ascii=False)
            self._cache[config_id] = config
            logger.info(f"🔌 [MCP Config] 创建配置: {config_id}")
            return True, "ok"
        except Exception as e:
            logger.error(f"🔌 [MCP Config] 创建配置失败: {config_id}, 错误: {e}")
            return False, str(e)

    def update_config(self, config_id: str, updates: dict[str, Any]) -> tuple[bool, str]:
        """
        更新 MCP 配置

        Args:
            config_id: 配置 ID
            updates: 要更新的字段字典

        Returns:
            (是否成功, 消息)
        """
        if config_id not in self._cache:
            return False, f"配置 '{config_id}' 不存在"

        current = self._cache[config_id]
        current_dict = current.to_dict()

        # 合并更新
        for key, value in updates.items():
            if key in current_dict:
                current_dict[key] = value

        try:
            updated_config = MCPConfig.from_dict(current_dict)
            config_path = self._get_config_path(config_id)
            with open(config_path, "w", encoding="UTF-8") as f:
                json.dump(updated_config.to_dict(), f, indent=4, ensure_ascii=False)
            self._cache[config_id] = updated_config
            logger.info(f"🔌 [MCP Config] 更新配置: {config_id}")
            return True, "ok"
        except Exception as e:
            logger.error(f"🔌 [MCP Config] 更新配置失败: {config_id}, 错误: {e}")
            return False, str(e)

    def delete_config(self, config_id: str) -> tuple[bool, str]:
        """
        删除 MCP 配置

        Args:
            config_id: 配置 ID

        Returns:
            (是否成功, 消息)
        """
        if config_id not in self._cache:
            return False, f"配置 '{config_id}' 不存在"

        config_path = self._get_config_path(config_id)
        try:
            config_path.unlink()
            del self._cache[config_id]
            logger.info(f"🔌 [MCP Config] 删除配置: {config_id}")
            return True, "ok"
        except Exception as e:
            logger.error(f"🔌 [MCP Config] 删除配置失败: {config_id}, 错误: {e}")
            return False, str(e)

    def reload(self) -> None:
        """重新加载所有配置文件"""
        self._load_all()
        logger.info(f"🔌 [MCP Config] 重新加载完成，共 {len(self._cache)} 个配置")


# 全局单例
mcp_config_manager = MCPConfigManager()
