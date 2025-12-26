# managers/boss_manager.py
"""
Boss系统管理器 - 处理Boss生成、战斗、奖励等逻辑
参照NoneBot2插件的xiuxian_boss实现
"""

import random
import time
from typing import Tuple, Dict, Optional
from ..data.data_manager import DataBase
from ..models_extended import Boss, UserStatus
from ..models import Player
from .combat_manager import CombatManager, CombatStats


class BossManager:
    """Boss系统管理器"""
    
    # Boss境界配置
    BOSS_LEVELS = [
        {"name": "练气", "level_index": 0, "hp_mult": 1.0, "atk_mult": 1.0, "reward_mult": 1.0},
        {"name": "筑基", "level_index": 3, "hp_mult": 1.5, "atk_mult": 1.2, "reward_mult": 1.5},
        {"name": "金丹", "level_index": 6, "hp_mult": 2.0, "atk_mult": 1.5, "reward_mult": 2.0},
        {"name": "元婴", "level_index": 9, "hp_mult": 2.5, "atk_mult": 1.8, "reward_mult": 2.5},
        {"name": "化神", "level_index": 12, "hp_mult": 3.0, "atk_mult": 2.0, "reward_mult": 3.0},
        {"name": "炼虚", "level_index": 15, "hp_mult": 4.0, "atk_mult": 2.5, "reward_mult": 4.0},
        {"name": "合体", "level_index": 18, "hp_mult": 5.0, "atk_mult": 3.0, "reward_mult": 5.0},
        {"name": "大乘", "level_index": 21, "hp_mult": 6.0, "atk_mult": 3.5, "reward_mult": 6.0},
    ]
    
    # Boss名称池
    BOSS_NAMES = [
        "血魔", "邪修", "魔头", "妖王", "魔君",
        "异兽", "凶兽", "妖尊", "魔尊", "邪帝",
        "天魔", "地魔", "魔神", "妖神", "邪神"
    ]
    
    def __init__(self, db: DataBase, combat_mgr: CombatManager, config_manager=None):
        self.db = db
        self.combat_mgr = combat_mgr
        self.config = config_manager.boss_config if config_manager else {}
        self.levels = self.config.get("levels", self.BOSS_LEVELS)
    
    async def spawn_boss(
        self,
        base_exp: int = 100000,
        level_config: Optional[Dict] = None
    ) -> Tuple[bool, str, Optional[Boss]]:
        """
        生成Boss
        
        Args:
            base_exp: 基础修为（用于计算属性）
            level_config: Boss等级配置，如果为None则随机选择
            
        Returns:
            (成功标志, 消息, Boss对象)
        """
        # 检查是否已有存活的Boss
        existing_boss = await self.db.ext.get_active_boss()
        if existing_boss:
            return False, f"❌ 当前已有Boss『{existing_boss.boss_name}』存在！", None
        
        # 选择Boss等级
        if not level_config:
            level_config = random.choice(self.levels)
        
        # 生成Boss名称
        boss_name = random.choice(self.BOSS_NAMES) + f"·{level_config['name']}境"
        
        # 计算Boss属性
        hp_mult = level_config["hp_mult"]
        atk_mult = level_config["atk_mult"]
        reward_mult = level_config["reward_mult"]
        
        # Boss的HP和ATK基于修为计算
        max_hp = int(base_exp * hp_mult // 2)
        atk = int(base_exp * atk_mult // 10)
        
        # 灵石奖励
        stone_reward = int(base_exp * reward_mult // 10)
        
        # Boss防御力（高境界Boss有减伤）
        defense = 0
        if level_config["level_index"] >= 15:  # 炼虚及以上
            defense = random.randint(40, 90)  # 40%-90%减伤
        
        # 创建Boss
        boss = Boss(
            boss_id=0,  # 自动生成
            boss_name=boss_name,
            boss_level=level_config["name"],
            hp=max_hp,
            max_hp=max_hp,
            atk=atk,
            defense=defense,
            stone_reward=stone_reward,
            create_time=int(time.time()),
            status=1  # 1=存活
        )
        
        boss_id = await self.db.ext.create_boss(boss)
        boss.boss_id = boss_id
        
        msg = f"""
╔══════════════════════╗
║    Boss降临    ║
╚══════════════════════╝

{boss_name}降临世间！

境界：{level_config["name"]}
HP：{max_hp}
ATK：{atk}
防御：{defense}%减伤
奖励：{stone_reward}灵石

快来挑战吧！
        """.strip()
        
        return True, msg, boss
    
    async def challenge_boss(
        self,
        user_id: str
    ) -> Tuple[bool, str, Optional[Dict]]:
        """
        挑战Boss
        
        Args:
            user_id: 挑战者ID
            
        Returns:
            (成功标志, 消息, 战斗结果)
        """
        # 1. 检查玩家
        player = await self.db.get_player_by_id(user_id)
        if not player:
            return False, "❌ 你还未踏入修仙之路！", None
        
        # 2. 检查Boss是否存在
        boss = await self.db.ext.get_active_boss()
        if not boss:
            return False, "❌ 当前没有Boss！", None
        
        # 3. 检查玩家状态
        user_cd = await self.db.ext.get_user_cd(user_id)
        if not user_cd:
            await self.db.ext.create_user_cd(user_id)
            user_cd = await self.db.ext.get_user_cd(user_id)
        
        if user_cd.type != UserStatus.IDLE:
            return False, "❌ 你当前正忙，无法挑战Boss！", None
        
        # 4. 计算玩家战斗属性
        # 获取buff加成
        impart_info = await self.db.ext.get_impart_info(user_id)
        hp_buff = impart_info.impart_hp_per if impart_info else 0.0
        mp_buff = impart_info.impart_mp_per if impart_info else 0.0
        atk_buff = impart_info.impart_atk_per if impart_info else 0.0
        crit_rate_buff = impart_info.impart_know_per if impart_info else 0.0
        
        # 计算HP/MP/ATK
        if player.hp == 0 or player.mp == 0:
            # 如果没有初始化战斗属性，先计算
            hp, mp = self.combat_mgr.calculate_hp_mp(player.experience, hp_buff, mp_buff)
            atk = self.combat_mgr.calculate_atk(player.experience, player.atkpractice, atk_buff)
            player.hp = hp
            player.mp = mp
            player.atk = atk
            await self.db.update_player(player)
        else:
            # 使用现有属性
            hp = player.hp
            mp = player.mp
            atk = player.atk
        
        # 创建玩家战斗属性
        player_stats = CombatStats(
            user_id=user_id,
            name=player.user_name if player.user_name else f"道友{user_id[:6]}",
            hp=hp,
            max_hp=int(player.experience * (1 + hp_buff) // 2),
            mp=mp,
            max_mp=int(player.experience * (1 + mp_buff)),
            atk=atk,
            defense=0,  # 可以根据装备添加
            crit_rate=int(crit_rate_buff * 100),  # 转换为百分比
            exp=player.experience
        )
        
        # 创建Boss战斗属性
        boss_stats = CombatStats(
            user_id=str(boss.boss_id),
            name=boss.boss_name,
            hp=boss.hp,
            max_hp=boss.max_hp,
            mp=boss.max_hp,  # Boss的MP等于HP
            max_mp=boss.max_hp,
            atk=boss.atk,
            defense=boss.defense,
            crit_rate=30,  # Boss固定30%会心率
            exp=boss.stone_reward  # 奖励存在exp字段
        )
        
        # 5. 开始战斗
        battle_result = self.combat_mgr.player_vs_boss(player_stats, boss_stats)
        
        # 6. 处理战斗结果
        winner = battle_result["winner"]
        reward = battle_result["reward"]
        
        if winner == user_id:
            # 玩家胜利
            boss.status = 0  # 标记Boss为已击败
            await self.db.ext.defeat_boss(boss.boss_id)
            
            # 发放奖励
            player.gold += reward
            
            result_msg = f"""
╔══════════════════════╗
║    挑战成功！    ║
╚══════════════════════╝

你成功击败了『{boss.boss_name}』！

战斗回合数：{battle_result['rounds']}
获得灵石：{reward}

{player_stats.name}
HP：{battle_result['player_final_hp']}/{player_stats.max_hp}
            """.strip()
        else:
            # 玩家失败
            boss.hp = battle_result["boss_final_hp"]
            await self.db.ext.update_boss(boss)
            
            result_msg = f"""
╔══════════════════════╗
║    挑战失败    ║
╚══════════════════════╝

你被『{boss.boss_name}』击败了！

战斗回合数：{battle_result['rounds']}
安慰奖：{reward}灵石

{boss.boss_name} 剩余HP：{boss.hp}/{boss.max_hp}
            """.strip()
            
            # 即使失败也给予部分奖励
            if reward > 0:
                player.gold += reward
        
        # 更新玩家HP/MP
        player.hp = battle_result["player_final_hp"]
        player.mp = battle_result["player_final_mp"]
        await self.db.update_player(player)
        
        # 返回完整战斗日志
        combat_log = "\n".join(battle_result["combat_log"])
        full_msg = combat_log + "\n\n" + result_msg
        
        return True, full_msg, battle_result
    
    async def get_boss_info(self) -> Tuple[bool, str, Optional[Boss]]:
        """
        获取当前Boss信息
        
        Returns:
            (成功标志, 消息, Boss对象)
        """
        boss = await self.db.ext.get_active_boss()
        if not boss:
            return False, "❌ 当前没有Boss！", None
        
        hp_percent = (boss.hp / boss.max_hp) * 100
        
        msg = f"""
╔══════════════════════╗
║    当前Boss    ║
╚══════════════════════╝

名称：{boss.boss_name}
境界：{boss.boss_level}

HP：{boss.hp}/{boss.max_hp} ({hp_percent:.1f}%)
ATK：{boss.atk}
防御：{boss.defense}%减伤

奖励：{boss.stone_reward}灵石

使用 /挑战Boss 来挑战！
        """.strip()
        
        return True, msg, boss
    
    async def auto_spawn_boss(self, player_count: int = 0) -> Tuple[bool, str, Optional[Boss]]:
        """
        自动生成Boss（定时任务使用）
        根据服务器玩家数量和平均等级自动调整Boss难度
        
        Args:
            player_count: 玩家数量（用于调整难度）
            
        Returns:
            (成功标志, 消息, Boss对象)
        """
        # 检查是否已有Boss
        existing_boss = await self.db.ext.get_active_boss()
        if existing_boss:
            return False, "当前已有Boss存在", None
        
        # 获取所有玩家的平均等级
        all_players = await self.db.get_all_players()
        if not all_players:
            # 没有玩家，生成低级Boss
            level_config = self.levels[0]
            base_exp = 50000
        else:
            # 计算平均修为
            total_exp = sum(p.experience for p in all_players)
            avg_exp = total_exp // len(all_players) if all_players else 50000
            
            # 根据平均修为选择Boss等级
            for config in reversed(self.levels):
                if avg_exp >= config.get("level_index", 0) * 10000:
                    level_config = config
                    break
            else:
                level_config = self.levels[0]
            
            # Boss修为比平均稍高
            base_exp = int(avg_exp * 1.2)
        
        # 生成Boss
        return await self.spawn_boss(base_exp, level_config)
