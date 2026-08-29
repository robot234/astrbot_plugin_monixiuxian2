# handlers/spirit_farm_handlers.py
"""灵田处理器"""

import re

from astrbot.api.event import AstrMessageEvent

from ..data import DataBase
from ..managers.spirit_farm_manager import SpiritFarmManager
from ..models import Player
from .utils import player_required

__all__ = ["SpiritFarmHandlers"]


class SpiritFarmHandlers:
    """灵田处理器"""

    def __init__(self, db: DataBase, farm_mgr: SpiritFarmManager):
        self.db = db
        self.mgr = farm_mgr

    def _parse_plant_input(self, raw_text: str) -> tuple[str, int | None]:
        """解析种植参数，支持数量、全部、最大等写法。"""
        text = (raw_text or "").replace("\u3000", " ").strip()
        if not text:
            return "", None

        text = re.sub(r"\s+", " ", text)

        if text.startswith("批量种植"):
            text = text[len("批量种植"):].strip()
        elif text.startswith("种植"):
            text = text[len("种植"):].strip()

        if not text:
            return "", None

        all_tokens = {"全部", "全种", "种满", "拉满", "最大", "max", "MAX", "all", "ALL"}

        parts = text.split()
        if len(parts) >= 2:
            if parts[0] in all_tokens:
                return " ".join(parts[1:]).strip(), -1
            if parts[-1] in all_tokens:
                return " ".join(parts[:-1]).strip(), -1
            if parts[0].isdigit():
                return " ".join(parts[1:]).strip(), int(parts[0])
            if parts[-1].isdigit():
                return " ".join(parts[:-1]).strip(), int(parts[-1])

        match = re.match(r"^(.+?)[xX＊*](\d+)$", text)
        if match:
            return match.group(1).strip(), int(match.group(2))

        match = re.match(r"^(.+?)(\d+)$", text)
        if match:
            return match.group(1).strip(), int(match.group(2))

        for token in all_tokens:
            if text.startswith(token):
                return text[len(token):].strip(), -1
            if text.endswith(token):
                return text[:-len(token)].strip(), -1

        return text, 1

    @player_required
    async def handle_farm_info(self, player: Player, event: AstrMessageEvent):
        """查看灵田信息"""
        info = await self.mgr.get_farm_info(player.user_id)
        yield event.plain_result(info)

    @player_required
    async def handle_create_farm(self, player: Player, event: AstrMessageEvent):
        """开垦灵田"""
        success, msg = await self.mgr.create_farm(player)
        yield event.plain_result(msg)

    @player_required
    async def handle_plant(self, player: Player, event: AstrMessageEvent, herb_name: str = ""):
        """种植灵草"""
        name, count = self._parse_plant_input(herb_name)

        if not name:
            yield event.plain_result(
                "🌱 可种植的灵草\n"
                "━━━━━━━━━━━━━━━\n"
                "灵草 - 1小时（修为+500）\n"
                "血灵草 - 2小时（修为+1500）\n"
                "冰心草 - 4小时（修为+4000）\n"
                "火焰花 - 8小时（修为+10000）\n"
                "九叶灵芝 - 24小时（修为+30000）\n"
                "━━━━━━━━━━━━━━━\n"
                "📌 用法示例：\n"
                "/种植 灵草\n"
                "/种植 灵草 5\n"
                "/种植 5 灵草\n"
                "/种植 灵草x5\n"
                "/种植 灵草 全部\n"
                "/批量种植 血灵草 8"
            )
            return

        if count is None:
            count = 1
        elif count == -1:
            count = 999999
        else:
            count = max(1, count)

        success, msg = await self.mgr.plant_herb(player, name, count)
        yield event.plain_result(msg)

    @player_required
    async def handle_harvest(self, player: Player, event: AstrMessageEvent):
        """收获灵草"""
        success, msg = await self.mgr.harvest(player)
        yield event.plain_result(msg)

    @player_required
    async def handle_upgrade_farm(self, player: Player, event: AstrMessageEvent):
        """升级灵田"""
        success, msg = await self.mgr.upgrade_farm(player)
        yield event.plain_result(msg)
