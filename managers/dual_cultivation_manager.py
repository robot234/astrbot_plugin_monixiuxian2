# managers/dual_cultivation_manager.py
"""道侣系统管理器 - 共享功能版本"""
import time
import random
from typing import Tuple, Optional, Dict, List, TYPE_CHECKING
from ..data import DataBase
from ..models import Player
from ..models_extended import UserStatus, PartnerRequest

if TYPE_CHECKING:
    from ..core.storage_ring_manager import StorageRingManager
    from ..core.pill_manager import PillManager

__all__ = ["DualCultivationManager"]

# 道侣系统配置
DUAL_CULT_COOLDOWN = 3600  # 双修冷却时间（1小时）
DUAL_CULT_BASE_EXP_BONUS = 0.10  # 基础双修修为互增（10%）
PARTNER_REQUEST_EXPIRE = 300  # 道侣请求过期时间（5分钟）
DUAL_CULT_INTIMACY_GAIN = 100  # 双修获得的亲密度
DAILY_INTIMACY_GAIN = 20  # 每日互动亲密度
BREAKUP_COOLDOWN = 86400 * 3  # 解除道侣后3天内不能再结道侣

# 共享功能配置
CULTIVATION_SPEED_BONUS = 0.20  # 道侣同时闭关时的修炼加速（20%）
CULTIVATION_SPEED_BONUS_MAX = 0.50  # 最大修炼加速（50%，高亲密度）

# 亲密度等级配置
INTIMACY_LEVELS = {
    1: {"min": 0, "max": 999, "title": "初识", "cultivation_bonus": 0.10},
    2: {"min": 1000, "max": 4999, "title": "相知", "cultivation_bonus": 0.20},
    3: {"min": 5000, "max": 14999, "title": "情深", "cultivation_bonus": 0.30},
    4: {"min": 15000, "max": 29999, "title": "心心相印", "cultivation_bonus": 0.40},
    5: {"min": 30000, "max": 999999999, "title": "道侣双成", "cultivation_bonus": 0.50},
}


