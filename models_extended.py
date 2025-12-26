# models.py - 新增模型定义

from dataclasses import dataclass
from enum import IntEnum
from typing import TYPE_CHECKING, List, Optional
import json

if TYPE_CHECKING:
    from .config_manager import ConfigManager


class UserStatus(IntEnum):
    """用户状态枚举"""
    IDLE = 0           # 空闲
    CULTIVATING = 1    # 闭关中
    ADVENTURING = 2    # 历练中
    EXPLORING = 3      # 探索秘境中
    SECT_TASK = 4      # 宗门任务中
    
    @classmethod
    def get_name(cls, status: int) -> str:
        """获取状态名称"""
        names = {
            cls.IDLE: "空闲",
            cls.CULTIVATING: "闭关中",
            cls.ADVENTURING: "历练中",
            cls.EXPLORING: "探索秘境中",
            cls.SECT_TASK: "宗门任务中",
        }
        return names.get(status, "忙碌中")

@dataclass
class Sect:
    """宗门数据模型"""
    
    sect_id: int  # 宗门ID（主键）
    sect_name: str  # 宗门名称
    sect_owner: str  # 宗主用户ID
    sect_scale: int = 0  # 建设度
    sect_used_stone: int = 0  # 可用灵石
    sect_fairyland: int = 0  # 洞天福地等级
    sect_materials: int = 0  # 资材
    mainbuff: str = "0"  # 主修功法buff ID列表（JSON字符串）
    secbuff: str = "0"  # 辅修功法buff ID列表（JSON字符串）
    elixir_room_level: int = 0  # 丹房等级
    
    def get_mainbuff_list(self) -> List[int]:
        """获取主修功法ID列表"""
        try:
            if self.mainbuff == "0" or not self.mainbuff:
                return []
            return json.loads(self.mainbuff) if isinstance(self.mainbuff, str) else [self.mainbuff]
        except:
            return []
    
    def set_mainbuff_list(self, buff_list: List[int]):
        """设置主修功法ID列表"""
        self.mainbuff = json.dumps(buff_list, ensure_ascii=False) if buff_list else "0"
    
    def get_secbuff_list(self) -> List[int]:
        """获取辅修功法ID列表"""
        try:
            if self.secbuff == "0" or not self.secbuff:
                return []
            return json.loads(self.secbuff) if isinstance(self.secbuff, str) else [self.secbuff]
        except:
            return []
    
    def set_secbuff_list(self, buff_list: List[int]):
        """设置辅修功法ID列表"""
        self.secbuff = json.dumps(buff_list, ensure_ascii=False) if buff_list else "0"


@dataclass
class BuffInfo:
    """Buff信息数据模型（用户装备的功法、法器等）"""
    
    id: int  # 主键
    user_id: str  # 用户ID
    main_buff: int = 0  # 主修功法ID
    sec_buff: int = 0  # 辅修功法ID
    faqi_buff: int = 0  # 法器buff ID
    fabao_weapon: int = 0  # 法宝武器ID
    armor_buff: int = 0  # 防具buff ID
    atk_buff: int = 0  # 永久攻击buff
    blessed_spot: int = 0  # 洞天福地等级
    sub_buff: int = 0  # 副buff


@dataclass
class Boss:
    """Boss数据模型"""
    
    boss_id: int  # Boss ID（主键）
    boss_name: str  # Boss名称
    boss_level: str  # Boss境界
    hp: int  # 血量
    max_hp: int  # 最大血量
    atk: int  # 攻击力
    defense: int = 0  # 防御力
    stone_reward: int = 0  # 灵石奖励
    create_time: int = 0  # 生成时间
    status: int = 1  # 状态（0已击败，1存活）
    

@dataclass
class Rift:
    """秘境数据模型"""
    
    rift_id: int  # 秘境ID（主键）
    rift_name: str  # 秘境名称
    rift_level: int  # 秘境等级
    required_level: int # 需求境界
    rewards: str = "{}"  # 奖励配置（JSON字符串）
    
    def get_rewards(self) -> dict:
        """获取奖励字典"""
        try:
            return json.loads(self.rewards)
        except:
            return {}
    
    def set_rewards(self, rewards_dict: dict):
        """设置奖励字典"""
        self.rewards = json.dumps(rewards_dict, ensure_ascii=False)


@dataclass
class ImpartInfo:
    """传承信息数据模型"""
    
    id: int  # 主键
    user_id: str  # 用户ID
    impart_hp_per: float = 0.0  # HP加成百分比
    impart_mp_per: float = 0.0  # MP加成百分比
    impart_atk_per: float = 0.0  # ATK加成百分比
    impart_know_per: float = 0.0  # 会心率加成百分比
    impart_burst_per: float = 0.0  # 爆伤加成百分比


@dataclass
class UserCd:
    """用户CD信息数据模型"""
    
    user_id: str  # 用户ID（主键）
    type: int = UserStatus.IDLE  # CD类型，参见 UserStatus 枚举
    create_time: int = 0  # 创建时间
    scheduled_time: int = 0  # 计划完成时间
