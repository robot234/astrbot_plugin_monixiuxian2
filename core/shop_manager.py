# core/shop_manager.py

import random
import time
import json
from typing import List, Dict, Optional, Tuple

from astrbot.api import AstrBotConfig, logger
from ..config_manager import ConfigManager
from ..models import Item

class ShopManager:
    """商店管理器，负责商店物品生成、刷新和购买"""

    def __init__(self, config: AstrBotConfig, config_manager: ConfigManager):
        self.config = config
        self.config_manager = config_manager

    def _get_all_shop_items(self) -> List[Dict]:
        """获取所有可以在商店出售的物品"""
        all_items = []

        # 添加武器
        for weapon in self.config_manager.weapons_data.values():
            if weapon.get('shop_weight', 0) > 0 and weapon.get('price', 0) > 0:
                all_items.append({
                    'id': weapon['id'],
                    'name': weapon['name'],
                    'type': 'weapon',
                    'price': weapon['price'],
                    'weight': weapon['shop_weight'],
                    'rank': weapon.get('rank', '凡品'),
                    'data': weapon
                })

        # 添加物品（防具、心法、功法）
        for item in self.config_manager.items_data.values():
            if item.get('shop_weight', 0) > 0 and item.get('price', 0) > 0:
                all_items.append({
                    'id': item.get('id', item['name']),
                    'name': item['name'],
                    'type': item['type'],
                    'price': item['price'],
                    'weight': item['shop_weight'],
                    'rank': item.get('rank', '凡品'),
                    'data': item
                })

        # 添加破境丹
        for pill in self.config_manager.pills_data.values():
            if pill.get('shop_weight', 0) > 0 and pill.get('price', 0) > 0:
                all_items.append({
                    'id': pill['id'],
                    'name': pill['name'],
                    'type': 'pill',
                    'price': pill['price'],
                    'weight': pill['shop_weight'],
                    'rank': pill.get('rank', '凡品'),
                    'data': pill
                })

        # 添加修为丹
        for pill in self.config_manager.exp_pills_data.values():
            if pill.get('shop_weight', 0) > 0 and pill.get('price', 0) > 0:
                all_items.append({
                    'id': pill['id'],
                    'name': pill['name'],
                    'type': 'exp_pill',
                    'price': pill['price'],
                    'weight': pill['shop_weight'],
                    'rank': pill.get('rank', '凡品'),
                    'data': pill
                })

        # 添加功能丹
        for pill in self.config_manager.utility_pills_data.values():
            if pill.get('shop_weight', 0) > 0 and pill.get('price', 0) > 0:
                all_items.append({
                    'id': pill['id'],
                    'name': pill['name'],
                    'type': 'utility_pill',
                    'price': pill['price'],
                    'weight': pill['shop_weight'],
                    'rank': pill.get('rank', '凡品'),
                    'data': pill
                })

        return all_items

    def _weighted_random_choice(self, items: List[Dict], count: int) -> List[Dict]:
        """基于权重的随机选择（不重复）"""
        if len(items) <= count:
            return items.copy()

        selected = []
        available_items = items.copy()

        for _ in range(count):
            if not available_items:
                break

            # 计算总权重
            total_weight = sum(item['weight'] for item in available_items)
            if total_weight == 0:
                # 如果所有权重都是0，则随机选择
                choice = random.choice(available_items)
            else:
                # 基于权重选择
                rand = random.uniform(0, total_weight)
                cumulative = 0
                choice = available_items[0]
                for item in available_items:
                    cumulative += item['weight']
                    if rand <= cumulative:
                        choice = item
                        break

            selected.append(choice)
            available_items.remove(choice)

        return selected

    def generate_shop_items(self, count: int) -> List[Dict]:
        """生成商店物品列表

        Args:
            count: 要生成的物品数量

        Returns:
            商店物品列表，每个物品包含 id, name, type, price, discount, final_price
        """
        all_items = self._get_all_shop_items()
        if not all_items:
            logger.warning("没有可用的商店物品")
            return []

        # 随机选择物品
        selected_items = self._weighted_random_choice(all_items, count)

        # 获取折扣配置
        discount_min = self.config.get("SHOP_DISCOUNT_MIN", 0.8)
        discount_max = self.config.get("SHOP_DISCOUNT_MAX", 1.2)

        # 生成商店物品
        shop_items = []
        for item in selected_items:
            # 随机折扣
            discount = random.uniform(discount_min, discount_max)
            final_price = int(item['price'] * discount)

            shop_items.append({
                'id': item['id'],
                'name': item['name'],
                'type': item['type'],
                'rank': item['rank'],
                'original_price': item['price'],
                'discount': discount,
                'price': final_price,
                'data': item['data']
            })

        return shop_items

    def should_refresh_shop(self, last_refresh_time: int) -> bool:
        """检查商店是否需要刷新

        Args:
            last_refresh_time: 上次刷新时间（Unix时间戳）

        Returns:
            是否需要刷新
        """
        refresh_hours = self.config.get("SHOP_REFRESH_HOURS", 6)
        if refresh_hours <= 0:
            return False

        current_time = int(time.time())
        time_diff = current_time - last_refresh_time
        refresh_interval = refresh_hours * 3600  # 转换为秒

        return time_diff >= refresh_interval

    def format_shop_display(self, shop_items: List[Dict]) -> str:
        """格式化商店展示信息

        Args:
            shop_items: 商店物品列表

        Returns:
            格式化的商店展示文本
        """
        if not shop_items:
            return "商店暂无物品出售"

        lines = ["=== 修仙商店 ===\n"]

        for idx, item in enumerate(shop_items, 1):
            discount_text = ""
            if item['discount'] < 1.0:
                discount_percent = int((1.0 - item['discount']) * 100)
                discount_text = f" [{discount_percent}%折]"
            elif item['discount'] > 1.0:
                price_increase = int((item['discount'] - 1.0) * 100)
                discount_text = f" [+{price_increase}%]"

            # 物品类型标签
            type_label = {
                'weapon': '武器',
                'armor': '防具',
                'main_technique': '心法',
                'technique': '功法',
                'pill': '破境丹',
                'exp_pill': '修为丹',
                'utility_pill': '功能丹',
                '丹药': '丹药'
            }.get(item['type'], '物品')

            line = f"{idx}. [{item['rank']}] {item['name']} ({type_label}){discount_text}\n"
            line += f"   价格: {item['price']} 灵石"

            if item['original_price'] != item['price']:
                line += f" (原价: {item['original_price']})"

            lines.append(line + "\n")

        lines.append(f"\n提示: 使用 '购买 [物品名]' 购买物品")
        return "".join(lines)

    def get_item_details(self, item_data: Dict) -> str:
        """获取物品详细信息

        Args:
            item_data: 物品数据字典

        Returns:
            物品详细描述
        """
        item_type = item_data.get('type', '')
        data = item_data.get('data', {})

        details = [f"名称: {item_data['name']}"]
        details.append(f"品级: {item_data['rank']}")
        details.append(f"价格: {item_data['price']} 灵石")

        # 添加描述
        if 'description' in data:
            details.append(f"描述: {data['description']}")

        # 添加属性信息
        if item_type == 'weapon':
            attrs = []
            if data.get('magic_damage', 0) > 0:
                attrs.append(f"法伤+{data['magic_damage']}")
            if data.get('physical_damage', 0) > 0:
                attrs.append(f"物伤+{data['physical_damage']}")
            if data.get('magic_defense', 0) > 0:
                attrs.append(f"法防+{data['magic_defense']}")
            if data.get('physical_defense', 0) > 0:
                attrs.append(f"物防+{data['physical_defense']}")
            if data.get('mental_power', 0) > 0:
                attrs.append(f"精神力+{data['mental_power']}")
            if attrs:
                details.append(f"属性: {', '.join(attrs)}")
            if 'required_level_index' in data:
                level_name = "炼气期"
                if data['required_level_index'] < len(self.config_manager.level_data):
                    level_name = self.config_manager.level_data[data['required_level_index']]['level_name']
                details.append(f"需求境界: {level_name}")

        elif item_type in ['armor', 'main_technique', 'technique']:
            attrs = []
            if data.get('magic_damage', 0) > 0:
                attrs.append(f"法伤+{data['magic_damage']}")
            if data.get('physical_damage', 0) > 0:
                attrs.append(f"物伤+{data['physical_damage']}")
            if data.get('magic_defense', 0) > 0:
                attrs.append(f"法防+{data['magic_defense']}")
            if data.get('physical_defense', 0) > 0:
                attrs.append(f"物防+{data['physical_defense']}")
            if data.get('mental_power', 0) > 0:
                attrs.append(f"精神力+{data['mental_power']}")
            if item_type == 'main_technique':
                if data.get('exp_multiplier', 0) > 0:
                    attrs.append(f"修为倍率+{data['exp_multiplier']:.1%}")
                if data.get('spiritual_qi', 0) > 0:
                    attrs.append(f"灵气+{data['spiritual_qi']}")
            if attrs:
                details.append(f"属性: {', '.join(attrs)}")

        elif item_type in ['pill', 'exp_pill', 'utility_pill']:
            if 'required_level_index' in data and data['required_level_index'] > 0:
                level_name = "炼气期"
                if data['required_level_index'] < len(self.config_manager.level_data):
                    level_name = self.config_manager.level_data[data['required_level_index']]['level_name']
                details.append(f"需求境界: {level_name}")

        return "\n".join(details)
