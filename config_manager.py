import json
from pathlib import Path
from typing import List, Dict, Any, Optional

from astrbot.api import logger
from .data.default_configs import SECT_CONFIG, BOSS_CONFIG, RIFT_CONFIG, ALCHEMY_CONFIG

class ConfigManager:
    """配置管理器，加载境界、物品、武器和丹药配置"""

    def __init__(self, base_dir: Path):
        self._base_dir = base_dir
        self.level_data: List[dict] = []  # 灵修境界数据
        self.body_level_data: List[dict] = []  # 体修境界数据
        self.items_data: Dict[str, dict] = {}  # 物品数据，key为物品名称
        self.weapons_data: Dict[str, dict] = {}  # 武器数据，key为武器名称
        self.pills_data: Dict[str, dict] = {}  # 破境丹数据，key为丹药名称
        self.exp_pills_data: Dict[str, dict] = {}  # 修为丹数据，key为丹药名称
        self.utility_pills_data: Dict[str, dict] = {}  # 功能丹数据，key为丹药名称
        self.storage_rings_data: Dict[str, dict] = {}  # 储物戒数据，key为储物戒名称
        
        # 技能和功法配置
        self.skills_data: Dict[str, dict] = {}  # 技能数据，key为技能ID
        self.techniques_data: Dict[str, dict] = {}  # 功法数据，key为功法ID
        
        # 新增系统配置
        self.sect_config: Dict[str, Any] = {}
        self.boss_config: Dict[str, Any] = {}
        self.rift_config: Dict[str, Any] = {}
        self.alchemy_config: Dict[str, Any] = {}
        
        self._load_all()

    def get_level_data(self, cultivation_type: str = "灵修") -> List[dict]:
        """根据修炼类型获取对应的境界数据"""
        if cultivation_type == "体修":
            return self.body_level_data
        return self.level_data

    def _load_json_data(self, file_path: Path) -> List[dict]:
        """加载JSON配置文件（列表格式）"""
        if not file_path.exists():
            logger.warning(f"数据文件 {file_path} 不存在，将使用空数据。")
            return []
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                logger.info(f"成功加载 {file_path.name} (共 {len(data)} 条数据)。")
                return data
        except Exception as e:
            logger.error(f"加载数据文件 {file_path} 失败: {e}")
            return []
    
    def _load_json(self, filename: str) -> Dict[str, dict]:
        """加载JSON配置文件（字典格式）
        
        Args:
            filename: 配置文件名
            
        Returns:
            配置字典，key为ID或名称
        """
        config_dir = self._base_dir / "config"
        file_path = config_dir / filename
        
        if not file_path.exists():
            logger.warning(f"配置文件 {file_path} 不存在，将使用空数据。")
            return {}
        
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                
                if isinstance(data, dict):
                    # 确保每个条目都有id字段
                    for item_id, item_data in data.items():
                        if isinstance(item_data, dict) and "id" not in item_data:
                            item_data["id"] = item_id
                    logger.info(f"成功加载 {filename} (共 {len(data)} 条数据)。")
                    return data
                elif isinstance(data, list):
                    # 如果是列表格式，转换为字典
                    result = {}
                    for item in data:
                        if isinstance(item, dict):
                            item_id = item.get("id", item.get("name", ""))
                            if item_id:
                                result[item_id] = item
                    logger.info(f"成功加载 {filename} (共 {len(result)} 条数据)。")
                    return result
                else:
                    logger.error(f"配置文件 {filename} 格式不正确。")
                    return {}
        except Exception as e:
            logger.error(f"加载配置文件 {filename} 失败: {e}")
            return {}
            
    def _load_config_with_default(self, file_path: Path, default_config: Dict) -> Dict:
        """加载配置，如果不存在则创建默认配置"""
        if not file_path.exists():
            try:
                # 确保目录存在
                file_path.parent.mkdir(parents=True, exist_ok=True)
                with open(file_path, 'w', encoding='utf-8') as f:
                    json.dump(default_config, f, ensure_ascii=False, indent=2)
                logger.info(f"创建默认配置文件: {file_path.name}")
                return default_config
            except Exception as e:
                logger.error(f"创建配置文件 {file_path} 失败: {e}")
                return default_config
        
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                logger.info(f"成功加载配置文件: {file_path.name}")
                return data
        except Exception as e:
            logger.error(f"加载配置文件 {file_path} 失败: {e}")
            return default_config

    def _load_items_data(self, file_path: Path) -> Dict[str, dict]:
        """加载物品配置文件并转换为字典（key为物品名称）"""
        if not file_path.exists():
            logger.warning(f"物品数据文件 {file_path} 不存在，将使用空数据。")
            return {}
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)

                if isinstance(data, list):
                    items_dict = {item.get("name", ""): item for item in data if isinstance(item, dict) and item.get("name")}
                elif isinstance(data, dict):
                    items_dict = {}
                    for item_id, item_data in data.items():
                        if isinstance(item_data, dict) and item_data.get("name"):
                            if "id" not in item_data:
                                item_data["id"] = item_id
                            items_dict[item_data["name"]] = item_data
                else:
                    logger.error(f"物品数据文件 {file_path} 格式不正确，应该是数组或字典。")
                    return {}

                logger.info(f"成功加载 {file_path.name} (共 {len(items_dict)} 个物品)。")
                return items_dict
        except Exception as e:
            logger.error(f"加载物品数据文件 {file_path} 失败: {e}")
            return {}

    def _load_all(self):
        """加载所有配置文件"""
        config_dir = self._base_dir / "config"
        
        # 加载基础配置
        self.level_data = self._load_json_data(config_dir / "level_config.json")
        self.body_level_data = self._load_json_data(config_dir / "body_level_config.json")
        self.items_data = self._load_items_data(config_dir / "items.json")
        self.weapons_data = self._load_items_data(config_dir / "weapons.json")
        self.pills_data = self._load_items_data(config_dir / "pills.json")
        self.exp_pills_data = self._load_items_data(config_dir / "exp_pills.json")
        self.utility_pills_data = self._load_items_data(config_dir / "utility_pills.json")
        self.storage_rings_data = self._load_items_data(config_dir / "storage_rings.json")
        
        # 加载技能和功法配置
        self.skills_data = self._load_json("skills.json")
        self.techniques_data = self._load_json("techniques.json")
        
        # 加载新系统配置
        self.sect_config = self._load_config_with_default(config_dir / "sect_config.json", SECT_CONFIG)
        self.boss_config = self._load_config_with_default(config_dir / "boss_config.json", BOSS_CONFIG)
        self.rift_config = self._load_config_with_default(config_dir / "rift_config.json", RIFT_CONFIG)
        self.alchemy_config = self._load_config_with_default(config_dir / "alchemy_config.json", ALCHEMY_CONFIG)
        self.alchemy_recipes = self._load_items_data(config_dir / "alchemy_recipes.json")
        
        # 加载游戏配置（包含各系统的硬编码参数）
        self.game_config = self._load_config_with_default(config_dir / "game_config.json", {})
        
        self._pill_names_cache = None

        logger.info(
            f"配置管理器初始化完成，"
            f"加载了 {len(self.level_data)} 个灵修境界配置，"
            f"{len(self.body_level_data)} 个体修境界配置，"
            f"{len(self.skills_data)} 个技能配置，"
            f"{len(self.techniques_data)} 个功法配置，"
            f"以及新系统配置 (宗门/Boss/秘境/炼丹)"
        )
    
    # ==================== 物品和武器相关方法 ====================
    
    def get_items_config(self) -> Dict[str, dict]:
        """获取物品配置
        
        Returns:
            物品配置字典，key为物品名称
        """
        return self.items_data
    
    def get_weapons_config(self) -> Dict[str, dict]:
        """获取武器配置
        
        Returns:
            武器配置字典，key为武器名称
        """
        return self.weapons_data
    
    # ==================== 技能相关方法 ====================
    
    def get_skill_by_id(self, skill_id: str) -> Optional[dict]:
        """根据技能ID获取技能配置
        
        Args:
            skill_id: 技能ID
            
        Returns:
            技能配置字典，如果找不到返回None
        """
        return self.skills_data.get(skill_id)
    
    def get_skill_by_name(self, skill_name: str) -> Optional[dict]:
        """根据技能名称获取技能配置
        
        Args:
            skill_name: 技能名称
            
        Returns:
            技能配置字典，如果找不到返回None
        """
        for skill_id, skill_config in self.skills_data.items():
            if skill_config.get("name") == skill_name:
                return skill_config
        return None
    
    def get_all_skills(self) -> Dict[str, dict]:
        """获取所有技能配置
        
        Returns:
            技能配置字典，key为技能ID
        """
        return self.skills_data
    
    # ==================== 功法相关方法 ====================
    
    def get_technique_by_id(self, technique_id: str) -> Optional[dict]:
        """根据功法ID获取功法配置
        
        Args:
            technique_id: 功法ID
            
        Returns:
            功法配置字典，如果找不到返回None
        """
        return self.techniques_data.get(technique_id)
    
    def get_technique_by_name(self, name: str) -> Optional[dict]:
        """根据功法名称获取功法配置
        
        Args:
            name: 功法名称
            
        Returns:
            功法配置字典，如果找不到返回None
        """
        # 首先尝试直接用名称作为ID查找
        if name in self.techniques_data:
            return self.techniques_data[name]
        
        # 然后遍历查找name字段匹配的
        for tech_id, tech_config in self.techniques_data.items():
            if tech_config.get("name") == name:
                return tech_config
        
        return None
    
    def get_all_techniques(self) -> Dict[str, dict]:
        """获取所有功法配置
        
        Returns:
            功法配置字典，key为功法ID
        """
        return self.techniques_data
    
    def get_techniques_config(self) -> Dict[str, dict]:
        """获取功法配置（兼容旧接口）
        
        Returns:
            功法配置字典
        """
        return self.techniques_data
    
    # ==================== 境界相关方法 ====================
    
    def get_level_config(self) -> Dict[str, dict]:
        """获取灵修境界配置（字典格式，key为level_index字符串）
        
        Returns:
            境界配置字典
        """
        result = {}
        for i, level in enumerate(self.level_data):
            result[str(i)] = level
        return result
    
    def get_body_level_config(self) -> Dict[str, dict]:
        """获取体修境界配置（字典格式，key为level_index字符串）
        
        Returns:
            境界配置字典
        """
        result = {}
        for i, level in enumerate(self.body_level_data):
            result[str(i)] = level
        return result
    
    # ==================== 丹药相关方法 ====================
    
    def is_pill(self, item_name: str) -> bool:
        """检查物品是否为丹药类型（统一的丹药判断方法）"""
        if item_name in self.pills_data:
            return True
        if item_name in self.exp_pills_data:
            return True
        if item_name in self.utility_pills_data:
            return True
        
        item_config = self.items_data.get(item_name)
        if item_config and item_config.get("type") == "丹药":
            return True
        
        return False
    
    def get_all_pill_names(self) -> set:
        """获取所有注册的丹药名称"""
        if self._pill_names_cache is not None:
            return self._pill_names_cache
        
        pill_names = set()
        pill_names.update(self.pills_data.keys())
        pill_names.update(self.exp_pills_data.keys())
        pill_names.update(self.utility_pills_data.keys())
        
        for name, item in self.items_data.items():
            if isinstance(item, dict) and item.get("type") == "丹药":
                pill_names.add(name)
        
        self._pill_names_cache = pill_names
        return pill_names
    
    def invalidate_cache(self):
        """清除缓存，在配置重载时调用"""
        self._pill_names_cache = None
