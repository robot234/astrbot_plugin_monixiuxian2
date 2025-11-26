# core/breakthrough_manager.py

import random
from typing import Optional, Tuple
from astrbot.api import logger

from ..models import Player
from ..data import DataBase
from ..config_manager import ConfigManager


class BreakthroughManager:
    """突破管理器 - 处理境界突破相关逻辑"""

    def __init__(self, db: DataBase, config_manager: ConfigManager, config: dict):
        self.db = db
        self.config_manager = config_manager
        self.config = config

    def check_breakthrough_requirements(self, player: Player) -> Tuple[bool, str]:
        """检查玩家是否满足突破条件

        Args:
            player: 玩家对象

        Returns:
            (是否满足, 错误消息)
        """
        # 检查是否已经是最高境界
        if player.level_index >= len(self.config_manager.level_data) - 1:
            return False, "你已经达到了最高境界，无法继续突破！"

        # 获取下一境界所需修为
        next_level_index = player.level_index + 1
        next_level_data = self.config_manager.level_data[next_level_index]
        required_exp = next_level_data.get("exp_needed", 0)

        # 检查修为是否满足
        if player.experience < required_exp:
            current_level = self.config_manager.level_data[player.level_index]["level_name"]
            next_level = next_level_data["level_name"]
            return False, (
                f"修为不足！\n"
                f"当前境界：{current_level}\n"
                f"当前修为：{player.experience}\n"
                f"突破至【{next_level}】需要修为：{required_exp}"
            )

        return True, ""

    def calculate_breakthrough_success_rate(
        self,
        player: Player,
        pill_name: Optional[str] = None,
        temp_bonus: float = 0.0
    ) -> Tuple[float, str]:
        """计算突破成功率

        Args:
            player: 玩家对象
            pill_name: 使用的破境丹名称（可选）

        Returns:
            (成功率, 说明信息)
        """
        # 获取基础成功率
        next_level_index = player.level_index + 1
        next_level_data = self.config_manager.level_data[next_level_index]
        base_success_rate = next_level_data.get("success_rate", 0.5)

        info_lines = [
            f"基础成功率：{base_success_rate:.1%}"
        ]

        final_rate = base_success_rate + temp_bonus
        max_rate = 1.0  # 默认最大100%

        if temp_bonus:
            info_lines.append(f"临时丹药加成：{temp_bonus:+.1%}")

        # 如果使用了破境丹
        if pill_name:
            pill_data = self.config_manager.pills_data.get(pill_name)
            if pill_data and pill_data.get("subtype") == "breakthrough":
                breakthrough_bonus = pill_data.get("breakthrough_bonus", 0)
                max_rate = pill_data.get("max_success_rate", 1.0)

                # 计算加成后的成功率
                final_rate = min(base_success_rate + temp_bonus + breakthrough_bonus, max_rate)

                info_lines.append(f"破境丹加成：+{breakthrough_bonus:.1%}")
                info_lines.append(f"最大成功率限制：{max_rate:.1%}")
            else:
                logger.warning(f"无效的破境丹：{pill_name}")

        final_rate = max(0.0, min(final_rate, max_rate))
        info_lines.append(f"最终成功率：{final_rate:.1%}")
        info = "\n".join(info_lines)

        return final_rate, info

    async def execute_breakthrough(
        self,
        player: Player,
        pill_name: Optional[str] = None,
        temp_bonus: float = 0.0,
        death_rate_multiplier: float = 1.0
    ) -> Tuple[bool, str, bool]:
        """执行突破

        Args:
            player: 玩家对象
            pill_name: 使用的破境丹名称（可选）

        Returns:
            (是否成功, 消息, 是否死亡)
        """
        # 检查突破条件
        can_breakthrough, error_msg = self.check_breakthrough_requirements(player)
        if not can_breakthrough:
            return False, error_msg, False

        # 计算成功率
        success_rate, rate_info = self.calculate_breakthrough_success_rate(player, pill_name, temp_bonus)

        # 判定突破结果
        random_value = random.random()
        breakthrough_success = random_value < success_rate

        current_level_name = self.config_manager.level_data[player.level_index]["level_name"]
        next_level_index = player.level_index + 1
        next_level_data = self.config_manager.level_data[next_level_index]
        next_level_name = next_level_data["level_name"]

        if breakthrough_success:
            # 突破成功 - 提升境界并更新属性
            old_level_index = player.level_index
            player.level_index = next_level_index

            # 直接从下一境界配置中读取突破增量，并累加到玩家属性上
            # 这样可以保留玩家初始化时的随机属性值
            lifespan_gain = next_level_data.get("breakthrough_lifespan_gain", 0)
            spiritual_qi_gain = next_level_data.get("breakthrough_spiritual_qi_gain", 0)
            mental_power_gain = next_level_data.get("breakthrough_mental_power_gain", 0)
            physical_damage_gain = next_level_data.get("breakthrough_physical_damage_gain", 0)
            magic_damage_gain = next_level_data.get("breakthrough_magic_damage_gain", 0)
            physical_defense_gain = next_level_data.get("breakthrough_physical_defense_gain", 0)
            magic_defense_gain = next_level_data.get("breakthrough_magic_defense_gain", 0)

            # 应用属性增长
            player.lifespan += lifespan_gain
            player.physical_damage += physical_damage_gain
            player.magic_damage += magic_damage_gain
            player.physical_defense += physical_defense_gain
            player.magic_defense += magic_defense_gain
            player.max_spiritual_qi += spiritual_qi_gain
            player.mental_power += mental_power_gain

            # 恢复满灵气
            player.spiritual_qi = player.max_spiritual_qi

            # 保存到数据库
            await self.db.update_player(player)

            success_msg = (
                f"✨ 突破成功！✨\n"
                f"━━━━━━━━━━━━━━━\n"
                f"{rate_info}\n"
                f"━━━━━━━━━━━━━━━\n"
                f"恭喜你从【{current_level_name}】突破至【{next_level_name}】！\n"
                f"境界提升，实力大增！\n"
                f"\n【属性增长】\n"
                f"寿命 +{lifespan_gain}\n"
                f"最大灵气 +{spiritual_qi_gain}\n"
                f"法伤 +{magic_damage_gain}\n"
                f"物伤 +{physical_damage_gain}\n"
                f"法防 +{magic_defense_gain}\n"
                f"物防 +{physical_defense_gain}\n"
                f"精神力 +{mental_power_gain}\n"
                f"\n【当前属性】\n"
                f"寿命：{player.lifespan}\n"
                f"最大灵气：{player.max_spiritual_qi}\n"
                f"法伤：{player.magic_damage}\n"
                f"物伤：{player.physical_damage}\n"
                f"法防：{player.magic_defense}\n"
                f"物防：{player.physical_defense}\n"
                f"精神力：{player.mental_power}"
            )

            logger.info(
                f"玩家 {player.user_id} 突破成功：{current_level_name} -> {next_level_name}"
            )

            return True, success_msg, False

        else:
            # 突破失败 - 判断是否死亡
            death_probability_range = self.config.get("VALUES", {}).get(
                "BREAKTHROUGH_DEATH_PROBABILITY",
                [0.01, 0.1]  # 默认1%-10%死亡概率
            )

            # 随机一个死亡概率
            death_rate = random.uniform(death_probability_range[0], death_probability_range[1])
            death_rate = max(0.0, min(1.0, death_rate * death_rate_multiplier))
            died = random.random() < death_rate

            if died:
                # 检查是否有回生丹效果
                from .pill_manager import PillManager
                pill_manager = PillManager(self.db, self.config_manager)
                resurrected = await pill_manager.handle_resurrection(player)

                if resurrected:
                    # 回生丹触发，玩家复活
                    resurrection_msg = (
                        f"💀 突破失败，走火入魔！💀\n"
                        f"━━━━━━━━━━━━━━━\n"
                        f"{rate_info}\n"
                        f"━━━━━━━━━━━━━━━\n"
                        f"你在突破【{next_level_name}】时走火入魔...\n"
                        f"\n"
                        f"⚡ 回生丹效果触发！⚡\n"
                        f"━━━━━━━━━━━━━━━\n"
                        f"🌟 你涅槃重生了！\n"
                        f"⚠️ 但所有属性降低到之前的一半\n"
                        f"💊 回生丹效果已消耗\n"
                        f"━━━━━━━━━━━━━━━\n"
                        f"请继续修炼，重回巅峰！"
                    )

                    logger.info(
                        f"玩家 {player.user_id} 突破失败触发回生丹，成功复活"
                    )

                    # 返回False（突破失败），消息，False（未真正死亡）
                    return False, resurrection_msg, False

                # 玩家死亡 - 删除数据
                await self.db.delete_player(player.user_id)

                death_msg = (
                    f"💀 突破失败，走火入魔！💀\n"
                    f"━━━━━━━━━━━━━━━\n"
                    f"{rate_info}\n"
                    f"━━━━━━━━━━━━━━━\n"
                    f"你在突破【{next_level_name}】时走火入魔，身死道消...\n"
                    f"所有修为和装备化为虚无\n"
                    f"若想重新修仙，请使用'我要修仙'命令重新开始"
                )

                logger.info(
                    f"玩家 {player.user_id} 突破失败并死亡：{current_level_name} -> {next_level_name}，死亡概率 {death_rate:.2%}"
                )

                return False, death_msg, True

            else:
                # 突破失败但未死亡 - 扣除部分修为
                exp_penalty = int(player.experience * 0.1)  # 扣除10%修为
                player.experience = max(0, player.experience - exp_penalty)

                await self.db.update_player(player)

                fail_msg = (
                    f"❌ 突破失败 ❌\n"
                    f"━━━━━━━━━━━━━━━\n"
                    f"{rate_info}\n"
                    f"━━━━━━━━━━━━━━━\n"
                    f"突破【{next_level_name}】失败，但幸运地保住了性命\n"
                    f"修为受损，损失了 {exp_penalty} 点修为\n"
                    f"当前修为：{player.experience}\n"
                    f"请继续修炼，再接再厉！"
                )

                logger.info(
                    f"玩家 {player.user_id} 突破失败：{current_level_name} -> {next_level_name}，"
                    f"损失修为 {exp_penalty}"
                )

                return False, fail_msg, False
