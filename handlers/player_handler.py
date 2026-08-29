# handlers/player_handler.py
import time
import random
from datetime import datetime
from astrbot.api.event import AstrMessageEvent
from astrbot.api import AstrBotConfig
from ..data import DataBase
from ..core import CultivationManager, PillManager
from ..core.skill_manager import SkillManager
from ..models import Player
from ..models_extended import UserStatus
from ..config_manager import ConfigManager
from .utils import player_required

CMD_START_XIUXIAN = "我要修仙"
CMD_PLAYER_INFO = "我的信息"
CMD_START_CULTIVATION = "闭关"
CMD_END_CULTIVATION = "出关"
CMD_CHECK_IN = "签到"
REBIRTH_COOLDOWN = 1 * 3600  # 1小时冷却

__all__ = ["PlayerHandler"]

class PlayerHandler:
    """玩家基础信息处理器 - 支持灵修/体修选择"""

    def __init__(self, db: DataBase, config: AstrBotConfig, config_manager: ConfigManager, 
                 adventure_event_mgr=None):
        self.db = db
        self.config = config
        self.config_manager = config_manager
        self.cultivation_manager = CultivationManager(config, config_manager)
        self.pill_manager = PillManager(self.db, self.config_manager)
        self.skill_manager = SkillManager(self.db, self.config_manager)
        self.adventure_event_mgr = adventure_event_mgr
        self.dual_cult_mgr = None  # 道侣系统管理器

    def set_adventure_event_manager(self, mgr):
        """设置奇遇事件管理器（用于延迟注入）"""
        self.adventure_event_mgr = mgr

    def set_dual_cultivation_manager(self, mgr):
        """设置道侣系统管理器（用于延迟注入）"""
        self.dual_cult_mgr = mgr

    async def handle_start_xiuxian(self, event: AstrMessageEvent, cultivation_type: str = ""):
        """处理创建角色

        Args:
            cultivation_type: 修炼类型，"灵修"或"体修"，为空则显示选择提示
        """
        user_id = event.get_sender_id()

        # 检查是否已创建角色
        if await self.db.get_player_by_id(user_id):
            yield event.plain_result("道友，你已踏入仙途，无需重复此举。")
            return

        # 如果没有提供职业选择，显示选择提示
        if not cultivation_type or cultivation_type.strip() == "":
            help_msg = (
                "🌟 欢迎踏入修仙之路！\n"
                "━━━━━━━━━━━━━━━\n"
                "请选择你的修炼方式：\n\n"
                "【灵修】以灵气为主，法术攻击\n"
                "• 寿命：100\n"
                "• 灵气：100-1000\n"
                "• 法伤：5-100\n"
                "• 物伤：5\n"
                "• 法防：0\n"
                "• 物防：5\n"
                "• 精神力：100-500\n\n"
                "【体修】以气血为主，肉身强横\n"
                "• 寿命：50-100\n"
                "• 气血：100-500\n"
                "• 法伤：0\n"
                "• 物伤：100-500\n"
                "• 法防：50-200\n"
                "• 物防：100-500\n"
                "• 精神力：100-500\n"
                "━━━━━━━━━━━━━━━\n"
                "⚠️ 修仙风险警告 ⚠️\n"
                "• 突破失败有概率走火入魔身死道消\n"
                "• 生命值归零也会导致死亡\n"
                "• 死亡后所有数据清除，需重新入仙途\n"
                "━━━━━━━━━━━━━━━\n"
                f"💡 使用方法：\n"
                f"  {CMD_START_XIUXIAN} 灵修\n"
                f"  {CMD_START_XIUXIAN} 体修"
            )
            yield event.plain_result(help_msg)
            return

        # 验证职业类型
        cultivation_type = cultivation_type.strip()
        if cultivation_type not in ["灵修", "体修"]:
            yield event.plain_result(f"职业选择错误！请选择「灵修」或「体修」。")
            return

        # 生成新玩家
        new_player = self.cultivation_manager.generate_new_player_stats(user_id, cultivation_type)
        await self.db.create_player(new_player)

        # 获取灵根描述
        root_name = new_player.spiritual_root.replace("灵根", "")
        root_description = self.cultivation_manager._get_root_description(root_name)

        reply_msg = (
            f"🎉 恭喜道友 {event.get_sender_name()} 踏上仙途！\n"
            f"━━━━━━━━━━━━━━━\n"
            f"修炼方式：【{new_player.cultivation_type}】\n"
            f"灵根：【{new_player.spiritual_root}】\n"
            f"评价：{root_description}\n"
            f"启动资金：{new_player.gold} 灵石\n"
            f"━━━━━━━━━━━━━━━\n"
            f"⚠️ 修仙有风险，突破需谨慎！\n"
            f"突破失败或生命值归零会导致\n"
            f"身死道消，所有数据清除！\n"
            f"━━━━━━━━━━━━━━━\n"
            f"💡 发送「{CMD_PLAYER_INFO}」查看状态"
        )
        yield event.plain_result(reply_msg)

    @player_required
    async def handle_player_info(self, player: Player, event: AstrMessageEvent):
        """处理查看玩家信息 - 展示新属性"""
        display_name = event.get_sender_name()
        required_exp = player.get_required_exp(self.config_manager)

        # 更新丹药效果并计算最终属性倍率
        await self.pill_manager.update_temporary_effects(player)
        pill_multipliers = self.pill_manager.calculate_pill_attribute_effects(player)

        # 获取装备加成后的属性
        from ..core import EquipmentManager
        equipment_manager = EquipmentManager(self.db, self.config_manager)
        equipped_items = equipment_manager.get_equipped_items(
            player,
            self.config_manager.items_data,
            self.config_manager.weapons_data,
            self.config_manager.techniques_data
        )
        total_attrs = player.get_total_attributes(equipped_items, pill_multipliers)

        # 获取战力（综合攻防）
        combat_power = (
            int(total_attrs['physical_damage']) + int(total_attrs['magic_damage']) +
            int(total_attrs['physical_defense']) + int(total_attrs['magic_defense']) +
            int(total_attrs['mental_power']) // 10
        )
        
        # 获取宗门信息
        sect_name = "无宗门"
        position_name = "散修"
        if player.sect_id and player.sect_id != 0:
            sect = await self.db.ext.get_sect_by_id(player.sect_id)
            if sect:
                sect_name = sect.sect_name
                if sect.sect_owner == player.user_id:
                    position_name = "宗主"
                elif player.sect_position == 1:
                    position_name = "长老"
                elif player.sect_position == 2:
                    position_name = "亲传弟子"
                elif player.sect_position == 3:
                    position_name = "内门弟子"
                else:
                    position_name = "外门弟子"
        
        # 获取装备信息
        weapon_name = player.weapon if player.weapon else "无"
        armor_name = player.armor if player.armor else "无"
        accessory_name = player.accessory if player.accessory else "无"
        technique_name = player.main_technique if player.main_technique else "无"
        
        # 获取突破状态
        breakthrough_rate = f"+{player.level_up_rate}%" if player.level_up_rate > 0 else "0%"
        
        # 构建信息显示
        dao_hao = player.user_name if player.user_name else display_name
        
        reply_msg = (
            f"📋 道友 {dao_hao} 的信息\n"
            f"━━━━━━━━━━━━━━━\n"
            f"\n"
            f"【基本信息】\n"
            f"  道号：{dao_hao}\n"
            f"  境界：{player.get_level(self.config_manager)}\n"
            f"  修为：{int(player.experience):,}/{int(required_exp):,}\n"
            f"  灵石：{player.gold:,}\n"
            f"  战力：{combat_power:,}\n"
            f"  灵根：{player.spiritual_root}\n"
            f"  突破加成：{breakthrough_rate}\n"
            f"\n"
            f"【修炼属性】\n"
            f"  修炼方式：{player.cultivation_type}\n"
            f"  状态：{player.state}\n"
            f"  寿命：{player.lifespan}\n"
            f"  精神力：{total_attrs['mental_power']}\n"
        )
        
        # 根据修炼类型添加不同属性
        if player.cultivation_type == "体修":
            reply_msg += (
                f"  气血：{player.blood_qi}/{total_attrs.get('max_blood_qi', 0)}\n"
                f"  物伤：{total_attrs['physical_damage']}\n"
                f"  法伤：{total_attrs['magic_damage']}\n"
                f"  物防：{total_attrs['physical_defense']}\n"
                f"  法防：{total_attrs['magic_defense']}\n"
            )
        else:
            reply_msg += (
                f"  灵气：{player.spiritual_qi}/{total_attrs.get('max_spiritual_qi', 0)}\n"
                f"  法伤：{total_attrs['magic_damage']}\n"
                f"  物伤：{total_attrs['physical_damage']}\n"
                f"  法防：{total_attrs['magic_defense']}\n"
                f"  物防：{total_attrs['physical_defense']}\n"
            )
        
        # 添加战斗属性
        reply_msg += (
            f"\n"
            f"【战斗属性】\n"
            f"  HP：{player.hp}/{player.max_hp}\n"
            f"  MP：{player.mp}/{player.max_mp}\n"
            f"  速度：{player.speed}\n"
            f"  暴击率：{player.critical_rate:.1%}\n"
            f"  暴击伤害：{player.critical_damage:.1f}x\n"
            f"  命中率：{player.hit_rate:.1%}\n"
            f"  闪避率：{player.dodge_rate:.1%}\n"
        )
        
        # 获取已装备技能
        equipped_skill_configs = self.skill_manager.get_equipped_skill_configs(player)
        if equipped_skill_configs:
            skill_names = [s.get("name", "未知") for s in equipped_skill_configs]
            reply_msg += (
                f"\n"
                f"【已装备技能】\n"
                f"  {' | '.join(skill_names)}\n"
            )
        else:
            reply_msg += (
                f"\n"
                f"【已装备技能】\n"
                f"  (无)\n"
            )
        
        reply_msg += (
            f"\n"
            f"【装备信息】\n"
            f"  主修功法：{technique_name}\n"
            f"  法器：{weapon_name}\n"
            f"  防具：{armor_name}\n"
            f"  饰品：{accessory_name}\n"
        )
        
        # 显示功法被动效果
        if player.main_technique:
            technique_config = self.config_manager.get_technique_by_name(player.main_technique)
            if technique_config:
                passive_effects = technique_config.get("passive_effects", {})
                growth_modifiers = technique_config.get("growth_modifiers", {})
                
                passive_lines = []
                
                # 被动效果
                if passive_effects:
                    for effect_key, effect_value in passive_effects.items():
                        if effect_value != 0:
                            effect_name = self._get_effect_name(effect_key)
                            if isinstance(effect_value, float) and effect_value < 1:
                                passive_lines.append(f"{effect_name}+{effect_value:.0%}")
                            else:
                                passive_lines.append(f"{effect_name}+{effect_value}")
                
                # 成长修正（只显示非1.0的）
                growth_lines = []
                for mod_key, mod_value in growth_modifiers.items():
                    if mod_value != 1.0:
                        mod_name = self._get_modifier_name(mod_key)
                        if mod_value > 1.0:
                            growth_lines.append(f"{mod_name}×{mod_value:.1f}")
                        else:
                            growth_lines.append(f"{mod_name}×{mod_value:.1f}")
                
                if passive_lines or growth_lines:
                    reply_msg += f"\n【功法效果】\n"
                    if passive_lines:
                        reply_msg += f"  被动：{', '.join(passive_lines)}\n"
                    if growth_lines:
                        reply_msg += f"  成长：{', '.join(growth_lines)}\n"
        
        reply_msg += (
            f"\n"
            f"【宗门信息】\n"
            f"  所在宗门：{sect_name}\n"
            f"  宗门职位：{position_name}\n"
        )
        
        # 道侣信息
        if player.has_partner():
            partner = await self.db.get_player_by_id(player.partner_id)
            if partner:
                partner_name = partner.user_name or partner.user_id[:8]
                reply_msg += (
                    f"\n"
                    f"【道侣信息】\n"
                    f"  道侣：{partner_name}\n"
                    f"  亲密度：{player.partner_intimacy}（{player.get_intimacy_title()}）\n"
                )
        
        # 获取贷款信息
        loan = await self.db.ext.get_active_loan(player.user_id)
        if loan:
            now = int(time.time())
            remaining_seconds = loan["due_at"] - now
            remaining_days = remaining_seconds // 86400
            remaining_hours = (remaining_seconds % 86400) // 3600
            
            days_borrowed = max(1, (now - loan["borrowed_at"]) // 86400)
            interest = int(loan["principal"] * loan["interest_rate"] * days_borrowed)
            total_due = loan["principal"] + interest
            
            loan_type_name = "突破贷款" if loan["loan_type"] == "breakthrough" else "普通贷款"
            
            if remaining_seconds <= 0:
                time_str = "⚠️ 已逾期！"
            elif remaining_days <= 0:
                time_str = f"🔴 {remaining_hours}小时"
            elif remaining_days <= 1:
                time_str = f"🟠 {remaining_days}天{remaining_hours}小时"
            else:
                time_str = f"🟡 {remaining_days}天"
            
            reply_msg += (
                f"\n"
                f"【贷款信息】💰\n"
                f"  类型：{loan_type_name}\n"
                f"  应还：{total_due:,} 灵石\n"
                f"  剩余：{time_str}\n"
                f"  💀 逾期将被追杀致死！\n"
            )
        
        reply_msg += "━━━━━━━━━━━━━━━"
        
        yield event.plain_result(reply_msg)

    def _get_effect_name(self, effect_key: str) -> str:
        """获取效果名称"""
        effect_names = {
            "critical_rate": "暴击率",
            "critical_damage": "暴击伤害",
            "dodge_rate": "闪避率",
            "hit_rate": "命中率",
            "speed": "速度",
            "physical_damage": "物伤",
            "magic_damage": "法伤",
            "physical_defense": "物防",
            "magic_defense": "法防",
            "hp_bonus": "HP",
            "mp_bonus": "MP",
            "lifesteal": "生命偷取",
        }
        return effect_names.get(effect_key, effect_key)
    
    def _get_modifier_name(self, mod_key: str) -> str:
        """获取成长修正名称"""
        modifier_names = {
            "physical_attack": "物攻成长",
            "magic_attack": "法攻成长",
            "physical_defense": "物防成长",
            "magic_defense": "法防成长",
            "hp": "HP成长",
            "mp": "MP成长",
            "speed": "速度成长",
            "lifespan": "寿命成长",
            "mental_power": "精神力成长",
            "blood_qi": "气血成长",
            "spiritual_qi": "灵气成长",
        }
        return modifier_names.get(mod_key, mod_key)

    @player_required
    async def handle_start_cultivation(self, player: Player, event: AstrMessageEvent):
        """处理闭关指令"""
        # 检查是否已经在闭关
        if player.state == "修炼中":
            yield event.plain_result("道友已在闭关中，请勿重复进入。")
            return
        
        # 检查是否在其他活动中（历练、秘境探索等）
        user_cd = await self.db.ext.get_user_cd(player.user_id)
        if user_cd and user_cd.type != UserStatus.IDLE:
            current_status = UserStatus.get_name(user_cd.type)
            yield event.plain_result(f"❌ 道友当前正{current_status}，无法闭关修炼！")
            return

        # 记录闭关开始时间
        player.state = "修炼中"
        player.cultivation_start_time = int(time.time())
        await self.db.update_player(player)
        await self.db.ext.set_user_busy(player.user_id, UserStatus.CULTIVATING, 0)

        # 检查道侣是否也在闭关
        partner_msg = ""
        if self.dual_cult_mgr and player.has_partner():
            is_partner_cultivating, msg, bonus = await self.dual_cult_mgr.check_partner_cultivating(player)
            if is_partner_cultivating:
                partner_msg = msg

        yield event.plain_result(
            "🧘 道友已进入闭关状态\n"
            "━━━━━━━━━━━━━━━\n"
            "闭关期间，你将与世隔绝，潜心修炼。\n"
            f"💡 发送「{CMD_END_CULTIVATION}」结束闭关\n"
            "⏱️ 每分钟将获得修为，受灵根资质影响。\n"
            "💚 闭关期间会缓慢恢复HP和MP。"
            f"{partner_msg}"
        )

    @player_required
    async def handle_end_cultivation(self, player: Player, event: AstrMessageEvent):
        """处理出关指令"""
        # 检查是否在闭关中
        if player.state != "修炼中":
            yield event.plain_result("道友当前并未闭关，无需出关。")
            return

        # 检查是否有闭关开始时间
        if player.cultivation_start_time == 0:
            yield event.plain_result("数据异常：未记录闭关开始时间。")
            return

        # 计算闭关时长（分钟）
        end_time = int(time.time())
        duration_seconds = end_time - player.cultivation_start_time
        duration_minutes = duration_seconds // 60

        if duration_minutes < 1:
            yield event.plain_result("道友闭关时间不足1分钟，未获得修为。请继续闭关修炼。")
            return

        # 闭关时长上限根据境界调整（基础24小时，每提升一个大境界增加6小时）
        # level_index: 0-8练气, 9-17筑基, 18-26金丹, 27-35元婴, 36-44化神, 45-53炼虚, 54-62合体, 63-71大乘, 72+渡劫
        base_minutes = 1440  # 24小时
        realm_bonus = (player.level_index // 9) * 360  # 每个大境界增加6小时
        MAX_CULTIVATION_MINUTES = base_minutes + realm_bonus
        effective_minutes = min(duration_minutes, MAX_CULTIVATION_MINUTES)
        exceeded_time = duration_minutes > MAX_CULTIVATION_MINUTES

        # 更新丹药效果，确保持续结算
        await self.pill_manager.update_temporary_effects(player)
        pill_multipliers = self.pill_manager.calculate_pill_attribute_effects(player)

        # 获取主修心法的修为加成
        technique_bonus = 0.0
        if player.main_technique:
            from ..core import EquipmentManager
            equipment_manager = EquipmentManager(self.db, self.config_manager)
            equipped_items = equipment_manager.get_equipped_items(
                player,
                self.config_manager.items_data,
                self.config_manager.weapons_data,
                self.config_manager.techniques_data
            )
            # 找到主修心法
            for item in equipped_items:
                if item.item_type == "main_technique":
                    technique_bonus = item.exp_multiplier
                    break

        # 计算道侣修炼加速
        partner_bonus = 0.0
        partner_bonus_msg = ""
        if self.dual_cult_mgr and player.has_partner():
            partner_bonus = await self.dual_cult_mgr.get_cultivation_speed_bonus(player)
            if partner_bonus > 0:
                partner = await self.db.get_player_by_id(player.partner_id)
                partner_name = partner.user_name if partner else "道侣"
                partner_bonus_msg = f"\n💕 道侣加速：+{partner_bonus:.0%}（{partner_name}同修）"

        # 计算获得的修为（使用有效时长）
        base_gained_exp = self.cultivation_manager.calculate_cultivation_exp(
            player,
            effective_minutes,
            technique_bonus,
            pill_multipliers
        )
        
        # 应用道侣加速
        gained_exp = int(base_gained_exp * (1 + partner_bonus))

        # ========== 计算HP/MP回复 ==========
        # 基础回复率：每分钟回复 0.5% 的最大HP/MP
        # 功法加成：如果有主修心法，额外增加回复效率
        base_recovery_rate = 0.005  # 每分钟 0.5%
        
        # 功法回复加成
        technique_recovery_bonus = 0.0
        if player.main_technique:
            technique_config = self.config_manager.get_technique_by_name(player.main_technique)
            if technique_config:
                passive_effects = technique_config.get("passive_effects", {})
                technique_recovery_bonus = passive_effects.get("regeneration", 0)
        
        # 计算总回复率
        total_recovery_rate = base_recovery_rate + technique_recovery_bonus
        
        # 计算回复量（使用有效时长）
        hp_recovery_percent = min(1.0, effective_minutes * total_recovery_rate)
        mp_recovery_percent = min(1.0, effective_minutes * total_recovery_rate)
        
        # 计算实际回复量
        hp_before = player.hp
        mp_before = player.mp
        
        hp_recovery = int(player.max_hp * hp_recovery_percent)
        mp_recovery = int(player.max_mp * mp_recovery_percent)
        
        # 应用回复
        player.hp = min(player.max_hp, player.hp + hp_recovery)
        player.mp = min(player.max_mp, player.mp + mp_recovery)
        
        actual_hp_recovery = player.hp - hp_before
        actual_mp_recovery = player.mp - mp_before

        # 更新玩家数据
        player.experience += gained_exp
        player.state = "空闲"
        player.cultivation_start_time = 0
        await self.db.update_player(player)
        await self.db.ext.set_user_free(player.user_id)

        # 计算闭关时长显示
        hours = duration_minutes // 60
        minutes = duration_minutes % 60
        time_str = ""
        if hours > 0:
            time_str += f"{hours}小时"
        if minutes > 0:
            time_str += f"{minutes}分钟"

        # 超时提示
        exceed_msg = ""
        if exceeded_time:
            effective_hours = MAX_CULTIVATION_MINUTES // 60
            exceed_msg = f"\n⚠️ 闭关超过{effective_hours}小时，仅计算前{effective_hours}小时收益"

        # 回复信息
        recovery_msg = ""
        if actual_hp_recovery > 0 or actual_mp_recovery > 0:
            recovery_msg = (
                f"\n💚 HP恢复：+{actual_hp_recovery} ({player.hp}/{player.max_hp})"
                f"\n💙 MP恢复：+{actual_mp_recovery} ({player.mp}/{player.max_mp})"
            )

        reply_msg = (
            "🌟 道友出关成功！\n"
            "━━━━━━━━━━━━━━━\n"
            f"⏱️ 闭关时长：{time_str}\n"
            f"📈 获得修为：{gained_exp:,}{partner_bonus_msg}{exceed_msg}"
            f"{recovery_msg}\n"
            f"💫 当前修为：{player.experience:,}\n"
            "━━━━━━━━━━━━━━━\n"
            "道友已回归红尘，可继续修行。"
        )

        # 尝试触发奇遇事件
        adventure_msg = ""
        if self.adventure_event_mgr and duration_minutes >= 30:
            triggered, event_msg, _ = await self.adventure_event_mgr.try_trigger_event(
                player, "cultivation_end", {"duration_minutes": duration_minutes}
            )
            if triggered and event_msg:
                adventure_msg = f"\n\n{event_msg}"

        yield event.plain_result(reply_msg + adventure_msg)

    @player_required
    async def handle_check_in(self, player: Player, event: AstrMessageEvent):
        """处理签到指令"""
        # 获取今天的日期（格式：YYYY-MM-DD）
        today = datetime.now().strftime("%Y-%m-%d")

        # 检查是否已经签到过
        if player.last_check_in_date == today:
            yield event.plain_result(
                "📅 道友今日已经签到过了\n"
                "请明日再来。"
            )
            return

        # 获取签到奖励范围配置
        check_in_gold_min = self.config["VALUES"].get("CHECK_IN_GOLD_MIN", 50)
        check_in_gold_max = self.config["VALUES"].get("CHECK_IN_GOLD_MAX", 500)

        # 确保最小值不大于最大值
        if check_in_gold_min > check_in_gold_max:
            check_in_gold_min, check_in_gold_max = check_in_gold_max, check_in_gold_min

        # 生成随机奖励
        check_in_gold = random.randint(check_in_gold_min, check_in_gold_max)

        # 更新玩家数据
        player.gold += check_in_gold
        player.last_check_in_date = today
        await self.db.update_player(player)

        # 道侣每日亲密度增加
        partner_msg = ""
        if self.dual_cult_mgr and player.has_partner():
            has_partner, intimacy_gain = await self.dual_cult_mgr.daily_intimacy_gain(player)
            if has_partner and intimacy_gain > 0:
                partner = await self.db.get_player_by_id(player.partner_id)
                partner_name = partner.user_name if partner else "道侣"
                partner_msg = f"\n💕 与道侣【{partner_name}】心意相通，亲密度+{intimacy_gain}"

        reply_msg = (
            "✅ 签到成功！\n"
            "━━━━━━━━━━━━━━━\n"
            f"💰 获得灵石：{check_in_gold}\n"
            f"💎 当前灵石：{player.gold}"
            f"{partner_msg}\n"
            "━━━━━━━━━━━━━━━\n"
            "明日再来，莫要忘记哦~"
        )

        # 尝试触发奇遇事件
        adventure_msg = ""
        if self.adventure_event_mgr:
            triggered, event_msg, _ = await self.adventure_event_mgr.try_trigger_event(
                player, "check_in", {}
            )
            if triggered and event_msg:
                adventure_msg = f"\n\n{event_msg}"

        yield event.plain_result(reply_msg + adventure_msg)

    @player_required
    async def handle_give_gold(self, player: Player, event: AstrMessageEvent, target_id: str = "", amount: int = 0):
        """处理玩家互送灵石。"""
        if not target_id:
            yield event.plain_result("❌ 请@要赠送的目标，并附带数量，例如：送灵石 @某人 100")
            return

        if target_id == player.user_id:
            yield event.plain_result("❌ 不能给自己送灵石。")
            return

        if amount <= 0:
            yield event.plain_result("❌ 赠送数量必须大于 0。")
            return

        target_player = await self.db.get_player_by_id(target_id)
        if not target_player:
            yield event.plain_result("❌ 对方尚未开始修仙，无法接收灵石。")
            return

        if player.gold < amount:
            yield event.plain_result(f"❌ 灵石不足，当前仅有 {player.gold:,} 灵石。")
            return

        player.gold -= amount
        target_player.gold += amount

        await self.db.update_player(player)
        await self.db.update_player(target_player)

        target_name = target_player.user_name or f"道友{str(target_id)[:8]}"
        yield event.plain_result(
            f"🎁 赠送成功！\n"
            f"💸 你向【{target_name}】赠送了 {amount:,} 灵石\n"
            f"💎 你的剩余灵石：{player.gold:,}\n"
            f"💎 对方当前灵石：{target_player.gold:,}"
        )

    @player_required
    async def handle_rebirth(self, player: Player, event: AstrMessageEvent, confirm_text: str = ""):
        """弃道重修（1小时冷却）"""
        user_cd = await self.db.ext.get_user_cd(player.user_id)
        if user_cd and user_cd.type != UserStatus.IDLE:
            status_name = UserStatus.get_name(user_cd.type)
            yield event.plain_result(f"❌ 你当前正在「{status_name}」，无法弃道重修。")
            return

        if player.state != "空闲":
            yield event.plain_result("❌ 只有处于空闲状态时才能弃道重修。请先结束闭关/历练等活动。")
            return

        loan = await self.db.ext.get_active_loan(player.user_id)
        if loan:
            yield event.plain_result("❌ 你仍有未结清的灵石贷款，无法重修。请先还款。")
            return

        key = f"rebirth_last_{player.user_id}"
        last_ts = await self.db.ext.get_system_config(key)
        now = int(time.time())
        if last_ts:
            diff = now - int(last_ts)
            if diff < REBIRTH_COOLDOWN:
                remaining = REBIRTH_COOLDOWN - diff
                minutes = remaining // 60
                seconds = remaining % 60
                yield event.plain_result(
                    "⌛ 弃道重修冷却中\n"
                    "━━━━━━━━━━━━━━━\n"
                    f"距离下次重修还需：{minutes}分钟{seconds}秒"
                )
                return

        if confirm_text.strip() != "确认":
            yield event.plain_result(
                "⚠️ 弃道重修将删除当前角色的所有数据，并无法撤回！\n"
                "限制：每1小时只能重修一次，且必须在空闲状态、无贷款时使用。\n"
                "━━━━━━━━━━━━━━━\n"
                "若你已做好准备，请发送：\n"
                "弃道重修 确认"
            )
            return

        await self.db.delete_player_cascade(player.user_id)
        await self.db.ext.set_system_config(key, str(now))

        yield event.plain_result(
            "💀 你选择了弃道重修，旧生一切化为尘埃。\n"
            "━━━━━━━━━━━━━━━\n"
            "可立即使用「我要修仙」重新踏上仙途。\n"
            "（1小时内不可再次重修）"
        )
