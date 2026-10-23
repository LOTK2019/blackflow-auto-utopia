from dataclasses import dataclass, field, asdict
import json
import os
import sys
from pathlib import Path
from .rewards import DEFAULT_REWARD_ORDER

APP_ROOT = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent.parent


def data_root(install_root, frozen, environ=None):
    environ = os.environ if environ is None else environ
    if not frozen:
        return Path(install_root)
    if environ.get("BLACKFLOW_DATA_DIR"):
        return Path(environ["BLACKFLOW_DATA_DIR"]).expanduser().resolve()
    return Path(environ.get("LOCALAPPDATA", str(Path.home() / "AppData/Local"))) / "BlackFlowUtopia"


ROOT = data_root(APP_ROOT, getattr(sys, "frozen", False))
ROOT.mkdir(parents=True, exist_ok=True)
RESOURCE_ROOT = Path(getattr(sys, "_MEIPASS", APP_ROOT))
BUNDLED_MAA = RESOURCE_ROOT / "maa" if (RESOURCE_ROOT / "maa/MaaCore.dll").is_file() else None


def read_blackflow_strategy(maa_dir):
    path = Path(maa_dir) / "resource/roguelike/BlackFlow/strategy.json"
    try:
        strategy = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError(f"MAA 黑流树海策略缺失或损坏：{path}；请使用完整的独立版引擎或更新 MAA 程序与配套资源") from exc
    profile = next((p for p in strategy.get("profiles", []) if p.get("id") == "burn_with_investment"), None)
    flight = next((m for m in strategy.get("modules", []) if m.get("id") == "mechanic_flight"), None)
    missing = [name for name, value in (("burn_with_investment", profile), ("mechanic_flight", flight)) if value is None]
    if missing:
        raise ValueError("MAA 资源不兼容，缺少黑流树海策略：" + "、".join(missing) + "；请使用独立版内置引擎，或同时更新 MAA 程序与资源")
    return strategy, profile, flight
REWARD_TARGETS = {"默认排序": "", "空间租赁（背包+2）": "6", "林间代步（加工品）": "2", "调查预付款（8源石锭）": "5", "未编号物（普通收藏品）": "4", "退行补偿（随机收藏品）": "", "巢寄生（背包-1）": "3"}


