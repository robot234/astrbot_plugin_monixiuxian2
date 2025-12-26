# data/data_manager.py

import aiosqlite
import json
from dataclasses import fields
from pathlib import Path
from typing import Tuple, List, Optional
from ..models import Player
from .database_extended import DatabaseExtended

# 获取 Player 模型的所有字段名（用于过滤数据库中的多余字段，作为迁移未完成时的兼容）
PLAYER_FIELDS = {f.name for f in fields(Player)}

class DataBase:
    """数据库管理类，提供基础玩家操作"""

    def __init__(self, db_file: str = "xiuxian_data_lite.db"):
        self.db_path = Path(db_file)
        self.conn: aiosqlite.Connection = None
        self.ext: Optional[DatabaseExtended] = None  # 扩展操作类

    async def connect(self):
        """连接数据库"""
        self.conn = await aiosqlite.connect(self.db_path)
        self.conn.row_factory = aiosqlite.Row
        self.ext = DatabaseExtended(self.conn)  # 初始化扩展操作

    async def close(self):
        """关闭数据库连接"""
        if self.conn:
            await self.conn.close()

    async def create_player(self, player: Player):
        """创建新玩家"""
        await self.conn.execute(
            """
            INSERT INTO players (
                user_id, level_index, spiritual_root,cultivation_type, user_name, lifespan,
                experience, gold, state, cultivation_start_time, last_check_in_date, level_up_rate,
                weapon, armor, main_technique, techniques,
                hp, mp, atk, atkpractice,
                spiritual_qi, max_spiritual_qi, blood_qi, max_blood_qi,
                magic_damage, physical_damage, magic_defense, physical_defense, mental_power,
                sect_id, sect_position, sect_contribution, sect_task, sect_elixir_get,
                blessed_spot_flag, blessed_spot_name,
                active_pill_effects, permanent_pill_gains, has_resurrection_pill, has_debuff_shield, pills_inventory,
                storage_ring, storage_ring_items,
                daily_pill_usage, last_daily_reset
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                player.user_id,
                player.level_index,
                player.spiritual_root,
                player.cultivation_type,
                player.user_name,
                player.lifespan,
                player.experience,
                player.gold,
                player.state,
                player.cultivation_start_time,
                player.last_check_in_date,
                player.level_up_rate,
                player.weapon,
                player.armor,
                player.main_technique,
                player.techniques,
                player.hp,
                player.mp,
                player.atk,
                player.atkpractice,
                player.spiritual_qi,
                player.max_spiritual_qi,
                player.blood_qi,
                player.max_blood_qi,
                player.magic_damage,
                player.physical_damage,
                player.magic_defense,
                player.physical_defense,
                player.mental_power,
                player.sect_id,
                player.sect_position,
                player.sect_contribution,
                player.sect_task,
                player.sect_elixir_get,
                player.blessed_spot_flag,
                player.blessed_spot_name,
                player.active_pill_effects,
                player.permanent_pill_gains,
                player.has_resurrection_pill,
                int(player.has_debuff_shield),
                player.pills_inventory,
                player.storage_ring,
                player.storage_ring_items,
                player.daily_pill_usage,
                player.last_daily_reset
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
                # 过滤掉 Player 模型中不存在的字段（兼容旧数据库/迁移未完成的情况）
                filtered_data = {k: v for k, v in dict(row).items() if k in PLAYER_FIELDS}
                return Player(**filtered_data)
            return None

    async def get_player_by_name(self, user_name: str) -> Player:
        """根据道号获取玩家信息"""
        async with self.conn.execute(
            "SELECT * FROM players WHERE user_name = ?",
            (user_name,)
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                filtered_data = {k: v for k, v in dict(row).items() if k in PLAYER_FIELDS}
                return Player(**filtered_data)
            return None

    async def update_player(self, player: Player):
        """更新玩家信息"""
        await self.conn.execute(
            """
            UPDATE players SET
                level_index = ?,
                spiritual_root = ?,
                cultivation_type = ?,
                user_name = ?,
                lifespan = ?,
                experience = ?,
                gold = ?,
                state = ?,
                cultivation_start_time = ?,
                last_check_in_date = ?,
                level_up_rate = ?,
                weapon = ?,
                armor = ?,
                main_technique = ?,
                techniques = ?,
                hp = ?,
                mp = ?,
                atk = ?,
                atkpractice = ?,
                spiritual_qi = ?,
                max_spiritual_qi = ?,
                blood_qi = ?,
                max_blood_qi = ?,
                magic_damage = ?,
                physical_damage = ?,
                magic_defense = ?,
                physical_defense = ?,
                mental_power = ?,
                sect_id = ?,
                sect_position = ?,
                sect_contribution = ?,
                sect_task = ?,
                sect_elixir_get = ?,
                blessed_spot_flag = ?,
                blessed_spot_name = ?,
                active_pill_effects = ?,
                permanent_pill_gains = ?,
                has_resurrection_pill = ?,
                has_debuff_shield = ?,
                pills_inventory = ?,
                storage_ring = ?,
                storage_ring_items = ?,
                daily_pill_usage = ?,
                last_daily_reset = ?
            WHERE user_id = ?
            """,
            (
                player.level_index,
                player.spiritual_root,
                player.cultivation_type,
                player.user_name,
                player.lifespan,
                player.experience,
                player.gold,
                player.state,
                player.cultivation_start_time,
                player.last_check_in_date,
                player.level_up_rate,
                player.weapon,
                player.armor,
                player.main_technique,
                player.techniques,
                player.hp,
                player.mp,
                player.atk,
                player.atkpractice,
                player.spiritual_qi,
                player.max_spiritual_qi,
                player.blood_qi,
                player.max_blood_qi,
                player.magic_damage,
                player.physical_damage,
                player.magic_defense,
                player.physical_defense,
                player.mental_power,
                player.sect_id,
                player.sect_position,
                player.sect_contribution,
                player.sect_task,
                player.sect_elixir_get,
                player.blessed_spot_flag,
                player.blessed_spot_name,
                player.active_pill_effects,
                player.permanent_pill_gains,
                player.has_resurrection_pill,
                int(player.has_debuff_shield),
                player.pills_inventory,
                player.storage_ring,
                player.storage_ring_items,
                player.daily_pill_usage,
                player.last_daily_reset,
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
            # 过滤掉 Player 模型中不存在的字段（兼容旧数据库/迁移未完成的情况）
            return [Player(**{k: v for k, v in dict(row).items() if k in PLAYER_FIELDS}) for row in rows]

    # ===== 商店数据操作 =====

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
                except json.JSONDecodeError:
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

    async def decrement_shop_item_stock(self, shop_id: str, item_name: str, quantity: int = 1) -> tuple[bool, int, int]:
        """尝试扣减指定商店物品的库存（原子操作，可批量）

        Args:
            shop_id: 商店ID
            item_name: 物品名称
            quantity: 扣减数量（默认1，最小1）

        Returns:
            (是否成功, last_refresh_time, 扣减后的库存数量)
        """
        # 防御性：至少扣减1
        quantity = max(1, int(quantity))
        await self.conn.execute("BEGIN IMMEDIATE")
        try:
            async with self.conn.execute(
                "SELECT last_refresh_time, current_items FROM shop WHERE shop_id = ?",
                (shop_id,)
            ) as cursor:
                row = await cursor.fetchone()

            if not row:
                await self.conn.rollback()
                return False, 0, 0

            last_refresh_time = row[0]
            try:
                current_items = json.loads(row[1])
            except json.JSONDecodeError:
                current_items = []

            target_index = -1
            for idx, item in enumerate(current_items):
                if item.get('name') == item_name:
                    target_index = idx
                    break

            if target_index == -1:
                await self.conn.rollback()
                return False, last_refresh_time, 0

            stock = current_items[target_index].get('stock', 0)
            if stock is None or stock <= 0:
                await self.conn.rollback()
                return False, last_refresh_time, max(stock or 0, 0)

            if stock < quantity:
                await self.conn.rollback()
                return False, last_refresh_time, stock

            new_stock = stock - quantity
            current_items[target_index]['stock'] = new_stock

            items_json = json.dumps(current_items, ensure_ascii=False)
            await self.conn.execute(
                "UPDATE shop SET current_items = ?, last_refresh_time = ? WHERE shop_id = ?",
                (items_json, last_refresh_time, shop_id)
            )
            await self.conn.commit()
            return True, last_refresh_time, new_stock
        except Exception:
            await self.conn.rollback()
            raise

    async def increment_shop_item_stock(self, shop_id: str, item_name: str, quantity: int = 1):
        """回滚库存（在购买失败时恢复库存），支持批量"""
        quantity = max(1, int(quantity))
        await self.conn.execute("BEGIN IMMEDIATE")
        try:
            async with self.conn.execute(
                "SELECT last_refresh_time, current_items FROM shop WHERE shop_id = ?",
                (shop_id,)
            ) as cursor:
                row = await cursor.fetchone()

            if not row:
                await self.conn.rollback()
                return

            last_refresh_time = row[0]
            try:
                current_items = json.loads(row[1])
            except json.JSONDecodeError:
                current_items = []

            for item in current_items:
                if item.get('name') == item_name:
                    current_stock = item.get('stock', 0) or 0
                    item['stock'] = current_stock + quantity
                    break

            items_json = json.dumps(current_items, ensure_ascii=False)
            await self.conn.execute(
                "UPDATE shop SET current_items = ?, last_refresh_time = ? WHERE shop_id = ?",
                (items_json, last_refresh_time, shop_id)
            )
            await self.conn.commit()
        except Exception:
            await self.conn.rollback()
            raise

