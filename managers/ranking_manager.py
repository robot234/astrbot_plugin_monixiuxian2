# managers/ranking_manager.py
"""
排行榜系统管理器 - 处理各种排行榜逻辑
"""

import time
from typing import Tuple, List, TYPE_CHECKING, Optional
from ..data.data_manager import DataBase

if TYPE_CHECKING:
    from ..config_manager import ConfigManager
    from ..models import Player
    from ..core.battle_manager import BattleManager
    from ..core.equipment_manager import EquipmentManager
    from ..core.skill_manager import SkillManager

# 宗门职位映射（安全映射，防止索引越界）
POSITION_MAP = {
    0: "宗主",
    1: "长老",
    2: "亲传",
    3: "内门",
    4: "外门",
}

# 名称最大显示长度
MAX_NAME_LENGTH = 12

# 擂台战配置
ARENA_CHALLENGE_COOLDOWN = 600  # 挑战冷却时间（秒）：10分钟
ARENA_FAILED_CHALLENGE_COOLDOWN = 300  # 挑战失败冷却时间（秒）：5分钟（未上榜玩家）
ARENA_MAX_RANK = 10  # 排行榜最大显示人数
ARENA_INITIAL_PLAYERS = 10  # 初始按创建时间排名的玩家数

# 前十名称号（一眼能看出排名）
ARENA_TITLES = {
    1: "擂台·第一",
    2: "擂台·第二",
    3: "擂台·第三",
    4: "擂台·第四",
    5: "擂台·第五",
    6: "擂台·第六",
    7: "擂台·第七",
    8: "擂台·第八",
    9: "擂台·第九",
    10: "擂台·第十",
}


def _short_id(user_id) -> str:
    """安全获取短ID，防止非字符串类型报错"""
    if user_id is None:
        return "未知"
    return str(user_id)[:6]


def _safe_name(player: Optional["Player"], fallback_id) -> str:
    """安全获取玩家名称，带长度截断和特殊字符过滤"""
    if player and player.user_name:
        name = player.user_name
    else:
        name = f"道友{_short_id(fallback_id)}"
    
    # 过滤危险字符（@可能触发群通知）
    name = name.replace("@", "＠")
    # 截断过长名称
    if len(name) > MAX_NAME_LENGTH:
        name = name[:MAX_NAME_LENGTH] + "…"
    return name


