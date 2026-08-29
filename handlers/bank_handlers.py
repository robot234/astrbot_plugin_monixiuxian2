# handlers/bank_handlers.py
"""灵石银行处理器 - 包含存取款、贷款、流水查询功能"""
import time
from astrbot.api.event import AstrMessageEvent
from ..data import DataBase
from ..managers.bank_manager import (
    BankManager, get_realm_name, LOAN_LIMITS_BY_REALM, 
    BANK_EXAMINERS, get_tier_realm_name, get_max_loan_for_tier
)
from ..models import Player
from .utils import player_required

__all__ = ["BankHandlers"]


class BankHandlers:
    """灵石银行处理器"""
    
    def __init__(self, db: DataBase, bank_mgr: BankManager, 
                 battle_manager=None, equipment_manager=None, skill_manager=None):
        self.db = db
        self.bank_mgr = bank_mgr
        self.battle_manager = battle_manager
        self.equipment_manager = equipment_manager
        self.skill_manager = skill_manager
    
    @player_required
    async def handle_bank_info(self, player: Player, event: AstrMessageEvent):
        """查看银行信息"""
        info = await self.bank_mgr.get_bank_info(player)
        
        # 判断额度是否通过挑战提升
        tier_source = ""
        if info["loan_tier"] > info["realm_tier"]:
            tier_source = " (挑战提升)"
        
        msg_lines = [
            "🏦 灵石银行",
            "━━━━━━━━━━━━━━━",
            f"💰 存款余额：{info['balance']:,} 灵石",
            f"📈 待领利息：{info['pending_interest']:,} 灵石",
            f"📊 日利率：0.1%（复利）",
            "━━━━━━━━━━━━━━━",
            f"💎 持有灵石：{player.gold:,}",
            f"🎯 当前境界：{info['realm']}",
            f"📋 贷款额度：{info['loan_tier_realm']}{tier_source}",
            f"💵 最高可贷：{info['loan_limit']:,} 灵石",
        ]
        
        # 显示贷款信息
        if info.get("loan"):
            loan_info = await self.bank_mgr.get_loan_info(player)
            if loan_info:
                loan_type_name = "突破贷款" if loan_info["loan_type"] == "breakthrough" else "普通贷款"
                status = "⚠️ 已逾期！" if loan_info["is_overdue"] else f"剩余 {loan_info['days_remaining']} 天"
                msg_lines.extend([
                    "━━━━━━━━━━━━━━━",
                    f"📋 当前贷款（{loan_type_name}）",
                    f"   本金：{loan_info['principal']:,} 灵石",
                    f"   当前利息：{loan_info['current_interest']:,} 灵石",
                    f"   应还总额：{loan_info['total_due']:,} 灵石",
                    f"   状态：{status}",
                ])
        
        # 显示挑战提示
        if info["can_challenge"]:
            next_tier = info["loan_tier"] + 1
            if next_tier in BANK_EXAMINERS:
                next_examiner = BANK_EXAMINERS[next_tier]
                next_limit = get_max_loan_for_tier(next_tier)
                msg_lines.extend([
                    "━━━━━━━━━━━━━━━",
                    f"⚔️ 可挑战：{next_examiner['name']}",
                    f"   胜利后额度提升至 {next_limit:,} 灵石",
                ])
        
        msg_lines.extend([
            "━━━━━━━━━━━━━━━",
            "💡 指令：",
            "  /存灵石 <数量>",
            "  /取灵石 <数量>",
            "  /领取利息",
            "  /贷款 <数量>",
            "  /还款",
            "  /银行流水",
            "  /挑战银行 - 提升贷款额度",
        ])
        
        yield event.plain_result("\n".join(msg_lines))
    
    @player_required
    async def handle_deposit(self, player: Player, event: AstrMessageEvent, amount: int = 0):
        """存入灵石"""
        if amount <= 0:
            yield event.plain_result("❌ 请输入存款金额，例如：/存灵石 10000")
            return
        
        success, msg = await self.bank_mgr.deposit(player, amount)
        prefix = "✅" if success else "❌"
        yield event.plain_result(f"{prefix} {msg}")
    
    @player_required
    async def handle_withdraw(self, player: Player, event: AstrMessageEvent, amount: int = 0):
        """取出灵石"""
        if amount <= 0:
            yield event.plain_result("❌ 请输入取款金额，例如：/取灵石 10000")
            return
        
        success, msg = await self.bank_mgr.withdraw(player, amount)
        prefix = "✅" if success else "❌"
        yield event.plain_result(f"{prefix} {msg}")
    
    @player_required
    async def handle_claim_interest(self, player: Player, event: AstrMessageEvent):
        """领取利息"""
        success, msg = await self.bank_mgr.claim_interest(player)
        prefix = "✅" if success else "❌"
        yield event.plain_result(f"{prefix} {msg}")
    
    @player_required
    async def handle_loan(self, player: Player, event: AstrMessageEvent, amount: int = 0):
        """申请贷款"""
        if amount <= 0:
            # 显示贷款帮助，包含境界限制和挑战提示
            current_realm = get_realm_name(player.level_index)
            player_limit = await self.bank_mgr.get_player_effective_loan_limit(player)
            current_tier = await self.bank_mgr.get_player_loan_tier(player)
            current_tier_realm = get_tier_realm_name(current_tier)
            
            # 构建境界贷款上限列表
            limit_lines = []
            for realm, info in LOAN_LIMITS_BY_REALM.items():
                tier = info["tier"]
                is_current = tier == current_tier
                marker = "👉" if is_current else "  "
                limit_lines.append(f"{marker}{realm}：最高 {info['max_loan']:,} 灵石")
            
            # 挑战提示
            challenge_hint = ""
            if current_tier < 5:
                next_tier = current_tier + 1
                if next_tier in BANK_EXAMINERS:
                    next_examiner = BANK_EXAMINERS[next_tier]
                    next_limit = get_max_loan_for_tier(next_tier)
                    challenge_hint = (
                        f"\n⚔️ 挑战【{next_examiner['name']}】\n"
                        f"   可提升额度至 {next_limit:,} 灵石\n"
                        f"   使用 /挑战银行 查看详情"
                    )
            
            yield event.plain_result(
                "🏦 贷款说明\n"
                "━━━━━━━━━━━━━━━\n"
                "📌 普通贷款：\n"
                "   日利率：0.5%\n"
                "   期限：7天\n"
                "━━━━━━━━━━━━━━━\n"
                "📊 贷款额度等级：\n"
                f"{chr(10).join(limit_lines)}\n"
                "━━━━━━━━━━━━━━━\n"
                f"🎯 你的境界：{current_realm}\n"
                f"📋 你的额度：{current_tier_realm}\n"
                f"💵 最高可贷：{player_limit:,} 灵石\n"
                f"{challenge_hint}"
                "━━━━━━━━━━━━━━━\n"
                "💀 逾期后果：被银行追杀致死！\n"
                "   所有修为和装备将化为虚无\n"
                "━━━━━━━━━━━━━━━\n"
                "💡 用法：/贷款 <金额>\n"
                "   例如：/贷款 5000"
            )
            return
        
        success, msg = await self.bank_mgr.borrow(player, amount, "normal")
        yield event.plain_result(msg)
    
    @player_required
    async def handle_repay(self, player: Player, event: AstrMessageEvent):
        """还款"""
        success, msg = await self.bank_mgr.repay(player)
        yield event.plain_result(msg)
    
    @player_required
    async def handle_transactions(self, player: Player, event: AstrMessageEvent):
        """查看银行流水"""
        transactions = await self.bank_mgr.get_transactions(player.user_id, 15)
        
        if not transactions:
            yield event.plain_result("📋 暂无交易记录")
            return
        
        msg_lines = [
            "📋 银行交易流水（最近15条）",
            "━━━━━━━━━━━━━━━",
        ]
        
        type_names = {
            "deposit": "💰 存入",
            "withdraw": "💸 取出",
            "interest": "📈 利息",
            "loan": "📥 贷款",
            "repay": "📤 还款",
            "overdue_penalty": "⚠️ 逾期",
        }
        
        for trans in transactions:
            trans_time = time.strftime("%m-%d %H:%M", time.localtime(trans["created_at"]))
            type_name = type_names.get(trans["trans_type"], trans["trans_type"])
            amount = trans["amount"]
            amount_str = f"+{amount:,}" if amount > 0 else f"{amount:,}"
            
            msg_lines.append(f"{trans_time} {type_name} {amount_str}")
        
        msg_lines.extend([
            "━━━━━━━━━━━━━━━",
            f"当前余额：{transactions[0]['balance_after']:,} 灵石" if transactions else ""
        ])
        
        yield event.plain_result("\n".join(msg_lines))
    
    @player_required
    async def handle_breakthrough_loan(self, player: Player, event: AstrMessageEvent, amount: int = 0):
        """申请突破贷款（用于购买破境丹）"""
        if amount <= 0:
            current_realm = get_realm_name(player.level_index)
            player_limit = await self.bank_mgr.get_player_effective_loan_limit(player)
            current_tier = await self.bank_mgr.get_player_loan_tier(player)
            current_tier_realm = get_tier_realm_name(current_tier)
            
            yield event.plain_result(
                "🏦 突破贷款说明\n"
                "━━━━━━━━━━━━━━━\n"
                "📌 专为突破准备的短期贷款：\n"
                "   日利率：0.8%（较高）\n"
                "   期限：3天（较短）\n"
                "━━━━━━━━━━━━━━━\n"
                f"🎯 你的境界：{current_realm}\n"
                f"📋 你的额度：{current_tier_realm}\n"
                f"💵 最高可贷：{player_limit:,} 灵石\n"
                "━━━━━━━━━━━━━━━\n"
                "✨ 突破成功后记得及时还款\n"
                "━━━━━━━━━━━━━━━\n"
                "💀 逾期后果：被银行追杀致死！\n"
                "   所有修为和装备将化为虚无\n"
                "━━━━━━━━━━━━━━━\n"
                "💡 用法：/突破贷款 <金额>"
            )
            return
        
        success, msg = await self.bank_mgr.borrow(player, amount, "breakthrough")
        yield event.plain_result(msg)
    
    @player_required
    async def handle_bank_challenge(self, player: Player, event: AstrMessageEvent, target_tier: int = 0):
        """挑战银行考核官"""
        # 检查是否有战斗管理器
        if not self.battle_manager or not self.equipment_manager or not self.skill_manager:
            yield event.plain_result("❌ 战斗系统未初始化，无法进行挑战。")
            return
        
        # 获取当前贷款等级
        current_tier = await self.bank_mgr.get_player_loan_tier(player)
        current_limit = get_max_loan_for_tier(current_tier)
        current_tier_realm = get_tier_realm_name(current_tier)
        
        if target_tier <= 0:
            # 显示挑战帮助
            msg_lines = [
                "⚔️ 银行考核挑战",
                "━━━━━━━━━━━━━━━",
                f"当前额度等级：{current_tier_realm}",
                f"当前最高可贷：{current_limit:,} 灵石",
                "━━━━━━━━━━━━━━━",
                "📋 可挑战的考核官：",
            ]
            
            # 获取可挑战的考核官
            available = self.bank_mgr.get_available_challenges(player, current_tier)
            
            if not available:
                msg_lines.append("  (已达最高额度等级)")
            else:
                for challenge in available:
                    tier = challenge["tier"]
                    name = challenge["name"]
                    realm = challenge["realm"]
                    reward_limit = get_max_loan_for_tier(tier)
                    
                    # 只显示下一级可挑战的
                    if tier == current_tier + 1:
                        msg_lines.append(f"  ⚔️ {tier}. {name}")
                        msg_lines.append(f"     境界：{realm}")
                        msg_lines.append(f"     胜利奖励：额度提升至 {reward_limit:,} 灵石")
                    else:
                        msg_lines.append(f"  🔒 {tier}. {name} (需先通过上一级)")
            
            # 检查冷却
            cooldown = await self.bank_mgr.get_challenge_cooldown(player)
            if cooldown > 0:
                minutes = cooldown // 60
                seconds = cooldown % 60
                msg_lines.extend([
                    "━━━━━━━━━━━━━━━",
                    f"⏱️ 冷却中：{minutes}分{seconds}秒",
                ])
            
            msg_lines.extend([
                "━━━━━━━━━━━━━━━",
                "💡 用法：/挑战银行 <等级>",
                f"   例如：/挑战银行 {current_tier + 1}" if current_tier < 5 else "",
                "⚠️ 挑战失败后有1小时冷却时间",
            ])
            
            yield event.plain_result("\n".join(msg_lines))
            return
        
        # 执行挑战
        success, msg, battle_result = await self.bank_mgr.challenge_examiner(
            player, 
            target_tier,
            self.battle_manager,
            self.equipment_manager,
            self.skill_manager
        )
        
        yield event.plain_result(msg)
