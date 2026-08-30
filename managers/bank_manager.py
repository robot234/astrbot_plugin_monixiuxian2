# managers/bank_manager.py
"""灵石银行系统管理器 - 包含存取款、贷款、流水记录功能"""
import time
import random
from decimal import Decimal, ROUND_DOWN
from typing import Tuple, List, Optional, TYPE_CHECKING
from ..data import DataBase
from ..models import Player

if TYPE_CHECKING:
    from ..core.battle_manager import CombatStats

__all__ = ["BankManager"]

# 银行配置默认值
DEFAULT_DAILY_INTEREST_RATE = 0.001  # 存款日利率 0.1%
DEFAULT_MAX_DEPOSIT = 10000000  # 最大存款上限 1000万
DEFAULT_LOAN_INTEREST_RATE = 0.005  # 贷款日利率 0.5%
DEFAULT_LOAN_DURATION_DAYS = 7  # 贷款期限 7天
DEFAULT_MAX_LOAN_AMOUNT = 1000000  # 最大贷款额度 100万（最高境界）
DEFAULT_MIN_LOAN_AMOUNT = 1000  # 最小贷款额度 1000
DEFAULT_BREAKTHROUGH_LOAN_RATE = 0.008  # 突破贷款日利率 0.8%（更高风险）
DEFAULT_BREAKTHROUGH_LOAN_DURATION = 3  # 突破贷款期限 3天
DEFAULT_CHALLENGE_COOLDOWN = 3600  # 挑战冷却时间 1小时

# 境界贷款上限配置
# level_index: 0-9 炼气期, 10-12 筑基期, 13-15 金丹期, 16-18 元婴期, 19+ 化神期及以上
LOAN_LIMITS_BY_REALM = {
    "炼气期": {"max_loan": 10000, "min_level_index": 0, "tier": 1},
    "筑基期": {"max_loan": 50000, "min_level_index": 10, "tier": 2},
    "金丹期": {"max_loan": 200000, "min_level_index": 13, "tier": 3},
    "元婴期": {"max_loan": 500000, "min_level_index": 16, "tier": 4},
    "化神期": {"max_loan": 1000000, "min_level_index": 19, "tier": 5},
}

# 银行考核官配置 - 每个境界对应一个考核官
BANK_EXAMINERS = {
    2: {  # 筑基期考核官
        "name": "银行护卫·铁甲",
        "realm": "筑基期",
        "description": "身披铁甲的银行护卫，实力相当于筑基期中期修士",
        "level_index": 11,  # 筑基期中期
        "base_stats": {
            "max_hp": 800,
            "max_mp": 200,
            "physical_attack": 120,
            "magic_attack": 80,
            "physical_defense": 100,
            "magic_defense": 60,
            "speed": 18,
            "critical_rate": 0.08,
            "critical_damage": 1.6,
            "hit_rate": 0.92,
            "dodge_rate": 0.08,
        },
        "reward_tier": 2,
    },
    3: {  # 金丹期考核官
        "name": "银行执事·金袍",
        "realm": "金丹期",
        "description": "身着金袍的银行执事，实力相当于金丹期中期修士",
        "level_index": 14,  # 金丹期中期
        "base_stats": {
            "max_hp": 2000,
            "max_mp": 500,
            "physical_attack": 350,
            "magic_attack": 280,
            "physical_defense": 280,
            "magic_defense": 200,
            "speed": 24,
            "critical_rate": 0.10,
            "critical_damage": 1.7,
            "hit_rate": 0.93,
            "dodge_rate": 0.10,
        },
        "reward_tier": 3,
    },
    4: {  # 元婴期考核官
        "name": "银行长老·玄衣",
        "realm": "元婴期",
        "description": "身穿玄衣的银行长老，实力相当于元婴期中期修士",
        "level_index": 17,  # 元婴期中期
        "base_stats": {
            "max_hp": 5000,
            "max_mp": 1200,
            "physical_attack": 1000,
            "magic_attack": 850,
            "physical_defense": 700,
            "magic_defense": 550,
            "speed": 30,
            "critical_rate": 0.12,
            "critical_damage": 1.8,
            "hit_rate": 0.94,
            "dodge_rate": 0.12,
        },
        "reward_tier": 4,
    },
    5: {  # 化神期考核官
        "name": "银行行长·白发",
        "realm": "化神期",
        "description": "白发苍苍的银行行长，实力相当于化神期中期修士",
        "level_index": 20,  # 化神期中期
        "base_stats": {
            "max_hp": 12000,
            "max_mp": 3000,
            "physical_attack": 3000,
            "magic_attack": 2500,
            "physical_defense": 2000,
            "magic_defense": 1600,
            "speed": 36,
            "critical_rate": 0.15,
            "critical_damage": 2.0,
            "hit_rate": 0.95,
            "dodge_rate": 0.15,
        },
        "reward_tier": 5,
    },
}


