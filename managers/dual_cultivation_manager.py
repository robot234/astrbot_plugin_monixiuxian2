# managers/dual_cultivation_manager.py
"""双修系统管理器"""
import time
import json
from typing import Tuple, Optional, Dict
from ..data import DataBase
from ..models import Player
from ..models_extended import UserStatus

__all__ = ["DualCultivationManager"]

# 双修配置
DUAL_CULT_COOLDOWN = 3600  # 1小时冷却
DUAL_CULT_EXP_BONUS = 0.1  # 10%修为互增


class DualCultivationManager:
    """双修管理器"""
    
    def __init__(self, db: DataBase):
        self.db = db
        self.pending_requests: Dict[str, Dict] = {}  # {target_id: {from_id, from_name, time}}
    
    async def send_request(self, initiator: Player, target_id: str) -> Tuple[bool, str]:
        """发起双修请求"""
        if initiator.user_id == target_id:
            return False, "❌ 不能与自己双修。"
        
        # 检查发起者状态（状态互斥）
        user_cd = await self.db.ext.get_user_cd(initiator.user_id)
        if user_cd and user_cd.type != UserStatus.IDLE:
            current_status = UserStatus.get_name(user_cd.type)
            return False, f"❌ 你当前正{current_status}，无法发起双修！"
        
        # 检查目标是否存在
        target = await self.db.get_player_by_id(target_id)
        if not target:
            return False, "❌ 对方还未踏入修仙之路。"
        
        # 检查目标状态
        target_cd = await self.db.ext.get_user_cd(target_id)
        if target_cd and target_cd.type != UserStatus.IDLE:
            return False, "❌ 对方正忙，无法接受双修请求。"
        
        # 检查冷却
        last_dual = await self._get_last_dual_time(initiator.user_id)
        now = int(time.time())
        if last_dual and (now - last_dual) < DUAL_CULT_COOLDOWN:
            remaining = DUAL_CULT_COOLDOWN - (now - last_dual)
            return False, f"❌ 双修冷却中，还需 {remaining // 60} 分钟。"
        
        # 发起请求
        self.pending_requests[target_id] = {
            "from_id": initiator.user_id,
            "from_name": initiator.user_name or initiator.user_id[:8],
            "time": now
        }
        
        return True, (
            f"💕 已向【{target.user_name or target_id[:8]}】发起双修请求！\n"
            f"对方使用 /接受双修 或 /拒绝双修 响应。\n"
            f"请求将在5分钟后过期。"
        )
    
    async def accept_request(self, acceptor: Player) -> Tuple[bool, str]:
        """接受双修请求"""
        request = self.pending_requests.get(acceptor.user_id)
        if not request:
            return False, "❌ 没有待处理的双修请求。"
        
        # 检查请求是否过期（5分钟）
        now = int(time.time())
        if now - request["time"] > 300:
            del self.pending_requests[acceptor.user_id]
            return False, "❌ 双修请求已过期。"
        
        initiator = await self.db.get_player_by_id(request["from_id"])
        if not initiator:
            del self.pending_requests[acceptor.user_id]
            return False, "❌ 请求发起者数据异常。"
        
        # 计算双修收益
        init_exp_gain = int(acceptor.experience * DUAL_CULT_EXP_BONUS)
        accept_exp_gain = int(initiator.experience * DUAL_CULT_EXP_BONUS)
        
        # 应用收益
        initiator.experience += init_exp_gain
        acceptor.experience += accept_exp_gain
        await self.db.update_player(initiator)
        await self.db.update_player(acceptor)
        
        # 记录冷却
        await self._set_last_dual_time(initiator.user_id, now)
        await self._set_last_dual_time(acceptor.user_id, now)
        
        # 清除请求
        del self.pending_requests[acceptor.user_id]
        
        return True, (
            f"💕 双修成功！\n"
            f"━━━━━━━━━━━━━━━\n"
            f"与【{request['from_name']}】双修\n"
            f"{request['from_name']} 获得修为：+{init_exp_gain:,}\n"
            f"你 获得修为：+{accept_exp_gain:,}\n"
            f"━━━━━━━━━━━━━━━\n"
            f"下次双修：1小时后"
        )
    
    async def reject_request(self, rejecter_id: str) -> Tuple[bool, str]:
        """拒绝双修请求"""
        request = self.pending_requests.get(rejecter_id)
        if not request:
            return False, "❌ 没有待处理的双修请求。"
        
        from_name = request["from_name"]
        del self.pending_requests[rejecter_id]
        
        return True, f"已拒绝【{from_name}】的双修请求。"
    
    async def _get_last_dual_time(self, user_id: str) -> Optional[int]:
        """获取上次双修时间"""
        async with self.db.conn.execute(
            "SELECT last_dual_time FROM dual_cultivation WHERE user_id = ?",
            (user_id,)
        ) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else None
    
    async def _set_last_dual_time(self, user_id: str, timestamp: int):
        """设置上次双修时间"""
        await self.db.conn.execute(
            """
            INSERT INTO dual_cultivation (user_id, last_dual_time)
            VALUES (?, ?)
            ON CONFLICT(user_id) DO UPDATE SET last_dual_time = excluded.last_dual_time
            """,
            (user_id, timestamp)
        )
        await self.db.conn.commit()
