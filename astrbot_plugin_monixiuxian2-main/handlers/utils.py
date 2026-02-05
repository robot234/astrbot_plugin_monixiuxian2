# handlers/utils.py
# 通用工具函数和装饰器

import time
from functools import wraps
from typing import Callable, Coroutine, AsyncGenerator

from astrbot.api.event import AstrMessageEvent
from ..models import Player
from ..models_extended import UserStatus

# 指令常量
CMD_START_XIUXIAN = "我要修仙"
CMD_PLAYER_INFO = "我的信息"
CMD_START_CULTIVATION = "闭关"
CMD_END_CULTIVATION = "出关"
CMD_CHECK_IN = "签到"

# 忙碌状态下允许执行的命令白名单
BUSY_STATE_ALLOWED_COMMANDS = [
    # 基础信息查看
    CMD_PLAYER_INFO,
    "我的信息",
    CMD_CHECK_IN,
    "签到",
    # 银行相关
    "银行",
    "存灵石",
    "取灵石",
    "领取利息",
    "贷款",
    "还款",
    "银行流水",
    # 背包查看（只读操作）
    "丹药背包",
    "我的丹药",
    "我的装备",
    "储物戒",
    "查看储物戒",
    # 排行榜查看
    "排行榜",
    "境界榜",
    "战力榜",
    "灵石榜",
    "宗门榜",
    "存款榜",
    # 帮助信息
    "修仙帮助",
    # 闭关相关
    CMD_END_CULTIVATION,
    "出关",
    # 历练/秘境结算
    "结束历练",
    "结束秘境",
    "结束任务",
]


def player_required(func: Callable[..., Coroutine[any, any, AsyncGenerator[any, None]]]):
    """
    一个装饰器，用于需要玩家登录才能执行的指令。
    它会自动检查玩家是否存在、状态是否空闲（特定指令除外），否则将玩家对象作为参数注入。
    同时检查贷款状态，如有贷款则显示还款提示。
    """
    @wraps(func)
    async def wrapper(self, event: AstrMessageEvent, *args, **kwargs):
        # self 是 Handler 类的实例 (e.g., PlayerHandler)
        player = await self.db.get_player_by_id(event.get_sender_id())

        if not player:
            yield event.plain_result(f"道友尚未踏入仙途，请发送「{CMD_START_XIUXIAN}」开启你的旅程。")
            return

        # 检查贷款状态并处理逾期
        loan_warning = await _check_loan_status(self.db, player)
        if loan_warning:
            if loan_warning.get("is_dead"):
                # 玩家因逾期被追杀，删除数据
                yield event.plain_result(loan_warning["message"])
                return
        
        message_text = event.get_message_str().strip()
        
        # 检查 user_cd 表的忙碌状态
        user_cd = await self.db.ext.get_user_cd(player.user_id)
        if user_cd and user_cd.type != UserStatus.IDLE:
            # 玩家处于忙碌状态，检查命令是否在白名单中
            is_allowed = _is_command_allowed(message_text, BUSY_STATE_ALLOWED_COMMANDS)
            
            if not is_allowed:
                status_name = UserStatus.get_name(user_cd.type)
                yield event.plain_result(f"道友当前正在「{status_name}」，无法分心他顾。\n💡 可使用「我的信息」「签到」「银行」等基础指令。")
                return
        
        # 状态检查：如果处于修炼中（闭关），只允许出关、查看信息和签到
        if player.state == "修炼中":
            is_allowed = _is_command_allowed(message_text, BUSY_STATE_ALLOWED_COMMANDS)

            if not is_allowed:
                yield event.plain_result(f"道友当前正在「{player.state}」中，无法分心他顾。\n💡 可使用「出关」「我的信息」「签到」「银行」等基础指令。")
                return

        # 将 player 对象作为第一个参数传递给原始函数
        async for result in func(self, player, event, *args, **kwargs):
            yield result
        
        # 如果有贷款警告，在指令执行完后显示
        if loan_warning and loan_warning.get("warning_message"):
            yield event.plain_result(loan_warning["warning_message"])

    return wrapper


