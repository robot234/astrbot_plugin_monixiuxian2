# managers/bank_manager.py
"""灵石银行系统管理器 - 包含存取款、贷款、流水记录功能"""
import time
from typing import Tuple, List, Optional
from ..data import DataBase
from ..models import Player

__all__ = ["BankManager"]

# 银行配置
DAILY_INTEREST_RATE = 0.001  # 存款日利率 0.1%
MAX_DEPOSIT = 10000000  # 最大存款上限 1000万

# 贷款配置
LOAN_INTEREST_RATE = 0.005  # 贷款日利率 0.5%
LOAN_DURATION_DAYS = 7  # 贷款期限 7天
MAX_LOAN_AMOUNT = 1000000  # 最大贷款额度 100万
MIN_LOAN_AMOUNT = 1000  # 最小贷款额度 1000

# 突破贷款配置
BREAKTHROUGH_LOAN_RATE = 0.008  # 突破贷款日利率 0.8%（更高风险）
BREAKTHROUGH_LOAN_DURATION = 3  # 突破贷款期限 3天


class BankManager:
    """灵石银行管理器"""
    
    def __init__(self, db: DataBase):
        self.db = db
    
    # ===== 存款相关 =====
    
    async def get_bank_info(self, player: Player) -> dict:
        """获取银行账户信息
        
        Returns:
            dict: {balance, last_interest_time, pending_interest, loan_info}
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
        
        return bank_info
    
    def _calculate_interest(self, balance: int, last_time: int) -> int:
        """计算待领利息"""
        if balance <= 0 or last_time <= 0:
            return 0
        
        now = int(time.time())
        days_passed = (now - last_time) // 86400
        
        if days_passed < 1:
            return 0
        
        # 复利计算
        interest = int(balance * ((1 + DAILY_INTEREST_RATE) ** days_passed - 1))
        return interest
    
    async def deposit(self, player: Player, amount: int) -> Tuple[bool, str]:
        """存入灵石"""
        if amount <= 0:
            return False, "存款金额必须大于0。"
        
        await self.db.conn.execute("BEGIN IMMEDIATE")
        try:
            player = await self.db.get_player_by_id(player.user_id)
            if player.gold < amount:
                await self.db.conn.rollback()
                return False, f"灵石不足！你只有 {player.gold:,} 灵石。"
            
            bank_data = await self.db.ext.get_bank_account(player.user_id)
            current_balance = bank_data["balance"] if bank_data else 0
            
            if current_balance + amount > MAX_DEPOSIT:
                await self.db.conn.rollback()
                return False, f"存款上限为 {MAX_DEPOSIT:,} 灵石，当前余额 {current_balance:,}。"
            
            player.gold -= amount
            await self.db.update_player(player)
            
            new_balance = current_balance + amount
            now = int(time.time())
            await self.db.ext.update_bank_account(
                player.user_id, 
                new_balance, 
                now if current_balance == 0 else bank_data["last_interest_time"]
            )
            
            await self._add_transaction(player.user_id, "deposit", amount, new_balance, "存入灵石")
            
            await self.db.conn.commit()
            return True, f"成功存入 {amount:,} 灵石！\n当前余额：{new_balance:,} 灵石"
        except Exception as e:
            await self.db.conn.rollback()
            raise
    
    async def withdraw(self, player: Player, amount: int) -> Tuple[bool, str]:
        """取出灵石"""
        if amount <= 0:
            return False, "取款金额必须大于0。"
        
        await self.db.conn.execute("BEGIN IMMEDIATE")
        try:
            player = await self.db.get_player_by_id(player.user_id)
            bank_data = await self.db.ext.get_bank_account(player.user_id)
            if not bank_data or bank_data["balance"] < amount:
                await self.db.conn.rollback()
                current = bank_data["balance"] if bank_data else 0
                return False, f"余额不足！当前余额：{current:,} 灵石。"
            
            new_balance = bank_data["balance"] - amount
            await self.db.ext.update_bank_account(
                player.user_id, 
                new_balance, 
                bank_data["last_interest_time"]
            )
            
            player.gold += amount
            await self.db.update_player(player)
            
            await self._add_transaction(player.user_id, "withdraw", -amount, new_balance, "取出灵石")
            
            await self.db.conn.commit()
            return True, f"成功取出 {amount:,} 灵石！\n当前余额：{new_balance:,} 灵石\n当前持有：{player.gold:,} 灵石"
        except Exception as e:
            await self.db.conn.rollback()
            raise
    
    async def claim_interest(self, player: Player) -> Tuple[bool, str]:
        """领取利息"""
        bank_data = await self.db.ext.get_bank_account(player.user_id)
        if not bank_data or bank_data["balance"] <= 0:
            return False, "你还没有存款，无法领取利息。"
        
        interest = self._calculate_interest(
            bank_data["balance"], 
            bank_data["last_interest_time"]
        )
        
        if interest <= 0:
            return False, "利息不足1灵石，请明日再来。"
        
        # 利息转入本金
        new_balance = bank_data["balance"] + interest
        now = int(time.time())
        await self.db.ext.update_bank_account(player.user_id, new_balance, now)
        
        # 记录流水
        await self._add_transaction(player.user_id, "interest", interest, new_balance, "领取利息")
        
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
        if amount < MIN_LOAN_AMOUNT:
            return False, f"最小贷款金额为 {MIN_LOAN_AMOUNT:,} 灵石。"
        
        if amount > MAX_LOAN_AMOUNT:
            return False, f"最大贷款金额为 {MAX_LOAN_AMOUNT:,} 灵石。"
        
        await self.db.conn.execute("BEGIN IMMEDIATE")
        try:
            player = await self.db.get_player_by_id(player.user_id)
            existing_loan = await self.db.ext.get_active_loan(player.user_id)
            if existing_loan:
                await self.db.conn.rollback()
                return False, "你已有未还清的贷款，请先还款后再申请新贷款。"
            
            if loan_type == "breakthrough":
                interest_rate = BREAKTHROUGH_LOAN_RATE
                duration_days = BREAKTHROUGH_LOAN_DURATION
                type_name = "突破贷款"
            else:
                interest_rate = LOAN_INTEREST_RATE
                duration_days = LOAN_DURATION_DAYS
                type_name = "普通贷款"
            
            now = int(time.time())
            due_at = now + duration_days * 86400
            
            await self.db.ext.create_loan(
                player.user_id, amount, interest_rate, now, due_at, loan_type
            )
            
            player.gold += amount
            await self.db.update_player(player)
            
            bank_data = await self.db.ext.get_bank_account(player.user_id)
            balance = bank_data["balance"] if bank_data else 0
            await self._add_transaction(player.user_id, "loan", amount, balance, f"{type_name}：借入{amount:,}灵石")
            
            total_interest = int(amount * interest_rate * duration_days)
            total_due = amount + total_interest
            
            await self.db.conn.commit()
            return True, (
                f"💰 {type_name}成功！\n"
                f"━━━━━━━━━━━━━━━\n"
                f"借入金额：{amount:,} 灵石\n"
                f"日利率：{interest_rate:.1%}\n"
                f"还款期限：{duration_days} 天\n"
                f"到期应还：约 {total_due:,} 灵石\n"
                f"━━━━━━━━━━━━━━━\n"
                f"当前持有：{player.gold:,} 灵石\n"
                f"💀 逾期将被银行追杀致死！"
            )
        except Exception as e:
            await self.db.conn.rollback()
            raise
    
    async def repay(self, player: Player) -> Tuple[bool, str]:
        """还款"""
        await self.db.conn.execute("BEGIN IMMEDIATE")
        try:
            player = await self.db.get_player_by_id(player.user_id)
            loan_info = await self.get_loan_info(player)
            if not loan_info:
                await self.db.conn.rollback()
                return False, "你当前没有需要偿还的贷款。"
            
            total_due = loan_info["total_due"]
            
            if player.gold < total_due:
                await self.db.conn.rollback()
                return False, (
                    f"灵石不足！\n"
                    f"应还金额：{total_due:,} 灵石\n"
                    f"（本金 {loan_info['principal']:,} + 利息 {loan_info['current_interest']:,}）\n"
                    f"当前持有：{player.gold:,} 灵石\n"
                    f"还差：{total_due - player.gold:,} 灵石"
                )
            
            player.gold -= total_due
            await self.db.update_player(player)
            
            await self.db.ext.close_loan(loan_info["id"])
            
            bank_data = await self.db.ext.get_bank_account(player.user_id)
            balance = bank_data["balance"] if bank_data else 0
            await self._add_transaction(
                player.user_id, "repay", -total_due, balance, 
                f"还款：本金{loan_info['principal']:,}+利息{loan_info['current_interest']:,}"
            )
            
            loan_type_name = "突破贷款" if loan_info["loan_type"] == "breakthrough" else "普通贷款"
            
            await self.db.conn.commit()
            return True, (
                f"✅ 还款成功！\n"
                f"━━━━━━━━━━━━━━━\n"
                f"贷款类型：{loan_type_name}\n"
                f"已还本金：{loan_info['principal']:,} 灵石\n"
                f"已还利息：{loan_info['current_interest']:,} 灵石\n"
                f"合计支付：{total_due:,} 灵石\n"
                f"━━━━━━━━━━━━━━━\n"
                f"当前持有：{player.gold:,} 灵石"
            )
        except Exception as e:
            await self.db.conn.rollback()
            raise
    
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
                await self.db.ext.mark_loan_overdue(loan["id"])
                continue
            
            player_name = player.user_name or f"道友{player.user_id[:6]}"
            
            # 删除玩家数据（银行追杀致死）- 级联删除所有关联数据
            await self.db.delete_player_cascade(player.user_id)
            
            # 标记贷款逾期
            await self.db.ext.mark_loan_overdue(loan["id"])
            
            # 记录流水
            await self._add_transaction(
                loan["user_id"], "bank_kill", 0, 0,
                f"逾期未还款，被银行追杀致死"
            )
            
            processed.append({
                **loan,
                "player_name": player_name,
                "death": True
            })
        
        return processed
    
    # ===== 流水相关 =====
    
    async def _add_transaction(self, user_id: str, trans_type: str, amount: int, 
                                balance_after: int, description: str):
        """添加交易流水"""
        now = int(time.time())
        await self.db.ext.add_bank_transaction(
            user_id, trans_type, amount, balance_after, description, now
        )
    
    async def get_transactions(self, user_id: str, limit: int = 20) -> List[dict]:
        """获取交易流水"""
        return await self.db.ext.get_bank_transactions(user_id, limit)
    
    # ===== 排行榜 =====
    
    async def get_deposit_ranking(self, limit: int = 10) -> List[dict]:
        """获取存款排行榜"""
        return await self.db.ext.get_deposit_ranking(limit)
