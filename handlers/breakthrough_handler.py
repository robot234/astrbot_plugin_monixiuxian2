# handlers/breakthrough_handler.py

from astrbot.api.event import AstrMessageEvent
from ..data import DataBase
from ..core import BreakthroughManager, PillManager
from ..core.equipment_manager import EquipmentManager
from ..core.skill_manager import SkillManager
from ..core.storage_ring_manager import StorageRingManager
from ..config_manager import ConfigManager
from ..models import Player
from .utils import player_required

CMD_BREAKTHROUGH = "突破"
CMD_BREAKTHROUGH_INFO = "突破信息"
BREAKTHROUGH_PILL_REDUCTION_RATIO = 0.58
TEMP_BONUS_REDUCTION_RATIO = 0.38

__all__ = ["BreakthroughHandler"]


class BreakthroughHandler:
    """突破系统处理器"""

    def __init__(self, db: DataBase, config_manager: ConfigManager, config: dict):
        self.db = db
        self.config_manager = config_manager
        self.config = config
        self.breakthrough_manager = BreakthroughManager(db, config_manager, config)
        self.pill_manager = PillManager(db, config_manager)
        
        # 初始化装备和技能管理器用于战斗
        self.storage_ring_mgr = StorageRingManager(db, config_manager)
        self.equipment_manager = EquipmentManager(db, config_manager, self.storage_ring_mgr)
        self.skill_manager = SkillManager(db, config_manager)

    @player_required
    async def handle_breakthrough_info(self, player: Player, event: AstrMessageEvent):
        """查看突破信息"""
        display_name = event.get_sender_name()

        # 根据修炼类型获取对应的境界数据
        level_data = self.config_manager.get_level_data(player.cultivation_type)

        # 检查是否已经是最高境界
        if player.level_index >= len(level_data) - 1:
            yield event.plain_result("你已经达到了最高境界，无法继续突破！")
            return

        await self.pill_manager.update_temporary_effects(player)
        modifiers = self.pill_manager.get_breakthrough_modifiers(player)

        # 获取突破信息（包含心魔难度）
        info = self.breakthrough_manager.get_breakthrough_info(
            player,
            modifiers.get("temp_bonus", 0)
        )
        
        current_level_name = info["current_level"]
        next_level_name = info["next_level"]
        required_exp = info["required_exp"]
        cultivation_speed = info["cultivation_speed"]
        difficulty = info["difficulty"]
        base_difficulty = info["base_difficulty"]
        difficulty_reduction = info["difficulty_reduction"]
        difficulty_rating = info["difficulty_rating"]
        difficulty_color = info["difficulty_color"]
        spiritual_root = info["spiritual_root"]

        # 检查修为是否满足
        exp_satisfied = player.experience >= required_exp
        exp_status = "✅ 满足" if exp_satisfied else "❌ 不足"

        # 查找适用的破境丹
        available_pills = []
        for pill_name, pill_data in self.config_manager.pills_data.items():
            if (pill_data.get("subtype") == "breakthrough" and
                pill_data.get("target_level_index") == player.level_index + 1):
                breakthrough_bonus = pill_data.get("breakthrough_bonus", 0)
                difficulty_reduction = breakthrough_bonus * BREAKTHROUGH_PILL_REDUCTION_RATIO
                available_pills.append({
                    "name": pill_name,
                    "rank": pill_data.get("rank", ""),
                    "difficulty_reduction": difficulty_reduction
                })

        # 构建信息显示
        info_lines = [
            f"=== {display_name} 的突破信息 ===\n",
            f"当前境界：{current_level_name}\n",
            f"下一境界：{next_level_name}\n",
            f"━━━━━━━━━━━━━━━\n",
            f"【突破条件】\n",
            f"所需修为：{required_exp:,}\n",
            f"当前修为：{player.experience:,}\n",
            f"修为状态：{exp_status}\n",
            f"━━━━━━━━━━━━━━━\n",
            f"【心魔信息】\n",
            f"灵根/体质：{spiritual_root}\n",
            f"修炼速度：{cultivation_speed:.1f}x\n",
            f"基础难度：{base_difficulty:.2f}\n",
            f"当前难度：{difficulty_color} {difficulty_rating} ({difficulty:.2f})\n",
        ]

        # 难度说明
        info_lines.append(f"\n💡 难度说明：\n")
        info_lines.append(f"• 心魔会随境界阶梯化增强，越往后越难\n")
        info_lines.append(f"• 资质越偏离中位，心魔会额外增强\n")
        info_lines.append(f"• 破境丹和临时增益会直接削减最终难度\n")

        if modifiers.get("temp_bonus", 0) > 0:
            temp_reduction = modifiers["temp_bonus"] * TEMP_BONUS_REDUCTION_RATIO
            info_lines.append(f"\n🔮 临时丹药效果：心魔难度 -{temp_reduction:.1%}\n")

        if difficulty_reduction > 0:
            info_lines.append(f"🧪 当前总减难：-{difficulty_reduction:.2f}\n")
        
        death_reduce = 1 - modifiers.get("permanent_death_multiplier", 1.0)
        if death_reduce > 0:
            info_lines.append(f"🛡️ 死亡概率降低：{death_reduce:.1%}\n")

        if available_pills:
            info_lines.append(f"\n【可用破境丹】\n")
            for pill in available_pills:
                info_lines.append(
                    f"• {pill['name']}（{pill['rank']}）\n"
                    f"  使用后心魔难度降低：{pill['difficulty_reduction']:.1%}\n"
                )
        else:
            info_lines.append(f"\n暂无适用的破境丹\n")

        # 突破说明
        info_lines.extend([
            f"━━━━━━━━━━━━━━━\n",
            f"【突破说明】\n",
            f"• 使用命令：{CMD_BREAKTHROUGH} 或 {CMD_BREAKTHROUGH} [破境丹名称]\n",
            f"• 突破时需要与心魔战斗\n",
            f"• 战胜心魔：境界提升，实力大增\n",
            f"• 战败心魔：损失8%修为，有概率死亡\n",
            f"• 心魔战斗失败的死亡率较低\n",
            f"• 死亡后：所有数据清除，需重新入仙途\n",
            f"=" * 28
        ])

        yield event.plain_result("".join(info_lines))

    @player_required
    async def handle_breakthrough(self, player: Player, event: AstrMessageEvent, pill_name: str = None):
        """执行突破"""
        display_name = event.get_sender_name()

        await self.pill_manager.update_temporary_effects(player)
        modifiers = self.pill_manager.get_breakthrough_modifiers(player)

        # 根据修炼类型获取对应的境界数据
        level_data = self.config_manager.get_level_data(player.cultivation_type)

        # 如果指定了破境丹，验证其有效性
        if pill_name and pill_name.strip():
            pill_name = pill_name.strip()
            pill_data = self.config_manager.pills_data.get(pill_name)

            if not pill_data:
                yield event.plain_result(f"❌ 未找到破境丹：{pill_name}")
                return

            if pill_data.get("subtype") != "breakthrough":
                yield event.plain_result(f"❌ {pill_name} 不是破境丹")
                return

            # 检查是否适用于当前突破
            target_level = pill_data.get("target_level_index", -1)
            if target_level != player.level_index + 1:
                current_level = level_data[player.level_index]["level_name"]
                target_level_name = f"境界{target_level}"
                if 0 <= target_level < len(level_data):
                    target_level_name = level_data[target_level]["level_name"]
                yield event.plain_result(
                    f"❌ {pill_name} 不适用于当前突破\n"
                    f"当前境界：{current_level}\n"
                    f"此丹药用于突破到：【{target_level_name}】"
                )
                return

            yield event.plain_result(f"使用【{pill_name}】，准备与心魔战斗...")
        else:
            pill_name = None
            yield event.plain_result("准备与心魔战斗...")

        # 执行突破（心魔战斗）
        success, message, died, battle_result = await self.breakthrough_manager.execute_breakthrough(
            player,
            pill_name,
            modifiers.get("temp_bonus", 0),
            modifiers.get("permanent_death_multiplier", 1.0),
            self.equipment_manager,
            self.skill_manager
        )

        if modifiers.get("has_temp_effects", False):
            await self.pill_manager.consume_breakthrough_effects(player)

        yield event.plain_result(message)