def _is_command_allowed(message_text: str, allowed_commands: list) -> bool:
    """检查命令是否在允许列表中"""
    for cmd in allowed_commands:
        if message_text.startswith(cmd):
            return True
    return False


async def _check_loan_status(db, player: Player) -> dict:
    """检查玩家贷款状态
    
    Returns:
        dict: {is_dead, message, warning_message} 或 None
    """
    try:
        loan = await db.ext.get_active_loan(player.user_id)
        if not loan:
            return None
        
        now = int(time.time())
        due_at = loan["due_at"]
        
        # 检查是否已逾期
        if now > due_at:
            # 使用事务保护，防止并发删除
            await db.conn.execute("BEGIN IMMEDIATE")
            try:
                # 重新检查贷款状态（可能已被其他请求处理）
                loan = await db.ext.get_active_loan(player.user_id)
                if not loan or loan["status"] != "active":
                    await db.conn.rollback()
                    return None
                
                # 再次检查是否逾期
                if now <= loan["due_at"]:
                    await db.conn.rollback()
                    return None
                
                player_name = player.user_name or f"道友{player.user_id[:6]}"
                
                # 删除玩家（级联删除所有关联数据）
                await db.delete_player_cascade(player.user_id)
                
                # 标记贷款逾期
                await db.ext.mark_loan_overdue(loan["id"])
                
                # 记录流水
                await db.ext.add_bank_transaction(
                    player.user_id, "bank_kill", 0, 0,
                    "逾期未还款，被银行追杀致死", now
                )
                
                await db.conn.commit()
                
                loan_type_name = "突破贷款" if loan["loan_type"] == "breakthrough" else "普通贷款"
                
                return {
                    "is_dead": True,
                    "message": (
                        f"💀 银行追杀令 💀\n"
                        f"━━━━━━━━━━━━━━━\n"
                        f"道友【{player_name}】因{loan_type_name}逾期未还\n"
                        f"欠款本金：{loan['principal']:,} 灵石\n"
                        f"━━━━━━━━━━━━━━━\n"
                        f"银行派出的追杀者已将你击杀！\n"
                        f"所有修为和装备化为虚无...\n"
                        f"━━━━━━━━━━━━━━━\n"
                        f"若想重新修仙，请使用「我要修仙」命令"
                    )
                }
            except Exception:
                await db.conn.rollback()
                raise
        
        # 计算剩余时间
        remaining_seconds = due_at - now
        remaining_days = remaining_seconds // 86400
        remaining_hours = (remaining_seconds % 86400) // 3600
        
        # 计算应还金额
        days_borrowed = max(1, (now - loan["borrowed_at"]) // 86400)
        interest = int(loan["principal"] * loan["interest_rate"] * days_borrowed)
        total_due = loan["principal"] + interest
        
        loan_type_name = "突破贷款" if loan["loan_type"] == "breakthrough" else "普通贷款"
        
        # 根据剩余时间设置警告等级
        if remaining_days <= 0:
            urgency = "🔴 紧急"
            time_str = f"{remaining_hours} 小时"
        elif remaining_days <= 1:
            urgency = "🟠 警告"
            time_str = f"{remaining_days} 天 {remaining_hours} 小时"
        else:
            urgency = "🟡 提醒"
            time_str = f"{remaining_days} 天"
        
        warning_message = (
            f"\n━━━━━━━━━━━━━━━\n"
            f"{urgency}【{loan_type_name}还款提醒】\n"
            f"应还金额：{total_due:,} 灵石\n"
            f"剩余时间：{time_str}\n"
            f"⚠️ 逾期将被银行追杀致死！\n"
            f"请使用 /还款 命令还款"
        )
        
        return {
            "is_dead": False,
            "warning_message": warning_message
        }
        
    except Exception:
        return None
