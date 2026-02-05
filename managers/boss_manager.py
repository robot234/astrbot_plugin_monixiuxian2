# managers/boss_manager.py
"""
Boss系统管理器 - 处理Boss生成、战斗、奖励等逻辑
参照NoneBot2插件的xiuxian_boss实现
"""

import random
import time
from typing import Tuple, Dict, Optional, List, TYPE_CHECKING
from ..data.data_manager import DataBase
from ..models_extended import Boss, UserStatus
from ..models import Player

if TYPE_CHECKING:
    from ..core import StorageRingManager
    from ..core.battle_manager import BattleManager
    from ..core.equipment_manager import EquipmentManager
    from ..core.skill_manager import SkillManager
    from ..config_manager import ConfigManager


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
    
    # Boss物品掉落表
    BOSS_DROP_TABLE = {
        "low": [  # 低级Boss (练气-金丹)
            {"name": "灵兽内丹", "weight": 40, "min": 1, "max": 2},
            {"name": "妖兽精血", "weight": 30, "min": 1, "max": 3},
            {"name": "玄铁", "weight": 30, "min": 3, "max": 6},
        ],
        "mid": [  # 中级Boss (元婴-化神)
            {"name": "灵兽内丹", "weight": 30, "min": 2, "max": 4},
            {"name": "星辰石", "weight": 25, "min": 2, "max": 4},
            {"name": "天材地宝", "weight": 20, "min": 1, "max": 2},
            {"name": "功法残页", "weight": 25, "min": 1, "max": 2},
        ],
        "high": [  # 高级Boss (炼虚及以上)
            {"name": "天材地宝", "weight": 30, "min": 2, "max": 4},
            {"name": "混沌精华", "weight": 25, "min": 1, "max": 2},
            {"name": "神兽之骨", "weight": 20, "min": 1, "max": 1},
            {"name": "远古秘籍", "weight": 15, "min": 1, "max": 1},
            {"name": "仙器碎片", "weight": 10, "min": 1, "max": 1},
        ],
    }
    
    def __init__(
        self, 
        db: DataBase, 
        battle_mgr: "BattleManager", 
        config_manager: "ConfigManager" = None, 
        storage_ring_manager: "StorageRingManager" = None,
        equipment_manager: "EquipmentManager" = None,
        skill_manager: "SkillManager" = None
    ):
        self.db = db
        self.battle_mgr = battle_mgr
        self.config_manager = config_manager
        self.storage_ring_manager = storage_ring_manager
        self.equipment_manager = equipment_manager
        self.skill_manager = skill_manager
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
👹 Boss降临
━━━━━━━━━━━━━━━

{boss_name}降临世间！

境界：{level_config["name"]}
HP：{max_hp}
ATK：{atk}
防御：{defense}%减伤
奖励：{stone_reward}灵石