def get_realm_name(level_index: int) -> str:
    """根据境界索引获取大境界名称"""
    if level_index >= 19:
        return "化神期"
    elif level_index >= 16:
        return "元婴期"
    elif level_index >= 13:
        return "金丹期"
    elif level_index >= 10:
        return "筑基期"
    else:
        return "炼气期"


def get_realm_tier(level_index: int) -> int:
    """根据境界索引获取境界等级（1-5）"""
    if level_index >= 19:
        return 5
    elif level_index >= 16:
        return 4
    elif level_index >= 13:
        return 3
    elif level_index >= 10:
        return 2
    else:
        return 1


def get_max_loan_for_tier(tier: int) -> int:
    """根据等级获取最大贷款额度"""
    tier_to_loan = {
        1: 10000,
        2: 50000,
        3: 200000,
        4: 500000,
        5: 1000000,
    }
    return tier_to_loan.get(tier, 10000)


def get_max_loan_for_player(level_index: int) -> int:
    """根据玩家境界获取最大贷款额度"""
    return get_max_loan_for_tier(get_realm_tier(level_index))


def get_tier_realm_name(tier: int) -> str:
    """根据等级获取境界名称"""
    tier_to_realm = {
        1: "炼气期",
        2: "筑基期",
        3: "金丹期",
        4: "元婴期",
        5: "化神期",
    }
    return tier_to_realm.get(tier, "炼气期")


