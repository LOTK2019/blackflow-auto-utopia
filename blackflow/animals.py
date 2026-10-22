"""黄色种植结果与蓝色奖励分别处理；目标按多重集合比较，允许额外收获。"""
from collections import Counter

ANIMAL_TYPES = {'襁褓中的猫':'swaddled_cat','襁褓中的狗':'swaddled_dog',
                '襁褓羽蛇':'swaddled_feathered_serpent','襁褓三头犬':'swaddled_cerberus'}
ANIMAL_EFFECTS = {'襁褓中的猫':'下局初始源石锭+5','襁褓中的狗':'下局初始希望+1',
                 '襁褓羽蛇':'通过至少两个区域后，下局增加蓝色奖励选项；不自动选择该奖励',
                 '襁褓三头犬':'通过至少两个区域后，下局增加奖励选择次数'}


def animals_satisfy(actual, required):
    def canonical(value):return ANIMAL_TYPES.get(value,value)
    found=Counter(canonical(v) for v in actual)
    wanted=Counter(canonical(v) for v in required)
    return all(found[name]>=count for name,count in wanted.items())


def animals_from_ocr(texts):
    """每张动物卡分别计数；不去重，避免两只同品种被折叠。"""
    found=[]
    for item in texts:
        if item.get('score',0) < .65:
            continue
        text=item['text'].replace(' ','')
        for suffix,kind in (('三头犬','swaddled_cerberus'),('羽蛇','swaddled_feathered_serpent'),
                            ('中的猫','swaddled_cat'),('中的狗','swaddled_dog')):
            if text.endswith(suffix):
                found.append(kind)
                break
    return tuple(sorted(found)) if found else None