快来挑战吧！
        """.strip()
        
        return True, msg, boss
    
    def _create_boss_combat_stats(self, boss: Boss):
        """
        为Boss创建战斗属性
        
        Args:
            boss: Boss对象
            
        Returns:
            CombatStats对象
        """
        from ..core.battle_manager import CombatStats
        
        # 根据Boss境界计算属性
        level_index = 0
        for level in self.levels:
            if level["name"] == boss.boss_level:
                level_index = level["level_index"]
                break
        
        # Boss的物理/法术攻击基于ATK
        physical_attack = boss.atk
        magic_attack = int(boss.atk * 0.8)  # Boss法攻略低于物攻
        
        # Boss的防御基于defense百分比转换
        physical_defense = int(boss.defense * 2)  # 防御值
        magic_defense = int(boss.defense * 1.5)
        
        # Boss速度基于境界
        speed = 10 + level_index * 2
        
        # Boss暴击率和暴击伤害
        critical_rate = 0.1 + level_index * 0.01  # 10%-30%
        critical_damage = 1.5 + level_index * 0.02  # 1.5x-2.0x
        
        return CombatStats(
            user_id=f"boss_{boss.boss_id}",
            name=boss.boss_name,
            hp=boss.hp,
            max_hp=boss.max_hp,
            mp=boss.max_hp // 2,  # Boss MP为HP的一半
            max_mp=boss.max_hp // 2,
            physical_attack=physical_attack,
            magic_attack=magic_attack,
            physical_defense=physical_defense,
            magic_defense=magic_defense,
            speed=speed,
            critical_rate=min(0.5, critical_rate),
            critical_damage=critical_damage,
            hit_rate=0.95,
            dodge_rate=0.05 + level_index * 0.005,  # 5%-15%
            skills=[],  # Boss暂不使用技能
            skill_cooldowns={},
            shield=0,
            buffs=[],
            debuffs=[]
        )
    
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
        
        # 4. 检查玩家血量，如果血量过低，需要冷却时间
        if player.hp <= 1:
            import json
            cooldown_time = 10 * 60  # 10分钟冷却
            
            try:
                extra_data = json.loads(user_cd.extra_data) if user_cd.extra_data else {}
                last_defeat_time = extra_data.get('last_boss_defeat_time', 0)
                
                if last_defeat_time:
                    if int(time.time()) - last_defeat_time < cooldown_time:
                        remaining_time = cooldown_time - (int(time.time()) - last_defeat_time)
                        minutes = remaining_time // 60
                        seconds = remaining_time % 60
                        return False, f"❌ 你当前血量过低，需要休息一段时间才能再次挑战Boss！\n\n💡 剩余冷却时间：{minutes}分{seconds}秒", None
            except Exception:
                pass
        
        # 5. 使用新的 BattleManager 准备玩家战斗属性
        player_stats = self.battle_mgr.prepare_combat_stats(
            player=player,
            equipment_manager=self.equipment_manager,
            skill_manager=self.skill_manager
        )
        
        # 挑战Boss前恢复HP/MP到满
        player_stats.hp = player_stats.max_hp
        player_stats.mp = player_stats.max_mp
        
        # 6. 创建Boss战斗属性
        boss_stats = self._create_boss_combat_stats(boss)
        
        # 7. 执行战斗（使用新的战斗系统）
        battle_result = self.battle_mgr.execute_battle(
            player_stats, 
            boss_stats, 
            battle_type="duel"  # Boss战斗使用决斗模式
        )
        
        # 8. 处理战斗结果
        winner = battle_result["winner"]
        is_player_win = (winner == user_id)
        
        # 计算奖励
        if is_player_win:
            reward = boss.stone_reward
        else:
            # 失败给予部分奖励（基于造成的伤害比例）
            damage_dealt = boss.max_hp - battle_result["p2_final"]["hp"]
            damage_ratio = damage_dealt / boss.max_hp if boss.max_hp > 0 else 0
            reward = int(boss.stone_reward * damage_ratio * 0.3)  # 最多30%奖励
        
        if is_player_win:
            # 玩家胜利
            boss.status = 0  # 标记Boss为已击败
            await self.db.ext.defeat_boss(boss.boss_id)
            
            # 发放奖励
            player.gold += reward
            
            # 物品掉落
            item_msg = ""
            dropped_items = []
            if self.storage_ring_manager:
                dropped_items = await self._roll_boss_drops(player, boss)
                if dropped_items:
                    item_lines = []
                    for item_name, count in dropped_items:
                        success, _ = await self.storage_ring_manager.store_item(player, item_name, count, silent=True)
                        if success:
                            item_lines.append(f"  · {item_name} x{count}")
                        else:
                            item_lines.append(f"  · {item_name} x{count}（储物戒已满，丢失）")
                    if item_lines:
                        item_msg = "\n\n📦 获得物品：\n" + "\n".join(item_lines)
            
            # 更新玩家HP（按战斗结果比例）
            final_hp_ratio = battle_result["p1_final"]["hp"] / battle_result["p1_final"]["max_hp"]
            player.hp = max(1, int(player.max_hp * final_hp_ratio))
            player.mp = player.max_mp  # MP恢复满
            await self.db.update_player(player)
            
            result_msg = f"""
🎉 挑战成功！
━━━━━━━━━━━━━━━

你成功击败了『{boss.boss_name}』！

