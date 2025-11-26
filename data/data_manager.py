# data/data_manager.py

import aiosqlite
import json
from pathlib import Path
from typing import Tuple, List
from ..models import Player

class DataBase:
    """数据库管理类，提供基础玩家操作"""

    def __init__(self, db_file: str = "xiuxian_data_lite.db"):
        self.db_path = Path(db_file)
        self.conn: aiosqlite.Connection = None

    async def connect(self):
        """连接数据库"""
        self.conn = await aiosqlite.connect(self.db_path)
        self.conn.row_factory = aiosqlite.Row

    async def close(self):
        """关闭数据库连接"""
        if self.conn:
            await self.conn.close()

    async def create_player(self, player: Player):
        """创建新玩家"""
        await self.conn.execute(
            """
            INSERT INTO players (
                user_id, level_index, spiritual_root, cultivation_type, lifespan,
                experience, gold, state, cultivation_start_time, last_check_in_date,
                spiritual_qi, max_spiritual_qi, magic_damage, physical_damage,
                magic_defense, physical_defense, mental_power,
                weapon, armor, main_technique, techniques,
                active_pill_effects, permanent_pill_gains, has_resurrection_pill, has_debuff_shield, pills_inventory
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                player.user_id,
                player.level_index,
                player.spiritual_root,
                player.cultivation_type,
                player.lifespan,
                player.experience,
                player.gold,
                player.state,
                player.cultivation_start_time,
                player.last_check_in_date,
                player.spiritual_qi,
                player.max_spiritual_qi,
                player.magic_damage,
                player.physical_damage,
                player.magic_defense,
                player.physical_defense,
                player.mental_power,
                player.weapon,
                player.armor,
                player.main_technique,
                player.techniques,
                player.active_pill_effects,
                player.permanent_pill_gains,
                player.has_resurrection_pill,
                int(player.has_debuff_shield),
                player.pills_inventory
            )
        )
        await self.conn.commit()

    async def get_player_by_id(self, user_id: str) -> Player:
        """根据用户ID获取玩家信息"""
        async with self.conn.execute(
            "SELECT * FROM players WHERE user_id = ?",
            (user_id,)
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                return Player(**dict(row))
            return None

    async def update_player(self, player: Player):
        """更新玩家信息"""
        await self.conn.execute(
            """
            UPDATE players SET
                level_index = ?,
                spiritual_root = ?,
                cultivation_type = ?,
                lifespan = ?,
                experience = ?,
                gold = ?,
                state = ?,
                cultivation_start_time = ?,
                last_check_in_date = ?,
                spiritual_qi = ?,
                max_spiritual_qi = ?,
                magic_damage = ?,
                physical_damage = ?,
                magic_defense = ?,
                physical_defense = ?,
                mental_power = ?,
                weapon = ?,
                armor = ?,
                main_technique = ?,
                techniques = ?,
                active_pill_effects = ?,
                permanent_pill_gains = ?,
                has_resurrection_pill = ?,
                has_debuff_shield = ?,
                pills_inventory = ?
            WHERE user_id = ?
            """,
            (
                player.level_index,
                player.spiritual_root,
                player.cultivation_type,
                player.lifespan,
                player.experience,
                player.gold,
                player.state,
                player.cultivation_start_time,
                player.last_check_in_date,
                player.spiritual_qi,
                player.max_spiritual_qi,
                player.magic_damage,
                player.physical_damage,
                player.magic_defense,
                player.physical_defense,
                player.mental_power,
                player.weapon,
                player.armor,
                player.main_technique,
                player.techniques,
                player.active_pill_effects,
                player.permanent_pill_gains,
                player.has_resurrection_pill,
                int(player.has_debuff_shield),
                player.pills_inventory,
                player.user_id
            )
        )
        await self.conn.commit()

    async def delete_player(self, user_id: str):
        """删除玩家"""
        await self.conn.execute(
            "DELETE FROM players WHERE user_id = ?",
            (user_id,)
        )
        await self.conn.commit()

    async def get_all_players(self):
        """获取所有玩家"""
        async with self.conn.execute("SELECT * FROM players") as cursor:
            rows = await cursor.fetchall()
            return [Player(**dict(row)) for row in rows]

    # ========== 商店数据操作 ==========

    async def get_shop_data(self, shop_id: str = "global") -> Tuple[int, List[dict]]:
        """获取商店数据

        Args:
            shop_id: 商店ID，默认为全局商店

        Returns:
            (last_refresh_time, current_items) 元组
        """
        async with self.conn.execute(
            "SELECT last_refresh_time, current_items FROM shop WHERE shop_id = ?",
            (shop_id,)
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                last_refresh_time = row[0]
                try:
                    current_items = json.loads(row[1])
                except:
                    current_items = []
                return last_refresh_time, current_items
            return 0, []

    async def update_shop_data(self, shop_id: str, last_refresh_time: int, current_items: List[dict]):
        """更新商店数据

        Args:
            shop_id: 商店ID
            last_refresh_time: 最后刷新时间戳
            current_items: 当前商店物品列表
        """
        items_json = json.dumps(current_items, ensure_ascii=False)
        await self.conn.execute(
            """
            INSERT OR REPLACE INTO shop (shop_id, last_refresh_time, current_items)
            VALUES (?, ?, ?)
            """,
            (shop_id, last_refresh_time, items_json)
        )
        await self.conn.commit()