@dataclass
class Config:
    maa_dir: str = str(BUNDLED_MAA or "")
    adb_path: str = ""
    address: str = "auto"
    difficulty: int = 16
    roles: str = "灵活部署"
    six_star: str = "结城理"
    four_stars: list[str] = field(default_factory=lambda: ["冬时", "深海色"])
    use_support: bool = False
    use_nonfriend_support: bool = False
    fallback_six_stars: list[str] = field(default_factory=list)
    allow_other_six_star: bool = True
    reward_target: str = "默认排序"
    prepare_squad: str = "堡垒战术分队"
    prepare_roles: str = "坚不可摧"
    phase_timeout: int = 900
    prepare_method: str = '黄商店种植'
    node_filter_enabled: bool = False
    min_effective_nodes: int = 10
    reward_priority: list[str] = field(default_factory=lambda:list(DEFAULT_REWARD_ORDER))
    require_first_reward: bool = False
    required_reward_top_n: int = 0  # 0关闭；旧版 require_first_reward=True 仍按前1项。
    animal_counts: dict[str,int] = field(default_factory=lambda:{'猫':0,'狗':0,'三头犬':0})

    @property
    def require_animals(self):
        return any(self.animal_counts.values())

    @property
    def desired_animals(self):
        names={'猫':'襁褓中的猫','狗':'襁褓中的狗','三头犬':'襁褓三头犬'}
        return [names[name] for name,count in self.animal_counts.items() for _ in range(count)]

    @classmethod
    def load(cls, path=None):
        target = Path(path) if path is not None else ROOT / "config.json"
        if not target.is_file() and path is None and APP_ROOT != ROOT and (APP_ROOT / "config.json").is_file():
            target = APP_ROOT / "config.json"  # 首次使用可导入旧版旁置配置。
        data = json.loads(target.read_text(encoding="utf-8")) if target.is_file() else {}
        data.pop("max_cycles", None)  # 兼容移除循环上限之前保存的配置。
        if BUNDLED_MAA:
            data["maa_dir"] = str(BUNDLED_MAA)  # 独立版永远使用配套内置资源。
        return cls(**data)

    def save(self, path=None):
        target = Path(path) if path is not None else ROOT / "config.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        data = asdict(self)
        if BUNDLED_MAA:
            data["maa_dir"] = ""  # 不保存随解压位置变化的内置引擎绝对路径。
        target.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def operators(self):
        chars = json.loads((Path(self.maa_dir) / "resource/battle_data.json").read_text(encoding="utf-8"))["chars"]
        return {v["name"]: v for v in chars.values() if not v.get("name", "").startswith("预备干员")}

    def validate(self, check_strategy=True):
        if type(self.required_reward_top_n) is not int or not 0 <= self.required_reward_top_n <= len(DEFAULT_REWARD_ORDER):
            raise ValueError('必须命中的奖励范围须为0～12；0表示关闭')
        if set(self.animal_counts) != {'猫','狗','三头犬'} or any(type(n) is not int or not 0<=n<=3 for n in self.animal_counts.values()) or sum(self.animal_counts.values())>3:
            raise ValueError('猫、狗、三头犬的数量须为0～3，要求的总数不超过3；0表示不要求')
        if self.require_animals and self.prepare_method != '黄商店种植':
            raise ValueError('指定动物组合需要选择黄商店种植')
        if len(self.reward_priority) != len(DEFAULT_REWARD_ORDER) or set(self.reward_priority) != set(DEFAULT_REWARD_ORDER):
            raise ValueError('开局奖励排序须包含全部12个选项，且不能重复')
        from .strategy import PREPARE_METHODS
        if self.prepare_method not in PREPARE_METHODS:
            raise ValueError('准备方式无效')
        if not 1 <= self.min_effective_nodes <= 100:
            raise ValueError('有效节点数量须为1～100')
        if not Path(self.adb_path).is_file():
            raise ValueError("找不到 ADB，请检查路径")
        if not (Path(self.maa_dir) / "MaaCore.dll").is_file():
            raise ValueError("找不到 MaaCore.dll，请选择 MAA 安装目录")
        if check_strategy:
            read_blackflow_strategy(self.maa_dir)
        if not 2 <= self.difficulty <= 16:
            raise ValueError("正式局保密等级必须为 2～16；请确保账号已解锁所选等级")
        if len(self.four_stars) != 2 or len(set([self.six_star, *self.four_stars])) != 3:
            raise ValueError("需要一名六星和两名不同的四星")
        ops = self.operators()
        for name, rarity in [(self.six_star, 6), *((n, 4) for n in self.four_stars), *((n, 6) for n in self.fallback_six_stars)]:
            if name not in ops or ops[name]["rarity"] != rarity:
                raise ValueError(f"干员不存在或星级不符合要求：{name}（应为 {rarity} 星）")
        roles = [ops[n]["profession"] for n in [self.six_star, *self.four_stars]]
        if len(set(roles)) != 3:
            raise ValueError("三名开局干员职业必须不同")
        if any(ops[n]["profession"] != roles[0] for n in self.fallback_six_stars):
            raise ValueError("备选六星必须与首选六星同职业，才能使用同一张招募券")
        if self.prepare_squad not in ("特勤分队", "堡垒战术分队") or self.prepare_roles not in ("稳扎稳打", "坚不可摧"):
            raise ValueError("准备局需要可保证精二机械师的分队 / 开局组合")
        if self.phase_timeout < 60:
            raise ValueError("阶段超时至少 60 秒")
        if self.reward_target not in REWARD_TARGETS:
            raise ValueError("开局奖励选择无效")

    def allowed_six(self):
        ops = self.operators()
        names = [self.six_star, *self.fallback_six_stars]
        if self.allow_other_six_star:
            names.extend(n for n, v in ops.items() if v["rarity"] == 6 and v["profession"] == ops[self.six_star]["profession"])
        return list(dict.fromkeys(names))
