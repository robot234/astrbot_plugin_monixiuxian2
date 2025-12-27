# managers/alchemy_manager.py
"""
炼丹系统管理器 - 处理炼丹、配方等逻辑（简化版）
"""

import random
from typing import Tuple, List, Dict, Optional, TYPE_CHECKING
from ..data.data_manager import DataBase
from ..models import Player
from ..models_extended import UserStatus

if TYPE_CHECKING:
    from ..config_manager import ConfigManager
    from ..core import StorageRingManager


class AlchemyManager:
    """炼丹系统管理器（简化版）"""
    
    # 丹药配方（简化版本）
    PILL_RECIPES = {
        1: {
            "id": 1,
            "name": "聚气丹",
            "level_required": 0,
            "materials": {"灵草": 3, "灵石": 100},
            "success_rate": 80,
            "effect": {"type": "exp", "value": 1000},
            "desc": "增加1000修为"
        },
        2: {
            "id": 2,
            "name": "筑基丹",
            "level_required": 2,
            "materials": {"灵草": 5, "灵石": 500},
            "success_rate": 60,
            "effect": {"type": "exp", "value": 5000},
            "desc": "增加5000修为"
        },
        3: {
            "id": 3,
            "name": "金丹",
            "level_required": 5,
            "materials": {"灵草": 10, "灵石": 2000},
            "success_rate": 40,
            "effect": {"type": "exp", "value": 20000},
            "desc": "增加20000修为"
        },
        4: {
            "id": 4,
            "name": "回春丹",
            "level_required": 1,
            "materials": {"灵草": 2, "灵石": 200},
            "success_rate": 70,
            "effect": {"type": "hp_restore", "value": 50},
            "desc": "恢复50%气血"
        },
        5: {
            "id": 5,
            "name": "聚灵丹",
            "level_required": 1,
            "materials": {"灵草": 2, "灵石": 200},
            "success_rate": 70,
            "effect": {"type": "mp_restore", "value": 50},
            "desc": "恢复50%真元"
        },
    }
    
    def __init__(self, db: DataBase, config_manager: "ConfigManager" = None, storage_ring_manager: "StorageRingManager" = None):
        self.db = db
        self.config_manager = config_manager
        self.storage_ring_manager = storage_ring_manager
        self.config = config_manager.alchemy_config if config_manager else {}
        
        # 加载配方（处理key类型和字段兼容性）
        raw_recipes = self.config.get("recipes", self.PILL_RECIPES)
        self.recipes = {}
        for k, v in raw_recipes.items():
            try:
                recipe_id = int(k)
                # 标准化配方字段（兼容旧格式）
                self.recipes[recipe_id] = self._normalize_recipe(recipe_id, v)
            except ValueError:
                continue
    
    def _normalize_recipe(self, recipe_id: int, recipe: Dict) -> Dict:
        """标准化配方字段，兼容不同格式的配置"""
        # 默认效果映射
        default_effects = {
            "聚气丹": {"type": "exp", "value": 1000, "desc": "增加1000修为"},
            "筑基丹": {"type": "exp", "value": 5000, "desc": "增加5000修为"},
            "金丹": {"type": "exp", "value": 20000, "desc": "增加20000修为"},
            "回春丹": {"type": "hp_restore", "value": 50, "desc": "恢复50%气血"},
            "聚灵丹": {"type": "mp_restore", "value": 50, "desc": "恢复50%真元"},
        }
        
        name = recipe.get("name", f"丹药{recipe_id}")
        effect_info = default_effects.get(name, {"type": "exp", "value": 1000, "desc": "增加修为"})
        
        return {
            "id": recipe.get("id", recipe_id),
            "name": name,
            "level_required": recipe.get("level_required", recipe.get("level", 0)),
            "materials": recipe.get("materials", recipe.get("cost", {})),
            "success_rate": recipe.get("success_rate", recipe.get("success", 50)),
            "effect": recipe.get("effect", {"type": effect_info["type"], "value": effect_info["value"]}),
            "desc": recipe.get("desc", effect_info["desc"])
        }
    
    async def get_available_recipes(self, user_id: str) -> Tuple[bool, str]:
        """
        获取可用的丹药配方
        
        Args:
            user_id: 用户ID
            
        Returns:
            (成功标志, 消息)
        """
        player = await self.db.get_player_by_id(user_id)
        if not player:
            return False, "❌ 你还未踏入修仙之路！"
        
        available_recipes = []
        for recipe_id, recipe in self.recipes.items():
            if player.level_index >= recipe.get("level_required", 0):
                available_recipes.append(recipe)
        
        if not available_recipes:
            return False, "❌ 你当前境界无法炼制任何丹药！"
        
        msg = "🔥 丹药配方\n"
        msg += "━━━━━━━━━━━━━━━\n\n"
        
        for recipe in available_recipes:
            materials_str = ", ".join([f"{k}×{v}" for k, v in recipe["materials"].items()])
            msg += f"【{recipe['name']}】(ID:{recipe['id']})\n"
            msg += f"  需求境界：Lv.{recipe['level_required']}\n"
            msg += f"  材料：{materials_str}\n"
            msg += f"  成功率：{recipe['success_rate']}%\n"
            msg += f"  效果：{recipe['desc']}\n\n"
        
        msg += "使用 /炼丹 <丹药ID> 开始炼制"
        
        return True, msg
    
    async def craft_pill(
        self,
        user_id: str,
        pill_id: int
    ) -> Tuple[bool, str, Optional[Dict]]:
        """
        炼制丹药
        
        Args:
            user_id: 用户ID
            pill_id: 丹药ID
            
        Returns:
            (成功标志, 消息, 结果数据)
        """
        # 1. 检查用户
        player = await self.db.get_player_by_id(user_id)
        if not player:
            return False, "❌ 你还未踏入修仙之路！", None
        
        # 2. 检查用户状态（状态互斥）
        user_cd = await self.db.ext.get_user_cd(user_id)
        if user_cd and user_cd.type != UserStatus.IDLE:
            current_status = UserStatus.get_name(user_cd.type)
            return False, f"❌ 你当前正{current_status}，无法炼丹！", None
        
        # 3. 检查配方
        if pill_id not in self.recipes:
            return False, "❌ 无效的丹药ID！", None
        
        recipe = self.recipes[pill_id]
        
        # 3. 检查境界要求
        if player.level_index < recipe["level_required"]:
            return False, f"❌ 炼制{recipe['name']}需要达到境界等级 {recipe['level_required']}！", None
        
        # 4. 检查所有材料
        materials = recipe["materials"]
        missing_materials = []
        
        # 检查灵石
        required_gold = materials.get("灵石", 0)
        if player.gold < required_gold:
            missing_materials.append(f"灵石（需要{required_gold}，拥有{player.gold}）")
        
        # 检查储物戒中的材料
        if self.storage_ring_manager:
            for material_name, required_count in materials.items():
                if material_name == "灵石":
                    continue
                current_count = self.storage_ring_manager.get_item_count(player, material_name)
                if current_count < required_count:
                    missing_materials.append(f"{material_name}（需要{required_count}，拥有{current_count}）")
        else:
            # 没有储物戒管理器时，跳过其他材料检查（兼容旧逻辑）
            pass
        
        if missing_materials:
            return False, f"❌ 材料不足！\n" + "\n".join(f"  · {m}" for m in missing_materials), None
        
        # 5. 扣除所有材料
        player.gold -= required_gold
        
        # 扣除储物戒中的材料
        consumed_materials = []
        if self.storage_ring_manager:
            for material_name, required_count in materials.items():
                if material_name == "灵石":
                    continue
                success, _ = await self.storage_ring_manager.retrieve_item(player, material_name, required_count)
                if success:
                    consumed_materials.append(f"{material_name}×{required_count}")
        
        # 6. 判断成功率
        success_rate = recipe["success_rate"]
        # 境界加成：每高一级境界，成功率+2%
        level_bonus = (player.level_index - recipe["level_required"]) * 2
        final_success_rate = min(95, success_rate + level_bonus)
        
        roll = random.randint(1, 100)
        is_success = roll <= final_success_rate
        
        if is_success:
            # 炼制成功
            effect_type = recipe["effect"]["type"]
            effect_value = recipe["effect"]["value"]
            
            # 应用效果（简化版本，直接给修为或恢复HP/MP）
            if effect_type == "exp":
                player.experience += effect_value
                effect_msg = f"修为 +{effect_value:,}"
            elif effect_type == "hp_restore":
                if player.hp > 0:
                    max_hp = player.experience // 2
                    restore_amount = int(max_hp * effect_value / 100)
                    player.hp = min(max_hp, player.hp + restore_amount)
                    effect_msg = f"气血恢复 +{restore_amount}"
                else:
                    effect_msg = "气血已恢复"
            elif effect_type == "mp_restore":
                if player.mp > 0:
                    max_mp = player.experience
                    restore_amount = int(max_mp * effect_value / 100)
                    player.mp = min(max_mp, player.mp + restore_amount)
                    effect_msg = f"真元恢复 +{restore_amount}"
                else:
                    effect_msg = "真元已恢复"
            else:
                effect_msg = "未知效果"
            
            await self.db.update_player(player)
            
            # 构建消耗材料显示
            cost_lines = []
            if required_gold > 0:
                cost_lines.append(f"灵石 -{required_gold}")
            cost_lines.extend(consumed_materials)
            cost_str = "、".join(cost_lines) if cost_lines else "无"
            
            msg = f"""
🎉 炼丹成功！
━━━━━━━━━━━━━━━

你成功炼制了【{recipe['name']}】！

{effect_msg}

消耗：{cost_str}
成功率：{final_success_rate}%
            """.strip()
            
            result_data = {
                "success": True,
                "pill_name": recipe["name"],
                "effect": effect_msg,
                "cost": required_gold,
                "materials_consumed": consumed_materials
            }
        else:
            # 炼制失败
            await self.db.update_player(player)
            
            # 构建消耗材料显示
            cost_lines = []
            if required_gold > 0:
                cost_lines.append(f"灵石 -{required_gold}")
            cost_lines.extend(consumed_materials)
            cost_str = "、".join(cost_lines) if cost_lines else "无"
            
            msg = f"""
💔 炼丹失败
━━━━━━━━━━━━━━━

炼制【{recipe['name']}】失败了...

材料已消耗
消耗：{cost_str}
成功率：{final_success_rate}%

再接再厉！
            """.strip()
            
            result_data = {
                "success": False,
                "pill_name": recipe["name"],
                "cost": required_gold,
                "materials_consumed": consumed_materials
            }
        
        return True, msg, result_data
    
    async def use_pill(
        self,
        user_id: str,
        pill_name: str
    ) -> Tuple[bool, str]:
        """
        使用丹药（简化版本，实际应该从背包系统中使用）
        
        Args:
            user_id: 用户ID
            pill_name: 丹药名称
            
        Returns:
            (成功标志, 消息)
        """
        # 这是一个占位方法，实际应该与背包系统集成
        return False, "❌ 此功能尚未完全实现，请先炼制丹药！"