战斗回合数：{battle_result['rounds']}
获得灵石：{reward}{item_msg}

{player_stats.name}
HP：{battle_result['p1_final']['hp']}/{player_stats.max_hp}
            """.strip()
            
            # 添加战斗结果信息供广播使用
            battle_result["reward"] = reward
            
        else:
            # 玩家失败
            boss.hp = battle_result["p2_final"]["hp"]
            await self.db.ext.update_boss(boss)
            
            # 更新玩家HP为1（濒死状态）
            player.hp = 1
            player.mp = player.max_mp
            if reward > 0:
                player.gold += reward
            await self.db.update_player(player)
            
            # 记录失败时间
            import json
            try:
                extra_data = json.loads(user_cd.extra_data) if user_cd.extra_data else {}
                extra_data['last_boss_defeat_time'] = int(time.time())
                user_cd.extra_data = json.dumps(extra_data)
                await self.db.ext.update_user_cd(user_cd)
            except Exception:
                pass
            
            result_msg = f"""
💀 挑战失败
━━━━━━━━━━━━━━━

你被『{boss.boss_name}』击败了！

战斗回合数：{battle_result['rounds']}
安慰奖：{reward}灵石

{boss.boss_name} 剩余HP：{boss.hp}/{boss.max_hp}
            """.strip()
        
        # 生成战斗摘要
        battle_summary = self.battle_mgr.generate_battle_summary(battle_result, include_full_log=False)
        full_msg = battle_summary + "\n\n" + result_msg
        
        return True, full_msg, battle_result
    
    async def get_boss_info(self) -> Tuple[bool, str, Optional[Boss]]:
        """
        获取当前Boss信息
        
        Returns:
            (成功标志, 消息, Boss对象)
        """
        boss = await self.db.ext.get_active_boss()
        if not boss:
            # 计算下一个Boss复活时间（默认2小时后）
            next_spawn_time = int(time.time()) + 2 * 3600
            # 格式化时间
            next_time_str = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(next_spawn_time))
            return False, f"❌ 当前没有Boss！\n\n💡 预计下一个Boss将在 {next_time_str} 复活", None
        
        hp_percent = (boss.hp / boss.max_hp) * 100
        
        msg = f"""
👹 当前Boss
━━━━━━━━━━━━━━━

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
    
    async def _roll_boss_drops(self, player: Player, boss: Boss) -> List[Tuple[str, int]]:
        """
        根据Boss等级随机掉落物品
        
        Args:
            player: 玩家对象
            boss: Boss对象
            
        Returns:
            掉落物品列表 [(物品名, 数量), ...]
        """
        dropped_items = []
        
        # 根据Boss等级确定掉落表
        boss_level_index = 0
        for level in self.levels:
            if level["name"] == boss.boss_level:
                boss_level_index = level["level_index"]
                break
        
        if boss_level_index <= 6:  # 练气-金丹
            drop_table = self.BOSS_DROP_TABLE["low"]
        elif boss_level_index <= 12:  # 元婴-化神
            drop_table = self.BOSS_DROP_TABLE["mid"]
        else:  # 炼虚及以上
            drop_table = self.BOSS_DROP_TABLE["high"]
        
        # Boss击杀100%掉落至少1件物品
        total_weight = sum(item["weight"] for item in drop_table)
        roll = random.randint(1, total_weight)
        
        current_weight = 0
        for item in drop_table:
            current_weight += item["weight"]
            if roll <= current_weight:
                count = random.randint(item["min"], item["max"])
                dropped_items.append((item["name"], count))
                break
        
        # 高级Boss有70%概率额外掉落
        if boss_level_index >= 9:  # 元婴及以上
            extra_chance = 50 if boss_level_index < 15 else 70
            if random.randint(1, 100) <= extra_chance:
                roll = random.randint(1, total_weight)
                current_weight = 0
                for item in drop_table:
                    current_weight += item["weight"]
                    if roll <= current_weight:
                        count = random.randint(item["min"], item["max"])
                        dropped_items.append((item["name"], count))
                        break
        
        return dropped_items
