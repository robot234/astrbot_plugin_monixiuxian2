# handlers/storage_ring_handler.py

import json
import time

from astrbot.api.event import AstrMessageEvent
from astrbot.api.all import At, Plain
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
CMD_STORE_ALL = "存入所有"
CMD_RETRIEVE_ALL = "取出所有"
CMD_SEARCH_ITEM = "搜索物品"
CMD_VIEW_CATEGORY = "查看分类"

# 物品分类定义
ITEM_CATEGORIES = {
    "材料": ["灵草", "精铁", "玄铁", "星辰石", "灵石碎片", "灵兽毛皮", "灵兽内丹", 
             "妖兽精血", "功法残页", "秘境精华", "天材地宝", "混沌精华", "神兽之骨", 
             "远古秘籍", "仙器碎片"],
    "装备": ["武器", "防具", "法器", "饰品", "配饰"],
    "功法": ["心法", "技能"],
    "其他": []
}

__all__ = ["StorageRingHandler"]


class _GiftAbort(RuntimeError):
    """Expected gift conflict that must roll back the current transaction."""


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

        # 按分类显示存储的物品
        items = ring_info['items']
        if items:
            categorized = self._categorize_items(items)
            for category, cat_items in categorized.items():
                if cat_items:
                    lines.append(f"【{category}】\n")
                    for item_name, count in cat_items:
                        if count > 1:
                            lines.append(f"  · {item_name}×{count}\n")
                        else:
                            lines.append(f"  · {item_name}\n")
        else:
            lines.append("【存储物品】空\n")

        # 空间警告
        warning = self.storage_ring_manager.get_space_warning(player)
        if warning:
            lines.append(f"\n{warning}\n")

        lines.append(f"\n{'=' * 28}\n")
        lines.append(f"取出：{CMD_RETRIEVE_ITEM} 物品名 [数量]\n")
        lines.append(f"搜索：{CMD_SEARCH_ITEM} 关键词\n")
        lines.append(f"升级：{CMD_UPGRADE_RING} 储物戒名")

        yield event.plain_result("".join(lines))

    @player_required
    async def handle_store_item(self, player: Player, event: AstrMessageEvent, args: str):
        """存入物品到储物戒 - 已禁用手动存入"""
        yield event.plain_result(
            "📦 储物戒说明：\n"
            "物品会在以下情况自动存入储物戒：\n"
            "  · 商店购买物品\n"
            "  · 历练/秘境获得物品\n"
            "  · Boss击杀掉落\n"
            "  · 悬赏任务奖励\n"
            "  · 卸下装备\n"
            "\n⚠️ 不支持手动存入物品"
        )

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

    def _check_pill_inventory(self, player: Player, pill_name: str, count: int) -> bool:
        """检查丹药背包中是否有足够数量的丹药"""
        inventory = player.get_pills_inventory()
        return inventory.get(pill_name, 0) >= count

    def _get_pill_count(self, player: Player, pill_name: str) -> int:
        """获取丹药背包中某丹药的数量"""
        inventory = player.get_pills_inventory()
        return inventory.get(pill_name, 0)

    async def _remove_pill_from_inventory(self, player: Player, pill_name: str, count: int) -> bool:
        """从丹药背包中移除丹药"""
        inventory = player.get_pills_inventory()
        if inventory.get(pill_name, 0) < count:
            return False
        
        inventory[pill_name] -= count
        if inventory[pill_name] <= 0:
            del inventory[pill_name]
        player.set_pills_inventory(inventory)
        await self.db.update_player(player)
        return True

    async def _add_pill_to_inventory(self, player: Player, pill_name: str, count: int):
        """添加丹药到丹药背包"""
        inventory = player.get_pills_inventory()
        inventory[pill_name] = inventory.get(pill_name, 0) + count
        player.set_pills_inventory(inventory)
        await self.db.update_player(player)

    @staticmethod
    def _gift_inventory_column(source_type: str) -> str:
        if source_type == "pill":
            return "pills_inventory"
        if source_type == "storage":
            return "storage_ring_items"
        raise _GiftAbort("赠予物品来源无效")

    async def _read_gift_inventory_locked(self, user_id: str, source_type: str):
        column = self._gift_inventory_column(source_type)
        async with self.db.conn.execute(
            f"SELECT {column} FROM players WHERE user_id = ?",
            (user_id,),
            commit=False,
        ) as cursor:
            row = await cursor.fetchone()
        if not row:
            raise _GiftAbort("玩家不存在或已被删除")
        return column, row[0]

    async def _mutate_gift_inventory_locked(
        self,
        player: Player,
        source_type: str,
        item_name: str,
        count: int,
        *,
        adding: bool,
    ) -> str:
        """CAS-update an escrow inventory while the transaction is owned."""
        column, old_raw = await self._read_gift_inventory_locked(player.user_id, source_type)
        try:
            inventory = json.loads(old_raw or "{}")
        except (TypeError, json.JSONDecodeError) as exc:
            raise _GiftAbort("玩家物品数据损坏") from exc
        if not isinstance(inventory, dict):
            raise _GiftAbort("玩家物品数据损坏")

        value = inventory.get(item_name, 0)
        nested = isinstance(value, dict)
        quantity = value.get("count") if nested else value
        if isinstance(quantity, bool) or not isinstance(quantity, int):
            raise _GiftAbort("玩家物品数量无效")

        if adding:
            if source_type == "storage" and item_name not in inventory:
                capacity = self.storage_ring_manager.get_ring_capacity(player.storage_ring)
                if len(inventory) >= capacity:
                    raise _GiftAbort(f"储物戒已满！({capacity}/{capacity}格)")
            new_quantity = quantity + count
            if nested:
                updated = dict(value)
                updated["count"] = new_quantity
                inventory[item_name] = updated
            else:
                inventory[item_name] = new_quantity
        else:
            if item_name not in inventory or quantity < count:
                raise _GiftAbort(f"物品【{item_name}】数量不足")
            if count == quantity:
                del inventory[item_name]
            elif nested:
                updated = dict(value)
                updated["count"] = quantity - count
                inventory[item_name] = updated
            else:
                inventory[item_name] = quantity - count

        new_raw = json.dumps(inventory, ensure_ascii=False)
        if old_raw is None:
            cursor = await self.db.conn.execute(
                f"UPDATE players SET {column} = ? WHERE user_id = ? AND {column} IS NULL",
                (new_raw, player.user_id),
                commit=False,
            )
        else:
            cursor = await self.db.conn.execute(
                f"UPDATE players SET {column} = ? WHERE user_id = ? AND {column} = ?",
                (new_raw, player.user_id, old_raw),
                commit=False,
            )
        if cursor.rowcount != 1:
            raise _GiftAbort("玩家物品状态已变化，请重试")
        return new_raw

    @staticmethod
    def _gift_quantity(inventory: dict, item_name: str) -> int:
        value = inventory.get(item_name, 0)
        quantity = value.get("count") if isinstance(value, dict) else value
        if isinstance(quantity, bool) or not isinstance(quantity, int):
            return 0
        return quantity

    async def _fetch_gift_locked(
        self,
        *,
        gift_id: int | None = None,
        receiver_id: str | None = None,
        sender_id: str | None = None,
        live: bool | None = None,
    ):
        clauses = ["1 = 1"]
        params = []
        if gift_id is not None:
            clauses.append("id = ?")
            params.append(gift_id)
        if receiver_id is not None:
            clauses.append("receiver_id = ?")
            params.append(receiver_id)
        if sender_id is not None:
            clauses.append("sender_id = ?")
            params.append(sender_id)
        if live is True:
            clauses.append("expires_at > ?")
            params.append(int(time.time()))
        elif live is False:
            clauses.append("expires_at <= ?")
            params.append(int(time.time()))

        async with self.db.conn.execute(
            """
            SELECT id, receiver_id, sender_id, sender_name, item_name, count,
                   source_type, created_at, expires_at
            FROM pending_gifts
            WHERE """ + " AND ".join(clauses) + "\n"
            "            ORDER BY created_at DESC, id DESC\n"
            "            LIMIT 1",
            tuple(params),
            commit=False,
        ) as cursor:
            row = await cursor.fetchone()
        if not row:
            return None
        return {
            "id": row[0],
            "receiver_id": row[1],
            "sender_id": row[2],
            "sender_name": row[3],
            "item_name": row[4],
            "count": row[5],
            "source_type": row[6],
            "created_at": row[7],
            "expires_at": row[8],
        }

    async def _restore_gift_locked(self, gift: dict):
        sender = await self.db.get_player_by_id(gift["sender_id"])
        if not sender:
            raise _GiftAbort("赠予者已不存在，暂时无法返还物品")
        new_raw = await self._mutate_gift_inventory_locked(
            sender,
            gift.get("source_type", "storage"),
            gift["item_name"],
            gift["count"],
            adding=True,
        )
        return sender, new_raw

    async def _claim_gift_locked(self, gift: dict, *, expired: bool = False) -> None:
        now = int(time.time())
        expiry_clause = "expires_at <= ?" if expired else "expires_at > ?"
        cursor = await self.db.conn.execute(
            f"""
            DELETE FROM pending_gifts
            WHERE id = ? AND receiver_id = ? AND sender_id = ? AND {expiry_clause}
            """,
            (gift["id"], gift["receiver_id"], gift["sender_id"], now),
            commit=False,
        )
        if cursor.rowcount != 1:
            raise _GiftAbort("赠予请求已被处理或状态已变化")

    async def create_gift(
        self,
        sender: Player,
        receiver_id: str,
        item_name: str,
        count: int,
        sender_name: str = "",
    ):
        """Escrow the sender's item and create one pending gift atomically."""
        if isinstance(count, bool) or not isinstance(count, int) or count <= 0:
            return False, "数量必须大于0", None
        if not receiver_id or receiver_id == sender.user_id:
            return False, "不能赠予物品给自己", None
        if not item_name:
            return False, "请指定要赠予的物品名称", None

        try:
            async with self.db.transaction():
                current_sender = await self.db.get_player_by_id(sender.user_id)
                receiver = await self.db.get_player_by_id(receiver_id)
                if not current_sender or not receiver:
                    raise _GiftAbort("目标玩家尚未开始修仙")

                _, storage_raw = await self._read_gift_inventory_locked(sender.user_id, "storage")
                _, pills_raw = await self._read_gift_inventory_locked(sender.user_id, "pill")
                try:
                    storage = json.loads(storage_raw or "{}")
                    pills = json.loads(pills_raw or "{}")
                except (TypeError, json.JSONDecodeError) as exc:
                    raise _GiftAbort("玩家物品数据损坏") from exc
                if not isinstance(storage, dict) or not isinstance(pills, dict):
                    raise _GiftAbort("玩家物品数据损坏")

                if self._gift_quantity(storage, item_name) >= count:
                    source_type = "storage"
                elif self._gift_quantity(pills, item_name) >= count:
                    source_type = "pill"
                else:
                    raise _GiftAbort(f"你没有足够的【{item_name}】")

                new_raw = await self._mutate_gift_inventory_locked(
                    current_sender, source_type, item_name, count, adding=False
                )
                gift_id = await self.db.ext.create_pending_gift(
                    receiver_id=receiver_id,
                    sender_id=current_sender.user_id,
                    sender_name=sender_name or current_sender.user_name or current_sender.user_id[:8],
                    item_name=item_name,
                    count=count,
                    expires_hours=24,
                    source_type=source_type,
                    commit=False,
                )
        except _GiftAbort as exc:
            return False, str(exc), None

        if source_type == "pill":
            sender.pills_inventory = new_raw
        else:
            sender.storage_ring_items = new_raw
        return True, f"赠予请求已发送，物品将在对方确认后交付（ID：{gift_id}）", source_type

    async def accept_gift(self, player: Player):
        """Accept one gift with a conditional exactly-once claim."""
        outcome = None
        try:
            async with self.db.transaction():
                current_receiver = await self.db.get_player_by_id(player.user_id)
                if not current_receiver:
                    raise _GiftAbort("接收者不存在或已被删除")
                gift = await self._fetch_gift_locked(receiver_id=player.user_id, live=True)
                if gift:
                    new_raw = await self._mutate_gift_inventory_locked(
                        current_receiver,
                        gift.get("source_type", "storage"),
                        gift["item_name"],
                        gift["count"],
                        adding=True,
                    )
                    await self._claim_gift_locked(gift)
                    outcome = (True, gift, new_raw)
                else:
                    expired_gift = await self._fetch_gift_locked(receiver_id=player.user_id, live=False)
                    if not expired_gift:
                        outcome = (False, None, None)
                    else:
                        sender, sender_raw = await self._restore_gift_locked(expired_gift)
                        await self._claim_gift_locked(expired_gift, expired=True)
                        outcome = (False, expired_gift, sender_raw)
        except _GiftAbort as exc:
            return False, str(exc), None

        success, gift, new_raw = outcome
        if gift is None:
            return False, "你没有待接收的赠予物品", None
        if not success:
            return False, f"赠予【{gift['item_name']}】已过期，物品已返还给发送者", None

        source_type = gift.get("source_type", "storage")
        if source_type == "pill":
            player.pills_inventory = new_raw
            location = "丹药背包"
        else:
            player.storage_ring_items = new_raw
            location = "储物戒"
        return True, (
            f"已接收来自【{gift['sender_name']}】的赠予！\n"
            f"获得：【{gift['item_name']}】x{gift['count']}\n"
            f"已存入{location}"
        ), source_type

    async def reject_gift(self, player: Player):
        """Reject one live gift and refund its sender atomically."""
        try:
            async with self.db.transaction():
                gift = await self._fetch_gift_locked(receiver_id=player.user_id, live=True)
                if not gift:
                    return False, "你没有待处理的赠予请求", None
                sender, sender_raw = await self._restore_gift_locked(gift)
                await self._claim_gift_locked(gift)
        except _GiftAbort as exc:
            return False, str(exc), None

        if gift.get("source_type", "storage") == "pill":
            sender.pills_inventory = sender_raw
        else:
            sender.storage_ring_items = sender_raw
        return True, (
            f"已拒绝来自【{gift['sender_name']}】的赠予\n"
            f"【{gift['item_name']}】x{gift['count']} 已返还"
        ), gift.get("source_type", "storage")

    async def cancel_gift(self, sender: Player, gift_id: int | None = None):
        """Cancel one sender-owned live gift and refund the escrow atomically."""
        try:
            async with self.db.transaction():
                gift = await self._fetch_gift_locked(
                    gift_id=gift_id, sender_id=sender.user_id, live=True
                )
                if not gift:
                    return False, "你没有可取消的赠予请求", None
                current_sender = await self.db.get_player_by_id(sender.user_id)
                if not current_sender:
                    raise _GiftAbort("赠予者不存在或已被删除")
                sender_raw = await self._mutate_gift_inventory_locked(
                    current_sender,
                    gift.get("source_type", "storage"),
                    gift["item_name"],
                    gift["count"],
                    adding=True,
                )
                await self._claim_gift_locked(gift)
        except _GiftAbort as exc:
            return False, str(exc), None

        if gift.get("source_type", "storage") == "pill":
            sender.pills_inventory = sender_raw
        else:
            sender.storage_ring_items = sender_raw
        return True, f"已取消赠予【{gift['item_name']}】x{gift['count']}，物品已返还", gift.get("source_type", "storage")

    async def expire_gift(self, gift_id: int):
        """Refund and conditionally claim one expired gift."""
        try:
            async with self.db.transaction():
                gift = await self._fetch_gift_locked(gift_id=gift_id, live=False)
                if not gift:
                    return False, "赠予不存在或尚未过期", None
                sender, sender_raw = await self._restore_gift_locked(gift)
                await self._claim_gift_locked(gift, expired=True)
        except _GiftAbort as exc:
            return False, str(exc), None

        if gift.get("source_type", "storage") == "pill":
            sender.pills_inventory = sender_raw
        else:
            sender.storage_ring_items = sender_raw
        return True, f"赠予【{gift['item_name']}】已过期，物品已返还", gift.get("source_type", "storage")

    async def expire_pending_gifts(self, receiver_id: str | None = None) -> int:
        """Expire gifts one by one; each refund has its own conditional claim."""
        clauses = ["expires_at <= ?"]
        params = [int(time.time())]
        if receiver_id is not None:
            clauses.append("receiver_id = ?")
            params.append(receiver_id)
        async with self.db.transaction():
            async with self.db.conn.execute(
                "SELECT id FROM pending_gifts WHERE " + " AND ".join(clauses),
                tuple(params),
                commit=False,
            ) as cursor:
                rows = await cursor.fetchall()
        processed = 0
        for row in rows:
            success, _, _ = await self.expire_gift(row[0])
            processed += int(success)
        return processed

    async def cancel_pending_gift(self, sender: Player, gift_id: int | None = None):
        """Compatibility alias for callers that use the pending-gift name."""
        return await self.cancel_gift(sender, gift_id)

    @player_required
    async def handle_gift_item(self, player: Player, event: AstrMessageEvent, args: str):
        """赠予物品给其他玩家（支持储物戒和丹药背包）"""
        target_id = None
        item_name = None
        count = 1

        # 从消息链中提取 At 组件和 Plain 文本
        text_parts = []
        message_chain = event.message_obj.message if hasattr(event, 'message_obj') and event.message_obj else []
        
        for comp in message_chain:
            if isinstance(comp, At):
                # 兼容多种At属性名
                if target_id is None:
                    if hasattr(comp, 'qq'):
                        target_id = str(comp.qq)
                    elif hasattr(comp, 'target'):
                        target_id = str(comp.target)
                    elif hasattr(comp, 'uin'):
                        target_id = str(comp.uin)
            elif isinstance(comp, Plain):
                text_parts.append(comp.text)

        # 合并文本内容并移除命令前缀
        text_content = "".join(text_parts).strip()
        for prefix in ["#赠予", "/赠予", "赠予"]:
            if text_content.startswith(prefix):
                text_content = text_content[len(prefix):].strip()
                break
        
        # 如果没有从At组件获取到target_id，尝试从文本解析纯数字QQ号
        if not target_id and text_content:
            parts = text_content.split(None, 1)
            if len(parts) >= 1:
                potential_id = parts[0].lstrip('@')
                if potential_id.isdigit() and len(potential_id) >= 5:
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
                f"示例：{CMD_GIFT_ITEM} 123456789 精铁 5\n"
                f"━━━━━━━━━━━━━━━\n"
                f"💡 支持赠送储物戒和丹药背包中的物品"
            )
            return

        if not item_name:
            yield event.plain_result("请指定要赠予的物品名称")
            return

        if count <= 0:
            yield event.plain_result("数量必须大于0")
            return

        success, msg, source_type = await self.create_gift(
            sender=player,
            receiver_id=target_id,
            item_name=item_name,
            count=count,
            sender_name=event.get_sender_name(),
        )
        if not success:
            yield event.plain_result(f"赠予失败：{msg}")
            return

        source_label = "丹药背包" if source_type == "pill" else "储物戒"
        yield event.plain_result(
            f"📦 赠予请求已发送！\n"
            f"【{item_name}】x{count}（来自{source_label}）→ @{target_id}\n"
            f"等待对方确认...（24小时内有效）\n"
            f"对方可使用 {CMD_ACCEPT_GIFT} 接收或 {CMD_REJECT_GIFT} 拒绝"
        )

    @player_required
    async def handle_accept_gift(self, player: Player, event: AstrMessageEvent):
        """接收赠予的物品"""
        success, message, _ = await self.accept_gift(player)
        yield event.plain_result(("✅ " if success else "❌ ") + message)

    @player_required
    async def handle_reject_gift(self, player: Player, event: AstrMessageEvent):
        """拒绝赠予的物品"""
        success, message, _ = await self.reject_gift(player)
        yield event.plain_result(("✅ " if success else "❌ ") + message)

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

    def _categorize_items(self, items: dict) -> dict:
        """将物品按分类整理"""
        result = {cat: [] for cat in ITEM_CATEGORIES.keys()}
        
        for item_name, count in items.items():
            categorized = False
            for category, keywords in ITEM_CATEGORIES.items():
                if category == "其他":
                    continue
                # 检查物品名是否包含分类关键词
                for keyword in keywords:
                    if keyword in item_name or item_name in keyword:
                        result[category].append((item_name, count))
                        categorized = True
                        break
                if categorized:
                    break
            
            # 根据配置判断物品类型
            if not categorized:
                item_config = self.config_manager.items_data.get(item_name, {})
                item_type = item_config.get("type", "")
                
                if item_type in ["weapon", "武器"]:
                    result["装备"].append((item_name, count))
                elif item_type in ["armor", "防具", "accessory", "饰品"]:
                    result["装备"].append((item_name, count))
                elif item_type in ["technique", "功法", "main_technique"]:
                    result["功法"].append((item_name, count))
                elif item_type in ["material", "材料"]:
                    result["材料"].append((item_name, count))
                else:
                    result["其他"].append((item_name, count))
        
        # 移除空分类
        return {k: v for k, v in result.items() if v}

    @player_required
    async def handle_search_item(self, player: Player, event: AstrMessageEvent, keyword: str):
        """搜索储物戒中的物品"""
        if not keyword or keyword.strip() == "":
            yield event.plain_result(
                f"请指定搜索关键词\n"
                f"用法：{CMD_SEARCH_ITEM} 关键词\n"
                f"示例：{CMD_SEARCH_ITEM} 灵草"
            )
            return

        keyword = keyword.strip().lower()
        items = player.get_storage_ring_items()
        
        # 模糊搜索
        matched = []
        for item_name, count in items.items():
            if keyword in item_name.lower():
                matched.append((item_name, count))
        
        if not matched:
            yield event.plain_result(f"未找到包含「{keyword}」的物品")
            return
        
        lines = [f"=== 搜索结果：{keyword} ===\n"]
        for item_name, count in matched:
            lines.append(f"  · {item_name}×{count}\n")
        lines.append(f"\n共找到 {len(matched)} 种物品")
        
        yield event.plain_result("".join(lines))

    @player_required
    async def handle_store_all(self, player: Player, event: AstrMessageEvent, category: str = None):
        """批量存入物品（预留接口，实际物品来源需要其他系统配合）"""
        yield event.plain_result(
            f"📦 批量存入功能说明：\n"
            f"当前物品会在以下情况自动存入储物戒：\n"
            f"  · 商店购买物品\n"
            f"  · 历练/秘境获得物品\n"
            f"  · Boss击杀掉落\n"
            f"  · 悬赏任务奖励\n"
            f"  · 卸下装备\n"
            f"\n所有物品获取后会自动存入储物戒"
        )

    @player_required
    async def handle_retrieve_all(self, player: Player, event: AstrMessageEvent, category: str = None):
        """批量取出指定分类的物品"""
        if not category or category.strip() == "":
            yield event.plain_result(
                f"请指定要取出的分类\n"
                f"用法：{CMD_RETRIEVE_ALL} 分类名\n"
                f"可用分类：材料、装备、功法、其他\n"
                f"示例：{CMD_RETRIEVE_ALL} 材料"
            )
            return
        
        category = category.strip()
        if category not in ITEM_CATEGORIES:
            yield event.plain_result(f"未知分类：{category}\n可用分类：材料、装备、功法、其他")
            return
        
        items = player.get_storage_ring_items()
        categorized = self._categorize_items(items)
        cat_items = categorized.get(category, [])
        
        if not cat_items:
            yield event.plain_result(f"储物戒中没有【{category}】类物品")
            return
        
        # 取出所有该分类的物品
        retrieved = []
        failed = []
        for item_name, count in cat_items:
            success, msg = await self.storage_ring_manager.retrieve_item(player, item_name, count)
            if success:
                retrieved.append(f"{item_name}×{count}")
            else:
                failed.append(f"{item_name}：{msg}")
        
        lines = [f"=== 批量取出【{category}】 ===\n"]
        if retrieved:
            lines.append(f"✅ 已取出：\n")
            for item in retrieved:
                lines.append(f"  · {item}\n")
        if failed:
            lines.append(f"\n❌ 失败：\n")
            for item in failed:
                lines.append(f"  · {item}\n")
        
        yield event.plain_result("".join(lines))
