import asyncio
from io import BytesIO
from pathlib import Path
from typing import Optional, Dict

try:
    from PIL import Image, ImageDraw, ImageFont
    HAS_PIL = True
except ImportError:
    HAS_PIL = False

from astrbot.api import logger
from astrbot.core.utils.astrbot_path import get_astrbot_data_path

# 资源路径配置
# 默认寻找 data/xiuxian 目录 (AstrBot数据目录下的xiuxian文件夹)
ASSETS_PATH = Path(get_astrbot_data_path()) / "xiuxian"
FONT_PATH = ASSETS_PATH / "font" / "font.ttf"
IMG_PATH = ASSETS_PATH / "info_img"

class ImageGenerator:
    """图片生成器"""
    
    def __init__(self):
        self.has_pil = HAS_PIL
        if not self.has_pil:
            logger.warning("【修仙插件】未检测到 Pillow 库，将无法生成图片卡片。请安装 pip install Pillow")
            
    def _get_font(self, size: int):
        if not FONT_PATH.exists():
            # 尝试使用系统字体或默认
            return ImageFont.load_default()
        return ImageFont.truetype(str(FONT_PATH), size)

    async def generate_user_info_card(self, user_id: str, detail_map: Dict) -> Optional[BytesIO]:
        """
        生成用户信息卡片
        
        Args:
            user_id: 用户ID
            detail_map: 属性字典 (参考 NoneBot 插件格式)
            
        Returns:
            BytesIO: 图片数据，如果生成失败返回None
        """
        if not self.has_pil:
            return None
            
        if not IMG_PATH.exists():
            logger.warning(f"【修仙插件】资源目录 {IMG_PATH} 不存在，无法生成卡片。")
            return None

        try:
            # 跑在线程池中避免阻塞
            return await asyncio.to_thread(self._draw_info_card_sync, user_id, detail_map)
        except Exception as e:
            logger.error(f"生成图片失败: {e}")
            return None

    def _draw_info_card_sync(self, user_id: str, detail_map: Dict) -> BytesIO:
        # 画布基础尺寸
        width = 1100
        height = 2250
        
        # 1. 背景图
        back_path = IMG_PATH / "back.png"
        if back_path.exists():
            img = Image.open(back_path).convert("RGBA").resize((width, height))
        else:
            img = Image.new("RGBA", (width, height), (50, 50, 50, 255))
            
        # 字体
        font_36 = self._get_font(36)
        font_40 = self._get_font(40)
        color_text = (242, 250, 242)
        
        draw = ImageDraw.Draw(img)
        
        # 简单绘制逻辑 (复刻原版布局)
        
        # 2. 基本信息栏 (头像位置预留)
        # 绘制 QQ/User ID
        line3_path = IMG_PATH / "line3.png"
        if line3_path.exists():
            line3 = Image.open(line3_path).convert("RGBA").resize((400, 60))
            # 绘制ID
            l_draw = ImageDraw.Draw(line3)
            id_text = f"ID: {user_id}"
            w = l_draw.textlength(id_text, font=font_36)
            l_draw.text(((400-w)/2, 10), id_text, fill=color_text, font=font_36)
            img.paste(line3, (130, 520), line3)

        # 3. 属性列表 (右侧)
        right_keys = ['道号', '境界', '修为', '灵石', '战力']
        base_y = 100
        for i, key in enumerate(right_keys):
            val = detail_map.get(key, "未知")
            self._draw_status_line(img, key, str(val), 550, base_y + i * 103, font_36, color_text)

        # 4. 基本信息 (中间)
        self._draw_section_header(img, "【基本信息】", 600, font_40, color_text)
        base_keys = ["灵根", "突破状态", "主修功法", "攻击力", "法器", "防具"]
        base_list_y = 703
        for i, key in enumerate(base_keys):
            val = detail_map.get(key, "无")
            self._draw_wide_line(img, key, str(val), 100, base_list_y + i * 103, font_36, color_text)

        # 5. 宗门信息
        sect_y_header = base_list_y + len(base_keys) * 103 + 50 # 动态计算高度? 原版是硬编码
        sect_y_header = 1442 # 原版硬编码
        self._draw_section_header(img, "【宗门信息】", sect_y_header, font_40, color_text)
        
        sect_keys = ["所在宗门", "宗门职位"]
        sect_y_list = 1547
        for i, key in enumerate(sect_keys):
            val = detail_map.get(key, "无")
            self._draw_wide_line(img, key, str(val), 100, sect_y_list + i * 103, font_36, color_text)

        # 6. 转换输出
        img = img.convert("RGB")
        output = BytesIO()
        img.save(output, format="JPEG", quality=90)
        output.seek(0)
        return output

    def _draw_status_line(self, img, key, value, x, y, font, color):
        path = IMG_PATH / "line3.png"
        text = f"{key}:{value}"
        if path.exists():
            line = Image.open(path).convert("RGBA").resize((450, 68))
            d = ImageDraw.Draw(line)
            try:
                # Pillow 9.2+ using textbbox or textlength, older using textsize
                # simple centered logic
                d.text((70, 15), text, fill=color, font=font)
            except:
                 d.text((70, 15), text, fill=color, font=font)
            img.paste(line, (x, y), line)
        else:
            # fallback
            d = ImageDraw.Draw(img)
            d.text((x, y), text, fill=color, font=font)

    def _draw_wide_line(self, img, key, value, x, y, font, color):
        path = IMG_PATH / "line4.png"
        text = f"{key}:{value}"
        if path.exists():
            line = Image.open(path).convert("RGBA").resize((900, 100))
            d = ImageDraw.Draw(line)
            d.text((100, 30), text, fill=color, font=font)
            img.paste(line, (x, y), line)
        else:
            d = ImageDraw.Draw(img)
            d.text((x, y), text, fill=color, font=font)

    def _draw_section_header(self, img, text, y, font, color):
        path = IMG_PATH / "line2.png"
        if path.exists():
            line = Image.open(path).convert("RGBA").resize((900, 100))
            d = ImageDraw.Draw(line)
            # Centered text approx
            w = d.textlength(text, font=font)
            d.text(((900-w)/2, 30), text, fill=color, font=font)
            img.paste(line, (100, y), line)
        else:
            d = ImageDraw.Draw(img)
            d.text((100, y), text, fill=color, font=font)