class DualCultivationManager:
    """道侣系统管理器"""
    
    def __init__(self, db: DataBase):
        self.db = db
        self.storage_ring_mgr = None
        self.pill_mgr = None
    
    def set_dependencies(self, storage_ring_mgr: "StorageRingManager", pill_mgr: "PillManager" = None):
        """设置依赖的管理器"""
        self.storage_ring_mgr = storage_ring_mgr
        self.pill_mgr = pill_mgr
    
    # ==================== 数据库操作 ====================
    
    async def ensure_partner_tables(self):
        """确保道侣系统相关表存在"""
        # 道侣请求表
        await self.db.conn.execute("""
            CREATE TABLE IF NOT EXISTS partner_requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                from_id TEXT NOT NULL,
                from_name TEXT NOT NULL,
                target_id TEXT NOT NULL,
                created_at INTEGER NOT NULL,
                expires_at INTEGER NOT NULL
            )
        """)
        
        # 双修冷却表
        await self.db.conn.execute("""
            CREATE TABLE IF NOT EXISTS dual_cultivation (
                user_id TEXT PRIMARY KEY,
                last_dual_time INTEGER NOT NULL
            )
        """)
        
        # 双修请求表
        await self.db.conn.execute("""
            CREATE TABLE IF NOT EXISTS dual_cultivation_requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                from_id TEXT NOT NULL,
                from_name TEXT NOT NULL,
                target_id TEXT NOT NULL,
                created_at INTEGER NOT NULL,
                expires_at INTEGER NOT NULL
            )
        """)
        
        # 解除道侣冷却表
        await self.db.conn.execute("""
            CREATE TABLE IF NOT EXISTS partner_breakup_cooldown (
                user_id TEXT PRIMARY KEY,
                breakup_time INTEGER NOT NULL
            )
        """)
        
        await self.db.conn.commit()
    
    async def _create_partner_request(self, from_id: str, from_name: str, target_id: str) -> int:
        """创建道侣请求"""
        now = int(time.time())
        expires_at = now + PARTNER_REQUEST_EXPIRE
        
        await self.db.conn.execute(
            "DELETE FROM partner_requests WHERE target_id = ?",
            (target_id,)
        )
        
        await self.db.conn.execute(
            """
            INSERT INTO partner_requests (from_id, from_name, target_id, created_at, expires_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (from_id, from_name, target_id, now, expires_at)
        )
        await self.db.conn.commit()
        
        async with self.db.conn.execute("SELECT last_insert_rowid()") as cursor:
            row = await cursor.fetchone()
            return row[0] if row else 0
    
    async def _get_pending_partner_request(self, target_id: str) -> Optional[PartnerRequest]:
        """获取待处理的道侣请求"""
        now = int(time.time())
        
        await self.db.conn.execute(
            "DELETE FROM partner_requests WHERE expires_at < ?",
            (now,)
        )
        await self.db.conn.commit()
        
        async with self.db.conn.execute(
            """
            SELECT id, from_id, from_name, target_id, created_at, expires_at
            FROM partner_requests
            WHERE target_id = ? AND expires_at > ?
            ORDER BY created_at DESC LIMIT 1
            """,
            (target_id, now)
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                return PartnerRequest(
                    id=row[0],
                    from_id=row[1],
                    from_name=row[2],
                    target_id=row[3],
                    created_at=row[4],
                    expires_at=row[5]
                )
            return None
    
    async def _delete_partner_request(self, request_id: int):
        """删除道侣请求"""
        await self.db.conn.execute(
            "DELETE FROM partner_requests WHERE id = ?",
            (request_id,)
        )
        await self.db.conn.commit()
    
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
    
    async def _get_breakup_cooldown(self, user_id: str) -> Optional[int]:
        """获取解除道侣冷却时间"""
        async with self.db.conn.execute(
            "SELECT breakup_time FROM partner_breakup_cooldown WHERE user_id = ?",
            (user_id,)
        ) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else None
    
    async def _set_breakup_cooldown(self, user_id: str, timestamp: int):
        """设置解除道侣冷却"""
        await self.db.conn.execute(
            """
            INSERT INTO partner_breakup_cooldown (user_id, breakup_time)
            VALUES (?, ?)
            ON CONFLICT(user_id) DO UPDATE SET breakup_time = excluded.breakup_time
            """,
            (user_id, timestamp)
        )
        await self.db.conn.commit()
    
    async def _clear_breakup_cooldown(self, user_id: str):
        """清除解除道侣冷却"""
        await self.db.conn.execute(
            "DELETE FROM partner_breakup_cooldown WHERE user_id = ?",
            (user_id,)
        )
        await self.db.conn.commit()
    
    # ==================== 辅助方法 ====================
    
    def _get_intimacy_level(self, intimacy: int) -> int:
        """获取亲密度等级"""
        if intimacy >= 30000:
            return 5
        elif intimacy >= 15000:
            return 4
        elif intimacy >= 5000:
            return 3
        elif intimacy >= 1000:
            return 2
        else:
            return 1
    
    def _get_cultivation_bonus(self, intimacy: int) -> float:
        """获取修炼加速比例"""
        level = self._get_intimacy_level(intimacy)
        return INTIMACY_LEVELS[level]["cultivation_bonus"]
    
    # ==================== 道侣关系管理 ====================
    
    async def send_partner_request(self, initiator: Player, target_id: str) -> Tuple[bool, str]:
        """发起道侣请求"""
        if initiator.user_id == target_id:
            return False, "❌ 不能与自己结为道侣。"
        
        if initiator.has_partner():
            return False, "❌ 你已有道侣，请先解除当前道侣关系。"
        
        breakup_time = await self._get_breakup_cooldown(initiator.user_id)
        now = int(time.time())
        if breakup_time and (now - breakup_time) < BREAKUP_COOLDOWN:
            remaining_days = (BREAKUP_COOLDOWN - (now - breakup_time)) // 86400 + 1
            return False, f"❌ 你刚解除道侣关系，需等待 {remaining_days} 天后才能再结道侣。"
        
        target = await self.db.get_player_by_id(target_id)
        if not target:
            return False, "❌ 对方还未踏入修仙之路。"
        
        if target.has_partner():
            return False, "❌ 对方已有道侣。"
        
        target_breakup_time = await self._get_breakup_cooldown(target_id)
        if target_breakup_time and (now - target_breakup_time) < BREAKUP_COOLDOWN:
            return False, "❌ 对方刚解除道侣关系，暂时无法结为道侣。"
        
        await self._create_partner_request(
            initiator.user_id,
            initiator.user_name or initiator.user_id[:8],
            target_id
        )
        
        target_name = target.user_name or target_id[:8]
        return True, (
            f"💕 已向【{target_name}】发起道侣请求！\n"
            f"━━━━━━━━━━━━━━━\n"
            f"对方使用「接受道侣」或「拒绝道侣」响应\n"
            f"请求将在5分钟后过期\n"
            f"━━━━━━━━━━━━━━━\n"
            f"💡 道侣共享功能：\n"
            f"• 共享储物戒 - 可取用对方物品\n"
            f"• 共享丹药 - 可使用对方丹药\n"
            f"• 共享灵石 - 灵石合并使用\n"
            f"• 修炼加速 - 同时闭关加速修炼"
        )
    
    async def accept_partner_request(self, acceptor: Player) -> Tuple[bool, str]:
        """接受道侣请求"""
        if acceptor.has_partner():
            return False, "❌ 你已有道侣，无法接受新的道侣请求。"
        
        request = await self._get_pending_partner_request(acceptor.user_id)
        if not request:
            return False, "❌ 没有待处理的道侣请求。"
        
        initiator = await self.db.get_player_by_id(request.from_id)
        if not initiator:
            await self._delete_partner_request(request.id)
            return False, "❌ 请求发起者数据异常。"
        
        if initiator.has_partner():
            await self._delete_partner_request(request.id)
            return False, "❌ 对方已与他人结为道侣。"
        
        now = int(time.time())
        
        initiator.partner_id = acceptor.user_id
        initiator.partner_bindtime = now
        initiator.partner_intimacy = 0
        
        acceptor.partner_id = initiator.user_id
        acceptor.partner_bindtime = now
        acceptor.partner_intimacy = 0
        
        await self.db.update_player(initiator)
        await self.db.update_player(acceptor)
        
        await self._clear_breakup_cooldown(initiator.user_id)
        await self._clear_breakup_cooldown(acceptor.user_id)
        
        await self._delete_partner_request(request.id)
        
        initiator_name = initiator.user_name or initiator.user_id[:8]
        acceptor_name = acceptor.user_name or acceptor.user_id[:8]
        
        # 计算共享灵石
        total_gold = initiator.gold + acceptor.gold
        
        return True, (
            f"💕 恭喜结为道侣！\n"
            f"━━━━━━━━━━━━━━━\n"
            f"【{initiator_name}】 ❤️ 【{acceptor_name}】\n"
            f"━━━━━━━━━━━━━━━\n"
            f"当前亲密度：0（初识）\n"
            f"共享灵石：{total_gold:,}\n"
            f"修炼加速：+10%\n"
            f"━━━━━━━━━━━━━━━\n"
            f"已解锁功能：\n"
            f"  📦 共享储物戒\n"
            f"  💊 共享丹药背包\n"
            f"  💰 共享灵石\n"
            f"  ⚡ 修炼加速\n"
            f"━━━━━━━━━━━━━━━\n"
            f"💡 使用「道侣双修」提升亲密度\n"
            f"💡 使用「道侣信息」查看详情"
        )
    
    async def reject_partner_request(self, rejecter_id: str) -> Tuple[bool, str]:
        """拒绝道侣请求"""
        request = await self._get_pending_partner_request(rejecter_id)
        if not request:
            return False, "❌ 没有待处理的道侣请求。"
        
        from_name = request.from_name
        await self._delete_partner_request(request.id)
        
        return True, f"已拒绝【{from_name}】的道侣请求。"
    
    async def break_up(self, player: Player, confirm: bool = False) -> Tuple[bool, str]:
        """解除道侣关系"""
        if not player.has_partner():
            return False, "❌ 你当前没有道侣。"
        
        if not confirm:
            partner = await self.db.get_player_by_id(player.partner_id)
            partner_name = partner.user_name if partner else "未知"
            return False, (
                f"⚠️ 确定要与【{partner_name}】解除道侣关系吗？\n"
                f"━━━━━━━━━━━━━━━\n"
                f"当前亲密度：{player.partner_intimacy}\n"
                f"解除后：\n"
                f"• 亲密度将清零\n"
                f"• 3天内无法再结道侣\n"
                f"• 共享功能将失效\n"
                f"━━━━━━━━━━━━━━━\n"
                f"💡 使用「解除道侣 确认」确认解除"
            )
        
        partner = await self.db.get_player_by_id(player.partner_id)
        now = int(time.time())
        
        player.partner_id = ""
        player.partner_bindtime = 0
        player.partner_intimacy = 0
        await self.db.update_player(player)
        await self._set_breakup_cooldown(player.user_id, now)
        
        if partner:
            partner.partner_id = ""
            partner.partner_bindtime = 0
            partner.partner_intimacy = 0
            await self.db.update_player(partner)
            await self._set_breakup_cooldown(partner.user_id, now)
            partner_name = partner.user_name or partner.user_id[:8]
        else:
            partner_name = "未知"
        
        return True, (
            f"💔 已与【{partner_name}】解除道侣关系\n"
            f"━━━━━━━━━━━━━━━\n"
            f"3天内无法再结道侣"
        )
    
    # ==================== 道侣双修 ====================
    
    async def dual_cultivate(self, player: Player) -> Tuple[bool, str]:
        """道侣双修"""
        if not player.has_partner():
            return False, "❌ 你当前没有道侣，无法进行道侣双修。"
        
        now = int(time.time())
        last_dual = await self._get_last_dual_time(player.user_id)
        if last_dual and (now - last_dual) < DUAL_CULT_COOLDOWN:
            remaining = DUAL_CULT_COOLDOWN - (now - last_dual)
            return False, f"❌ 双修冷却中，还需 {remaining // 60} 分钟。"
        
        partner = await self.db.get_player_by_id(player.partner_id)
        if not partner:
            return False, "❌ 道侣数据异常。"
        
        partner_last_dual = await self._get_last_dual_time(partner.user_id)
        if partner_last_dual and (now - partner_last_dual) < DUAL_CULT_COOLDOWN:
            remaining = DUAL_CULT_COOLDOWN - (now - partner_last_dual)
            return False, f"❌ 道侣双修冷却中，还需 {remaining // 60} 分钟。"
        
        # 计算双修收益
        player_exp_gain = int(partner.experience * DUAL_CULT_BASE_EXP_BONUS)
        partner_exp_gain = int(player.experience * DUAL_CULT_BASE_EXP_BONUS)
        
        player.experience += player_exp_gain
        partner.experience += partner_exp_gain
        
        old_level = self._get_intimacy_level(player.partner_intimacy)
        player.partner_intimacy += DUAL_CULT_INTIMACY_GAIN
        partner.partner_intimacy += DUAL_CULT_INTIMACY_GAIN
        new_level = self._get_intimacy_level(player.partner_intimacy)
        
        await self.db.update_player(player)
        await self.db.update_player(partner)
        
        await self._set_last_dual_time(player.user_id, now)
        await self._set_last_dual_time(partner.user_id, now)
        
        partner_name = partner.user_name or partner.user_id[:8]
        
        result = (
            f"💕 道侣双修成功！\n"
            f"━━━━━━━━━━━━━━━\n"
            f"与【{partner_name}】双修\n"
            f"━━━━━━━━━━━━━━━\n"
            f"你 获得修为：+{player_exp_gain:,}\n"
            f"{partner_name} 获得修为：+{partner_exp_gain:,}\n"
            f"亲密度：+{DUAL_CULT_INTIMACY_GAIN}\n"
            f"━━━━━━━━━━━━━━━\n"
            f"当前亲密度：{player.partner_intimacy}\n"
            f"下次双修：1小时后"
        )
        
        if new_level > old_level:
            level_info = INTIMACY_LEVELS[new_level]
            result += (
                f"\n\n🎉 亲密度提升至【{level_info['title']}】！\n"
                f"修炼加速提升至：+{level_info['cultivation_bonus']:.0%}"
            )
        
        return True, result
    
    # ==================== 共享灵石 ====================
    
    async def get_shared_gold(self, player: Player) -> Tuple[bool, str, int]:
        """获取共享灵石信息
        
        Returns:
            (成功, 消息, 总灵石)
        """
        if not player.has_partner():
            return True, (
                f"💰 你的灵石：{player.gold:,}\n"
                f"━━━━━━━━━━━━━━━\n"
                f"💡 结为道侣后可共享灵石"
            ), player.gold
        
        partner = await self.db.get_player_by_id(player.partner_id)
        if not partner:
            return False, "❌ 道侣数据异常。", 0
        
        partner_name = partner.user_name or partner.user_id[:8]
        total_gold = player.gold + partner.gold
        
        return True, (
            f"💰 共享灵石\n"
            f"━━━━━━━━━━━━━━━\n"
            f"你的灵石：{player.gold:,}\n"
            f"{partner_name}的灵石：{partner.gold:,}\n"
            f"━━━━━━━━━━━━━━━\n"
            f"共享总额：{total_gold:,}\n"
            f"━━━━━━━━━━━━━━━\n"
            f"💡 购买物品时会自动使用共享灵石"
        ), total_gold
    
    async def spend_shared_gold(self, player: Player, amount: int) -> Tuple[bool, str]:
        """消费共享灵石
        
        优先使用自己的灵石，不足时使用道侣的
        
        Returns:
            (成功, 消息)
        """
        if amount <= 0:
            return False, "❌ 金额必须大于0。"
        
        # 没有道侣，只能用自己的
        if not player.has_partner():
            if player.gold < amount:
                return False, f"❌ 灵石不足，需要 {amount:,}，当前拥有 {player.gold:,}。"
            player.gold -= amount
            await self.db.update_player(player)
            return True, ""
        
        partner = await self.db.get_player_by_id(player.partner_id)
        if not partner:
            # 道侣数据异常，只用自己的
            if player.gold < amount:
                return False, f"❌ 灵石不足，需要 {amount:,}，当前拥有 {player.gold:,}。"
            player.gold -= amount
            await self.db.update_player(player)
            return True, ""
        
        total_gold = player.gold + partner.gold
        if total_gold < amount:
            return False, f"❌ 共享灵石不足，需要 {amount:,}，共享总额 {total_gold:,}。"
        
        # 优先扣自己的
        if player.gold >= amount:
            player.gold -= amount
            await self.db.update_player(player)
        else:
            # 自己的不够，需要用道侣的
            remaining = amount - player.gold
            player.gold = 0
            partner.gold -= remaining
            await self.db.update_player(player)
            await self.db.update_player(partner)
        
        return True, ""
    
    async def check_shared_gold(self, player: Player, amount: int) -> Tuple[bool, int]:
        """检查共享灵石是否足够
        
        Returns:
            (是否足够, 共享总额)
        """
        if not player.has_partner():
            return player.gold >= amount, player.gold
        
        partner = await self.db.get_player_by_id(player.partner_id)
        if not partner:
            return player.gold >= amount, player.gold
        
        total_gold = player.gold + partner.gold
        return total_gold >= amount, total_gold
    
    # ==================== 共享储物戒 ====================
    
    async def get_partner_storage_ring(self, player: Player) -> Tuple[bool, str, Optional[Dict]]:
        """获取道侣的储物戒信息
        
        Returns:
            (成功, 消息, 物品字典)
        """
        if not player.has_partner():
            return False, "❌ 你当前没有道侣。", None
        
        partner = await self.db.get_player_by_id(player.partner_id)
        if not partner:
            return False, "❌ 道侣数据异常。", None
        
        partner_name = partner.user_name or partner.user_id[:8]
        items = partner.get_storage_ring_items()
        
        if not items:
            return True, (
                f"📦 {partner_name}的储物戒\n"
                f"━━━━━━━━━━━━━━━\n"
                f"储物戒：{partner.storage_ring}\n"
                f"物品：空\n"
                f"━━━━━━━━━━━━━━━\n"
                f"💡 道侣储物戒中没有物品"
            ), items
        
        # 构建物品列表 - 储物戒格式为 {item_name: count}
        item_lines = []
        for item_name, count in items.items():
            item_lines.append(f"  {item_name} x{count}")
        
        items_text = "\n".join(item_lines[:20])  # 最多显示20个
        if len(item_lines) > 20:
            items_text += f"\n  ...还有 {len(item_lines) - 20} 种物品"
        
        return True, (
            f"📦 {partner_name}的储物戒\n"
            f"━━━━━━━━━━━━━━━\n"
            f"储物戒：{partner.storage_ring}\n"
            f"物品数量：{len(items)} 种\n"
            f"━━━━━━━━━━━━━━━\n"
            f"{items_text}\n"
            f"━━━━━━━━━━━━━━━\n"
            f"💡 使用「道侣取出 物品名」取出物品"
        ), items
    
    async def take_from_partner_storage(self, player: Player, item_name: str, count: int = 1) -> Tuple[bool, str]:
        """从道侣储物戒取出物品（带事务保护）"""
        if not player.has_partner():
            return False, "❌ 你当前没有道侣。"
        
        if count <= 0:
            return False, "❌ 数量必须大于0。"
        
        player_id = player.user_id
        partner_id = player.partner_id
        
        # 使用事务保护
        await self.db.conn.execute("BEGIN IMMEDIATE")
        try:
            # 重新获取最新数据
            partner = await self.db.get_player_by_id(partner_id)
            if not partner:
                await self.db.conn.rollback()
                return False, "❌ 道侣数据异常。"
            
            current_player = await self.db.get_player_by_id(player_id)
            if not current_player:
                await self.db.conn.rollback()
                return False, "❌ 玩家数据异常。"
            
            partner_name = partner.user_name or partner.user_id[:8]
            partner_items = partner.get_storage_ring_items()
            
            if item_name not in partner_items:
                await self.db.conn.rollback()
                return False, f"❌ {partner_name}的储物戒中没有【{item_name}】。"
            
            # 储物戒格式为 {item_name: count}
            available_count = partner_items[item_name]
            
            if available_count < count:
                await self.db.conn.rollback()
                return False, f"❌ {partner_name}的储物戒中只有 {available_count} 个【{item_name}】。"
            
            # 检查自己的储物戒是否有空间
            my_items = current_player.get_storage_ring_items()
            if item_name not in my_items:
                # 需要新格子
                if self.storage_ring_mgr:
                    available_slots = self.storage_ring_mgr.get_available_slots(current_player)
                    if available_slots <= 0:
                        await self.db.conn.rollback()
                        capacity = self.storage_ring_mgr.get_ring_capacity(current_player.storage_ring)
                        return False, f"❌ 你的储物戒已满！({capacity}/{capacity}格)"
            
            # 从道侣储物戒移除
            if available_count == count:
                del partner_items[item_name]
            else:
                partner_items[item_name] = available_count - count
            partner.set_storage_ring_items(partner_items)
            
            # 添加到自己的储物戒
            my_items[item_name] = my_items.get(item_name, 0) + count
            current_player.set_storage_ring_items(my_items)
            
            # 更新两个玩家的数据
            await self.db.update_player(partner)
            await self.db.update_player(current_player)
            
            await self.db.conn.commit()
            
            return True, (
                f"✅ 成功从{partner_name}的储物戒取出\n"
                f"【{item_name}】x{count}"
            )
        except Exception:
            await self.db.conn.rollback()
            raise
    
    # ==================== 共享丹药背包 ====================
    
    async def get_partner_pills(self, player: Player) -> Tuple[bool, str, Optional[Dict]]:
        """获取道侣的丹药背包
        
        Returns:
            (成功, 消息, 丹药字典)
        """
        if not player.has_partner():
            return False, "❌ 你当前没有道侣。", None
        
        partner = await self.db.get_player_by_id(player.partner_id)
        if not partner:
            return False, "❌ 道侣数据异常。", None
        
        partner_name = partner.user_name or partner.user_id[:8]
        pills = partner.get_pills_inventory()
        
        if not pills:
            return True, (
                f"💊 {partner_name}的丹药背包\n"
                f"━━━━━━━━━━━━━━━\n"
                f"丹药：空\n"
                f"━━━━━━━━━━━━━━━\n"
                f"💡 道侣丹药背包中没有丹药"
            ), pills
        
        # 构建丹药列表
        pill_lines = []
        for pill_name, pill_count in pills.items():
            pill_lines.append(f"  {pill_name} x{pill_count}")
        
        pills_text = "\n".join(pill_lines[:15])
        if len(pill_lines) > 15:
            pills_text += f"\n  ...还有 {len(pill_lines) - 15} 种丹药"
        
        return True, (
            f"💊 {partner_name}的丹药背包\n"
            f"━━━━━━━━━━━━━━━\n"
            f"丹药种类：{len(pills)} 种\n"
            f"━━━━━━━━━━━━━━━\n"
            f"{pills_text}\n"
            f"━━━━━━━━━━━━━━━\n"
            f"💡 使用「道侣服用 丹药名」使用道侣的丹药"
        ), pills
    
    async def use_partner_pill(self, player: Player, pill_name: str) -> Tuple[bool, str]:
        """使用道侣的丹药（仅扣除丹药，不应用效果）
        
        注意：这里只是从道侣背包扣除丹药，返回丹药名称供调用方处理效果
        
        Returns:
            (成功, 丹药名称或错误消息)
        """
        if not player.has_partner():
            return False, "❌ 你当前没有道侣。"
        
        partner = await self.db.get_player_by_id(player.partner_id)
        if not partner:
            return False, "❌ 道侣数据异常。"
        
        partner_name = partner.user_name or partner.user_id[:8]
        pills = partner.get_pills_inventory()
        
        # 查找丹药（支持模糊匹配）
        found_pill_name = None
        for p_name in pills.keys():
            if pill_name in p_name or p_name in pill_name:
                found_pill_name = p_name
                break
        
        if not found_pill_name:
            return False, f"❌ {partner_name}的丹药背包中没有【{pill_name}】。"
        
        if pills[found_pill_name] <= 0:
            return False, f"❌ {partner_name}的【{found_pill_name}】已用完。"
        
        # 扣除丹药
        pills[found_pill_name] -= 1
        if pills[found_pill_name] <= 0:
            del pills[found_pill_name]
        partner.set_pills_inventory(pills)
        await self.db.update_player(partner)
        
        return True, found_pill_name  # 返回丹药名称，让调用方处理效果
    
    async def use_partner_pill_with_effect(self, player: Player, pill_name: str, pill_mgr: "PillManager") -> Tuple[bool, str]:
        """使用道侣的丹药并应用效果
        
        这是一个完整的方法，会从道侣背包扣除丹药并应用效果到玩家身上
        
        Args:
            player: 使用丹药的玩家
            pill_name: 丹药名称
            pill_mgr: 丹药管理器
            
        Returns:
            (成功, 消息)
        """
        if not player.has_partner():
            return False, "❌ 你当前没有道侣。"
        
        if not pill_mgr:
            return False, "❌ 丹药系统暂不可用。"
        
        player_id = player.user_id
        partner_id = player.partner_id
        
        partner = await self.db.get_player_by_id(partner_id)
        if not partner:
            return False, "❌ 道侣数据异常。"
        
        partner_name = partner.user_name or partner.user_id[:8]
        pills = partner.get_pills_inventory()
        
        # 查找丹药（支持模糊匹配）
        found_pill_name = None
        for p_name in pills.keys():
            if pill_name == p_name:
                # 精确匹配优先
                found_pill_name = p_name
                break
            elif pill_name in p_name or p_name in pill_name:
                found_pill_name = p_name
        
        if not found_pill_name:
            return False, f"❌ {partner_name}的丹药背包中没有【{pill_name}】。"
        
        if pills[found_pill_name] <= 0:
            return False, f"❌ {partner_name}的【{found_pill_name}】已用完。"
        
        # 获取丹药配置
        pill_data = pill_mgr.get_pill_by_name(found_pill_name)
        if not pill_data:
            return False, f"❌ 丹药【{found_pill_name}】配置不存在！"
        
        # 检查境界需求
        required_level = pill_data.get("required_level_index", 0)
        if player.level_index < required_level:
            level_data = pill_mgr.config_manager.get_level_data(player.cultivation_type)
            level_name = f"境界{required_level}"
            if level_data and 0 <= required_level < len(level_data):
                level_name = level_data[required_level]["level_name"]
            return False, (
                f"境界不足！使用【{found_pill_name}】需要达到【{level_name}】"
            )
        
        # 使用事务保护整个操作
        await self.db.conn.execute("BEGIN IMMEDIATE")
        try:
            # 重新获取最新数据
            partner = await self.db.get_player_by_id(partner_id)
            current_player = await self.db.get_player_by_id(player_id)
            
            if not partner or not current_player:
                await self.db.conn.rollback()
                return False, "❌ 数据异常。"
            
            pills = partner.get_pills_inventory()
            if found_pill_name not in pills or pills[found_pill_name] <= 0:
                await self.db.conn.rollback()
                return False, f"❌ {partner_name}的【{found_pill_name}】已用完。"
            
            # 扣除道侣的丹药
            pills[found_pill_name] -= 1
            if pills[found_pill_name] <= 0:
                del pills[found_pill_name]
            partner.set_pills_inventory(pills)
            await self.db.update_player(partner)
            
            # 临时添加丹药到玩家背包（use_pill 会自动扣除）
            player_pills = current_player.get_pills_inventory()
            player_pills[found_pill_name] = player_pills.get(found_pill_name, 0) + 1
            current_player.set_pills_inventory(player_pills)
            await self.db.update_player(current_player)
            
            await self.db.conn.commit()
        except Exception as e:
            await self.db.conn.rollback()
            return False, f"❌ 操作失败：{str(e)}"
        
        # 重新获取玩家数据用于 use_pill
        current_player = await self.db.get_player_by_id(player_id)
        if not current_player:
            return False, "❌ 玩家数据异常。"
        
        # 调用 use_pill 方法应用效果（这会自动扣除玩家背包中的丹药）
        effect_success, effect_msg = await pill_mgr.use_pill(current_player, found_pill_name)
        
        if effect_success:
            return True, (
                f"✅ 成功使用道侣的【{found_pill_name}】\n"
                f"━━━━━━━━━━━━━━━\n"
                f"{effect_msg}"
            )
        else:
            # 使用失败，需要恢复道侣的丹药
            # 注意：玩家背包中的丹药可能已被 use_pill 扣除或未扣除，需要检查
            await self.db.conn.execute("BEGIN IMMEDIATE")
            try:
                partner = await self.db.get_player_by_id(partner_id)
                current_player = await self.db.get_player_by_id(player_id)
                
                if partner:
                    # 恢复道侣的丹药
                    pills = partner.get_pills_inventory()
                    pills[found_pill_name] = pills.get(found_pill_name, 0) + 1
                    partner.set_pills_inventory(pills)
                    await self.db.update_player(partner)
                
                # 检查玩家背包中是否还有该丹药（如果有说明 use_pill 没有扣除）
                if current_player:
                    player_pills = current_player.get_pills_inventory()
                    if found_pill_name in player_pills and player_pills[found_pill_name] > 0:
                        # 移除临时添加的丹药
                        player_pills[found_pill_name] -= 1
                        if player_pills[found_pill_name] <= 0:
                            del player_pills[found_pill_name]
                        current_player.set_pills_inventory(player_pills)
                        await self.db.update_player(current_player)
                
                await self.db.conn.commit()
            except Exception:
                await self.db.conn.rollback()
                # 回滚失败也要返回原始错误信息
            
            return False, (
                f"⚠️ 使用道侣的【{found_pill_name}】失败\n"
                f"━━━━━━━━━━━━━━━\n"
                f"{effect_msg}"
            )
    
    # ==================== 修炼加速 ====================
    
    async def get_cultivation_speed_bonus(self, player: Player) -> float:
        """获取修炼加速比例
        
        当道侣同时闭关时，根据亲密度获得修炼加速
        
        Returns:
            加速比例（0.0 ~ 0.5）
        """
        if not player.has_partner():
            return 0.0
        
        partner = await self.db.get_player_by_id(player.partner_id)
        if not partner:
            return 0.0
        
        # 检查道侣是否也在闭关
        if partner.cultivation_start_time <= 0:
            return 0.0
        
        # 根据亲密度计算加速
        return self._get_cultivation_bonus(player.partner_intimacy)
    
    async def check_partner_cultivating(self, player: Player) -> Tuple[bool, str, float]:
        """检查道侣是否在闭关，返回加速信息
        
        Returns:
            (道侣是否在闭关, 消息, 加速比例)
        """
        if not player.has_partner():
            return False, "", 0.0
        
        partner = await self.db.get_player_by_id(player.partner_id)
        if not partner:
            return False, "", 0.0
        
        partner_name = partner.user_name or partner.user_id[:8]
        
        if partner.cultivation_start_time > 0:
            bonus = self._get_cultivation_bonus(player.partner_intimacy)
            return True, (
                f"\n💕 道侣【{partner_name}】也在闭关中\n"
                f"修炼速度提升：+{bonus:.0%}"
            ), bonus
        
        return False, "", 0.0
    
    # ==================== 道侣信息 ====================
    
    async def get_partner_info(self, player: Player) -> Tuple[bool, str]:
        """获取道侣信息"""
        if not player.has_partner():
            return True, (
                "💕 道侣系统\n"
                "━━━━━━━━━━━━━━━\n"
                "你当前没有道侣\n"
                "━━━━━━━━━━━━━━━\n"
                "💡 使用「求道侣 @某人」发起请求\n"
                "\n"
                "道侣共享功能：\n"
                "• 共享储物戒 - 可取用对方物品\n"
                "• 共享丹药 - 可使用对方丹药\n"
                "• 共享灵石 - 灵石合并使用\n"
                "• 修炼加速 - 同时闭关加速修炼"
            )
        
        partner = await self.db.get_player_by_id(player.partner_id)
        if not partner:
            return False, "❌ 道侣数据异常。"
        
        partner_name = partner.user_name or partner.user_id[:8]
        bind_time = time.strftime("%Y-%m-%d", time.localtime(player.partner_bindtime))
        days_together = (int(time.time()) - player.partner_bindtime) // 86400
        
        level = self._get_intimacy_level(player.partner_intimacy)
        level_info = INTIMACY_LEVELS[level]
        
        # 计算到下一级需要的亲密度
        if level < 5:
            next_level_info = INTIMACY_LEVELS[level + 1]
            intimacy_to_next = next_level_info["min"] - player.partner_intimacy
            progress_text = f"距下一级：{intimacy_to_next}"
        else:
            progress_text = "已达最高等级"
        
        # 共享灵石
        total_gold = player.gold + partner.gold
        
        # 道侣状态
        if partner.cultivation_start_time > 0:
            partner_status = "闭关中 ⚡"
        else:
            partner_status = partner.state
        
        return True, (
            f"💕 道侣信息\n"
            f"━━━━━━━━━━━━━━━\n"
            f"道侣：【{partner_name}】\n"
            f"状态：{partner_status}\n"
            f"结缘日期：{bind_time}\n"
            f"相伴天数：{days_together} 天\n"
            f"━━━━━━━━━━━━━━━\n"
            f"亲密度：{player.partner_intimacy}\n"
            f"等级：{level_info['title']}（{level}/5）\n"
            f"{progress_text}\n"
            f"━━━━━━━━━━━━━━━\n"
            f"共享功能：\n"
            f"  💰 共享灵石：{total_gold:,}\n"
            f"  ⚡ 修炼加速：+{level_info['cultivation_bonus']:.0%}\n"
            f"━━━━━━━━━━━━━━━\n"
            f"💡 使用「道侣双修」提升亲密度\n"
            f"💡 使用「道侣储物戒」查看道侣物品\n"
            f"💡 使用「道侣丹药」查看道侣丹药"
        )
    
    # ==================== 普通双修（无道侣） ====================
    
    async def send_dual_request(self, initiator: Player, target_id: str) -> Tuple[bool, str]:
        """发起普通双修请求（无道侣关系）"""
        if initiator.user_id == target_id:
            return False, "❌ 不能与自己双修。"
        
        if initiator.has_partner():
            if initiator.partner_id == target_id:
                return False, "💡 你们已是道侣，请使用「道侣双修」指令。"
            return False, "❌ 你已有道侣，只能与道侣进行双修。"
        
        target = await self.db.get_player_by_id(target_id)
        if not target:
            return False, "❌ 对方还未踏入修仙之路。"
        
        if target.has_partner():
            return False, "❌ 对方已有道侣，无法与你双修。"
        
        now = int(time.time())
        last_dual = await self._get_last_dual_time(initiator.user_id)
        if last_dual and (now - last_dual) < DUAL_CULT_COOLDOWN:
            remaining = DUAL_CULT_COOLDOWN - (now - last_dual)
            return False, f"❌ 双修冷却中，还需 {remaining // 60} 分钟。"
        
        target_last_dual = await self._get_last_dual_time(target_id)
        if target_last_dual and (now - target_last_dual) < DUAL_CULT_COOLDOWN:
            remaining = DUAL_CULT_COOLDOWN - (now - target_last_dual)
            return False, f"❌ 对方正在双修冷却，还需 {remaining // 60} 分钟。"
        
        await self.db.conn.execute(
            "DELETE FROM dual_cultivation_requests WHERE target_id = ?",
            (target_id,)
        )
        
        expires_at = now + PARTNER_REQUEST_EXPIRE
        await self.db.conn.execute(
            """
            INSERT INTO dual_cultivation_requests (from_id, from_name, target_id, created_at, expires_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (initiator.user_id, initiator.user_name or initiator.user_id[:8], target_id, now, expires_at)
        )
        await self.db.conn.commit()
        
        target_name = target.user_name or target_id[:8]
        return True, (
            f"💕 已向【{target_name}】发起双修请求！\n"
            f"对方使用「接受双修」或「拒绝双修」响应。\n"
            f"请求将在5分钟后过期。\n"
            f"━━━━━━━━━━━━━━━\n"
            f"💡 结为道侣后可解锁共享功能哦~"
        )
    
    async def accept_dual_request(self, acceptor: Player) -> Tuple[bool, str]:
        """接受普通双修请求"""
        if acceptor.has_partner():
            return False, "❌ 你已有道侣，只能与道侣进行双修。"
        
        request = await self._get_pending_dual_request(acceptor.user_id)
        if not request:
            return False, "❌ 没有待处理的双修请求。"
        
        initiator = await self.db.get_player_by_id(request["from_id"])
        if not initiator:
            await self._delete_dual_request(request["id"])
            return False, "❌ 请求发起者数据异常。"
        
        if initiator.has_partner():
            await self._delete_dual_request(request["id"])
            return False, "❌ 对方已有道侣，无法与你双修。"
        
        now = int(time.time())
        
        acceptor_last_dual = await self._get_last_dual_time(acceptor.user_id)
        if acceptor_last_dual and (now - acceptor_last_dual) < DUAL_CULT_COOLDOWN:
            await self._delete_dual_request(request["id"])
            remaining = DUAL_CULT_COOLDOWN - (now - acceptor_last_dual)
            return False, f"❌ 你的双修冷却中，还需 {remaining // 60} 分钟。"
        
        initiator_last_dual = await self._get_last_dual_time(initiator.user_id)
        if initiator_last_dual and (now - initiator_last_dual) < DUAL_CULT_COOLDOWN:
            await self._delete_dual_request(request["id"])
            remaining = DUAL_CULT_COOLDOWN - (now - initiator_last_dual)
            return False, f"❌ 对方仍在双修冷却，还需 {remaining // 60} 分钟。"
        
        init_exp_gain = int(acceptor.experience * DUAL_CULT_BASE_EXP_BONUS)
        accept_exp_gain = int(initiator.experience * DUAL_CULT_BASE_EXP_BONUS)
        
        initiator.experience += init_exp_gain
        acceptor.experience += accept_exp_gain
        await self.db.update_player(initiator)
        await self.db.update_player(acceptor)
        
        await self._set_last_dual_time(initiator.user_id, now)
        await self._set_last_dual_time(acceptor.user_id, now)
        
        await self._delete_dual_request(request["id"])
        
        return True, (
            f"💕 双修成功！\n"
            f"━━━━━━━━━━━━━━━\n"
            f"与【{request['from_name']}】双修\n"
            f"{request['from_name']} 获得修为：+{init_exp_gain:,}\n"
            f"你 获得修为：+{accept_exp_gain:,}\n"
            f"━━━━━━━━━━━━━━━\n"
            f"下次双修：1小时后\n"
            f"💡 结为道侣后可解锁共享功能哦~"
        )
    
    async def reject_dual_request(self, rejecter_id: str) -> Tuple[bool, str]:
        """拒绝普通双修请求"""
        request = await self._get_pending_dual_request(rejecter_id)
        if not request:
            return False, "❌ 没有待处理的双修请求。"
        
        from_name = request["from_name"]
        await self._delete_dual_request(request["id"])
        
        return True, f"已拒绝【{from_name}】的双修请求。"
    
    async def _get_pending_dual_request(self, target_id: str) -> Optional[Dict]:
        """获取待处理的双修请求"""
        now = int(time.time())
        
        await self.db.conn.execute(
            "DELETE FROM dual_cultivation_requests WHERE expires_at < ?",
            (now,)
        )
        await self.db.conn.commit()
        
        async with self.db.conn.execute(
            """
            SELECT id, from_id, from_name, target_id, created_at, expires_at
            FROM dual_cultivation_requests
            WHERE target_id = ? AND expires_at > ?
            ORDER BY created_at DESC LIMIT 1
            """,
            (target_id, now)
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                return {
                    "id": row[0],
                    "from_id": row[1],
                    "from_name": row[2],
                    "target_id": row[3],
                    "created_at": row[4],
                    "expires_at": row[5]
                }
            return None
    
    async def _delete_dual_request(self, request_id: int):
        """删除双修请求"""
        await self.db.conn.execute(
            "DELETE FROM dual_cultivation_requests WHERE id = ?",
            (request_id,)
        )
        await self.db.conn.commit()
    
    # ==================== 兼容旧接口 ====================
    
    async def daily_intimacy_gain(self, player: Player) -> Tuple[bool, int]:
        """每日互动增加亲密度（签到时调用）"""
        if not player.has_partner():
            return False, 0
        
        partner = await self.db.get_player_by_id(player.partner_id)
        if not partner:
            return False, 0
        
        player.partner_intimacy += DAILY_INTIMACY_GAIN
        partner.partner_intimacy += DAILY_INTIMACY_GAIN
        
        await self.db.update_player(player)
        await self.db.update_player(partner)
        
        return True, DAILY_INTIMACY_GAIN
    
    def get_cultivation_efficiency_bonus(self, player: Player) -> float:
        """获取道侣带来的闭关效率加成 - 同步版本，用于兼容"""
        if not player.has_partner():
            return 0.0
        return self._get_cultivation_bonus(player.partner_intimacy)
    
    def get_combat_stats_bonus(self, player: Player) -> float:
        """获取道侣带来的战斗属性加成 - 移除"""
        return 0.0
