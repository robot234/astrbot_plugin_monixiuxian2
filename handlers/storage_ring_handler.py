# handlers/storage_ring_handler.py

from astrbot.api.event import AstrMessageEvent
from ..data import DataBase
from ..core import StorageRingManager
from ..config_manager import ConfigManager
from ..models import Player
from .utils import player_required

CMD_STORAGE_RING = "储物戒"
CMD_STORE_ITEM = "存入"
CMD_RETRIEVE_ITEM = "取出"
CMD_UPGRADE_RING = "更换储物戒"
CMD_DISCARD_ITEM = "丢弃"
CMD_GIFT_ITEM = "赠予"
CMD_ACCEPT_GIFT = "接收"
CMD_REJECT_GIFT = "拒绝"

__all__ = ["StorageRingHandler"]


# 存储待处理的赠予请求 {接收者user_id: {"sender_id": str, "sender_name": str, "item_name": str, "count": int}}
pending_gifts = {}


class StorageRingHandler:
    """储物戒系统处理器"""

    def __init__(self, db: DataBase, config_manager: ConfigManager):
        self.db = db
        self.config_manager = config_manager
        self.storage_ring_manager = StorageRingManager(db, config_manager)

    @player_required
    async def handle_storage_ring(self, player: Player, event: AstrMessageEvent):
        """显示储物戒信息"""
        display_name = event.get_sender_name()

        # 获取储物戒信息
        ring_info = self.storage_ring_manager.get_storage_ring_info(player)

        lines = [
            f"=== {display_name} 的储物戒 ===\n",
            f"【{ring_info['name']}】（{ring_info['rank']}）\n",
            f"{ring_info['description']}\n",
            f"\n容量：{ring_info['used']}/{ring_info['capacity']}格\n",
            f"━━━━━━━━━━━━━━━\n",
        ]

        # 显示存储的物品（xxx*数量 格式）
        items = ring_info['items']
        if items:
            lines.append("【存储物品】\n")
            for item_name, count in items.items():
                if count > 1:
                    lines.append(f"  · {item_name}*{count}\n")
                else:
                    lines.append(f"  · {item_name}\n")
        else:
            lines.append("【存储物品】空\n")

        # 空间警告
        warning = self.storage_ring_manager.get_space_warning(player)
        if warning:
            lines.append(f"\n{warning}\n")

        lines.append(f"\n{'=' * 28}\n")
        lines.append(f"存入：{CMD_STORE_ITEM} 物品名 [数量]\n")
        lines.append(f"取出：{CMD_RETRIEVE_ITEM} 物品名 [数量]\n")
        lines.append(f"赠予：{CMD_GIFT_ITEM} QQ号 物品名 [数量]\n")
        lines.append(f"丢弃：{CMD_DISCARD_ITEM} 物品名 [数量]\n")
        lines.append(f"升级：{CMD_UPGRADE_RING} 储物戒名")

        yield event.plain_result("".join(lines))

    @player_required
    async def handle_store_item(self, player: Player, event: AstrMessageEvent, args: str):
        """存入物品到储物戒"""
        if not args or args.strip() == "":
            yield event.plain_result(
                f"请指定要存入的物品\n"
                f"用法：{CMD_STORE_ITEM} 物品名 [数量]\n"
                f"示例：{CMD_STORE_ITEM} 精铁 5"
            )
            return

        args = args.strip()
        parts = args.rsplit(" ", 1)

        # 解析物品名和数量
        if len(parts) == 2 and parts[1].isdigit():
            item_name = parts[0]
            count = int(parts[1])
        else:
            item_name = args
            count = 1

        if count <= 0:
            yield event.plain_result("数量必须大于0")
            return

        # 检查物品是否存在
        item_exists = (
            item_name in self.config_manager.items_data or
            item_name in self.config_manager.weapons_data
        )

        if not item_exists:
            yield event.plain_result(f"未找到物品：{item_name}")
            return

        # 存入物品
        success, message = await self.storage_ring_manager.store_item(player, item_name, count)

        if success:
            yield event.plain_result(f"✅ {message}")
        else:
            yield event.plain_result(f"❌ {message}")

    @player_required
    async def handle_retrieve_item(self, player: Player, event: AstrMessageEvent, args: str):
        """从储物戒取出物品"""
        if not args or args.strip() == "":
            yield event.plain_result(
                f"请指定要取出的物品\n"
                f"用法：{CMD_RETRIEVE_ITEM} 物品名 [数量]\n"
                f"示例：{CMD_RETRIEVE_ITEM} 精铁 5"
            )
            return

        args = args.strip()
        parts = args.rsplit(" ", 1)

        # 解析物品名和数量
        if len(parts) == 2 and parts[1].isdigit():
            item_name = parts[0]
            count = int(parts[1])
        else:
            item_name = args
            count = 1

        if count <= 0:
            yield event.plain_result("数量必须大于0")
            return

        # 取出物品
        success, message = await self.storage_ring_manager.retrieve_item(player, item_name, count)

        if success:
            yield event.plain_result(f"✅ {message}")
        else:
            yield event.plain_result(f"❌ {message}")

    @player_required
    async def handle_discard_item(self, player: Player, event: AstrMessageEvent, args: str):
        """丢弃储物戒中的物品"""
        if not args or args.strip() == "":
            yield event.plain_result(
                f"请指定要丢弃的物品\n"
                f"用法：{CMD_DISCARD_ITEM} 物品名 [数量]\n"
                f"示例：{CMD_DISCARD_ITEM} 精铁 5\n"
                f"⚠️ 丢弃的物品将永久销毁！"
            )
            return

        args = args.strip()
        parts = args.rsplit(" ", 1)

        # 解析物品名和数量
        if len(parts) == 2 and parts[1].isdigit():
            item_name = parts[0]
            count = int(parts[1])
        else:
            item_name = args
            count = 1

        if count <= 0:
            yield event.plain_result("数量必须大于0")
            return

        # 丢弃物品
        success, message = await self.storage_ring_manager.discard_item(player, item_name, count)

        if success:
            yield event.plain_result(f"🗑️ {message}")
        else:
            yield event.plain_result(f"❌ {message}")

    @player_required
    async def handle_gift_item(self, player: Player, event: AstrMessageEvent, args: str):
        """赠予物品给其他玩家"""
        from astrbot.api.message_components import At, Plain

        target_id = None
        item_name = None
        count = 1

        # 从消息链中提取 At 组件和文本内容
        text_parts = []
        message_chain = event.message_obj.message if hasattr(event, 'message_obj') and event.message_obj else []

        for comp in message_chain:
            if isinstance(comp, At):
                # 获取被@的用户ID
                if target_id is None:
                    target_id = str(comp.qq) if hasattr(comp, 'qq') else str(comp.target) if hasattr(comp, 'target') else None
            elif isinstance(comp, Plain):
                text_parts.append(comp.text)

        # 合并文本内容并移除命令前缀
        text_content = "".join(text_parts).strip()
        for prefix in ["#赠予", "赠予"]:
            if text_content.startswith(prefix):
                text_content = text_content[len(prefix):].strip()
                break

        # 如果没有从At组件获取到target_id，尝试从文本解析
        if not target_id and text_content:
            parts = text_content.split(None, 1)
            if len(parts) >= 1:
                potential_id = parts[0].lstrip('@')
                if potential_id.isdigit():
                    target_id = potential_id
                    text_content = parts[1].strip() if len(parts) > 1 else ""

        # 解析物品名和数量
        if text_content:
            parts = text_content.rsplit(" ", 1)
            if len(parts) == 2 and parts[1].isdigit():
                item_name = parts[0].strip()
                count = int(parts[1])
            else:
                item_name = text_content.strip()

        # 验证必要参数
        if not target_id:
            yield event.plain_result(
                f"请指定赠予对象\n"
                f"用法：{CMD_GIFT_ITEM} @某人 物品名 [数量]\n"
                f"或：{CMD_GIFT_ITEM} QQ号 物品名 [数量]\n"
                f"示例：{CMD_GIFT_ITEM} 123456789 精铁 5"
            )
            return

        if not item_name:
            yield event.plain_result("请指定要赠予的物品名称")
            return

        if count <= 0:
            yield event.plain_result("数量必须大于0")
            return

        # 检查物品是否在储物戒中
        if not self.storage_ring_manager.has_item(player, item_name, count):
            current = self.storage_ring_manager.get_item_count(player, item_name)
            if current == 0:
                yield event.plain_result(f"储物戒中没有【{item_name}】")
            else:
                yield event.plain_result(f"储物戒中【{item_name}】数量不足（当前：{current}个）")
            return

        target_player = await self.db.get_player_by_id(target_id)
        if not target_player:
            yield event.plain_result(f"目标玩家（QQ:{target_id}）尚未开始修仙")
            return

        if target_id == player.user_id:
            yield event.plain_result("不能赠予物品给自己")
            return

        # 先从储物戒中取出物品
        success, _ = await self.storage_ring_manager.retrieve_item(player, item_name, count)
        if not success:
            yield event.plain_result("赠予失败：无法取出物品")
            return

        # 存储待处理的赠予请求
        sender_name = event.get_sender_name()
        pending_gifts[target_id] = {
            "sender_id": player.user_id,
            "sender_name": sender_name,
            "item_name": item_name,
            "count": count
        }

        yield event.plain_result(
            f"📦 赠予请求已发送！\n"
            f"【{item_name}】x{count} → @{target_id}\n"
            f"等待对方确认...\n"
            f"对方可使用 {CMD_ACCEPT_GIFT} 接收或 {CMD_REJECT_GIFT} 拒绝"
        )

    @player_required
    async def handle_accept_gift(self, player: Player, event: AstrMessageEvent):
        """接收赠予的物品"""
        user_id = player.user_id

        if user_id not in pending_gifts:
            yield event.plain_result("你没有待接收的赠予物品")
            return

        gift = pending_gifts[user_id]
        item_name = gift["item_name"]
        count = gift["count"]
        sender_name = gift["sender_name"]

        # 尝试存入接收者的储物戒
        success, message = await self.storage_ring_manager.store_item(player, item_name, count)

        if success:
            del pending_gifts[user_id]
            yield event.plain_result(
                f"✅ 已接收来自【{sender_name}】的赠予！\n"
                f"获得：【{item_name}】x{count}"
            )
        else:
            # 存入失败，物品返还给发送者
            sender_id = gift["sender_id"]
            sender_player = await self.db.get_player_by_id(sender_id)
            if sender_player:
                await self.storage_ring_manager.store_item(sender_player, item_name, count, silent=True)

            del pending_gifts[user_id]
            yield event.plain_result(
                f"❌ 接收失败：{message}\n"
                f"物品已返还给【{sender_name}】"
            )

    @player_required
    async def handle_reject_gift(self, player: Player, event: AstrMessageEvent):
        """拒绝赠予的物品"""
        user_id = player.user_id

        if user_id not in pending_gifts:
            yield event.plain_result("你没有待处理的赠予请求")
            return

        gift = pending_gifts[user_id]
        item_name = gift["item_name"]
        count = gift["count"]
        sender_id = gift["sender_id"]
        sender_name = gift["sender_name"]

        # 物品返还给发送者
        sender_player = await self.db.get_player_by_id(sender_id)
        if sender_player:
            await self.storage_ring_manager.store_item(sender_player, item_name, count, silent=True)

        del pending_gifts[user_id]
        yield event.plain_result(
            f"已拒绝来自【{sender_name}】的赠予\n"
            f"【{item_name}】x{count} 已返还"
        )

    @player_required
    async def handle_upgrade_ring(self, player: Player, event: AstrMessageEvent, ring_name: str):
        """升级/更换储物戒"""
        if not ring_name or ring_name.strip() == "":
            # 显示可用的储物戒列表
            rings = self.storage_ring_manager.get_all_storage_rings()
            current_capacity = self.storage_ring_manager.get_ring_capacity(player.storage_ring)

            lines = [
                f"=== 储物戒列表 ===\n",
                f"当前：【{player.storage_ring}】({current_capacity}格)\n",
                f"━━━━━━━━━━━━━━━\n",
            ]

            for ring in rings:
                # 标记当前装备
                if ring["name"] == player.storage_ring:
                    marker = "✓ "
                elif ring["capacity"] <= current_capacity:
                    marker = "✗ "  # 容量不高于当前的
                else:
                    marker = "  "

                level_name = self.storage_ring_manager._format_required_level(ring["required_level_index"])
                lines.append(
                    f"{marker}【{ring['name']}】({ring['rank']})\n"
                    f"    容量：{ring['capacity']}格 | 需求：{level_name}\n"
                )

            lines.append(f"\n用法：{CMD_UPGRADE_RING} 储物戒名")
            lines.append("\n注：储物戒只能升级，不能卸下")

            yield event.plain_result("".join(lines))
            return

        ring_name = ring_name.strip()

        # 检查是否为储物戒类型
        ring_config = self.storage_ring_manager.get_storage_ring_config(ring_name)
        if not ring_config:
            yield event.plain_result(f"未找到储物戒：{ring_name}")
            return

        # 升级储物戒
        success, message = await self.storage_ring_manager.upgrade_ring(player, ring_name)

        if success:
            yield event.plain_result(f"✅ {message}")
        else:
            yield event.plain_result(f"❌ {message}")
