# managers/sect_manager.py
"""
宗门系统管理器 - 处理宗门创建、管理、捐献、任务等逻辑
参照NoneBot2插件的xiuxian_sect实现
"""

import random
import time
from typing import Tuple, List, Optional, Dict
from ..data.data_manager import DataBase
from ..models_extended import Sect, UserStatus
from ..models import Player


class SectManager:
    """宗门系统管理器"""
    
    # 宗门职位定义
    POSITIONS = {
        0: "宗主",
        1: "长老",
        2: "亲传弟子",
        3: "内门弟子",
        4: "外门弟子"
    }
    
    # 宗门职位权限
    POSITION_PERMISSIONS = {
        0: ["manage_all", "kick", "position_change", "build", "search_skill"],
        1: ["kick_outer", "build"],
        2: ["learn_skill"],
        3: ["learn_skill"],
        4: []  # 外门弟子无特殊权限
    }
    
    def __init__(self, db: DataBase, config_manager=None):
        self.db = db
        self.config = config_manager.sect_config if config_manager else {}
    
    async def create_sect(
        self,
        user_id: str,
        sect_name: str,
        required_stone: int = None,
        required_level: int = None
    ) -> Tuple[bool, str]:
        """
        创建宗门
        
        Args:
            user_id: 用户ID
            sect_name: 宗门名称
            required_stone: 需求灵石（默认为配置值或10000）
            required_level: 需求境界等级（默认为配置值或3）
            
        Returns:
            (成功标志, 消息)
        """
        # 加载配置
        if required_stone is None:
            required_stone = self.config.get("create_cost", 10000)
        if required_level is None:
            required_level = self.config.get("create_level_required", 3)
        # 1. 检查用户是否存在
        player = await self.db.get_player_by_id(user_id)
        if not player:
            return False, "❌ 你还未踏入修仙之路！"
        
        # 2. 检查是否已有宗门
        if player.sect_id != 0:
            return False, "❌ 你已经加入了宗门，无法创建新宗门！"
        
        # 3. 检查境界
        if player.level_index < required_level:
            return False, f"❌ 创建宗门需要达到境界等级 {required_level}！"
        
        # 4. 检查灵石
        if player.gold < required_stone:
            return False, f"❌ 创建宗门需要 {required_stone} 灵石！"
        
        # 5. 检查宗门名称是否重复
        existing_sect = await self.db.ext.get_sect_by_name(sect_name)
        if existing_sect:
            return False, f"❌ 宗门名称『{sect_name}』已被使用！"
        
        # 6. 扣除灵石
        player.gold -= required_stone
        await self.db.update_player(player)
        
        # 7. 创建宗门
        new_sect = Sect(
            sect_id=0,  # 自动生成
            sect_name=sect_name,
            sect_owner=user_id,
            sect_scale=100,  # 初始建设度
            sect_used_stone=0,
            sect_fairyland=0,
            sect_materials=100,  # 初始资材
            mainbuff="0",
            secbuff="0",
            elixir_room_level=0
        )
        
        sect_id = await self.db.ext.create_sect(new_sect)
        
        # 8. 更新玩家宗门信息（设为宗主）
        await self.db.ext.update_player_sect_info(user_id, sect_id, 0)
        
        # 9. 初始化用户buff信息（如果没有）
        buff_info = await self.db.ext.get_buff_info(user_id)
        if not buff_info:
            await self.db.ext.create_buff_info(user_id)
        
        return True, f"✨ 恭喜！你成功创建了宗门『{sect_name}』，成为一代宗主！"
    
    async def join_sect(self, user_id: str, sect_name: str) -> Tuple[bool, str]:
        """
        加入宗门
        
        Args:
            user_id: 用户ID
            sect_name: 宗门名称
            
        Returns:
            (成功标志, 消息)
        """
        # 1. 检查用户
        player = await self.db.get_player_by_id(user_id)
        if not player:
            return False, "❌ 你还未踏入修仙之路！"
        
        if player.sect_id != 0:
            return False, "❌ 你已经加入了宗门！请先退出当前宗门。"
        
        # 2. 查找宗门
        sect = await self.db.ext.get_sect_by_name(sect_name)
        if not sect:
            return False, f"❌ 未找到宗门『{sect_name}』！"
        
        # 3. 加入宗门（默认为外门弟子）
        await self.db.ext.update_player_sect_info(user_id, sect.sect_id, 4)
        
        # 4. 初始化buff信息
        buff_info = await self.db.ext.get_buff_info(user_id)
        if not buff_info:
            await self.db.ext.create_buff_info(user_id)
        
        return True, f"✨ 你成功加入了宗门『{sect_name}』，成为外门弟子！"
    
    async def leave_sect(self, user_id: str) -> Tuple[bool, str]:
        """
        退出宗门
        
        Args:
            user_id: 用户ID
            
        Returns:
            (成功标志, 消息)
        """
        player = await self.db.get_player_by_id(user_id)
        if not player:
            return False, "❌ 你还未踏入修仙之路！"
        
        if player.sect_id == 0:
            return False, "❌ 你还未加入任何宗门！"
        
        # 检查是否为宗主
        sect = await self.db.ext.get_sect_by_id(player.sect_id)
        if sect and sect.sect_owner == user_id:
            return False, "❌ 宗主无法直接退出宗门！请先传位或解散宗门。"
        
        sect_name = sect.sect_name if sect else "未知宗门"
        
        # 清除宗门信息
        await self.db.ext.update_player_sect_info(user_id, 0, 4)
        player.sect_contribution = 0
        await self.db.update_player(player)
        
        return True, f"✨ 你已退出宗门『{sect_name}』！"
    
    async def donate_to_sect(
        self,
        user_id: str,
        stone_amount: int
    ) -> Tuple[bool, str]:
        """
        宗门捐献（1灵石 = 10建设度）
        
        Args:
            user_id: 用户ID
            stone_amount: 捐献灵石数量
            
        Returns:
            (成功标志, 消息)
        """
        player = await self.db.get_player_by_id(user_id)
        if not player:
            return False, "❌ 你还未踏入修仙之路！"
        
        if player.sect_id == 0:
            return False, "❌ 你还未加入宗门！"
        
        if stone_amount <= 0:
            return False, "❌ 捐献数量必须大于0！"
        
        if player.gold < stone_amount:
            return False, f"❌ 你的灵石不足！当前拥有 {player.gold} 灵石。"
        
        # 扣除灵石
        player.gold -= stone_amount
        
        # 增加宗门贡献度（1灵石 = 1贡献）
        player.sect_contribution += stone_amount
        await self.db.update_player(player)
        
        # 增加宗门建设度和灵石（1灵石 = 10建设度）
        await self.db.ext.donate_to_sect(player.sect_id, stone_amount)
        
        scale_gained = stone_amount * 10
        
        return True, f"✨ 捐献成功！消耗 {stone_amount} 灵石，宗门获得 {scale_gained} 建设度！\n你的宗门贡献度：{player.sect_contribution}"
    
    async def get_sect_info(self, user_id: str) -> Tuple[bool, str, Optional[Dict]]:
        """
        获取宗门信息
        
        Args:
            user_id: 用户ID
            
        Returns:
            (成功标志, 消息, 宗门数据)
        """
        player = await self.db.get_player_by_id(user_id)
        if not player:
            return False, "❌ 你还未踏入修仙之路！", None
        
        if player.sect_id == 0:
            return False, "❌ 你还未加入宗门！", None
        
        sect = await self.db.ext.get_sect_by_id(player.sect_id)
        if not sect:
            return False, "❌ 宗门信息异常！", None
        
        # 获取宗主信息
        owner = await self.db.get_player_by_id(sect.sect_owner)
        owner_name = owner.user_name if owner and owner.user_name else sect.sect_owner
        
        # 获取成员数量
        members = await self.db.ext.get_sect_members(sect.sect_id)
        member_count = len(members)
        
        # 构建信息
        position_name = self.POSITIONS.get(player.sect_position, "未知")
        
        info_msg = f"""
╔══════════════════════╗
║    宗门信息    ║
╚══════════════════════╝

宗门名称：{sect.sect_name}
宗主：{owner_name}
建设度：{sect.sect_scale}
宗门灵石：{sect.sect_used_stone}
宗门资材：{sect.sect_materials}
丹房等级：{sect.elixir_room_level}
成员数量：{member_count}人

你的职位：{position_name}
你的贡献：{player.sect_contribution}
        """.strip()
        
        sect_data = {
            "sect": sect,
            "player_position": player.sect_position,
            "player_contribution": player.sect_contribution,
            "member_count": member_count
        }
        
        return True, info_msg, sect_data
    
    async def list_all_sects(self) -> Tuple[bool, str]:
        """
        获取所有宗门列表
        
        Returns:
            (成功标志, 消息)
        """
        sects = await self.db.ext.get_all_sects()
        
        if not sects:
            return False, "❌ 当前还没有任何宗门！"
        
        msg = "╔══════════════════════╗\n"
        msg += "║    宗门列表    ║\n"
        msg += "╚══════════════════════╝\n\n"
        
        for idx, sect in enumerate(sects[:10], 1):  # 只显示前10个
            owner = await self.db.get_player_by_id(sect.sect_owner)
            owner_name = owner.user_name if owner and owner.user_name else "未知"
            members = await self.db.ext.get_sect_members(sect.sect_id)
            
            msg += f"{idx}. 【{sect.sect_name}】\n"
            msg += f"   宗主：{owner_name}\n"
            msg += f"   建设度：{sect.sect_scale} | 成员：{len(members)}人\n\n"
        
        return True, msg
    
    async def change_position(
        self,
        operator_id: str,
        target_id: str,
        new_position: int
    ) -> Tuple[bool, str]:
        """
        变更宗门职位
        
        Args:
            operator_id: 操作者ID（必须是宗主）
            target_id: 目标用户ID
            new_position: 新职位（0-4）
            
        Returns:
            (成功标志, 消息)
        """
        # 检查操作者
        operator = await self.db.get_player_by_id(operator_id)
        if not operator or operator.sect_id == 0:
            return False, "❌ 你还未加入宗门！"
        
        if operator.sect_position != 0:
            return False, "❌ 只有宗主才能变更职位！"
        
        # 检查目标用户
        target = await self.db.get_player_by_id(target_id)
        if not target:
            return False, "❌ 目标用户不存在！"
        
        if target.sect_id != operator.sect_id:
            return False, "❌ 目标用户不在你的宗门！"
        
        if target_id == operator_id:
            return False, "❌ 无法变更自己的职位！"
        
        if new_position not in self.POSITIONS:
            return False, "❌ 无效的职位！职位范围：0（宗主）- 4（外门弟子）"
        
        if new_position == 0:
            return False, "❌ 无法直接任命宗主！请使用传位功能。"
        
        # 变更职位
        await self.db.ext.update_player_sect_info(target_id, target.sect_id, new_position)
        
        target_name = target.user_name if target.user_name else target_id
        position_name = self.POSITIONS[new_position]
        
        return True, f"✨ 已将 {target_name} 的职位变更为：{position_name}"
    
    async def transfer_ownership(
        self,
        current_owner_id: str,
        new_owner_id: str
    ) -> Tuple[bool, str]:
        """
        宗主传位
        
        Args:
            current_owner_id: 当前宗主ID
            new_owner_id: 新宗主ID
            
        Returns:
            (成功标志, 消息)
        """
        # 检查当前宗主
        current_owner = await self.db.get_player_by_id(current_owner_id)
        if not current_owner or current_owner.sect_id == 0:
            return False, "❌ 你还未加入宗门！"
        
        sect = await self.db.ext.get_sect_by_id(current_owner.sect_id)
        if not sect or sect.sect_owner != current_owner_id:
            return False, "❌ 你不是宗主！"
        
        # 检查新宗主
        new_owner = await self.db.get_player_by_id(new_owner_id)
        if not new_owner:
            return False, "❌ 目标用户不存在！"
        
        if new_owner.sect_id != current_owner.sect_id:
            return False, "❌ 目标用户不在你的宗门！"
        
        if new_owner_id == current_owner_id:
            return False, "❌ 无法传位给自己！"
        
        # 执行传位
        sect.sect_owner = new_owner_id
        await self.db.ext.update_sect(sect)
        
        # 更新职位：新宗主->宗主，旧宗主->长老
        await self.db.ext.update_player_sect_info(new_owner_id, sect.sect_id, 0)
        await self.db.ext.update_player_sect_info(current_owner_id, sect.sect_id, 1)
        
        new_owner_name = new_owner.user_name if new_owner.user_name else new_owner_id
        
        return True, f"✨ 宗主之位已传给 {new_owner_name}！你现在是长老。"
    
    async def kick_member(
        self,
        operator_id: str,
        target_id: str
    ) -> Tuple[bool, str]:
        """
        踢出宗门成员
        
        Args:
            operator_id: 操作者ID
            target_id: 目标用户ID
            
        Returns:
            (成功标志, 消息)
        """
        # 检查操作者权限
        operator = await self.db.get_player_by_id(operator_id)
        if not operator or operator.sect_id == 0:
            return False, "❌ 你还未加入宗门！"
        
        # 宗主和长老可以踢人
        if operator.sect_position not in [0, 1]:
            return False, "❌ 只有宗主和长老才能踢出成员！"
        
        # 检查目标
        target = await self.db.get_player_by_id(target_id)
        if not target:
            return False, "❌ 目标用户不存在！"
        
        if target.sect_id != operator.sect_id:
            return False, "❌ 目标用户不在你的宗门！"
        
        if target_id == operator_id:
            return False, "❌ 无法踢出自己！"
        
        # 长老只能踢外门弟子
        if operator.sect_position == 1 and target.sect_position <= 3:
            return False, "❌ 长老只能踢出外门弟子！"
        
        # 无法踢出宗主
        if target.sect_position == 0:
            return False, "❌ 无法踢出宗主！"
        
        # 踢出
        target_name = target.user_name if target.user_name else target_id
        await self.db.ext.update_player_sect_info(target_id, 0, 4)
        target.sect_contribution = 0
        await self.db.update_player(target)
        
        return True, f"✨ 已将 {target_name} 踢出宗门！"

    async def perform_sect_task(self, user_id: str) -> Tuple[bool, str]:
        """
        执行宗门任务
        
        Args:
            user_id: 用户ID
            
        Returns:
            (成功标志, 消息)
        """
        player = await self.db.get_player_by_id(user_id)
        if not player or player.sect_id == 0:
            return False, "❌ 你还未加入宗门！"
            
        # 检查CD (使用宗门任务CD类型，假设为4)
        user_cd = await self.db.ext.get_user_cd(user_id)
        if not user_cd:
            await self.db.ext.create_user_cd(user_id)
            user_cd = await self.db.ext.get_user_cd(user_id)
            
        current_time = int(time.time())
        # 假设 CD 记录在 type=4, scheduled_time 为下次可用时间
        # 这里重用 set_user_busy 逻辑，但任务通常是瞬时的，只设冷却
        if user_cd.type == UserStatus.SECT_TASK and current_time < user_cd.scheduled_time:
            remaining = user_cd.scheduled_time - current_time
            return False, f"❌ 宗门任务冷却中！还需 {remaining//60} 分钟。"

        # 执行任务
        contribution_gain = random.randint(10, 30)
        stone_gain = contribution_gain * 10
        
        player.sect_contribution += contribution_gain
        await self.db.update_player(player)
        
        # 宗门增加资源
        await self.db.ext.donate_to_sect(player.sect_id, 0) # 只更新建设度? donate_to_sect update both.
        # 手动更新宗门资源
        sect = await self.db.ext.get_sect_by_id(player.sect_id)
        if sect:
            sect.sect_materials += stone_gain
            await self.db.ext.update_sect(sect)

        # 设置1小时冷却
        await self.db.ext.set_user_busy(user_id, 4, current_time + 3600)
        
        return True, f"✨ 完成宗门任务！\n获得贡献：{contribution_gain}\n宗门资材：+{stone_gain}"
