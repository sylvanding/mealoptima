import json
import math
import numpy as np
from collections import defaultdict
from .example_data import *
from .warning_handler import WarningCollector


warnings = WarningCollector()


def generate_meal_plan(
    dishes, meal_config, nutrition_std, sys_config, meal_nutrition_std
):
    # 预处理每餐营养标准
    meal_nutrition_std_dict = defaultdict(dict)
    for item in meal_nutrition_std:
        meal_nutrition_std_dict[item["餐时段"]][item["营养素名称"]] = item["标准值"]

    # 预处理数据结构
    nutrition_std_dict = {item["营养素名称"]: item["标准值"] for item in nutrition_std}
    meal_time_configs = defaultdict(list)
    for mc in meal_config:
        meal_time_configs[mc["餐时段"]].append((mc["菜品类别"], mc["数量"]))

    # 检查每个餐时段的菜品数量
    for meal_time, categories in meal_time_configs.items():
        total_dishes = sum(count for (_, count) in categories)
        if total_dishes <= 0:
            # 如果该餐时段没有菜品，则从每日营养标准中减去该餐时段的营养标准
            for nutrient, value in meal_nutrition_std_dict[meal_time].items():
                nutrition_std_dict[nutrient] -= value
                if nutrition_std_dict[nutrient] < 0:
                    raise ValueError(
                        f"营养标准异常：{nutrient} 计算值为 {nutrition_std_dict[nutrient]}（应为正数），请检查 {meal_time} 时段的营养标准设置！"
                    )

    # 构建菜品映射：{餐时段: {类别: [菜品]}}
    dish_map = defaultdict(lambda: defaultdict(list))
    for dish in dishes:
        for meal_time in dish["适用餐时段"]:  # 适用餐时段为空时，默认菜品无效
            dish_map[meal_time][dish["菜品类别"]].append(dish)

    # 计算每日总菜品数
    total_dishes_per_day = sum(
        count for meal in meal_time_configs.values() for (_, count) in meal
    )
    avg_price_per_dish = sys_config["每日餐标(元)"] / total_dishes_per_day

    # 记录菜品最后使用日期
    last_used = {}
    meal_plan = []

    # 记录整体营养和价格
    total_nutrition = defaultdict(float)
    total_price = 0.0

    for day in range(sys_config["配餐天数"]):
        daily_plan = {"day": day + 1, "meals": defaultdict(list)}
        selected_dishes = set()
        current_day_nutrition = defaultdict(float)  # 存储每日总营养
        current_meal_nutrition = defaultdict(lambda: defaultdict(float))  # 存储每餐营养
        current_day_price = 0.0

        # 按餐时段顺序处理（重要的餐时段优先处理）
        for meal_time in ["午餐", "晚餐", "早餐"]:
            if meal_time not in meal_time_configs:
                continue

            # 按特定顺序排序：荤、素、主，然后是其余类别
            category_order = {"荤": 0, "素": 1, "主": 2}
            meal_time_configs[meal_time].sort(key=lambda x: category_order.get(x[0], 3))

            # 处理当前餐时段的每个类别需求
            for category, required_count in meal_time_configs[meal_time]:
                if required_count <= 0:
                    continue

                candidates = dish_map[meal_time][category]

                # 筛选可用菜品：未被选中且满足重复天数限制，主食不受此限制
                available = []

                if category == "主":
                    available = candidates
                else:
                    for dish in candidates:
                        dish_id = dish["菜品ID"]
                        if dish_id in selected_dishes:
                            continue
                        last_day = last_used.get(
                            dish_id, -sys_config["菜品最小重复天数"] - 1
                        )
                        if (day - last_day) >= sys_config["菜品最小重复天数"]:
                            available.append(dish)

                if len(available) < required_count:
                    raise ValueError(
                        f"Day {day + 1}, {meal_time}, {category}：可用菜品不足，请减少配餐天数和菜品数量！"
                    )

                # 动态计算当前已选部分的营养和价格
                def compute_score(
                    dish,
                    meal_time,
                    current_day_nutrition,
                    meal_nutrition_std_dict,
                    total_nutrition,
                    total_price,
                ):
                    # 获取当前餐时段的营养标准
                    meal_nutrition_std = meal_nutrition_std_dict[meal_time]

                    # 计算当前餐时段的营养得分
                    e_meal = (
                        current_meal_nutrition[meal_time]["能量(Kcal)"]
                        + dish["能量(Kcal)"]
                    ) / meal_nutrition_std["能量(Kcal)"]
                    p_meal = (
                        current_meal_nutrition[meal_time]["蛋白质(g)"]
                        + dish["蛋白质(g)"]
                    ) / meal_nutrition_std["蛋白质(g)"]
                    f_meal = (
                        current_meal_nutrition[meal_time]["脂肪(g)"] + dish["脂肪(g)"]
                    ) / meal_nutrition_std["脂肪(g)"]
                    c_meal = (
                        current_meal_nutrition[meal_time]["碳水化合物(g)"]
                        + dish["碳水化合物(g)"]
                    ) / meal_nutrition_std["碳水化合物(g)"]
                    nutri_score_meal = (
                        1
                        - abs(e_meal - 1)
                        + 1
                        - abs(p_meal - 1)
                        + 1
                        - abs(f_meal - 1)
                        + 1
                        - abs(c_meal - 1)
                    ) / 4

                    # 计算每日营养得分
                    e_day = (
                        current_day_nutrition["能量(Kcal)"] + dish["能量(Kcal)"]
                    ) / nutrition_std_dict["能量(Kcal)"]
                    p_day = (
                        current_day_nutrition["蛋白质(g)"] + dish["蛋白质(g)"]
                    ) / nutrition_std_dict["蛋白质(g)"]
                    f_day = (
                        current_day_nutrition["脂肪(g)"] + dish["脂肪(g)"]
                    ) / nutrition_std_dict["脂肪(g)"]
                    c_day = (
                        current_day_nutrition["碳水化合物(g)"] + dish["碳水化合物(g)"]
                    ) / nutrition_std_dict["碳水化合物(g)"]
                    nutri_score_day = (
                        1
                        - abs(e_day - 1)
                        + 1
                        - abs(p_day - 1)
                        + 1
                        - abs(f_day - 1)
                        + 1
                        - abs(c_day - 1)
                    ) / 4

                    # 计算整体营养得分
                    e_total = (total_nutrition["能量(Kcal)"] + dish["能量(Kcal)"]) / (
                        nutrition_std_dict["能量(Kcal)"] * sys_config["配餐天数"]
                    )
                    p_total = (total_nutrition["蛋白质(g)"] + dish["蛋白质(g)"]) / (
                        nutrition_std_dict["蛋白质(g)"] * sys_config["配餐天数"]
                    )
                    f_total = (total_nutrition["脂肪(g)"] + dish["脂肪(g)"]) / (
                        nutrition_std_dict["脂肪(g)"] * sys_config["配餐天数"]
                    )
                    c_total = (
                        total_nutrition["碳水化合物(g)"] + dish["碳水化合物(g)"]
                    ) / (nutrition_std_dict["碳水化合物(g)"] * sys_config["配餐天数"])
                    nutri_score_total = (
                        1
                        - abs(e_total - 1)
                        + 1
                        - abs(p_total - 1)
                        + 1
                        - abs(f_total - 1)
                        + 1
                        - abs(c_total - 1)
                    ) / 4

                    # 计算每日菜品动态均价得分
                    remaining_dishes = total_dishes_per_day - len(selected_dishes)
                    remaining_budget = sys_config["每日餐标(元)"] - current_day_price
                    # 如果剩余预算不足，则强制设置为0.01元，这样低价菜品在后续配餐中更容易被选中
                    if remaining_budget <= 0:
                        remaining_budget = 0.01
                    dynamic_avg = remaining_budget / remaining_dishes
                    price_ratio_dynamic = dish["最终定价"] / dynamic_avg
                    price_score_dynamic = 1 - abs(price_ratio_dynamic - 1)

                    # 计算每日价格得分
                    new_price_day = current_day_price + dish["最终定价"]
                    price_ratio_day = new_price_day / sys_config["每日餐标(元)"]
                    price_score_day = 1 - abs(price_ratio_day - 1)

                    # 混合每日价格得分
                    price_score_day = (price_score_day + price_score_dynamic) / 2

                    # 计算整体价格得分
                    new_price_total = total_price + dish["最终定价"]
                    price_ratio_total = new_price_total / (
                        sys_config["每日餐标(元)"] * sys_config["配餐天数"]
                    )
                    price_score_total = 1 - abs(price_ratio_total - 1)

                    # 综合营养和价格得分，动态调整权重比例（随着天数推进，整体得分的权重逐渐增加）
                    if sys_config["配餐天数"] <= 0:
                        raise ValueError(
                            "配餐天数异常：配餐天数应为正数，请检查配餐天数设置！"
                        )
                    strategy = int(sys_config.get("整体权重调整策略", 0))
                    if strategy == 0:
                        total_weight = min(
                            day / sys_config["配餐天数"], sys_config["整体权重上限"]
                        )
                    elif strategy == 1:
                        total_weight = sys_config["整体权重上限"] * (
                            1 - math.exp(-day / sys_config["配餐天数"])
                        )
                    else:
                        raise ValueError(
                            f"未知的整体权重调整策略。当前策略序号：{strategy}，推荐策略序号：0（线性）或1（指数）"
                        )

                    nutri_score = (1 - total_weight) * (
                        nutri_score_day * 0.5 + nutri_score_meal * 0.5
                    ) + total_weight * nutri_score_total
                    price_score = (
                        1 - total_weight
                    ) * price_score_day + total_weight * price_score_total

                    # 如果菜品是主食，不使用多样性保障机制
                    if dish["菜品类别"] == "主":
                        return (
                            sys_config["营养权重"] * nutri_score
                            + (1 - sys_config["营养权重"]) * price_score
                        )

                    # 多样性保障机制
                    dish_id = dish["菜品ID"]
                    diversity_score = 0.0

                    # 1. 使用频率惩罚（过去3天内每使用一次减0.1分）
                    recent_use = sum(
                        1
                        for d in range(day - 3, day)
                        if last_used.get(dish_id, -1) == d
                    )
                    diversity_score -= 0.1 * recent_use

                    # 2. 使用间隔奖励（超过7天未使用/从未使用的菜品加0.2分）
                    if dish_id not in last_used or (day - last_used[dish_id]) > 7:
                        diversity_score += 0.2

                    return (1 - sys_config["多样性权重"]) * (
                        sys_config["营养权重"] * nutri_score
                        + (1 - sys_config["营养权重"]) * price_score
                    ) + sys_config["多样性权重"] * diversity_score

                # 对候选菜品进行评分排序
                scored = sorted(
                    [
                        (
                            compute_score(
                                dish,
                                meal_time,
                                current_day_nutrition,
                                meal_nutrition_std_dict,
                                total_nutrition,
                                total_price,
                            ),
                            dish,
                        )
                        for dish in available
                    ],
                    key=lambda x: -x[0],
                )

                # 引入带权重的随机选择（在top_k中按分数权重随机选）
                top_k = min(sys_config.get("top_k", 3), len(scored))  # 默认取前3名
                candidates = scored[:top_k]

                # 使用softmax计算选择概率（带温度系数控制随机性强度）
                scores = np.array([s[0] for s in candidates])
                temperature = sys_config.get("temperature", 0.3)  # 值越小越倾向高分
                exp_scores = np.exp((scores - np.max(scores)) / temperature)
                probs = exp_scores / exp_scores.sum()

                # 随机选择required_count个（无重复）
                selected_indices = np.random.choice(
                    len(candidates), size=required_count, replace=False, p=probs
                )
                selected = [candidates[i][1] for i in selected_indices]

                # 更新每日状态
                for dish in selected:
                    dish_id = dish["菜品ID"]
                    selected_dishes.add(dish_id)
                    last_used[dish_id] = day
                    current_day_price += dish["最终定价"]
                    current_day_nutrition["能量(Kcal)"] += dish["能量(Kcal)"]
                    current_day_nutrition["蛋白质(g)"] += dish["蛋白质(g)"]
                    current_day_nutrition["脂肪(g)"] += dish["脂肪(g)"]
                    current_day_nutrition["碳水化合物(g)"] += dish["碳水化合物(g)"]
                    daily_plan["meals"][meal_time].append(
                        {
                            "菜品ID": dish_id,
                            "菜品类别": dish["菜品类别"],
                            "最终定价": dish["最终定价"],
                        }
                    )

        # 更新整体营养和价格
        total_price += current_day_price
        for nutrient in current_day_nutrition:
            total_nutrition[nutrient] += current_day_nutrition[nutrient]

        # 营养偏差检查
        daily_nutrition_comparison = {}  # 初始化每日营养对比字典
        for nutrient in nutrition_std_dict:
            if nutrition_std_dict[nutrient] <= 0:
                daily_nutrition_comparison[nutrient] = (
                    f"{current_day_nutrition[nutrient]:.1f}/0.0 ⚠️"  # 处理标准值<=0的情况
                )
                continue
            ratio = current_day_nutrition[nutrient] / nutrition_std_dict[nutrient]
            deviation = sys_config["营养素偏差比例"].get(nutrient, 0)
            min_ratio = 1 - deviation
            max_ratio = 1 + deviation
            status_symbol = "✅"  # 默认状态符号
            if not (min_ratio <= ratio <= max_ratio):
                status_symbol = "❌"  # 超出范围则修改状态符号
                sign = (
                    "+"
                    if current_day_nutrition[nutrient] > nutrition_std_dict[nutrient]
                    else "-"
                )
                warnings.add(
                    f"警告 [{sign}]：Day {day + 1} {nutrient} 不在允许范围内 [±{sys_config['营养素偏差比例'][nutrient] * 100:.1f}%] （当前值/标准值：{current_day_nutrition[nutrient]:.1f}/{nutrition_std_dict[nutrient]:.1f}）"
                )
            # <--- 新增: 添加营养对比字符串到字典
            daily_nutrition_comparison[nutrient] = (
                f"{status_symbol} {current_day_nutrition[nutrient]:.1f}/{nutrition_std_dict[nutrient]:.1f} [±{sys_config['营养素偏差比例'][nutrient] * 100:.1f}%]"
            )

        # 价格浮动检查
        daily_price_comparison_str = ""  # <--- 新增: 初始化每日价格对比字符串
        if sys_config["每日餐标(元)"] <= 0:
            raise ValueError("每日餐标异常：每日餐标应为正数，请检查每日餐标设置！")
        price_ratio = current_day_price / sys_config["每日餐标(元)"]
        price_deviation = sys_config["餐标浮动比例"]
        price_status_symbol = "✅"
        if not (1 - price_deviation <= price_ratio <= 1 + price_deviation):
            price_status_symbol = "❌"
            sign = "+" if current_day_price > sys_config["每日餐标(元)"] else "-"
            warnings.add(
                f"警告 [{sign}]：Day {day + 1} 价格 不在允许范围内 [±{sys_config['餐标浮动比例'] * 100:.1f}%] （当前值/标准值：{current_day_price:.1f}/{sys_config['每日餐标(元)']:.1f}）"
            )

        # <--- 新增: 构建价格对比字符串
        daily_price_comparison_str = f"{price_status_symbol} {current_day_price:.1f}/{sys_config['每日餐标(元)']:.1f} [±{sys_config['餐标浮动比例'] * 100:.1f}%]"

        # <--- 新增: 将对比信息添加到 daily_plan
        daily_plan["价格(当前值/标准值)"] = daily_price_comparison_str
        daily_plan["营养(当前值/标准值)"] = daily_nutrition_comparison

        meal_plan.append(daily_plan)

    # --- 新增: 计算平均每日指标对比 ---
    avg_daily_price = total_price / sys_config["配餐天数"]
    avg_daily_nutrition = {
        k: v / sys_config["配餐天数"] for k, v in total_nutrition.items()
    }
    # 计算平均每日价格对比字符串
    avg_price_comparison_str = ""
    if sys_config["每日餐标(元)"] > 0:
        avg_price_ratio = avg_daily_price / sys_config["每日餐标(元)"]
        price_deviation = sys_config["餐标浮动比例"]
        avg_price_status_symbol = "✅"
        if not (1 - price_deviation <= avg_price_ratio <= 1 + price_deviation):
            avg_price_status_symbol = "❌"
        avg_price_comparison_str = f"{avg_price_status_symbol} {avg_daily_price:.1f}/{sys_config['每日餐标(元)']:.1f} [±{price_deviation * 100:.1f}%]"
    else:
        avg_price_comparison_str = (
            f"⚠️ {avg_daily_price:.1f}/0.0 [餐标配置错误]"  # 处理餐标<=0的情况
        )

    # 计算平均每日营养对比字典
    avg_nutrition_comparison = {}
    for nutrient, avg_value in avg_daily_nutrition.items():
        std_value = nutrition_std_dict.get(nutrient, 0)  # 使用 .get() 避免KeyError
        if std_value <= 0:
            avg_nutrition_comparison[nutrient] = (
                f"⚠️ {avg_value:.1f}/0.0 [营养标准值配置错误]"  # 处理标准值<=0的情况
            )
            continue
        avg_ratio = avg_value / std_value
        deviation = sys_config["营养素偏差比例"].get(nutrient, 0)
        min_ratio = 1 - deviation
        max_ratio = 1 + deviation
        avg_status_symbol = "✅"
        if not (min_ratio <= avg_ratio <= max_ratio):
            avg_status_symbol = "❌"
        avg_nutrition_comparison[nutrient] = (
            f"{avg_status_symbol} {avg_value:.1f}/{std_value:.1f} [±{deviation * 100:.1f}%]"
        )
    # --- 结束: 计算平均每日指标对比 ---

    return {
        "meal_plan": meal_plan,
        "nutrition_std_dict": nutrition_std_dict,
        "warnings": warnings.get_warnings(),
        "avg_daily_price": avg_price_comparison_str,
        "avg_daily_nutrition": avg_nutrition_comparison,
    }


if __name__ == "__main__":
    result = generate_meal_plan(
        dishes, meal_config, nutrition_std, sys_config, meal_nutrition_std
    )

    print(json.dumps(result, indent=2, ensure_ascii=False))
    warnings.print_all()
