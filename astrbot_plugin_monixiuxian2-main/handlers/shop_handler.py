# handlers/shop_handler.py

import time
import re
from astrbot.api.event import AstrMessageEvent
from astrbot.api import AstrBotConfig, logger
from ..data import DataBase
from ..core import ShopManager, EquipmentManager, PillManager, StorageRingManager
from ..core.skill_manager import SkillManager
from ..models import Player
from ..config_manager import ConfigManager
from .utils import player_required

__all__ = ["ShopHandler"]

class ShopHandler:
    """商店处理器"""
    
    ITEM_ACQUIRE_HINTS = {
        'pill': "丹阁刷新、秘境稀有掉落",
        'exp_pill': "丹阁、炼丹系统、历练/秘境奖励",
        'utility_pill': "丹阁稀有、秘境/Boss 掉落",
        'legacy_pill': "百宝阁限量，购买后立即生效",
        'weapon': "器阁、Boss 掉落",
        'armor': "器阁、Boss 掉落",
        'accessory': "器阁、Boss 掉落",
        'main_technique': "百宝阁稀有刷新",
        'technique': "百宝阁、Boss 掉落",
        'skill_book': "百宝阁刷新、秘境/Boss 掉落",
        'material': "历练、秘境、悬赏、灵田收获与百宝阁限量",
    }

    def __init__(self, db: DataBase, config: AstrBotConfig, config_manager: ConfigManager):
        self.db = db
        self.config = config
        self.config_manager = config_manager
        self.shop_manager = ShopManager(config, config_manager)
        self.storage_ring_manager = StorageRingManager(db, config_manager)
        self.equipment_manager = EquipmentManager(db, config_manager, self.storage_ring_manager)
        self.pill_manager = PillManager(db, config_manager)
        self.skill_manager = SkillManager(db, config_manager)
        access_control = self.config.get("ACCESS_CONTROL", {})
        self.shop_manager_ids = {
            str(user_id)
            for user_id in access_control.get("SHOP_MANAGERS", [])
        }

    async def _ensure_pavilion_refreshed(self, pavilion_id: str, item_getter, count: int) -> None:
        """确保阁楼已刷新"""
        last_refresh_time, current_items = await self.db.get_shop_data(pavilion_id)
        if current_items:
            updated = self.shop_manager.ensure_items_have_stock(current_items)
            if updated:
                await self.db.update_shop_data(pavilion_id, last_refresh_time, current_items)
        refresh_hours = self.config.get("PAVILION_REFRESH_HOURS", 1)
        if not current_items or self.shop_manager.should_refresh_shop(last_refresh_time, refresh_hours):
            new_items = self.shop_manager.generate_pavilion_items(item_getter, count)
            await self.db.update_shop_data(pavilion_id, int(time.time()), new_items)

    async def _ensure_treasure_pavilion_refreshed(self) -> None:
        """确保百宝阁已刷新（特殊逻辑：技能书+功法+材料，不含丹药和武器防具）"""
        pavilion_id = "treasure_pavilion"
        last_refresh_time, current_items = await self.db.get_shop_data(pavilion_id)
        if current_items:
            updated = self.shop_manager.ensure_items_have_stock(current_items)
            if updated:
                await self.db.update_shop_data(pavilion_id, last_refresh_time, current_items)
        refresh_hours = self.config.get("PAVILION_REFRESH_HOURS", 1)
        if not current_items or self.shop_manager.should_refresh_shop(last_refresh_time, refresh_hours):
            new_items = self._generate_treasure_pavilion_items()
            await self.db.update_shop_data(pavilion_id, int(time.time()), new_items)

    def _generate_treasure_pavilion_items(self) -> list:
        """生成百宝阁物品列表（技能书+功法+材料，不含丹药和武器防具）"""
        import random
        
        items = []
        
        # 1. 添加技能书（从 skills.json）
        skill_count = self.config.get("TREASURE_PAVILION_SKILL_COUNT", 8)
        skills_data = self.config_manager.get_all_skills()
        
        if skills_data:
            skill_list = list(skills_data.values())
            # 按权重随机选择
            weights = [s.get("shop_weight", 100) for s in skill_list]
            selected_skills = []
            
            for _ in range(min(skill_count, len(skill_list))):
                if not skill_list:
                    break
                # 加权随机选择
                total_weight = sum(weights)
                if total_weight <= 0:
                    break
                r = random.uniform(0, total_weight)
                cumulative = 0
                for i, (skill, weight) in enumerate(zip(skill_list, weights)):
                    cumulative += weight
                    if r <= cumulative:
                        selected_skills.append(skill)
                        skill_list.pop(i)
                        weights.pop(i)
                        break
            
            for skill in selected_skills:
                items.append({
                    'name': f"{skill.get('name', '未知技能')}秘籍",
                    'type': 'skill_book',
                    'skill_id': skill.get('id', ''),
                    'skill_name': skill.get('name', ''),
                    'rank': self._get_skill_rank(skill),
                    'price': skill.get('price', 1000),
                    'stock': 1,
                    'description': skill.get('description', ''),
                    'required_level_index': skill.get('required_level_index', 0),
                    'damage_type': skill.get('damage_type', 'physical'),
                })
        
        # 2. 添加功法（从 techniques.json）
        technique_count = self.config.get("TREASURE_PAVILION_TECHNIQUE_COUNT", 6)
        techniques_data = self.config_manager.get_all_techniques()
        
        if techniques_data:
            technique_list = list(techniques_data.values())
            weights = [t.get("shop_weight", 100) for t in technique_list]
            selected_techniques = []
            
            for _ in range(min(technique_count, len(technique_list))):
                if not technique_list:
                    break
                total_weight = sum(weights)
                if total_weight <= 0:
                    break
                r = random.uniform(0, total_weight)
                cumulative = 0
                for i, (tech, weight) in enumerate(zip(technique_list, weights)):
                    cumulative += weight
                    if r <= cumulative:
                        selected_techniques.append(tech)
                        technique_list.pop(i)
                        weights.pop(i)
                        break
            
            for tech in selected_techniques:
                tech_type = tech.get('type', 'technique')
                items.append({
                    'name': tech.get('name', '未知功法'),
                    'type': tech_type,
                    'technique_id': tech.get('id', ''),
                    'rank': tech.get('rank', '凡品'),
                    'price': tech.get('price', 500),
                    'stock': 1,
                    'description': tech.get('description', ''),
                    'required_level_index': tech.get('required_level_index', 0),
                    'exp_multiplier': tech.get('exp_multiplier', 0),
                })
        
        # 3. 添加材料（从 items.json 中筛选）
        material_count = self.config.get("TREASURE_PAVILION_MATERIAL_COUNT", 5)
        materials = []
        for name, item in self.config_manager.items_data.items():
            if isinstance(item, dict) and item.get('type') == 'material':
                materials.append(item)
        
        if materials:
            weights = [m.get("shop_weight", 100) for m in materials]
            selected_materials = []
            
            for _ in range(min(material_count, len(materials))):
                if not materials:
                    break
                total_weight = sum(weights)
                if total_weight <= 0:
                    break
                r = random.uniform(0, total_weight)
                cumulative = 0
                for i, (mat, weight) in enumerate(zip(materials, weights)):
                    cumulative += weight
                    if r <= cumulative:
                        selected_materials.append(mat)
                        materials.pop(i)
                        weights.pop(i)
                        break
            
            for mat in selected_materials:
                items.append({
                    'name': mat.get('name', '未知材料'),
                    'type': 'material',
                    'rank': mat.get('rank', '普通'),
                    'price': mat.get('price', 100),
                    'stock': random.randint(1, 5),
                    'description': mat.get('description', ''),
                })
        
        # 4. 添加其他特殊物品（储物戒等）
        special_count = self.config.get("TREASURE_PAVILION_SPECIAL_COUNT", 3)
        special_items = []
        
        # 从储物戒配置中获取
        for name, ring in self.config_manager.storage_rings_data.items():
            if isinstance(ring, dict):
                special_items.append({
                    'name': ring.get('name', name),
                    'type': 'storage_ring',
                    'rank': ring.get('rank', '凡品'),
                    'price': ring.get('price', 1000),
                    'capacity': ring.get('capacity', 10),
                    'description': ring.get('description', ''),
                    'shop_weight': ring.get('shop_weight', 50),
                })
        
        if special_items:
            weights = [s.get("shop_weight", 50) for s in special_items]
            selected_special = []
            
            for _ in range(min(special_count, len(special_items))):
                if not special_items:
                    break
                total_weight = sum(weights)
                if total_weight <= 0:
                    break
                r = random.uniform(0, total_weight)
                cumulative = 0
                for i, (sp, weight) in enumerate(zip(special_items, weights)):
                    cumulative += weight
                    if r <= cumulative:
                        selected_special.append(sp)
                        special_items.pop(i)
                        weights.pop(i)
                        break
            
            for sp in selected_special:
                items.append({
                    'name': sp.get('name', '未知物品'),
                    'type': sp.get('type', 'special'),
                    'rank': sp.get('rank', '凡品'),
                    'price': sp.get('price', 1000),
                    'stock': 1,
                    'description': sp.get('description', ''),
                    'capacity': sp.get('capacity', 0),
                })
        
        # 随机打乱顺序
        random.shuffle(items)
        
        return items
    
    def _get_skill_rank(self, skill: dict) -> str:
        """根据技能属性推断品级"""
        required_level = skill.get('required_level_index', 0)
        price = skill.get('price', 0)
        
        if required_level >= 20 or price >= 50000:
            return "仙品"
        elif required_level >= 15 or price >= 20000:
            return "帝品"
        elif required_level >= 10 or price >= 10000:
            return "皇品"
        elif required_level >= 7 or price >= 5000:
            return "天品"
        elif required_level >= 4 or price >= 2000:
            return "地品"
        elif required_level >= 2 or price >= 1000:
            return "灵品"
        else:
            return "凡品"

    async def handle_pill_pavilion(self, event: AstrMessageEvent):
        """处理丹阁命令 - 展示丹药列表"""
        count = self.config.get("PAVILION_PILL_COUNT", 20)
        await self._ensure_pavilion_refreshed("pill_pavilion", self.shop_manager.get_pills_for_display, count)
        last_refresh, items = await self.db.get_shop_data("pill_pavilion")
        if not items:
            yield event.plain_result("丹阁暂无丹药出售。")
            return
        refresh_hours = self.config.get("PAVILION_REFRESH_HOURS", 1)
        display = self.shop_manager.format_pavilion_display("丹阁", items, refresh_hours, last_refresh)
        yield event.plain_result(display)

    async def handle_weapon_pavilion(self, event: AstrMessageEvent):
        """处理器阁命令 - 展示武器列表"""
        count = self.config.get("PAVILION_WEAPON_COUNT", 20)
        await self._ensure_pavilion_refreshed("weapon_pavilion", self.shop_manager.get_weapons_for_display, count)
        last_refresh, items = await self.db.get_shop_data("weapon_pavilion")
        if not items:
            yield event.plain_result("器阁暂无武器出售。")
            return
        refresh_hours = self.config.get("PAVILION_REFRESH_HOURS", 1)
        display = self.shop_manager.format_pavilion_display("器阁", items, refresh_hours, last_refresh)
        yield event.plain_result(display)

    async def handle_treasure_pavilion(self, event: AstrMessageEvent):
        """处理百宝阁命令 - 展示技能书、功法和特殊物品"""
        await self._ensure_treasure_pavilion_refreshed()
        last_refresh, items = await self.db.get_shop_data("treasure_pavilion")
        if not items:
            yield event.plain_result("百宝阁暂无物品出售。")
            return
        refresh_hours = self.config.get("PAVILION_REFRESH_HOURS", 1)
        display = self._format_treasure_pavilion_display(items, refresh_hours, last_refresh)
        yield event.plain_result(display)

    def _format_treasure_pavilion_display(self, items: list, refresh_hours: int, last_refresh: int) -> str:
        """格式化百宝阁显示"""
        import time as time_module
        
        lines = [
            "🏛️ 【百宝阁】",
            "━━━━━━━━━━━━━━━",
            "📚 技能秘籍 | 📜 功法心法 | 💎 珍稀物品",
            ""
        ]
        
        # 分类显示
        skill_books = [i for i in items if i.get('type') == 'skill_book']
        techniques = [i for i in items if i.get('type') in ['main_technique', 'technique']]
        materials = [i for i in items if i.get('type') == 'material']
        others = [i for i in items if i.get('type') not in ['skill_book', 'main_technique', 'technique', 'material']]
        
        if skill_books:
            lines.append("📚 【技能秘籍】")
            for item in skill_books:
                stock_str = f"×{item.get('stock', 1)}" if item.get('stock', 1) > 0 else "售罄"
                damage_type = "物理" if item.get('damage_type') == 'physical' else "法术"
                lines.append(f"  [{item.get('rank', '凡品')}] {item['name']} ({damage_type})")
                lines.append(f"      💰{item.get('price', 0):,} | {stock_str}")
            lines.append("")
        
        if techniques:
            lines.append("📜 【功法心法】")
            for item in techniques:
                stock_str = f"×{item.get('stock', 1)}" if item.get('stock', 1) > 0 else "售罄"
                type_str = "心法" if item.get('type') == 'main_technique' else "功法"
                exp_mult = item.get('exp_multiplier', 0)
                exp_str = f" 修炼+{exp_mult:.0%}" if exp_mult > 0 else ""
                lines.append(f"  [{item.get('rank', '凡品')}] {item['name']} ({type_str}){exp_str}")
                lines.append(f"      💰{item.get('price', 0):,} | {stock_str}")
            lines.append("")
        
        if materials:
            lines.append("🧪 【炼丹材料】")
            for item in materials:
                stock_str = f"×{item.get('stock', 1)}" if item.get('stock', 1) > 0 else "售罄"
                lines.append(f"  [{item.get('rank', '普通')}] {item['name']}")
                lines.append(f"      💰{item.get('price', 0):,} | {stock_str}")
            lines.append("")
        
        if others:
            lines.append("💎 【珍稀物品】")
            for item in others:
                stock_str = f"×{item.get('stock', 1)}" if item.get('stock', 1) > 0 else "售罄"
                extra_info = ""
                if item.get('type') == 'storage_ring' and item.get('capacity'):
                    extra_info = f" 容量:{item.get('capacity')}"
                lines.append(f"  [{item.get('rank', '凡品')}] {item['name']}{extra_info}")
                lines.append(f"      💰{item.get('price', 0):,} | {stock_str}")
            lines.append("")
        
        # 刷新时间
        now = int(time_module.time())
        next_refresh = last_refresh + refresh_hours * 3600
        remaining = max(0, next_refresh - now)
        hours = remaining // 3600
        minutes = (remaining % 3600) // 60
        
        lines.append("━━━━━━━━━━━━━━━")
        lines.append(f"⏰ 下次刷新：{hours}小时{minutes}分钟后")
        lines.append("💡 使用 '购买 <物品名>' 购买")
        
        return "\n".join(lines)

    async def _find_item_in_pavilions(self, item_name: str):
        """在所有阁楼中查找物品"""
        for pavilion_id in ["pill_pavilion", "weapon_pavilion", "treasure_pavilion"]:
            _, items = await self.db.get_shop_data(pavilion_id)
            if items:
                for item in items:
                    if item['name'] == item_name and item.get('stock', 0) > 0:
                        return pavilion_id, item
        return None, None

    @player_required
    async def handle_buy(self, player: Player, event: AstrMessageEvent, item_name: str = ""):
        """处理购买物品命令"""
        if not item_name or item_name.strip() == "":
            yield event.plain_result("请指定要购买的物品名称，例如：购买 青铜剑")
            return

        # 兼容全角空格/数字与"x10"写法
        normalized = item_name.strip().replace("　", " ")
        normalized = normalized.translate(str.maketrans("０１２３４５６７８９", "0123456789"))
        quantity = 1
        item_part = normalized

        def parse_qty(text: str):
            text = re.sub(r"\s+", " ", text)
            m = re.match(r"^(.*?)(?:\s+(\d+)|[xX＊*]\s*(\d+))$", text)
            if m:
                part = m.group(1).strip()
                qty_str = m.group(2) or m.group(3)
                return part, max(1, int(qty_str))
            return text.strip(), 1

        item_part, quantity = parse_qty(normalized)

        # 若指令解析只传入物品名（忽略数量），尝试从原始消息再解析一次
        if quantity == 1:
            try:
                raw_msg = event.get_message_str().strip()
                if raw_msg.startswith("购买"):
                    raw_msg = raw_msg[len("购买"):].strip()
                raw_msg = raw_msg.replace("　", " ")
                raw_msg = raw_msg.translate(str.maketrans("０１２３４５６７８９", "0123456789"))
                item_part, quantity = parse_qty(raw_msg)
            except Exception:
                pass

        item_name = item_part

        pavilion_id, target_item = await self._find_item_in_pavilions(item_name)
        if not target_item:
            yield event.plain_result(f"没有找到【{item_name}】，请检查物品名称或等待刷新。")
            return

        stock = target_item.get('stock', 0)
        if quantity > stock:
            yield event.plain_result(f"【{item_name}】库存不足，当前库存: {stock}。")
            return

        price = target_item['price']
        total_price = price * quantity
        if player.gold < total_price:
            yield event.plain_result(
                f"灵石不足！\n【{target_item['name']}】价格: {price} 灵石\n"
                f"购买数量: {quantity}\n需要灵石: {total_price}\n你的灵石: {player.gold}"
            )
            return

        item_type = target_item['type']
        result_lines = []

        await self.db.conn.execute("BEGIN IMMEDIATE")
        try:
            player = await self.db.get_player_by_id(event.get_sender_id())
            if player.gold < total_price:
                await self.db.conn.rollback()
                yield event.plain_result(
                    f"灵石不足！\n【{target_item['name']}】价格: {price} 灵石\n"
                    f"购买数量: {quantity}\n需要灵石: {total_price}\n你的灵石: {player.gold}"
                )
                return

            reserved, _, remaining = await self.db.decrement_shop_item_stock(pavilion_id, item_name, quantity, external_transaction=True)
            if not reserved:
                await self.db.conn.rollback()
                yield event.plain_result(f"【{item_name}】已售罄，请等待刷新。")
                return

            # 处理技能书购买
            if item_type == 'skill_book':
                skill_id = target_item.get('skill_id', '')
                skill_name = target_item.get('skill_name', '')
                
                # 检查是否已学会
                learned_skills = player.get_learned_skills()
                if skill_id in learned_skills:
                    await self.db.conn.rollback()
                    yield event.plain_result(f"你已经学会了【{skill_name}】，无需重复购买！")
                    return
                
                # 检查境界要求
                required_level = target_item.get('required_level_index', 0)
                if player.level_index < required_level:
                    level_data = self.config_manager.get_level_data(player.cultivation_type)
                    level_name = f"境界{required_level}"
                    if 0 <= required_level < len(level_data):
                        level_name = level_data[required_level].get("level_name", level_name)
                    await self.db.conn.rollback()
                    yield event.plain_result(f"境界不足！学习【{skill_name}】需要达到【{level_name}】")
                    return
                
                # 学习技能（不再扣费，因为购买时已扣）
                success, msg = await self.skill_manager.learn_skill(player, skill_id, cost_gold=False)
                if success:
                    result_lines.append(f"✨ 成功购买并学习技能【{skill_name}】！")
                    damage_type = "物理" if target_item.get('damage_type') == 'physical' else "法术"
                    result_lines.append(f"📚 类型：{damage_type}技能")
                    result_lines.append(f"💡 使用 '装备技能 {skill_name}' 来装备此技能")
                else:
                    await self.db.conn.rollback()
                    yield event.plain_result(f"学习技能失败：{msg}")
                    return

            elif item_type in ['weapon', 'armor', 'main_technique', 'technique', 'accessory']:
                success, msg = await self.storage_ring_manager.store_item(player, target_item['name'], quantity, external_transaction=True)
                if success:
                    type_name = {"weapon": "武器", "armor": "防具", "main_technique": "心法", "technique": "功法", "accessory": "饰品"}.get(item_type, "装备")
                    result_lines.append(f"成功购买{type_name}【{target_item['name']}】x{quantity}，已存入储物戒。")
                else:
                    result_lines.append(f"成功购买【{target_item['name']}】x{quantity}。")
                    result_lines.append(f"⚠️ 存入储物戒失败：{msg}")
            elif item_type in ['pill', 'exp_pill', 'utility_pill']:
                await self.pill_manager.add_pill_to_inventory(player, target_item['name'], count=quantity)
                result_lines.append(f"成功购买【{target_item['name']}】x{quantity}，已添加到背包。")
            elif item_type == 'legacy_pill':
                success, message = await self._apply_legacy_pill_effects(player, target_item, quantity)
                if not success:
                    await self.db.conn.rollback()
                    yield event.plain_result(message)
                    return
                result_lines.append(message)
            elif item_type == 'material':
                success, msg = await self.storage_ring_manager.store_item(player, target_item['name'], quantity, external_transaction=True)
                if success:
                    result_lines.append(f"成功购买材料【{target_item['name']}】x{quantity}，已存入储物戒。")
                else:
                    result_lines.append(f"成功购买材料【{target_item['name']}】x{quantity}。")
                    result_lines.append(f"⚠️ 存入储物戒失败：{msg}")
            elif item_type == 'storage_ring':
                # 储物戒购买逻辑
                success, msg = await self._handle_storage_ring_purchase(player, target_item)
                if success:
                    result_lines.append(msg)
                else:
                    await self.db.conn.rollback()
                    yield event.plain_result(msg)
                    return
            elif item_type == '功法':
                success, msg = await self.storage_ring_manager.store_item(player, target_item['name'], quantity, external_transaction=True)
                if success:
                    result_lines.append(f"成功购买功法【{target_item['name']}】x{quantity}，已存入储物戒。")
                else:
                    result_lines.append(f"成功购买功法【{target_item['name']}】x{quantity}。")
                    result_lines.append(f"⚠️ 存入储物戒失败：{msg}")
            else:
                await self.db.conn.rollback()
                yield event.plain_result(f"未知的物品类型：{item_type}")
                return

            player.gold -= total_price
            await self.db.update_player(player)
            await self.db.conn.commit()
            
            result_lines.append(f"花费灵石: {total_price}，剩余: {player.gold}")
            result_lines.append(f"剩余库存: {remaining}" if remaining > 0 else "该物品已售罄！")
            yield event.plain_result("\n".join(result_lines))
        except Exception as e:
            await self.db.conn.rollback()
            logger.error(f"购买异常: {e}")
            raise

    async def _handle_storage_ring_purchase(self, player: Player, item: dict) -> tuple:
        """处理储物戒购买
        
        Args:
            player: 玩家对象
            item: 储物戒物品配置
            
        Returns:
            (是否成功, 消息)
        """
        ring_name = item.get('name', '')
        capacity = item.get('capacity', 10)
        
        # 检查是否已有储物戒
        current_ring = player.storage_ring
        if current_ring:
            # 获取当前储物戒容量
            current_ring_data = self.config_manager.storage_rings_data.get(current_ring, {})
            current_capacity = current_ring_data.get('capacity', 10)
            
            if capacity <= current_capacity:
                return False, f"你当前的储物戒【{current_ring}】容量为{current_capacity}，新储物戒容量{capacity}不比它大，无需更换。"
        
        # 更换储物戒
        player.storage_ring = ring_name
        await self.db.update_player(player)
        
        if current_ring:
            return True, f"✨ 成功购买并更换储物戒【{ring_name}】！\n容量：{capacity}格\n（原储物戒【{current_ring}】已替换）"
        else:
            return True, f"✨ 成功购买储物戒【{ring_name}】！\n容量：{capacity}格"

    def _get_acquire_hint(self, item_type: str) -> str:
        """根据类型返回获取提示"""
        return self.ITEM_ACQUIRE_HINTS.get(item_type, "商店刷新或活动奖励")

    async def handle_item_info(self, event: AstrMessageEvent, item_name: str = ""):
        """查询物品/丹药的具体效果与获取方式"""
        if not item_name or item_name.strip() == "":
            yield event.plain_result(
                "请指定要查询的物品名称\n"
                "用法：物品信息 <名称>\n"
                "示例：物品信息 筑基丹"
            )
            return

        item_name = item_name.strip()
        
        # 首先检查是否是技能秘籍
        if item_name.endswith("秘籍"):
            skill_name = item_name[:-2]  # 去掉"秘籍"后缀
            skill_config = self.skill_manager.get_skill_by_name(skill_name)
            if skill_config:
                detail_text = self._format_skill_book_info(skill_config)
                acquire_hint = self._get_acquire_hint('skill_book')
                lines = [
                    detail_text,
                    f"获取途径：{acquire_hint}",
                    "💡 使用 /百宝阁 查看当前售卖的技能秘籍"
                ]
                yield event.plain_result("\n".join(lines))
                return
        
        # 检查是否是功法
        technique_config = self.config_manager.get_technique_by_name(item_name)
        if technique_config:
            detail_text = self._format_technique_info(technique_config)
            acquire_hint = self._get_acquire_hint(technique_config.get('type', 'technique'))
            lines = [
                detail_text,
                f"获取途径：{acquire_hint}",
                "💡 使用 /百宝阁 查看当前售卖的功法"
            ]
            yield event.plain_result("\n".join(lines))
            return

        item = self.shop_manager.find_item_by_name(item_name)
        if not item:
            yield event.plain_result(f"未找到物品【{item_name}】，请检查名称或等待刷新。")
            return

        detail_text = self.shop_manager.get_item_details(item)
        acquire_hint = self._get_acquire_hint(item.get('type', ''))

        lines = [
            detail_text,
            f"获取途径：{acquire_hint}",
            "💡 使用 /丹阁、/器阁、/百宝阁 查看当前售卖物品"
        ]
        yield event.plain_result("\n".join(lines))

    def _format_skill_book_info(self, skill_config: dict) -> str:
        """格式化技能秘籍信息"""
        lines = [
            f"📚 【{skill_config.get('name', '未知')}秘籍】",
            "━━━━━━━━━━━━━━━",
        ]
        
        damage_type = "物理" if skill_config.get('damage_type') == 'physical' else "法术"
        lines.append(f"类型：{damage_type}技能")
        lines.append(f"描述：{skill_config.get('description', '无')}")
        
        mp_cost = skill_config.get('mp_cost', 0)
        cooldown = skill_config.get('cooldown', 0)
        lines.append(f"消耗：{mp_cost} MP")
        if cooldown > 0:
            lines.append(f"冷却：{cooldown}回合")
        
        damage_config = skill_config.get('damage', {})
        base_damage = damage_config.get('base', 0)
        attack_ratio = damage_config.get('attack_ratio', 1.0)
        lines.append(f"伤害：{base_damage} + {attack_ratio:.1f}x攻击力")
        
        effects = skill_config.get('effects', [])
        if effects:
            effect_strs = []
            for eff in effects:
                eff_type = eff.get('type', '')
                eff_value = eff.get('value', 0)
                eff_duration = eff.get('duration', 1)
                effect_strs.append(f"{eff_type}({eff_value}, {eff_duration}回合)")
            lines.append(f"效果：{', '.join(effect_strs)}")
        
        required_level = skill_config.get('required_level_index', 0)
        price = skill_config.get('price', 0)
        lines.append(f"境界要求：{required_level}级")
        lines.append(f"价格：{price:,} 灵石")
        
        lines.append("━━━━━━━━━━━━━━━")
        return "\n".join(lines)

    def _format_technique_info(self, technique_config: dict) -> str:
        """格式化功法信息"""
        lines = [
            f"📜 【{technique_config.get('name', '未知')}】",
            "━━━━━━━━━━━━━━━",
        ]
        
        tech_type = "心法" if technique_config.get('type') == 'main_technique' else "功法"
        rank = technique_config.get('rank', '凡品')
        lines.append(f"类型：{tech_type} [{rank}]")
        lines.append(f"描述：{technique_config.get('description', '无')}")
        
        # 属性加成
        attrs = []
        if technique_config.get('exp_multiplier', 0) > 0:
            attrs.append(f"修炼速度+{technique_config['exp_multiplier']:.0%}")
        if technique_config.get('physical_damage', 0) > 0:
            attrs.append(f"物伤+{technique_config['physical_damage']}")
        if technique_config.get('magic_damage', 0) > 0:
            attrs.append(f"法伤+{technique_config['magic_damage']}")
        if technique_config.get('physical_defense', 0) > 0:
            attrs.append(f"物防+{technique_config['physical_defense']}")
        if technique_config.get('magic_defense', 0) > 0:
            attrs.append(f"法防+{technique_config['magic_defense']}")
        if technique_config.get('speed', 0) > 0:
            attrs.append(f"速度+{technique_config['speed']}")
        if technique_config.get('critical_rate', 0) > 0:
            attrs.append(f"暴击率+{technique_config['critical_rate']:.0%}")
        if technique_config.get('hp_bonus', 0) > 0:
            attrs.append(f"HP+{technique_config['hp_bonus']}")
        if technique_config.get('mp_bonus', 0) > 0:
            attrs.append(f"MP+{technique_config['mp_bonus']}")
        
        if attrs:
            lines.append(f"属性加成：{', '.join(attrs)}")
        
        # 成长修正
        growth = technique_config.get('growth_modifiers', {})
        if growth:
            growth_strs = []
            for key, value in growth.items():
                if value != 1.0:
                    growth_strs.append(f"{key}×{value:.1f}")
            if growth_strs:
                lines.append(f"成长修正：{', '.join(growth_strs)}")
        
        required_level = technique_config.get('required_level_index', 0)
        price = technique_config.get('price', 0)
        lines.append(f"境界要求：{required_level}级")
        lines.append(f"价格：{price:,} 灵石")
        
        lines.append("━━━━━━━━━━━━━━━")
        return "\n".join(lines)

    async def _apply_legacy_pill_effects(self, player: Player, item: dict, quantity: int) -> tuple:
        """应用旧系统丹药效果（items.json中的丹药）

        Args:
            player: 玩家对象
            item: 物品配置字典
            quantity: 购买数量

        Returns:
            (是否成功, 消息)
        """
        effects = item.get('data', {}).get('effect', {})
        if not effects:
            return False, f"丹药【{item['name']}】无效果配置。"

        effect_msgs = []
        pill_name = item['name']

        # 处理各种效果（乘以数量）
        for _ in range(quantity):
            # 恢复/扣除气血
            if 'add_hp' in effects:
                hp_change = effects['add_hp']
                if player.cultivation_type == "体修":
                    old_blood = player.blood_qi
                    player.blood_qi = max(0, min(player.max_blood_qi, player.blood_qi + hp_change))
                    if hp_change > 0:
                        effect_msgs.append(f"气血+{player.blood_qi - old_blood}")
                    else:
                        effect_msgs.append(f"气血{hp_change}")
                else:
                    old_qi = player.spiritual_qi
                    player.spiritual_qi = max(0, min(player.max_spiritual_qi, player.spiritual_qi + hp_change))
                    if hp_change > 0:
                        effect_msgs.append(f"灵气+{player.spiritual_qi - old_qi}")
                    else:
                        effect_msgs.append(f"灵气{hp_change}")

            # 增加修为
            if 'add_experience' in effects:
                exp_gain = effects['add_experience']
                player.experience += exp_gain
                effect_msgs.append(f"修为+{exp_gain}")

            # 增加最大气血/灵气上限
            if 'add_max_hp' in effects:
                max_hp_gain = effects['add_max_hp']
                if player.cultivation_type == "体修":
                    player.max_blood_qi += max_hp_gain
                    effect_msgs.append(f"最大气血+{max_hp_gain}")
                else:
                    player.max_spiritual_qi += max_hp_gain
                    effect_msgs.append(f"最大灵气+{max_hp_gain}")

            # 增加灵力（映射到法伤）
            if 'add_spiritual_power' in effects:
                sp_gain = effects['add_spiritual_power']
                player.magic_damage += sp_gain
                effect_msgs.append(f"法伤+{sp_gain}")

            # 增加精神力
            if 'add_mental_power' in effects:
                mp_gain = effects['add_mental_power']
                player.mental_power += mp_gain
                effect_msgs.append(f"精神力+{mp_gain}")

            # 增加攻击力（映射到物伤）
            if 'add_attack' in effects:
                atk_gain = effects['add_attack']
                player.physical_damage += atk_gain
                if atk_gain > 0:
                    effect_msgs.append(f"物伤+{atk_gain}")
                else:
                    effect_msgs.append(f"物伤{atk_gain}")

            # 增加防御力（映射到物防）
            if 'add_defense' in effects:
                def_gain = effects['add_defense']
                player.physical_defense += def_gain
                if def_gain > 0:
                    effect_msgs.append(f"物防+{def_gain}")
                else:
                    effect_msgs.append(f"物防{def_gain}")

            # 增加/扣除灵石
            if 'add_gold' in effects:
                gold_change = effects['add_gold']
                player.gold += gold_change
                if gold_change > 0:
                    effect_msgs.append(f"灵石+{gold_change}")
                else:
                    effect_msgs.append(f"灵石{gold_change}")

           

        # 确保属性不为负
        player.physical_damage = max(0, player.physical_damage)
        player.magic_damage = max(0, player.magic_damage)
        player.physical_defense = max(0, player.physical_defense)
        player.magic_defense = max(0, player.magic_defense)
        player.mental_power = max(0, player.mental_power)
        player.spiritual_qi = min(player.spiritual_qi, player.max_spiritual_qi)
        player.blood_qi = min(player.blood_qi, player.max_blood_qi)

        await self.db.update_player(player)

        # 去重效果消息
        unique_effects = list(dict.fromkeys(effect_msgs))
        effects_str = "、".join(unique_effects[:5])  # 最多显示5个效果
        if len(unique_effects) > 5:
            effects_str += "..."

        qty_str = f"x{quantity}" if quantity > 1 else ""
        return True, f"服用【{pill_name}】{qty_str}成功！效果：{effects_str}"
