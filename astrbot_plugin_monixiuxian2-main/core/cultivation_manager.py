# core/cultivation_manager.py
import random
from typing import Dict, Optional

from astrbot.api import AstrBotConfig, logger
from ..config_manager import ConfigManager
from ..models import Player

class CultivationManager:
    """修炼管理器，包含角色生成和闭关修炼功能"""

    def __init__(self, config: AstrBotConfig, config_manager: ConfigManager):
        self.config = config
        self.config_manager = config_manager

        # 灵根名称到配置项键的映射
        self.root_to_config_key = {
            # 废柴系列
            "伪": "PSEUDO_ROOT_SPEED",

            # 多灵根系列
            "金木水火": "QUAD_ROOT_SPEED",
            "金木水土": "QUAD_ROOT_SPEED",
            "金木火土": "QUAD_ROOT_SPEED",
            "金水火土": "QUAD_ROOT_SPEED",
            "木水火土": "QUAD_ROOT_SPEED",

            "金木水": "TRI_ROOT_SPEED",
            "金木火": "TRI_ROOT_SPEED",
            "金木土": "TRI_ROOT_SPEED",
            "金水火": "TRI_ROOT_SPEED",
            "金水土": "TRI_ROOT_SPEED",
            "金火土": "TRI_ROOT_SPEED",
            "木水火": "TRI_ROOT_SPEED",
            "木水土": "TRI_ROOT_SPEED",
            "木火土": "TRI_ROOT_SPEED",
            "水火土": "TRI_ROOT_SPEED",

            "金木": "DUAL_ROOT_SPEED",
            "金水": "DUAL_ROOT_SPEED",
            "金火": "DUAL_ROOT_SPEED",
            "金土": "DUAL_ROOT_SPEED",
            "木水": "DUAL_ROOT_SPEED",
            "木火": "DUAL_ROOT_SPEED",
            "木土": "DUAL_ROOT_SPEED",
            "水火": "DUAL_ROOT_SPEED",
            "水土": "DUAL_ROOT_SPEED",
            "火土": "DUAL_ROOT_SPEED",

            # 五行单灵根
            "金": "WUXING_ROOT_SPEED",
            "木": "WUXING_ROOT_SPEED",
            "水": "WUXING_ROOT_SPEED",
            "火": "WUXING_ROOT_SPEED",
            "土": "WUXING_ROOT_SPEED",

            # 变异灵根
            "雷": "THUNDER_ROOT_SPEED",
            "冰": "ICE_ROOT_SPEED",
            "风": "WIND_ROOT_SPEED",
            "暗": "DARK_ROOT_SPEED",
            "光": "LIGHT_ROOT_SPEED",

            # 天灵根（单属性极致）
            "天金": "HEAVENLY_ROOT_SPEED",
            "天木": "HEAVENLY_ROOT_SPEED",
            "天水": "HEAVENLY_ROOT_SPEED",
            "天火": "HEAVENLY_ROOT_SPEED",
            "天土": "HEAVENLY_ROOT_SPEED",
            "天雷": "HEAVENLY_ROOT_SPEED",

            # 传说级
            "阴阳": "YIN_YANG_ROOT_SPEED",
            "融合": "FUSION_ROOT_SPEED",

            # 神话级
            "混沌": "CHAOS_ROOT_SPEED",

            # 禁忌级体质
            "先天道体": "INNATE_BODY_SPEED",
            "神圣体质": "DIVINE_BODY_SPEED"
        }

        # 灵根池定义（按权重类别）
        self.root_pools = {
            "PSEUDO": ["伪"],
            "QUAD": ["金木水火", "金木水土", "金木火土", "金水火土", "木水火土"],
            "TRI": ["金木水", "金木火", "金木土", "金水火", "金水土", "金火土", "木水火", "木水土", "木火土", "水火土"],
            "DUAL": ["金木", "金水", "金火", "金土", "木水", "木火", "木土", "水火", "水土", "火土"],
            "WUXING": ["金", "木", "水", "火", "土"],
            "VARIANT": ["雷", "冰", "风", "暗", "光"],
            "HEAVENLY": ["天金", "天木", "天水", "天火", "天土", "天雷"],
            "LEGENDARY": ["阴阳", "融合"],
            "MYTHIC": ["混沌"],
            "DIVINE_BODY": ["先天道体", "神圣体质"]
        }

    def _calculate_base_stats(self, level_index: int, cultivation_type: str = "灵修") -> Dict[str, int]:
        """从境界配置中读取基础属性

        Args:
            level_index: 境界索引
            cultivation_type: 修炼类型，"灵修"或"体修"

        Returns:
            基础属性字典
        """
        level_data = self.config_manager.get_level_data(cultivation_type)
        if 0 <= level_index < len(level_data):
            level_config = level_data[level_index]
            base_lifespan = level_config.get("base_lifespan", 100 + level_index * 50)
            base_max_spiritual_qi = level_config.get("base_max_spiritual_qi", 50 + level_index * 20)
            base_max_blood_qi = level_config.get("base_max_blood_qi", 50 + level_index * 20)
            base_mental_power = level_config.get("base_mental_power", 50 + level_index * 20)
            base_physical_damage = level_config.get("base_physical_damage", 10 + level_index * 8)
            base_magic_damage = level_config.get("base_magic_damage", 10 + level_index * 8)
            base_physical_defense = level_config.get("base_physical_defense", 5 + level_index * 4)
            base_magic_defense = level_config.get("base_magic_defense", 5 + level_index * 4)

            return {
                "lifespan": base_lifespan,
                "max_spiritual_qi": base_max_spiritual_qi,
                "max_blood_qi": base_max_blood_qi,
                "mental_power": base_mental_power,
                "physical_damage": base_physical_damage,
                "magic_damage": base_magic_damage,
                "physical_defense": base_physical_defense,
                "magic_defense": base_magic_defense
            }
        else:
            # 回退逻辑，使用默认计算
            return {
                "lifespan": 100 + level_index * 50,
                "max_spiritual_qi": 50 + level_index * 20,
                "max_blood_qi": 50 + level_index * 20,
                "mental_power": 50 + level_index * 20,
                "physical_damage": 10 + level_index * 8,
                "magic_damage": 10 + level_index * 8,
                "physical_defense": 5 + level_index * 4,
                "magic_defense": 5 + level_index * 4
            }

    def _get_random_spiritual_root(self) -> str:
        """基于权重随机抽取灵根"""
        weights_config = self.config.get("SPIRIT_ROOT_WEIGHTS", {})

        # 构建权重池
        weight_pool = []

        # 伪灵根
        pseudo_weight = weights_config.get("PSEUDO_ROOT_WEIGHT", 1)
        weight_pool.extend([("PSEUDO", root) for root in self.root_pools["PSEUDO"]] * pseudo_weight)

        # 四灵根
        quad_weight = weights_config.get("QUAD_ROOT_WEIGHT", 10)
        weight_pool.extend([("QUAD", root) for root in self.root_pools["QUAD"]] * quad_weight)

        # 三灵根
        tri_weight = weights_config.get("TRI_ROOT_WEIGHT", 30)
        weight_pool.extend([("TRI", root) for root in self.root_pools["TRI"]] * tri_weight)

        # 双灵根
        dual_weight = weights_config.get("DUAL_ROOT_WEIGHT", 100)
        weight_pool.extend([("DUAL", root) for root in self.root_pools["DUAL"]] * dual_weight)

        # 五行单灵根
        wuxing_weight = weights_config.get("WUXING_ROOT_WEIGHT", 200)
        weight_pool.extend([("WUXING", root) for root in self.root_pools["WUXING"]] * wuxing_weight)

        # 变异灵根
        variant_weight = weights_config.get("VARIANT_ROOT_WEIGHT", 20)
        weight_pool.extend([("VARIANT", root) for root in self.root_pools["VARIANT"]] * variant_weight)

        # 天灵根
        heavenly_weight = weights_config.get("HEAVENLY_ROOT_WEIGHT", 5)
        weight_pool.extend([("HEAVENLY", root) for root in self.root_pools["HEAVENLY"]] * heavenly_weight)

        # 传说级
        legendary_weight = weights_config.get("LEGENDARY_ROOT_WEIGHT", 2)
        weight_pool.extend([("LEGENDARY", root) for root in self.root_pools["LEGENDARY"]] * legendary_weight)

        # 神话级
        mythic_weight = weights_config.get("MYTHIC_ROOT_WEIGHT", 1)
        weight_pool.extend([("MYTHIC", root) for root in self.root_pools["MYTHIC"]] * mythic_weight)

        # 禁忌级体质
        divine_weight = weights_config.get("DIVINE_BODY_WEIGHT", 1)
        weight_pool.extend([("DIVINE_BODY", root) for root in self.root_pools["DIVINE_BODY"]] * divine_weight)

        if not weight_pool:
            # 兜底方案：默认返回金灵根
            logger.warning("灵根权重池为空，使用默认金灵根")
            return "金"

        # 随机选择
        _, selected_root = random.choice(weight_pool)
        return selected_root

    def _get_root_description(self, root_name: str) -> str:
        """获取灵根描述"""
        descriptions = {
            "伪": "【废柴】资质低劣，修炼如龟速",

            # 四灵根
            "金木水火": "【凡品】四灵根杂乱，资质平庸",
            "金木水土": "【凡品】四灵根杂乱，资质平庸",
            "金木火土": "【凡品】四灵根杂乱，资质平庸",
            "金水火土": "【凡品】四灵根杂乱，资质平庸",
            "木水火土": "【凡品】四灵根杂乱，资质平庸",

            # 三灵根
            "金木水": "【凡品】三灵根较杂，资质一般",
            "金木火": "【凡品】三灵根较杂，资质一般",
            "金木土": "【凡品】三灵根较杂，资质一般",
            "金水火": "【凡品】三灵根较杂，资质一般",
            "金水土": "【凡品】三灵根较杂，资质一般",
            "金火土": "【凡品】三灵根较杂，资质一般",
            "木水火": "【凡品】三灵根较杂，资质一般",
            "木水土": "【凡品】三灵根较杂，资质一般",
            "木火土": "【凡品】三灵根较杂，资质一般",
            "水火土": "【凡品】三灵根较杂，资质一般",

            # 双灵根
            "金木": "【良品】双灵根，较为常见",
            "金水": "【良品】双灵根，较为常见",
            "金火": "【良品】双灵根，较为常见",
            "金土": "【良品】双灵根，较为常见",
            "木水": "【良品】双灵根，较为常见",
            "木火": "【良品】双灵根，较为常见",
            "木土": "【良品】双灵根，较为常见",
            "水火": "【良品】双灵根，较为常见",
            "水土": "【良品】双灵根，较为常见",
            "火土": "【良品】双灵根，较为常见",

            # 五行单灵根
            "金": "【上品】金之精华，锋锐无双",
            "木": "【上品】木之生机，生生不息",
            "水": "【上品】水之灵韵，柔中带刚",
            "火": "【上品】火之烈焰，霸道无匹",
            "土": "【上品】土之厚重，稳如磐石",

            # 变异灵根
            "雷": "【稀有】天地雷霆，毁灭之力",
            "冰": "【稀有】极寒冰封，万物凝固",
            "风": "【稀有】疾风骤雨，来去无踪",
            "暗": "【稀有】幽暗深邃，诡异莫测",
            "光": "【稀有】神圣光明，普照万物",

            # 天灵根
            "天金": "【极品】天选之子，金之极致",
            "天木": "【极品】天选之子，木之极致",
            "天水": "【极品】天选之子，水之极致",
            "天火": "【极品】天选之子，火之极致",
            "天土": "【极品】天选之子，土之极致",
            "天雷": "【极品】天选之子，雷之极致",

            # 传说级
            "阴阳": "【传说】阴阳调和，造化玄机",
            "融合": "【传说】五行融合，万法归一",

            # 神话级
            "混沌": "【神话】混沌初开，包罗万象",

            # 禁忌级
            "先天道体": "【禁忌】天生道体，与天地同寿",
            "神圣体质": "【禁忌】神之后裔，天赋异禀"
        }
        return descriptions.get(root_name, "【未知】神秘的灵根")

    def generate_new_player_stats(self, user_id: str, cultivation_type: str = "灵修") -> Player:
        """生成新玩家的初始数据

        Args:
            user_id: 用户ID
            cultivation_type: 修炼类型，"灵修"或"体修"
        """
        import random

        root = self._get_random_spiritual_root()
        initial_gold = self.config["VALUES"]["INITIAL_GOLD"]

        if cultivation_type == "灵修":
            # 灵修初始数据：寿命100，修为0，灵气100-1000，法伤5-100，物伤5，法防0，物防5，精神力100-500
            return Player(
                user_id=user_id,
                spiritual_root=f"{root}灵根",
                cultivation_type="灵修",
                lifespan=100,
                experience=0,
                gold=initial_gold,
                spiritual_qi=random.randint(100, 1000),
                max_spiritual_qi=random.randint(100, 1000),
                blood_qi=0,
                max_blood_qi=0,
                magic_damage=random.randint(5, 100),
                physical_damage=5,
                magic_defense=0,
                physical_defense=5,
                mental_power=random.randint(100, 500)
            )
        else:  # 体修
            # 体修初始数据：寿命50-100，修为0，气血100-500，法伤0，物伤100-500，法防50-200，物防100-500，精神力100-500
            initial_blood_qi = random.randint(100, 500)
            return Player(
                user_id=user_id,
                spiritual_root=f"{root}灵根",
                cultivation_type="体修",
                lifespan=random.randint(50, 100),
                experience=0,
                gold=initial_gold,
                spiritual_qi=0,
                max_spiritual_qi=0,
                blood_qi=initial_blood_qi,
                max_blood_qi=initial_blood_qi,
                magic_damage=0,
                physical_damage=random.randint(100, 500),
                magic_defense=random.randint(50, 200),
                physical_defense=random.randint(100, 500),
                mental_power=random.randint(100, 500)
            )

    def get_spiritual_root_speed(self, player: Player) -> float:
        """获取玩家灵根的修炼速度倍率

        Args:
            player: 玩家对象

        Returns:
            float: 灵根修炼速度倍率
        """
        # 从 player.spiritual_root 中提取灵根名称（去掉"灵根"两个字）
        root_name = player.spiritual_root.replace("灵根", "")

        # 获取对应的配置键
        config_key = self.root_to_config_key.get(root_name)
        if not config_key:
            logger.warning(f"未找到灵根 {root_name} 的速度配置，使用默认倍率 1.0")
            return 1.0

        # 从配置中获取速度倍率
        speeds_config = self.config.get("SPIRIT_ROOT_SPEEDS", {})
        speed = speeds_config.get(config_key, 1.0)
        return speed

    def calculate_cultivation_exp(
        self,
        player: Player,
        minutes: int,
        technique_bonus: float = 0.0,
        pill_multipliers: Optional[Dict[str, float]] = None
    ) -> int:
        """计算闭关修炼获得的修为

        Args:
            player: 玩家对象
            minutes: 闭关时长（分钟）
            technique_bonus: 心法提供的修为倍率加成（来自主修心法的exp_multiplier）

        Returns:
            int: 获得的修为值
        """
        # 获取基础修为配置
        base_exp = self.config["VALUES"].get("BASE_EXP_PER_MINUTE", 100)

        # 获取灵根速度倍率
        root_speed = self.get_spiritual_root_speed(player)

        # 获取丹药修炼倍率加成
        cultivation_pill_bonus = 1.0
        if pill_multipliers:
            cultivation_pill_bonus = pill_multipliers.get("cultivation_speed", 1.0)

        # 计算总修为倍率：灵根倍率 * (1 + 心法倍率) * 丹药倍率
        total_multiplier = root_speed * (1.0 + technique_bonus) * cultivation_pill_bonus

        # 计算总修为：基础修为 * 时长 * 总倍率
        total_exp = int(base_exp * minutes * total_multiplier)

        logger.info(
            f"玩家 {player.user_id} 闭关 {minutes} 分钟，"
            f"基础修为 {base_exp}，灵根倍率 {root_speed}，"
            f"心法加成 {technique_bonus:.2%}，丹药倍率 {cultivation_pill_bonus:.2f}，"
            f"获得修为 {total_exp}"
        )
        return total_exp

