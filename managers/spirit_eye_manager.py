# managers/spirit_eye_manager.py
"""天地灵眼系统管理器"""
import time
import random
from typing import Tuple, Optional, Dict, List
from ..data import DataBase
from ..models import Player

__all__ = ["SpiritEyeManager"]

# 灵眼配置
SPIRIT_EYE_TYPES = {
    1: {"name": "下品灵眼", "exp_per_hour": 500, "spawn_rate": 50},
    2: {"name": "中品灵眼", "exp_per_hour": 2000, "spawn_rate": 30},
    3: {"name": "上品灵眼", "exp_per_hour": 8000, "spawn_rate": 15},
    4: {"name": "极品灵眼", "exp_per_hour": 30000, "spawn_rate": 5},
}


class SpiritEyeManager:
    """天地灵眼管理器"""
    
    def __init__(self, db: DataBase):
        self.db = db
    
    async def get_user_spirit_eye(self, user_id: str) -> Optional[Dict]:
        """获取用户占据的灵眼"""
        async with self.db.conn.execute(
            "SELECT * FROM spirit_eyes WHERE owner_id = ?",
            (user_id,)
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                return dict(row)
            return None
    
    async def get_available_spirit_eyes(self) -> List[Dict]:
        """获取所有无主的灵眼"""
        async with self.db.conn.execute(
            "SELECT * FROM spirit_eyes WHERE owner_id IS NULL OR owner_id = ''"
        ) as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]
    
    async def spawn_spirit_eye(self) -> Tuple[bool, str]:
        """生成新灵眼（定时调用）"""
        # 随机生成灵眼类型
        roll = random.randint(1, 100)
        eye_type = 1
        cumulative = 0
        for etype, config in SPIRIT_EYE_TYPES.items():
            cumulative += config["spawn_rate"]
            if roll <= cumulative:
                eye_type = etype
                break
        
        config = SPIRIT_EYE_TYPES[eye_type]
        
        await self.db.conn.execute(
            """
            INSERT INTO spirit_eyes (eye_type, eye_name, exp_per_hour, spawn_time)
            VALUES (?, ?, ?, ?)
            """,
            (eye_type, config["name"], config["exp_per_hour"], int(time.time()))
        )
        await self.db.conn.commit()
        
        return True, f"天地间出现了一处【{config['name']}】！速来抢占！"
    
    async def claim_spirit_eye(self, player: Player, eye_id: int) -> Tuple[bool, str]:
        """抢占灵眼（原子操作）"""
        await self.db.conn.execute("BEGIN IMMEDIATE")
        try:
            # 检查是否已有灵眼
            existing = await self.get_user_spirit_eye(player.user_id)
            if existing:
                await self.db.conn.rollback()
                return False, f"❌ 你已占据【{existing['eye_name']}】，无法再抢占。"
            
            # 获取目标灵眼（带锁）
            async with self.db.conn.execute(
                "SELECT * FROM spirit_eyes WHERE eye_id = ?",
                (eye_id,)
            ) as cursor:
                row = await cursor.fetchone()
                if not row:
                    await self.db.conn.rollback()
                    return False, "❌ 灵眼不存在。"
                eye = dict(row)
            
            # 检查是否有主
            if eye["owner_id"]:
                await self.db.conn.rollback()
                return False, f"❌ 此灵眼已被【{eye['owner_name'] or '某人'}】占据。"
            
            # 抢占
            now = int(time.time())
            await self.db.conn.execute(
                """UPDATE spirit_eyes SET owner_id = ?, owner_name = ?, claim_time = ?, last_collect_time = ?
                   WHERE eye_id = ? AND (owner_id IS NULL OR owner_id = '')""",
                (player.user_id, player.user_name or player.user_id[:8], now, now, eye_id)
            )
            
            # 检查是否真的抢占成功（防止并发）
            if self.db.conn.total_changes == 0:
                await self.db.conn.rollback()
                return False, "❌ 抢占失败，灵眼已被他人占据。"
            
            await self.db.conn.commit()
            return True, (
                f"✨ 成功抢占【{eye['eye_name']}】！\n"
                f"每小时可获得 {eye['exp_per_hour']:,} 修为！\n"
                f"使用 /灵眼收取 领取收益"
            )
        except Exception as e:
            await self.db.conn.rollback()
            raise
    
    async def collect_spirit_eye(self, player: Player) -> Tuple[bool, str]:
        """收取灵眼收益"""
        eye = await self.get_user_spirit_eye(player.user_id)
        if not eye:
            return False, "❌ 你还没有占据灵眼。"
        
        # 使用last_collect_time计算收益，如果没有则使用claim_time
        last_collect = eye.get("last_collect_time") or eye.get("claim_time", 0)
        now = int(time.time())
        hours_passed = (now - last_collect) / 3600
        
        if hours_passed < 1:
            remaining = int(3600 - (now - last_collect))
            return False, f"❌ 收取冷却中，还需 {remaining // 60} 分钟。"
        
        # 计算收益（最多24小时）
        hours = min(24, int(hours_passed))
        exp_income = eye["exp_per_hour"] * hours
        
        player.experience += exp_income
        await self.db.update_player(player)
        
        # 更新last_collect_time
        await self.db.conn.execute(
            "UPDATE spirit_eyes SET last_collect_time = ? WHERE owner_id = ?",
            (now, player.user_id)
        )
        await self.db.conn.commit()
        
        return True, (
            f"✅ 灵眼收取成功！\n"
            f"━━━━━━━━━━━━━━━\n"
            f"【{eye['eye_name']}】\n"
            f"累计时长：{hours} 小时\n"
            f"获得修为：+{exp_income:,}"
        )
    
    async def release_spirit_eye(self, user_id: str) -> Tuple[bool, str]:
        """释放灵眼"""
        eye = await self.get_user_spirit_eye(user_id)
        if not eye:
            return False, "❌ 你没有占据灵眼。"
        
        await self.db.conn.execute(
            """
            UPDATE spirit_eyes SET owner_id = NULL, owner_name = NULL, claim_time = NULL
            WHERE owner_id = ?
            """,
            (user_id,)
        )
        await self.db.conn.commit()
        
        return True, f"已释放【{eye['eye_name']}】。"
    
    async def get_spirit_eye_info(self, user_id: str) -> str:
        """获取灵眼信息"""
        my_eye = await self.get_user_spirit_eye(user_id)
        available = await self.get_available_spirit_eyes()
        
        lines = ["👁️ 天地灵眼", "━━━━━━━━━━━━━━━"]
        
        if my_eye:
            now = int(time.time())
            hours = (now - my_eye.get("claim_time", now)) / 3600
            pending = int(min(24, hours) * my_eye["exp_per_hour"])
            lines.append(f"【我的灵眼】{my_eye['eye_name']}")
            lines.append(f"每小时：+{my_eye['exp_per_hour']:,} 修为")
            lines.append(f"待收取：约 +{pending:,} 修为")
            lines.append("")
        
        if available:
            lines.append("【可抢占的灵眼】")
            for eye in available[:5]:
                lines.append(f"  [{eye['eye_id']}] {eye['eye_name']} (+{eye['exp_per_hour']}/时)")
            lines.append("")
            lines.append("💡 /抢占灵眼 <ID>")
        else:
            lines.append("当前没有无主灵眼。")
        
        return "\n".join(lines)
