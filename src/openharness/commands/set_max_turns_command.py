from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from openharness.commands.registry import CommandContext, CommandResult


async def set_max_turns_handler(args: str, ctx: CommandContext) -> CommandResult:
    """Handle /set-max-turns command."""
    from openharness.commands.registry import CommandResult

    # 如果没有参数，显示当前值
    if not args.strip():
        current = getattr(ctx.engine, "_max_turns", 8)  # 降级到 8
        return CommandResult(
            message=f"📊 当前最大轮次：{current}\n\n用法：/set-max-turns <数字>\n   例如：/set-max-turns 30",
        )

    # 解析参数
    try:
        new_value = int(args.strip())
    except ValueError:
        return CommandResult(
            message="❌ 无效的数字。用法：/set-max-turns <数字>",
        )

    # 范围限制
    if new_value < 1:
        return CommandResult(
            message="❌ 轮次必须 >= 1",
        )
    if new_value > 100:
        return CommandResult(
            message="❌ 轮次必须 <= 100（过大会导致会话过长）",
        )

    # 动态设置到 engine
    ctx.engine.set_max_turns(new_value)

    # 持久化到 settings.json
    from openharness.config.settings import load_settings, save_settings
    settings = load_settings()
    old_value = settings.max_turns
    settings.max_turns = new_value
    save_settings(settings)

    return CommandResult(
        message=f"✅ 最大轮次已设置为 {new_value}（原 {old_value}）\n"
                f"   - 本次会话立即生效\n"
                f"   - 已保存到 ~/.openharness/settings.json",
    )