class BankManager:
    """灵石银行管理器"""
    
    def __init__(self, db: DataBase, config: dict = None):
        self.db = db
        self.config = config or {}
        
        # 从配置读取，使用默认值作为后备
        bank_config = self.config.get("BANK", {})
        self.daily_interest_rate = bank_config.get("DAILY_INTEREST_RATE", DEFAULT_DAILY_INTEREST_RATE)
        self.max_deposit = bank_config.get("MAX_DEPOSIT", DEFAULT_MAX_DEPOSIT)
        self.loan_interest_rate = bank_config.get("LOAN_INTEREST_RATE", DEFAULT_LOAN_INTEREST_RATE)
        self.loan_duration_days = bank_config.get("LOAN_DURATION_DAYS", DEFAULT_LOAN_DURATION_DAYS)
        self.max_loan_amount = bank_config.get("MAX_LOAN_AMOUNT", DEFAULT_MAX_LOAN_AMOUNT)
        self.min_loan_amount = bank_config.get("MIN_LOAN_AMOUNT", DEFAULT_MIN_LOAN_AMOUNT)
        self.breakthrough_loan_rate = bank_config.get("BREAKTHROUGH_LOAN_RATE", DEFAULT_BREAKTHROUGH_LOAN_RATE)
        self.breakthrough_loan_duration = bank_config.get("BREAKTHROUGH_LOAN_DURATION", DEFAULT_BREAKTHROUGH_LOAN_DURATION)
        self.challenge_cooldown = bank_config.get("CHALLENGE_COOLDOWN", DEFAULT_CHALLENGE_COOLDOWN)
    
    def get_player_loan_limit(self, player: Player) -> int:
        """获取玩家的贷款上限（考虑挑战提升的额度）"""
        # 基于境界的基础额度
        base_limit = get_max_loan_for_player(player.level_index)
        return base_limit
    
    async def get_player_loan_tier(self, player: Player) -> int:
        """获取玩家当前的贷款等级（可能通过挑战提升）"""
        # 先获取基于境界的等级
        realm_tier = get_realm_tier(player.level_index)
        
        # 检查是否有通过挑战获得的更高等级
        challenge_tier = await self.db.ext.get_player_loan_tier(player.user_id)
        if challenge_tier and challenge_tier > realm_tier:
            return challenge_tier
        
        return realm_tier
    
    async def get_player_effective_loan_limit(self, player: Player) -> int:
        """获取玩家的有效贷款上限（包含挑战提升）"""
        tier = await self.get_player_loan_tier(player)
        return get_max_loan_for_tier(tier)
    
    def get_loan_limits_info(self) -> str:
        """获取贷款额度说明"""
        lines = []
        for realm, info in LOAN_LIMITS_BY_REALM.items():
            lines.append(f"  {realm}：最高 {info['max_loan']:,} 灵石")
        return "\n".join(lines)
    
    # ===== 银行挑战相关 =====
    
    def get_available_challenges(self, player: Player, current_tier: int) -> List[dict]:
        """获取玩家可挑战的考核官列表"""
        available = []
        for tier, examiner in BANK_EXAMINERS.items():
            if tier > current_tier:
                available.append({
                    "tier": tier,
                    **examiner
                })
        return available
    
    async def get_challenge_cooldown(self, player: Player) -> int:
        """获取挑战冷却剩余时间（秒）"""
        last_challenge = await self.db.ext.get_system_config(f"bank_challenge_{player.user_id}")
        if not last_challenge:
            return 0
        
        now = int(time.time())
        elapsed = now - int(last_challenge)
        remaining = self.challenge_cooldown - elapsed
        return max(0, remaining)
    
    async def challenge_examiner(self, player: Player, target_tier: int, 
                                  battle_manager, equipment_manager, skill_manager) -> Tuple[bool, str, dict]:
        """挑战银行考核官
        
        Args:
            player: 玩家
            target_tier: 目标等级（2-5）
            battle_manager: 战斗管理器
            equipment_manager: 装备管理器
            skill_manager: 技能管理器
            
        Returns:
            (success, message, battle_result)
        """
        # 检查目标等级是否有效
        if target_tier not in BANK_EXAMINERS:
            return False, "❌ 无效的考核官等级！", {}
        
        # 获取当前贷款等级
        current_tier = await self.get_player_loan_tier(player)
        
        # 检查是否已经达到或超过目标等级
        if current_tier >= target_tier:
            current_limit = get_max_loan_for_tier(current_tier)
            return False, f"❌ 你的贷款额度已达到 {current_limit:,} 灵石，无需挑战此考核官！", {}
        
        # 检查是否只能挑战下一级
        if target_tier > current_tier + 1:
            next_tier = current_tier + 1
            next_examiner = BANK_EXAMINERS.get(next_tier)
            if next_examiner:
                return False, f"❌ 请先挑战【{next_examiner['name']}】！只能逐级挑战。", {}
        
        # 检查冷却时间
        cooldown = await self.get_challenge_cooldown(player)
        if cooldown > 0:
            minutes = cooldown // 60
            seconds = cooldown % 60
            return False, f"❌ 挑战冷却中，还需 {minutes}分{seconds}秒", {}
        
        # 获取考核官信息
        examiner = BANK_EXAMINERS[target_tier]
        
        # 准备玩家战斗属性
        player_stats = battle_manager.prepare_combat_stats(player, equipment_manager, skill_manager)
        
        # 创建考核官战斗属性
        examiner_stats = self._create_examiner_combat_stats(examiner, target_tier)
        
        # 执行战斗
        battle_result = battle_manager.execute_battle(
            player_stats, 
            examiner_stats, 
            battle_type="duel"  # 使用决斗模式，不会提前认输
        )
        
        # 记录挑战时间（无论胜负）
        now = int(time.time())
        await self.db.ext.set_system_config(f"bank_challenge_{player.user_id}", str(now))
        
        # 处理战斗结果 - 玩家是p1，考核官是p2
        if battle_result.get("winner") == player.user_id:
            # 玩家胜利，提升贷款等级
            await self.db.ext.set_player_loan_tier(player.user_id, target_tier)
            new_limit = get_max_loan_for_tier(target_tier)
            target_realm = get_tier_realm_name(target_tier)
            
            victory_msg = (
                f"🎉 恭喜战胜【{examiner['name']}】！\n"
                f"━━━━━━━━━━━━━━━\n"
                f"📈 贷款额度提升！\n"
                f"新额度等级：{target_realm}\n"
                f"最高可贷：{new_limit:,} 灵石\n"
                f"━━━━━━━━━━━━━━━\n"
            )
            
            # 添加战斗摘要
            battle_summary = battle_manager.generate_battle_summary(battle_result, include_full_log=False)
            victory_msg += battle_summary
            
            return True, victory_msg, battle_result
        else:
            # 玩家失败
            defeat_msg = (
                f"💀 挑战【{examiner['name']}】失败！\n"
                f"━━━━━━━━━━━━━━━\n"
                f"考核官实力强劲，你还需要更多修炼。\n"
                f"⏱️ 冷却时间：{self.challenge_cooldown // 60}分钟\n"
                f"━━━━━━━━━━━━━━━\n"
            )
            
            # 添加战斗摘要
            battle_summary = battle_manager.generate_battle_summary(battle_result, include_full_log=False)
            defeat_msg += battle_summary
            
            return False, defeat_msg, battle_result
    
    def _create_examiner_combat_stats(self, examiner: dict, tier: int) -> "CombatStats":
        """创建考核官的战斗属性"""
        from ..core.battle_manager import CombatStats
        
        stats = examiner["base_stats"]
        
        # 使用特殊的user_id标识考核官
        examiner_id = f"bank_examiner_{tier}"
        
        return CombatStats(
            user_id=examiner_id,
            name=examiner["name"],
            hp=stats["max_hp"],
            max_hp=stats["max_hp"],
            mp=stats["max_mp"],
            max_mp=stats["max_mp"],
            physical_attack=stats["physical_attack"],
            magic_attack=stats["magic_attack"],
            physical_defense=stats["physical_defense"],
            magic_defense=stats["magic_defense"],
            speed=stats["speed"],
            critical_rate=stats["critical_rate"],
            critical_damage=stats["critical_damage"],
            hit_rate=stats["hit_rate"],
            dodge_rate=stats["dodge_rate"],
            skills=[],  # 考核官不使用技能
            skill_cooldowns={},
            shield=0,
            buffs=[],
            debuffs=[],
        )
    
    def get_examiner_info(self, tier: int) -> Optional[dict]:
        """获取考核官信息"""
        return BANK_EXAMINERS.get(tier)
    
    # ===== 存款相关 =====
    
    async def get_bank_info(self, player: Player) -> dict:
        """获取银行账户信息
        
        Returns:
            dict: {balance, last_interest_time, pending_interest, loan_info, loan_limit}
        """
        bank_data = await self.db.ext.get_bank_account(player.user_id)
        if not bank_data:
            bank_info = {"balance": 0, "last_interest_time": 0, "pending_interest": 0}
        else:
            pending_interest = self._calculate_interest(
                bank_data["balance"], 
                bank_data["last_interest_time"]
            )
            bank_info = {
                "balance": bank_data["balance"],
                "last_interest_time": bank_data["last_interest_time"],
                "pending_interest": pending_interest
            }
        
        # 获取贷款信息
        loan = await self.db.ext.get_active_loan(player.user_id)
        bank_info["loan"] = loan
        
        # 添加贷款上限信息（包含挑战提升）
        effective_limit = await self.get_player_effective_loan_limit(player)
        current_tier = await self.get_player_loan_tier(player)
        realm_tier = get_realm_tier(player.level_index)
        
        bank_info["loan_limit"] = effective_limit
        bank_info["loan_tier"] = current_tier
        bank_info["realm_tier"] = realm_tier
        bank_info["realm"] = get_realm_name(player.level_index)
        bank_info["loan_tier_realm"] = get_tier_realm_name(current_tier)
        
        # 是否有可挑战的考核官
        bank_info["can_challenge"] = current_tier < 5
        
        return bank_info
    
    def _calculate_interest(self, balance: int, last_time: int) -> int:
        """计算待领利息（使用Decimal精确计算）"""
        if balance <= 0 or last_time <= 0:
            return 0
        
        now = int(time.time())
        days_passed = (now - last_time) // 86400
        
        if days_passed < 1:
            return 0
        
        # 使用Decimal进行精确复利计算
        balance_d = Decimal(str(balance))
        rate_d = Decimal(str(self.daily_interest_rate))
        
        # 复利计算: balance * ((1 + rate) ^ days - 1)
        compound = (1 + rate_d) ** days_passed - 1
        interest = balance_d * compound
        
        # 向下取整返回
        return int(interest.quantize(Decimal('1'), rounding=ROUND_DOWN))
    
    async def deposit(self, player: Player, amount: int) -> Tuple[bool, str]:
        """存入灵石"""
        if isinstance(amount, bool) or not isinstance(amount, int) or amount <= 0:
            return False, "存款金额必须大于0。"

        async with self.db.transaction() as tx:
            current_player = await self.db.get_player_by_id(player.user_id)
            if not current_player:
                return False, "玩家不存在或已被删除。"
            if current_player.gold < amount:
                return False, f"灵石不足！你只有 {current_player.gold:,} 灵石。"

            bank_data = await self.db.ext.get_bank_account(current_player.user_id)
            current_balance = bank_data["balance"] if bank_data else 0
            if current_balance + amount > self.max_deposit:
                return False, f"存款上限为 {self.max_deposit:,} 灵石，当前余额 {current_balance:,}。"

            cursor = await self.db.conn.execute(
                "UPDATE players SET gold = gold - ? WHERE user_id = ? AND gold >= ?",
                (amount, current_player.user_id, amount)
            )
            if cursor.rowcount != 1:
                tx.mark_rollback_only()
                return False, "灵石不足或玩家状态已变化，请重试。"

            new_balance = current_balance + amount
            now = int(time.time())
            await self.db.ext.update_bank_account(
                current_player.user_id,
                new_balance,
                now if current_balance == 0 else bank_data["last_interest_time"],
                commit=False,
            )
            await self._add_transaction(
                current_player.user_id, "deposit", amount, new_balance, "存入灵石", commit=False
            )
            player.gold = current_player.gold - amount
            return True, f"成功存入 {amount:,} 灵石！\n当前余额：{new_balance:,} 灵石"
    
    async def withdraw(self, player: Player, amount: int) -> Tuple[bool, str]:
        """取出灵石"""
        if isinstance(amount, bool) or not isinstance(amount, int) or amount <= 0:
            return False, "取款金额必须大于0。"

        async with self.db.transaction() as tx:
            current_player = await self.db.get_player_by_id(player.user_id)
            bank_data = await self.db.ext.get_bank_account(player.user_id)
            current = bank_data["balance"] if bank_data else 0
            if not current_player:
                return False, "玩家不存在或已被删除。"
            if not bank_data or current < amount:
                return False, f"余额不足！当前余额：{current:,} 灵石。"

            new_balance = current - amount
            cursor = await self.db.conn.execute(
                "UPDATE bank_accounts SET balance = balance - ? WHERE user_id = ? AND balance >= ?",
                (amount, current_player.user_id, amount)
            )
            if cursor.rowcount != 1:
                tx.mark_rollback_only()
                return False, "余额不足或账户状态已变化，请重试。"
            player_cursor = await self.db.conn.execute(
                "UPDATE players SET gold = gold + ? WHERE user_id = ?",
                (amount, current_player.user_id)
            )
            if player_cursor.rowcount != 1:
                tx.mark_rollback_only()
                return False, "玩家状态已变化，请重试。"
            await self._add_transaction(
                current_player.user_id, "withdraw", -amount, new_balance, "取出灵石", commit=False
            )
            player.gold = current_player.gold + amount
            return True, f"成功取出 {amount:,} 灵石！\n当前余额：{new_balance:,} 灵石\n当前持有：{current_player.gold + amount:,} 灵石"
    
    async def claim_interest(self, player: Player) -> Tuple[bool, str]:
        """领取利息"""

        async with self.db.transaction() as tx:
            bank_data = await self.db.ext.get_bank_account(player.user_id)
            if not bank_data or bank_data["balance"] <= 0:
                return False, "你还没有存款，无法领取利息。"
            interest = self._calculate_interest(bank_data["balance"], bank_data["last_interest_time"])
            if interest <= 0:
                return False, "利息不足1灵石，请明日再来。"

            new_balance = bank_data["balance"] + interest
            now = int(time.time())
            cursor = await self.db.conn.execute(
                "UPDATE bank_accounts SET balance = ?, last_interest_time = ? "
                "WHERE user_id = ? AND balance = ? AND last_interest_time = ?",
                (new_balance, now, player.user_id, bank_data["balance"], bank_data["last_interest_time"])
            )
            if cursor.rowcount != 1:
                tx.mark_rollback_only()
                return False, "账户状态已变化，请重试。"
            await self._add_transaction(
                player.user_id, "interest", interest, new_balance, "领取利息", commit=False
            )
            return True, f"成功领取利息 {interest:,} 灵石！\n当前余额：{new_balance:,} 灵石"
    
    # ===== 贷款相关 =====
    
    async def get_loan_info(self, player: Player) -> Optional[dict]:
        """获取贷款详情"""
        loan = await self.db.ext.get_active_loan(player.user_id)
        if not loan:
            return None
        
        now = int(time.time())
        days_borrowed = (now - loan["borrowed_at"]) // 86400
        days_remaining = max(0, (loan["due_at"] - now) // 86400)
        
        # 计算当前应还金额（本金 + 利息）
        interest = int(loan["principal"] * loan["interest_rate"] * max(1, days_borrowed))
        total_due = loan["principal"] + interest
        
        is_overdue = now > loan["due_at"]
        
        return {
            **loan,
            "days_borrowed": days_borrowed,
            "days_remaining": days_remaining,
            "current_interest": interest,
            "total_due": total_due,
            "is_overdue": is_overdue
        }
    
    async def borrow(self, player: Player, amount: int, loan_type: str = "normal") -> Tuple[bool, str]:
        """申请贷款
        
        Args:
            player: 玩家
            amount: 贷款金额
            loan_type: 贷款类型 (normal/breakthrough)
        """
        if isinstance(amount, bool) or not isinstance(amount, int) or amount <= 0:
            return False, "贷款金额必须是大于0的整数。"

        async with self.db.transaction() as tx:
            current_player = await self.db.get_player_by_id(player.user_id)
            if not current_player:
                return False, "玩家不存在或已被删除。"

            # Re-read the realm/tier while owning the transaction.  A caller's
            # Player object may be stale after a concurrent breakthrough.
            player_loan_limit = await self.get_player_effective_loan_limit(current_player)
            current_tier = await self.get_player_loan_tier(current_player)
            current_tier_realm = get_tier_realm_name(current_tier)
            if amount < self.min_loan_amount:
                return False, f"最小贷款金额为 {self.min_loan_amount:,} 灵石。"
            if amount > player_loan_limit:
                next_tier = current_tier + 1
                challenge_hint = ""
                if next_tier <= 5:
                    next_examiner = BANK_EXAMINERS.get(next_tier)
                    if next_examiner:
                        next_limit = get_max_loan_for_tier(next_tier)
                        challenge_hint = (
                            f"\n💡 挑战【{next_examiner['name']}】可提升至 {next_limit:,} 灵石"
                            f"\n   使用 /挑战银行 {next_tier} 发起挑战"
                        )
                return False, (
                    f"❌ 贷款金额超出上限！\n"
                    f"━━━━━━━━━━━━━━━\n"
                    f"额度等级：{current_tier_realm}\n"
                    f"贷款上限：{player_loan_limit:,} 灵石{challenge_hint}"
                )
            existing_loan = await self.db.ext.get_active_loan(current_player.user_id)
            if existing_loan:
                return False, "你已有未还清的贷款，请先还款后再申请新贷款。"

            if loan_type == "breakthrough":
                interest_rate = self.breakthrough_loan_rate
                duration_days = self.breakthrough_loan_duration
                type_name = "突破贷款"
            else:
                interest_rate = self.loan_interest_rate
                duration_days = self.loan_duration_days
                type_name = "普通贷款"
            
            now = int(time.time())
            due_at = now + duration_days * 86400
            
            loan_id = await self.db.ext.create_loan(
                current_player.user_id, amount, interest_rate, now, due_at, loan_type, commit=False
            )
            if not loan_id:
                tx.mark_rollback_only()
                return False, "贷款记录创建失败，请重试。"

            cursor = await self.db.conn.execute(
                "UPDATE players SET gold = gold + ? WHERE user_id = ?",
                (amount, current_player.user_id)
            )
            if cursor.rowcount != 1:
                tx.mark_rollback_only()
                return False, "玩家状态已变化，请重试。"

            bank_data = await self.db.ext.get_bank_account(current_player.user_id)
            balance = bank_data["balance"] if bank_data else 0
            await self._add_transaction(
                current_player.user_id, "loan", amount, balance, f"{type_name}：借入{amount:,}灵石", commit=False
            )
            player.gold = current_player.gold + amount
            
            total_interest = int(amount * interest_rate * duration_days)
            total_due = amount + total_interest
            
            return True, (
                f"💰 {type_name}成功！\n"
                f"━━━━━━━━━━━━━━━\n"
                f"借入金额：{amount:,} 灵石\n"
                f"日利率：{interest_rate:.1%}\n"
                f"还款期限：{duration_days} 天\n"
                f"到期应还：约 {total_due:,} 灵石\n"
                f"━━━━━━━━━━━━━━━\n"
                f"当前持有：{current_player.gold + amount:,} 灵石\n"
                f"💀 逾期将被银行追杀致死！"
            )
    
    async def repay(self, player: Player) -> Tuple[bool, str]:
        """还款"""
        async with self.db.transaction() as tx:
            current_player = await self.db.get_player_by_id(player.user_id)
            if not current_player:
                return False, "玩家不存在或已被删除。"
            loan_info = await self.get_loan_info(current_player)
            if not loan_info:
                return False, "你当前没有需要偿还的贷款。"

            total_due = loan_info["total_due"]

            if current_player.gold < total_due:
                return False, (
                    f"灵石不足！\n"
                    f"应还金额：{total_due:,} 灵石\n"
                    f"（本金 {loan_info['principal']:,} + 利息 {loan_info['current_interest']:,}）\n"
                    f"当前持有：{current_player.gold:,} 灵石\n"
                    f"还差：{total_due - current_player.gold:,} 灵石"
                )

            cursor = await self.db.conn.execute(
                "UPDATE players SET gold = gold - ? WHERE user_id = ? AND gold >= ?",
                (total_due, current_player.user_id, total_due)
            )
            if cursor.rowcount != 1:
                tx.mark_rollback_only()
                return False, "灵石不足或玩家状态已变化，请重试。"
            loan_cursor = await self.db.conn.execute(
                "UPDATE bank_loans SET status = 'closed' WHERE id = ? AND status = 'active'",
                (loan_info["id"],)
            )
            if loan_cursor.rowcount != 1:
                tx.mark_rollback_only()
                return False, "贷款状态已变化，请重试。"

            bank_data = await self.db.ext.get_bank_account(current_player.user_id)
            balance = bank_data["balance"] if bank_data else 0
            await self._add_transaction(
                current_player.user_id, "repay", -total_due, balance,
                f"还款：本金{loan_info['principal']:,}+利息{loan_info['current_interest']:,}",
                commit=False,
            )
            player.gold = current_player.gold - total_due
            
            loan_type_name = "突破贷款" if loan_info["loan_type"] == "breakthrough" else "普通贷款"
            
            return True, (
                f"✅ 还款成功！\n"
                f"━━━━━━━━━━━━━━━\n"
                f"贷款类型：{loan_type_name}\n"
                f"已还本金：{loan_info['principal']:,} 灵石\n"
                f"已还利息：{loan_info['current_interest']:,} 灵石\n"
                f"合计支付：{total_due:,} 灵石\n"
                f"━━━━━━━━━━━━━━━\n"
                f"当前持有：{current_player.gold - total_due:,} 灵石"
            )
    
    async def check_and_process_overdue_loans(self) -> List[dict]:
        """检查并处理逾期贷款 - 逾期玩家将被银行追杀致死
        
        Returns:
            处理过的逾期贷款列表
        """
        now = int(time.time())
        overdue_loans = await self.db.ext.get_overdue_loans(now)
        processed = []

        for loan in overdue_loans:
            player = await self.db.get_player_by_id(loan["user_id"])
            if not player:
                # 玩家已不存在，直接关闭贷款
                async with self.db.transaction():
                    await self.db.ext.mark_loan_overdue(loan["id"], commit=False)
                continue

            player_name = player.user_name or f"道友{player.user_id[:6]}"
            async with self.db.transaction():
                # Re-check the loan while owning the transaction so a
                # concurrent repayment cannot be followed by a deletion.
                active_loan = await self.db.ext.get_active_loan(player.user_id)
                if not active_loan or active_loan["id"] != loan["id"]:
                    continue

                # Delete the player, mark the loan, and write the ledger entry
                # as one atomic operation.
                await self.db.delete_player_cascade(player.user_id, commit=False)
                await self.db.ext.mark_loan_overdue(loan["id"], commit=False)
                await self._add_transaction(
                    loan["user_id"], "bank_kill", 0, 0,
                    "逾期未还款，被银行追杀致死", commit=False
                )

            processed.append({
                **loan,
                "player_name": player_name,
                "death": True
            })
        
        return processed
    
    # ===== 流水相关 =====
    
    async def _add_transaction(self, user_id: str, trans_type: str, amount: int,
                                balance_after: int, description: str, *, commit: bool = True):
        """添加交易流水"""
        now = int(time.time())
        await self.db.ext.add_bank_transaction(
            user_id, trans_type, amount, balance_after, description, now, commit=commit
        )
    
    async def get_transactions(self, user_id: str, limit: int = 20) -> List[dict]:
        """获取交易流水"""
        return await self.db.ext.get_bank_transactions(user_id, limit)
    
    # ===== 排行榜 =====
    
    async def get_deposit_ranking(self, limit: int = 10) -> List[dict]:
        """获取存款排行榜"""
        return await self.db.ext.get_deposit_ranking(limit)