class RankingManager:
    """排行榜系统管理器"""
    
    def __init__(
        self, 
        db: DataBase, 
        battle_mgr: "BattleManager", 
        config_manager: "ConfigManager",
        equipment_manager: "EquipmentManager",
        skill_manager: "SkillManager"
    ):
        self.db = db
        self.battle_mgr = battle_mgr
        self.config_manager = config_manager
        self.equipment_manager = equipment_manager
        self.skill_manager = skill_manager
        # 未上榜玩家的挑战冷却记录（内存缓存）
        self._failed_challenge_cooldowns: dict[str, int] = {}
    
    async def _ensure_db_connection(self):
        """确保数据库连接可用"""
        if self.db.conn is None:
            await self.db.connect()
    
    async def ensure_arena_tables(self):
        """确保擂台战相关表存在"""
        await self._ensure_db_connection()
        await self.db.conn.execute("""
            CREATE TABLE IF NOT EXISTS arena_ranking (
                user_id TEXT PRIMARY KEY,
                rank INTEGER NOT NULL,
                wins INTEGER DEFAULT 0,
                losses INTEGER DEFAULT 0,
                last_challenge_time INTEGER DEFAULT 0,
                created_at INTEGER DEFAULT 0
            )
        """)
        await self.db.conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_arena_rank ON arena_ranking(rank)
        """)
        await self.db.conn.commit()
    
    async def get_arena_rank(self, user_id: str) -> Optional[int]:
        """获取玩家的擂台排名"""
        await self._ensure_db_connection()
        cursor = await self.db.conn.execute(
            "SELECT rank FROM arena_ranking WHERE user_id = ?",
            (user_id,)
        )
        row = await cursor.fetchone()
        return row[0] if row else None
    
    async def get_arena_info(self, user_id: str) -> Optional[dict]:
        """获取玩家的擂台信息"""
        await self._ensure_db_connection()
        cursor = await self.db.conn.execute(
            "SELECT rank, wins, losses, last_challenge_time FROM arena_ranking WHERE user_id = ?",
            (user_id,)
        )
        row = await cursor.fetchone()
        if row:
            return {
                "rank": row[0],
                "wins": row[1],
                "losses": row[2],
                "last_challenge_time": row[3]
            }
        return None
    
    async def get_player_by_rank(self, rank: int) -> Optional[str]:
        """根据排名获取玩家ID"""
        await self._ensure_db_connection()
        cursor = await self.db.conn.execute(
            "SELECT user_id FROM arena_ranking WHERE rank = ?",
            (rank,)
        )
        row = await cursor.fetchone()
        return row[0] if row else None
    
    async def get_arena_ranking_list(self, limit: int = ARENA_MAX_RANK) -> List[dict]:
        """获取擂台排行榜列表"""
        await self._ensure_db_connection()
        cursor = await self.db.conn.execute(
            "SELECT user_id, rank, wins, losses FROM arena_ranking ORDER BY rank ASC LIMIT ?",
            (limit,)
        )
        rows = await cursor.fetchall()
        return [
            {"user_id": row[0], "rank": row[1], "wins": row[2], "losses": row[3]}
            for row in rows
        ]
    
    async def get_total_arena_players(self) -> int:
        """获取擂台总人数"""
        await self._ensure_db_connection()
        cursor = await self.db.conn.execute(
            "SELECT COUNT(*) FROM arena_ranking"
        )
        row = await cursor.fetchone()
        return row[0] if row else 0
    
    def _check_failed_challenge_cooldown(self, user_id: str) -> Tuple[bool, int]:
        """
        检查未上榜玩家的挑战失败冷却
        
        Returns:
            (是否在冷却中, 剩余冷却时间秒数)
        """
        current_time = int(time.time())
        last_failed_time = self._failed_challenge_cooldowns.get(user_id, 0)
        cooldown_remaining = ARENA_FAILED_CHALLENGE_COOLDOWN - (current_time - last_failed_time)
        if cooldown_remaining > 0:
            return True, cooldown_remaining
        return False, 0
    
    def _set_failed_challenge_cooldown(self, user_id: str):
        """设置未上榜玩家的挑战失败冷却"""
        self._failed_challenge_cooldowns[user_id] = int(time.time())
    
    def _clear_failed_challenge_cooldown(self, user_id: str):
        """清除未上榜玩家的挑战失败冷却（上榜后清除）"""
        if user_id in self._failed_challenge_cooldowns:
            del self._failed_challenge_cooldowns[user_id]
    
    async def initialize_arena_ranking(self) -> Tuple[bool, str]:
        """
        初始化擂台排名
        按玩家修为排序，前10名自动上榜
        """
        await self.ensure_arena_tables()
        
        # 检查是否已有排名数据
        total = await self.get_total_arena_players()
        if total > 0:
            return True, "擂台排名已存在"
        
        # 获取所有玩家
        all_players = await self.db.get_all_players()
        if not all_players:
            return False, "暂无玩家数据"
        
        # 按修为排序作为初始排名
        sorted_players = sorted(all_players, key=lambda p: p.experience, reverse=True)
        
        # 取前10名初始化
        initial_players = sorted_players[:ARENA_INITIAL_PLAYERS]
        current_time = int(time.time())
        
        for idx, player in enumerate(initial_players, 1):
            await self.db.conn.execute(
                """INSERT OR REPLACE INTO arena_ranking 
                   (user_id, rank, wins, losses, last_challenge_time, created_at)
                   VALUES (?, ?, 0, 0, 0, ?)""",
                (player.user_id, idx, current_time)
            )
        
        await self.db.conn.commit()
        return True, f"擂台排名初始化完成，共{len(initial_players)}名玩家上榜"
    
    async def join_arena(self, user_id: str) -> Tuple[bool, str]:
        """
        加入擂台（挑战最后一名上榜）
        新玩家需要击败当前最后一名才能上榜
        """
        await self.ensure_arena_tables()
        
        # 检查是否已在榜上
        current_rank = await self.get_arena_rank(user_id)
        if current_rank is not None:
            return False, f"你已在擂台排行榜第{current_rank}名，无需再次加入"
        
        # 获取当前榜上人数
        total = await self.get_total_arena_players()
        
        if total < ARENA_INITIAL_PLAYERS:
            # 榜上人数不足10人，直接加入到最后
            new_rank = total + 1
            current_time = int(time.time())
            await self.db.conn.execute(
                """INSERT INTO arena_ranking 
                   (user_id, rank, wins, losses, last_challenge_time, created_at)
                   VALUES (?, ?, 0, 0, 0, ?)""",
                (user_id, new_rank, current_time)
            )
            await self.db.conn.commit()
            # 清除可能存在的失败冷却
            self._clear_failed_challenge_cooldown(user_id)
            return True, f"✅ 成功加入擂台排行榜！当前排名：第{new_rank}名"
        
        # 需要挑战最后一名
        last_player_id = await self.get_player_by_rank(total)
        last_player = await self.db.get_player_by_id(last_player_id) if last_player_id else None
        last_name = _safe_name(last_player, last_player_id)
        return False, (
            f"❌ 擂台排行榜已满{total}人！\n"
            f"💡 请使用「战力挑战 @{last_name}」来争夺榜位"
        )
    
    async def challenge_arena(
        self, 
        challenger_id: str, 
        target_id: str
    ) -> Tuple[bool, str, Optional[dict]]:
        """
        擂台挑战
        
        Args:
            challenger_id: 挑战者ID
            target_id: 被挑战者ID
            
        Returns:
            (成功标志, 消息, 战斗结果)
        """
        await self.ensure_arena_tables()
        
        # 获取挑战者信息
        challenger = await self.db.get_player_by_id(challenger_id)
        if not challenger:
            return False, "❌ 你还没有开始修仙！", None
        
        # 获取被挑战者信息
        target = await self.db.get_player_by_id(target_id)
        if not target:
            return False, "❌ 对方还没有开始修仙！", None
        
        if challenger_id == target_id:
            return False, "❌ 不能挑战自己！", None
        
        # 获取双方擂台信息
        challenger_arena = await self.get_arena_info(challenger_id)
        target_arena = await self.get_arena_info(target_id)
        
        # 检查被挑战者是否在榜上
        if target_arena is None:
            return False, "❌ 对方不在擂台排行榜上！", None
        
        target_rank = target_arena["rank"]
        
        # 检查挑战者是否在榜上
        if challenger_arena is None:
            # 挑战者不在榜上，只能挑战最后一名
            total = await self.get_total_arena_players()
            if target_rank != total:
                last_player_id = await self.get_player_by_rank(total)
                last_player = await self.db.get_player_by_id(last_player_id) if last_player_id else None
                last_name = _safe_name(last_player, last_player_id)
                return False, (
                    f"❌ 你不在擂台排行榜上！\n"
                    f"💡 只能挑战最后一名【{last_name}】(第{total}名)来争夺榜位"
                ), None
            
            # 检查未上榜玩家的挑战失败冷却
            in_cooldown, cooldown_remaining = self._check_failed_challenge_cooldown(challenger_id)
            if in_cooldown:
                minutes = cooldown_remaining // 60
                seconds = cooldown_remaining % 60
                return False, f"❌ 挑战冷却中！剩余时间：{minutes}分{seconds}秒", None
        else:
            # 挑战者在榜上，只能挑战排名更高的
            challenger_rank = challenger_arena["rank"]
            if target_rank >= challenger_rank:
                return False, f"❌ 只能挑战排名比你高的对手！你当前排名：第{challenger_rank}名", None
            
            # 检查挑战冷却
            last_challenge = challenger_arena["last_challenge_time"]
            current_time = int(time.time())
            cooldown_remaining = ARENA_CHALLENGE_COOLDOWN - (current_time - last_challenge)
            if cooldown_remaining > 0:
                minutes = cooldown_remaining // 60
                seconds = cooldown_remaining % 60
                return False, f"❌ 挑战冷却中！剩余时间：{minutes}分{seconds}秒", None
        
        # 准备战斗
        challenger_stats = self.battle_mgr.prepare_combat_stats(
            challenger, self.equipment_manager, self.skill_manager
        )
        target_stats = self.battle_mgr.prepare_combat_stats(
            target, self.equipment_manager, self.skill_manager
        )
        
        # 执行战斗
        battle_result = self.battle_mgr.execute_battle(
            challenger_stats, target_stats, battle_type="arena"
        )
        
        challenger_name = _safe_name(challenger, challenger_id)
        target_name = _safe_name(target, target_id)
        current_time = int(time.time())
        
        # 处理战斗结果
        if battle_result["winner"] == challenger_id:
            # 挑战者胜利
            if challenger_arena is None:
                # 新玩家上榜，被挑战者被挤出
                # 将被挑战者的排名给挑战者
                await self.db.conn.execute(
                    """INSERT INTO arena_ranking 
                       (user_id, rank, wins, losses, last_challenge_time, created_at)
                       VALUES (?, ?, 1, 0, ?, ?)""",
                    (challenger_id, target_rank, current_time, current_time)
                )
                # 删除被挑战者
                await self.db.conn.execute(
                    "DELETE FROM arena_ranking WHERE user_id = ?",
                    (target_id,)
                )
                
                # 清除挑战者的失败冷却
                self._clear_failed_challenge_cooldown(challenger_id)
                
                # 获取新称号
                new_title = ARENA_TITLES.get(target_rank, "")
                title_msg = f"\n\n🏅 获得称号：【{new_title}】" if new_title else ""
                
                result_msg = (
                    f"🏆 擂台挑战胜利！\n"
                    f"━━━━━━━━━━━━━━━\n"
                    f"⚔️ {challenger_name} VS {target_name}\n"
                    f"━━━━━━━━━━━━━━━\n"
                    f"🎉 {challenger_name} 成功上榜！\n"
                    f"📊 当前排名：第{target_rank}名\n"
                    f"😢 {target_name} 被挤出排行榜{title_msg}"
                )
            else:
                # 交换排名
                challenger_rank = challenger_arena["rank"]
                await self.db.conn.execute(
                    "UPDATE arena_ranking SET rank = ?, wins = wins + 1, last_challenge_time = ? WHERE user_id = ?",
                    (target_rank, current_time, challenger_id)
                )
                await self.db.conn.execute(
                    "UPDATE arena_ranking SET rank = ?, losses = losses + 1 WHERE user_id = ?",
                    (challenger_rank, target_id)
                )
                
                # 获取新称号
                new_title = ARENA_TITLES.get(target_rank, "")
                old_title = ARENA_TITLES.get(challenger_rank, "")
                
                result_msg = (
                    f"🏆 擂台挑战胜利！\n"
                    f"━━━━━━━━━━━━━━━\n"
                    f"⚔️ {challenger_name} VS {target_name}\n"
                    f"━━━━━━━━━━━━━━━\n"
                    f"🎉 排名交换！\n"
                    f"📊 {challenger_name}：第{challenger_rank}名 → 第{target_rank}名\n"
                    f"📊 {target_name}：第{target_rank}名 → 第{challenger_rank}名"
                )
                
                # 检查是否进入前十，获得新称号
                if new_title and (not old_title or target_rank < challenger_rank):
                    result_msg += f"\n\n🏅 获得称号：【{new_title}】"
        else:
            # 挑战者失败
            if challenger_arena is not None:
                # 更新挑战时间和败场
                await self.db.conn.execute(
                    "UPDATE arena_ranking SET losses = losses + 1, last_challenge_time = ? WHERE user_id = ?",
                    (current_time, challenger_id)
                )
                # 被挑战者胜场+1
                await self.db.conn.execute(
                    "UPDATE arena_ranking SET wins = wins + 1 WHERE user_id = ?",
                    (target_id,)
                )
            else:
                # 挑战者不在榜上，设置失败冷却
                self._set_failed_challenge_cooldown(challenger_id)
                # 被挑战者胜场+1
                await self.db.conn.execute(
                    "UPDATE arena_ranking SET wins = wins + 1 WHERE user_id = ?",
                    (target_id,)
                )
            
            result_msg = (
                f"💔 擂台挑战失败！\n"
                f"━━━━━━━━━━━━━━━\n"
                f"⚔️ {challenger_name} VS {target_name}\n"
                f"━━━━━━━━━━━━━━━\n"
                f"😢 {target_name} 成功守擂！"
            )
        
        await self.db.conn.commit()
        
        # 添加战斗摘要
        battle_summary = self.battle_mgr.generate_battle_summary(battle_result)
        result_msg += f"\n\n{battle_summary}"
        
        return True, result_msg, battle_result
    
    async def get_player_arena_title(self, user_id: str) -> Optional[str]:
        """获取玩家的擂台称号（前十名）"""
        rank = await self.get_arena_rank(user_id)
        if rank and rank <= 10:
            return ARENA_TITLES.get(rank)
        return None

    async def get_my_arena_status(self, user_id: str) -> Tuple[bool, str]:
        """获取玩家自己的擂台状态信息。"""
        await self.ensure_arena_tables()

        player = await self.db.get_player_by_id(user_id)
        if not player:
            return False, "❌ 你还没有开始修仙！"

        total = await self.get_total_arena_players()
        arena_info = await self.get_arena_info(user_id)

        if arena_info is None:
            in_cooldown, cooldown_remaining = self._check_failed_challenge_cooldown(user_id)
            cooldown_text = "无"
            if in_cooldown:
                minutes = cooldown_remaining // 60
                seconds = cooldown_remaining % 60
                cooldown_text = f"{minutes}分{seconds}秒"

            msg = (
                "🏟️ 我的擂台信息\n"
                "━━━━━━━━━━━━━━━\n"
                "当前状态：未上榜\n"
                f"榜上人数：{total}\n"
                f"挑战冷却：{cooldown_text}\n"
            )

            if total > 0:
                last_player_id = await self.get_player_by_rank(total)
                last_player = await self.db.get_player_by_id(last_player_id) if last_player_id else None
                last_name = _safe_name(last_player, last_player_id)
                msg += f"💡 可挑战末位：第{total}名【{last_name}】\n"

            msg += "💡 使用「加入擂台」尝试入榜，或「擂台挑战 @某人」争夺榜位"
            return True, msg

        wins = arena_info["wins"]
        losses = arena_info["losses"]
        total_battles = wins + losses
        win_rate = (wins / total_battles * 100) if total_battles > 0 else 0
        rank = arena_info["rank"]
        title = ARENA_TITLES.get(rank, "无")

        current_time = int(time.time())
        cooldown_remaining = max(0, ARENA_CHALLENGE_COOLDOWN - (current_time - arena_info["last_challenge_time"]))
        if cooldown_remaining > 0:
            minutes = cooldown_remaining // 60
            seconds = cooldown_remaining % 60
            cooldown_text = f"{minutes}分{seconds}秒"
        else:
            cooldown_text = "已就绪"

        msg = (
            "🏟️ 我的擂台信息\n"
            "━━━━━━━━━━━━━━━\n"
            f"当前排名：第{rank}名\n"
            f"擂台称号：{title}\n"
            f"战绩：{wins}胜{losses}负\n"
            f"胜率：{win_rate:.1f}%\n"
            f"挑战冷却：{cooldown_text}\n"
            "💡 使用「擂台」查看排行榜，使用「擂台挑战 @某人」挑战更高排名"
        )
        return True, msg
    
    async def get_power_ranking(self, limit: int = 10) -> Tuple[bool, str]:
        """
        战力排行榜（基于擂台实战排名）
        
        Args:
            limit: 显示数量
            
        Returns:
            (成功标志, 消息)
        """
        await self.ensure_arena_tables()
        
        # 检查是否需要初始化
        total = await self.get_total_arena_players()
        if total == 0:
            # 自动初始化
            await self.initialize_arena_ranking()
            total = await self.get_total_arena_players()
        
        if total == 0:
            return False, "❌ 暂无擂台数据！请先有玩家加入修仙。"
        
        # 获取排行榜
        ranking_list = await self.get_arena_ranking_list(limit)
        
        if not ranking_list:
            return False, "❌ 暂无擂台数据！"
        
        msg = "🏆 战力排行榜（擂台战）\n"
        msg += "━━━━━━━━━━━━━━━\n"
        
        for item in ranking_list:
            player = await self.db.get_player_by_id(item["user_id"])
            name = _safe_name(player, item["user_id"])
            rank = item["rank"]
            wins = item["wins"]
            losses = item["losses"]
            
            # 获取称号
            title = ARENA_TITLES.get(rank, "")
            title_str = f"【{title}】" if title else ""
            
            # 获取境界
            level_name = player.get_level(self.config_manager) if player else "未知"
            
            # 胜率计算
            total_battles = wins + losses
            win_rate = (wins / total_battles * 100) if total_battles > 0 else 0
            
            msg += f"{rank}. {title_str}{name}\n"
            msg += f"   境界：{level_name}\n"
            msg += f"   战绩：{wins}胜{losses}负 (胜率{win_rate:.1f}%)\n\n"
        
        msg += f"━━━━━━━━━━━━━━━\n"
        msg += f"📊 共{total}人上榜\n"
        msg += f"💡 使用「战力挑战 @某人」挑战更高排名\n"
        msg += f"💡 使用「加入擂台」加入排行榜"
        
        return True, msg
    
    async def get_level_ranking(self, limit: int = 10) -> Tuple[bool, str]:
        """
        境界排行榜
        
        Args:
            limit: 显示数量
            
        Returns:
            (成功标志, 消息)
        """
        all_players = await self.db.get_all_players()
        
        if not all_players:
            return False, "❌ 暂无数据！"
        
        # 按修为排序
        sorted_players = sorted(all_players, key=lambda p: p.experience, reverse=True)[:limit]
        
        msg = "📊 境界排行榜\n"
        msg += "━━━━━━━━━━━━━━━\n"
        
        for idx, player in enumerate(sorted_players, 1):
            name = _safe_name(player, player.user_id)
            level_name = player.get_level(self.config_manager)
            msg += f"{idx}. {name}\n"
            msg += f"   境界：{level_name} | 修为：{player.experience:,}\n\n"
        
        return True, msg
    
    async def get_wealth_ranking(self, limit: int = 10) -> Tuple[bool, str]:
        """
        财富排行榜（灵石）
        
        Args:
            limit: 显示数量
            
        Returns:
            (成功标志, 消息)
        """
        all_players = await self.db.get_all_players()
        
        if not all_players:
            return False, "❌ 暂无数据！"
        
        # 按灵石排序
        sorted_players = sorted(all_players, key=lambda p: p.gold, reverse=True)[:limit]
        
        msg = "📊 财富排行榜\n"
        msg += "━━━━━━━━━━━━━━━\n"
        
        for idx, player in enumerate(sorted_players, 1):
            name = _safe_name(player, player.user_id)
            msg += f"{idx}. {name}\n"
            msg += f"   灵石：{player.gold:,}\n\n"
        
        return True, msg
    
    async def get_sect_ranking(self, limit: int = 10) -> Tuple[bool, str]:
        """
        宗门排行榜（建设度）
        
        Args:
            limit: 显示数量
            
        Returns:
            (成功标志, 消息)
        """
        all_sects = await self.db.ext.get_all_sects()
        
        if not all_sects:
            return False, "❌ 暂无宗门数据！"
        
        # 显式按建设度排序，不依赖DB层的排序行为
        top_sects = sorted(all_sects, key=lambda s: s.sect_scale, reverse=True)[:limit]
        
        msg = "📊 宗门排行榜\n"
        msg += "━━━━━━━━━━━━━━━\n"
        
        for idx, sect in enumerate(top_sects, 1):
            owner = await self.db.get_player_by_id(sect.sect_owner)
            owner_name = _safe_name(owner, sect.sect_owner)
            members = await self.db.ext.get_sect_members(sect.sect_id)
            
            # 宗门名称也需要安全处理
            sect_name = sect.sect_name.replace("@", "＠")
            if len(sect_name) > MAX_NAME_LENGTH:
                sect_name = sect_name[:MAX_NAME_LENGTH] + "…"
            
            msg += f"{idx}. 【{sect_name}】\n"
            msg += f"   宗主：{owner_name}\n"
            msg += f"   建设度：{sect.sect_scale:,} | 成员：{len(members)}人\n\n"
        
        return True, msg
    
    async def get_deposit_ranking(self, limit: int = 10) -> Tuple[bool, str]:
        """
        存款排行榜（银行存款）
        
        Args:
            limit: 显示数量
            
        Returns:
            (成功标志, 消息)
        """
        rankings = await self.db.ext.get_deposit_ranking(limit)
        
        if not rankings:
            return False, "❌ 暂无存款数据！"
        
        msg = "📊 存款排行榜\n"
        msg += "━━━━━━━━━━━━━━━\n"
        
        for idx, item in enumerate(rankings, 1):
            uid = item["user_id"]
            player = await self.db.get_player_by_id(uid)
            name = _safe_name(player, uid)
            msg += f"{idx}. {name}\n"
            msg += f"   存款：{item['balance']:,} 灵石\n\n"
        
        return True, msg
    
    async def get_contribution_ranking(self, sect_id: int, limit: int = 10) -> Tuple[bool, str]:
        """
        宗门贡献度排行榜
        
        Args:
            sect_id: 宗门ID
            limit: 显示数量
            
        Returns:
            (成功标志, 消息)
        """
        sect = await self.db.ext.get_sect_by_id(sect_id)
        if not sect:
            return False, "❌ 宗门不存在！"
        
        members = await self.db.ext.get_sect_members(sect_id)
        
        if not members:
            return False, "❌ 宗门暂无成员！"
        
        # 按贡献度排序
        sorted_members = sorted(members, key=lambda p: p.sect_contribution, reverse=True)[:limit]
        
        # 宗门名称安全处理
        sect_name = sect.sect_name.replace("@", "＠")
        if len(sect_name) > MAX_NAME_LENGTH:
            sect_name = sect_name[:MAX_NAME_LENGTH] + "…"
        
        msg = f"📊 {sect_name} 贡献排行\n"
        msg += f"━━━━━━━━━━━━━━━\n"
        
        for idx, member in enumerate(sorted_members, 1):
            name = _safe_name(member, member.user_id)
            # 使用安全映射获取职位名称，防止索引越界
            position_name = POSITION_MAP.get(member.sect_position, "成员")
            msg += f"{idx}. {name} ({position_name})\n"
            msg += f"   贡献度：{member.sect_contribution:,}\n\n"
        
        return True, msg
