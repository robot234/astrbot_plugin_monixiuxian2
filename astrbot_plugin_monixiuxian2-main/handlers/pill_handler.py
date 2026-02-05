# handlers/pill_handler.py

from astrbot.api.event import AstrMessageEvent
from ..data import DataBase
from ..core import PillManager
from ..models import Player
from ..config_manager import ConfigManager
from .utils import player_required

CMD_USE_PILL = "服用丹药"
CMD_SHOW_PILLS = "丹药背包"
CMD_PILL_INFO = "丹药信息"

__all__ = ["PillHandler"]


class PillHandler:
    """丹药系统处理器 - 处理丹药使用和查看"""

    def __init__(self, db: DataBase, config_manager: ConfigManager):
        self.db = db
        self.config_manager = config_manager
        self.pill_manager = PillManager(db, config_manager)

    def _format_required_level(self, level_index: int) -> str:
        """同时展示灵修/体修的需求境界名称"""
        names = []
        if 0 <= level_index < len(self.config_manager.level_data):
            name = self.config_manager.level_data[level_index].get("level_name", "")
            if name:
                names.append(name)
        if 0 <= level_index < len(self.config_manager.body_level_data):
            name = self.config_manager.body_level_data[level_index].get("level_name", "")
            if name and name not in names:
                names.append(name)
        if not names:
            return "未知境界"
        return " / ".join(names)

    @player_required
    async def handle_use_pill(self, player: Player, event: AstrMessageEvent, pill_name: str = ""):
        """处理服用丹药指令

        Args:
            player: 玩家对象
            event: 事件对象
            pill_name: 丹药名称
        """
        # 检查是否提供了丹药名称
        if not pill_name or pill_name.strip() == "":
            yield event.plain_result(
                "请指定要服用的丹药名称！\n"
                f"💡 使用方法：{CMD_USE_PILL} [丹药名称]\n"
                f"💡 例如：{CMD_USE_PILL} 炼气丹"
            )
            return

        pill_name = pill_name.strip()

        # 先更新临时效果（移除过期的）
        await self.pill_manager.update_temporary_effects(player)

        # 使用丹药
        success, message = await self.pill_manager.use_pill(player, pill_name)

        if success:
            yield event.plain_result(message)
        else:
            yield event.plain_result(f"❌ {message}")

    @player_required
    async def handle_show_pills(self, player: Player, event: AstrMessageEvent):
        """处理查看丹药背包指令

        Args:
            player: 玩家对象
            event: 事件对象
        """
        # 先更新临时效果
        await self.pill_manager.update_temporary_effects(player)

        # 获取丹药背包显示
        inventory_display = self.pill_manager.get_pill_inventory_display(player)

        # 获取当前生效的临时效果
        active_effects = player.get_active_pill_effects()
        effects_display = []

        if active_effects:
            effects_display.append("\n--- 当前生效的临时效果 ---")
            for effect in active_effects:
                pill_name = effect.get("pill_name", "未知丹药")
                import time
                remaining_seconds = effect.get("expiry_time", 0) - int(time.time())
                if remaining_seconds > 0:
                    remaining_minutes = remaining_seconds // 60
                    hours = remaining_minutes // 60
                    minutes = remaining_minutes % 60

                    if hours > 0:
                        time_str = f"{hours}小时{minutes}分钟"
                    else:
                        time_str = f"{minutes}分钟"

                    effects_display.append(f"🌟 {pill_name} (剩余: {time_str})")

        # 检查回生丹状态
        resurrection_status = ""
        if player.has_resurrection_pill:
            resurrection_status = "\n🛡️ 当前拥有回生丹效果（可抵消一次死亡）"

        # 组合显示
        full_message = inventory_display
        if effects_display:
            full_message += "\n" + "\n".join(effects_display)
        if resurrection_status:
            full_message += resurrection_status

        yield event.plain_result(full_message)

    @player_required
    async def handle_pill_info(self, player: Player, event: AstrMessageEvent, pill_name: str = ""):
        """处理查看丹药信息指令

        Args:
            player: 玩家对象
            event: 事件对象
            pill_name: 丹药名称
        """
        if not pill_name or pill_name.strip() == "":
            yield event.plain_result(
                "请指定要查看的丹药名称！\n"
                f"💡 使用方法：{CMD_PILL_INFO} [丹药名称]\n"
                f"💡 例如：{CMD_PILL_INFO} 炼气丹"
            )
            return

        pill_name = pill_name.strip()

        # 获取丹药配置
        pill_data = self.pill_manager.get_pill_by_name(pill_name)
        if not pill_data:
            yield event.plain_result(f"❌ 找不到丹药【{pill_name}】的信息！")
            return

        # 构建丹药信息显示
        info_lines = [
            f"--- 丹药信息 ---",
            f"名称：{pill_data.get('name', '未知')}",
            f"品级：{pill_data.get('rank', '未知')}",
            f"类型：{self._get_subtype_display(pill_data.get('subtype', ''))}"
        ]

        # 描述
        description = pill_data.get('description', '')
        if description:
            info_lines.append(f"描述：{description}")

        # 需求境界
        required_level = pill_data.get('required_level_index', 0)
        if required_level > 0:
            level_name = self._format_required_level(required_level)
            info_lines.append(f"需求境界：{level_name}")

        # 价格
        price = pill_data.get('price', 0)
        if price > 0:
            info_lines.append(f"价格：{price} 灵石")

        # 效果描述
        effect_type = pill_data.get('effect_type', '')
        if effect_type:
            info_lines.append(f"\n【效果】")
            info_lines.append(self._get_effect_description(pill_data))

        info_lines.append("-" * 20)

        yield event.plain_result("\n".join(info_lines))

    def _get_subtype_display(self, subtype: str) -> str:
        """获取丹药子类型的显示名称"""
        subtype_map = {
            "exp": "修为丹",
            "resurrection": "回生丹",
            "cultivation_boost": "修炼加速",
            "permanent_attribute": "永久属性",
            "combat_boost": "战斗增益",
            "defensive_boost": "防御增益",
            "instant_restore": "瞬间恢复",
            "regeneration": "持续恢复",
            "debuff": "负面效果",
            "breakthrough_boost": "突破辅助",
            "breakthrough": "突破丹",
        }
        return subtype_map.get(subtype, "其他")

    def _get_effect_description(self, pill_data: dict) -> str:
        """获取丹药效果描述"""
        effect_type = pill_data.get('effect_type', '')
        subtype = pill_data.get('subtype', '')
        lines = []

        if subtype == "exp":
            exp_gain = pill_data.get('exp_gain', 0)
            lines.append(f"  增加修为：{exp_gain}")

        elif subtype == "resurrection":
            lines.append("  抵消一次死亡，复活后属性减半")

        elif effect_type == "temporary":
            duration = pill_data.get('duration_minutes', 0)
            lines.append(f"  持续时间：{duration}分钟")

            if 'cultivation_multiplier' in pill_data:
                mult = pill_data['cultivation_multiplier']
                lines.append(f"  修炼速度：{mult:+.0%}")

            if 'physical_damage_multiplier' in pill_data:
                mult = pill_data['physical_damage_multiplier']
                lines.append(f"  物伤：{mult:+.0%}")

            if 'magic_damage_multiplier' in pill_data:
                mult = pill_data['magic_damage_multiplier']
                lines.append(f"  法伤：{mult:+.0%}")

            if 'physical_defense_multiplier' in pill_data:
                mult = pill_data['physical_defense_multiplier']
                lines.append(f"  物防：{mult:+.0%}")

            if 'magic_defense_multiplier' in pill_data:
                mult = pill_data['magic_defense_multiplier']
                lines.append(f"  法防：{mult:+.0%}")

        elif effect_type == "permanent":
            lines.append("  永久效果（受30%上限限制）：")

            if 'physical_damage_gain' in pill_data:
                gain = pill_data['physical_damage_gain']
                lines.append(f"  物伤：{gain:+d}")

            if 'magic_damage_gain' in pill_data:
                gain = pill_data['magic_damage_gain']
                lines.append(f"  法伤：{gain:+d}")

            if 'physical_defense_gain' in pill_data:
                gain = pill_data['physical_defense_gain']
                lines.append(f"  物防：{gain:+d}")

            if 'magic_defense_gain' in pill_data:
                gain = pill_data['magic_defense_gain']
                lines.append(f"  法防：{gain:+d}")

            if 'mental_power_gain' in pill_data:
                gain = pill_data['mental_power_gain']
                lines.append(f"  精神力：{gain:+d}")

            if 'lifespan_gain' in pill_data:
                gain = pill_data['lifespan_gain']
                lines.append(f"  寿命：{gain:+d}")

        elif effect_type == "instant":
            if 'spiritual_qi_restore' in pill_data:
                restore = pill_data['spiritual_qi_restore']
                if restore == -1:
                    lines.append("  瞬间恢复灵气至满")
                else:
                    lines.append(f"  瞬间恢复灵气：{restore}")

        return "\n".join(lines) if lines else "  特殊效果"
