"""
角色处理器模块

负责组装完整的角色提示词，将模板、角色资料和系统约束组合成最终的prompt。
支持注入情绪状态和群聊上下文。
"""

from .mood import get_mood_description
from .prompts import ROLE_PLAYING_START, SYSTEM_CONSTRAINTS
from .resource import load_persona
from ..buildin_tools import get_current_date


async def build_persona_prompt(
    char_name: str,
    mood_key: str | None = None,
    group_description: str | None = None,
) -> str:
    """
    组装完整的角色提示词

    将角色扮演开始提示词、角色资料和系统约束提示词组合成完整的prompt。
    支持注入情绪状态（mood）和群聊上下文。

    Args:
        char_name: 角色名称
        mood_key: 情绪隔离 key（群聊为 group_id，私聊为 user_id）
        group_description: 群聊简介/用户画像（可选，用于群聊适应性）

    Returns:
        完整的角色扮演prompt字符串
    """
    persona_content = await load_persona(char_name)
    current_time = await get_current_date()

    prompt = f"{ROLE_PLAYING_START}\n{persona_content}\n{SYSTEM_CONSTRAINTS}\n当前时间：{current_time}"

    # 注入情绪状态（群聊和私聊都支持）
    if mood_key:
        mood_desc = await get_mood_description(
            persona_name=char_name,
            group_id=mood_key,
        )
        if mood_desc:
            prompt += f"\n\n【当前状态】{mood_desc}"

    # 注入群聊上下文（群聊适应性）
    if group_description:
        prompt += f"\n\n【当前群聊环境】{group_description}"

    return prompt
