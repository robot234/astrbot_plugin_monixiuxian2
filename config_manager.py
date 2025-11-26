# config_manager.py

import json
from pathlib import Path
from typing import List, Dict

from astrbot.api import logger

class ConfigManager:
    """配置管理器，加载境界、物品、武器和丹药配置"""

    def __init__(self, base_dir: Path):
        self._base_dir = base_dir
        self.level_data: List[dict] = []
        self.items_data: Dict[str, dict] = {}  # 物品数据，key为物品名称
        self.weapons_data: Dict[str, dict] = {}  # 武器数据，key为武器名称
        self.pills_data: Dict[str, dict] = {}  # 破境丹数据，key为丹药名称
        self.exp_pills_data: Dict[str, dict] = {}  # 修为丹数据，key为丹药名称
        self.utility_pills_data: Dict[str, dict] = {}  # 功能丹数据，key为丹药名称
        self._load_all()

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

    def _load_items_data(self, file_path: Path) -> Dict[str, dict]:
        """加载物品配置文件并转换为字典（key为物品名称）"""
        if not file_path.exists():
            logger.warning(f"物品数据文件 {file_path} 不存在，将使用空数据。")
            return {}
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)

                # 支持两种格式：
                # 1. 数组格式：[{"name": "xxx", ...}, ...]
                # 2. 字典格式：{"1001": {"name": "xxx", ...}, ...}
                if isinstance(data, list):
                    # 数组格式，直接转换为以name为key的字典
                    items_dict = {item.get("name", ""): item for item in data if isinstance(item, dict) and item.get("name")}
                elif isinstance(data, dict):
                    # 字典格式（以ID为key），转换为以name为key的字典
                    items_dict = {}
                    for item_id, item_data in data.items():
                        if isinstance(item_data, dict) and item_data.get("name"):
                            # 添加id字段（如果没有的话）
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
        level_path = self._base_dir / "config" / "level_config.json"
        self.level_data = self._load_json_data(level_path)

        items_path = self._base_dir / "config" / "items.json"
        self.items_data = self._load_items_data(items_path)

        weapons_path = self._base_dir / "config" / "weapons.json"
        self.weapons_data = self._load_items_data(weapons_path)

        pills_path = self._base_dir / "config" / "pills.json"
        self.pills_data = self._load_items_data(pills_path)

        exp_pills_path = self._base_dir / "config" / "exp_pills.json"
        self.exp_pills_data = self._load_items_data(exp_pills_path)

        utility_pills_path = self._base_dir / "config" / "utility_pills.json"
        self.utility_pills_data = self._load_items_data(utility_pills_path)

        logger.info(
            f"配置管理器初始化完成，"
            f"加载了 {len(self.level_data)} 个境界配置，"
            f"{len(self.items_data)} 个物品配置，"
            f"{len(self.weapons_data)} 个武器配置，"
            f"{len(self.pills_data)} 个破境丹配置，"
            f"{len(self.exp_pills_data)} 个修为丹配置，"
            f"{len(self.utility_pills_data)} 个功能丹配置"
        )
