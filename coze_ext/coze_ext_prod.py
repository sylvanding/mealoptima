from runtime import Args
from typings.meal_planner_lark.meal_planner_lark import Input, Output

# lark-oapi v1.4.12
import lark_oapi as lark
from lark_oapi.api.bitable.v1 import *

import math
import numpy as np
import json, collections
from collections import defaultdict


class WarningCollector:
    def __init__(self):
        self.warnings = []

    def get_warnings(self):
        return self.warnings

    def add(self, message):
        self.warnings.append(message)

    def print_all(self):
        if self.warnings:
            print("\n".join(self.warnings))


def generate_meal_plan(
    dishes, meal_config, nutrition_std, sys_config, meal_nutrition_std
):
    warnings = WarningCollector()

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


# 构造飞书多维表格插件的请求选项
def build_lark_request_option(user_access_token):
    if user_access_token.startswith("t-"):
        # 飞书多维表格插件只能使用 tenant_access_token 授权，以`t-`开头
        option = (
            lark.RequestOption.builder().tenant_access_token(user_access_token).build()
        )
    elif user_access_token.startswith("u-"):
        option = (
            lark.RequestOption.builder().user_access_token(user_access_token).build()
        )
    else:
        raise ValueError(f"Invalid user_access_token: {user_access_token}")
    return option


def extract_field_value(field_data):
    """
    从飞书表格字段数据中提取值

    Args:
        field_data: 飞书表格的字段数据

    Returns:
        提取的字段值
    """
    # 如果field_data不是字典，直接返回
    if not isinstance(field_data, dict):
        return field_data

    if "value" in field_data:
        # 如果值是列表且只有一个元素，则取第一个元素
        if isinstance(field_data["value"], list) and len(field_data["value"]) == 1:
            return field_data["value"][0]
        else:
            return field_data["value"]
    # 某些字段可能直接包含值
    elif "text" in field_data:
        # 如果text是列表且只有一个元素，则取第一个元素
        if isinstance(field_data["text"], list) and len(field_data["text"]) == 1:
            return field_data["text"][0]
        else:
            return field_data["text"]
    else:
        # 如果无法确定值的位置，则返回整个字段数据
        return field_data


# 将飞书系统配置记录转为标准配置格式
def convert_feishu_sys_config_to_standard_data(records):
    """
    将飞书系统配置记录转为标准配置格式

    Args:
        records: 飞书表格记录列表，格式如 [{'fields': {'配置名称': {...}, '值': {...}}, 'record_id': '...'}]

    Returns:
        转换后的配置字典
    """
    sys_config = {}

    for record in records:
        if "fields" not in record:
            continue

        fields = record["fields"]
        if "配置名称" not in fields or "值" not in fields:
            continue

        config_name = extract_field_value(fields["配置名称"][0])
        config_value = extract_field_value(fields["值"])

        # 尝试将值转换为适当的数据类型
        try:
            # 尝试转换为数字
            if (
                isinstance(config_value, str)
                and config_value.replace(".", "", 1).isdigit()
            ):
                if "." in config_value:
                    config_value = float(config_value)
                else:
                    config_value = int(config_value)
        except:  # noqa: E722
            # 如果转换失败，保持原始值
            pass

        if config_name.startswith("营养素偏差比例"):
            if "营养素偏差比例" not in sys_config:
                sys_config["营养素偏差比例"] = {}
            sys_config["营养素偏差比例"][config_name.split("-")[-1]] = config_value
        else:
            sys_config[config_name] = config_value

    return sys_config


# 将飞书表格记录转换为标准数据格式
def convert_feishu_records_to_standard_data(records):
    """
    将飞书表格记录转换为标准数据格式

    Args:
        records: 飞书表格记录列表，格式如 [{'fields': {...}, 'record_id': '...'}]

    Returns:
        转换后的数据列表
    """
    standard_data = []

    for record in records:
        if "fields" not in record:
            continue

        # 创建标准数据项
        item = {}

        # 遍历字段并提取值
        for field_name, field_data in record["fields"].items():
            item[field_name] = extract_field_value(field_data)

        # 添加记录ID
        if "record_id" in record:
            item["record_id"] = record["record_id"]

        standard_data.append(item)

    return standard_data


# 获取飞书表格数据
def get_feishu_table_data(
    client,
    app_token,
    table_id,
    user_access_token,
    filter=None,
    field_names=None,
    automatic_fields=False,
):
    # 构造请求体
    request_body_builder = SearchAppTableRecordRequestBody.builder()
    if filter:
        request_body_builder.filter(filter)
    if field_names:
        request_body_builder.field_names(field_names)
    if automatic_fields:
        request_body_builder.automatic_fields(automatic_fields)

    # 构造请求对象
    request_builder = SearchAppTableRecordRequest.builder()
    request_builder.app_token(app_token)
    request_builder.table_id(table_id)
    request_builder.page_size(80)  # 分页大小
    request_builder.request_body(request_body_builder.build())

    option = build_lark_request_option(user_access_token)

    all_records = []
    page_token = None

    # 分页获取数据
    while True:
        if page_token:
            request_builder.page_token(page_token)

        # 构建最终请求
        request: SearchAppTableRecordRequest = request_builder.build()

        # 发起请求
        response: SearchAppTableRecordResponse = (
            client.bitable.v1.app_table_record.search(request, option)
        )

        # 处理失败返回
        if not response.success():
            error_msg = f"client.bitable.v1.app_table_record.search failed, code: {response.code}, msg: {response.msg}, log_id: {response.get_log_id()}, resp: \n{json.dumps(json.loads(response.raw.content), indent=4, ensure_ascii=False)}"
            lark.logger.error(error_msg)
            raise Exception(error_msg)

        # 处理业务结果
        result_json = lark.JSON.marshal(response.data, indent=4)
        result_dict = json.loads(result_json, object_pairs_hook=collections.OrderedDict)
        all_records.extend(result_dict["items"])

        # 检查是否还有更多记录
        if not response.data.has_more:
            break

        # 更新 page_token
        page_token = response.data.page_token

    return all_records


# 创建client
def create_client():
    # 使用 user_access_token 需开启 token 配置, 并在 request_option 中配置 token
    client = (
        lark.Client.builder()
        .enable_set_token(True)
        .log_level(lark.LogLevel.DEBUG)
        .build()
    )
    return client


# 从飞书表格获取输入数据
def get_input_data(client, args_input, return_data=None):
    data_list = [
        "dishes",
        "meal_config",
        "nutrition_std",
        "meal_nutrition_std",
        "sys_config",
    ]
    if return_data is None:
        return_data = data_list
    elif isinstance(return_data, str):
        return_data = [return_data]
        # 检查return_data是否在data_list中
        for data in return_data:
            if data not in data_list:
                raise ValueError(f"Invalid return_data: {data}")

    result = {}

    # 获取菜品数据
    if "dishes" in return_data:
        dishes = get_feishu_table_data(
            client,
            args_input.app_token,
            args_input.dishes_table_id,
            args_input.user_access_token,
            filter={
                "conjunction": "and",
                "conditions": [
                    {
                        "field_name": "是否上架",
                        "operator": "is",
                        "value": ["在售"],
                    }
                ],
            },
            field_names=[
                "菜品ID",
                "最终定价",
                "菜品类别",
                "适用餐时段",
                "能量(Kcal)",
                "蛋白质(g)",
                "脂肪(g)",
                "碳水化合物(g)",
            ],
        )
        dishes = convert_feishu_records_to_standard_data(dishes)
        # 令 “菜品ID” = “record_id” 方便后续双向连接
        for dish in dishes:
            dish["菜品ID"] = dish["record_id"]
        result["dishes"] = dishes

    # 获取餐类配置
    if "meal_config" in return_data:
        meal_config = get_feishu_table_data(
            client,
            args_input.app_token,
            args_input.meal_config_table_id,
            args_input.user_access_token,
            field_names=[
                "餐时段",
                "菜品类别",
                "数量",
            ],
        )
        meal_config = convert_feishu_records_to_standard_data(meal_config)
        result["meal_config"] = meal_config

    # 获取每日营养标准
    if "nutrition_std" in return_data:
        nutrition_std = get_feishu_table_data(
            client,
            args_input.app_token,
            args_input.nutrition_std_table_id,
            args_input.user_access_token,
            field_names=[
                "营养素名称",
                "标准值",
            ],
        )
        nutrition_std = convert_feishu_records_to_standard_data(nutrition_std)
        result["nutrition_std"] = nutrition_std

    # 获取每餐营养标准
    if "meal_nutrition_std" in return_data:
        meal_nutrition_std = get_feishu_table_data(
            client,
            args_input.app_token,
            args_input.meal_nutrition_std_table_id,
            args_input.user_access_token,
            field_names=[
                "餐时段",
                "营养素名称",
                "标准值",
            ],
        )
        meal_nutrition_std = convert_feishu_records_to_standard_data(meal_nutrition_std)
        result["meal_nutrition_std"] = meal_nutrition_std

    # 获取系统配置
    if "sys_config" in return_data:
        sys_config = get_feishu_table_data(
            client,
            args_input.app_token,
            args_input.sys_config_table_id,
            args_input.user_access_token,
            filter={
                "conjunction": "and",
                "conditions": [
                    {
                        "field_name": "配置类型",
                        "operator": "is",
                        "value": ["可编辑"],
                    }
                ],
            },
            field_names=["配置名称", "值"],
        )
        sys_config = convert_feishu_sys_config_to_standard_data(sys_config)
        result["sys_config"] = sys_config

    return result


# 飞书表格新增多条记录
def add_feishu_records(client, app_token, table_id, user_access_token, records):
    """在多维表格数据表中新增多条记录，单次调用最多新增 1,000 条记录"""
    if isinstance(records, dict):
        records = [records]
    elif isinstance(records, list):
        pass
    else:
        raise TypeError(
            f"records参数类型错误: 期望dict或list，实际为{type(records).__name__}"
        )

    # 构造 AppTableRecord List
    app_table_record_list = [
        AppTableRecord.builder().fields(fields).build()
        for fields in records
        if isinstance(fields, dict)
    ]

    # 构造请求对象
    request: BatchCreateAppTableRecordRequest = (
        BatchCreateAppTableRecordRequest.builder()
        .app_token(app_token)
        .table_id(table_id)
        .request_body(
            BatchCreateAppTableRecordRequestBody.builder()
            .records(app_table_record_list)
            .build()
        )
        .build()
    )

    # 发起请求
    option = build_lark_request_option(user_access_token)
    response: BatchCreateAppTableRecordResponse = (
        client.bitable.v1.app_table_record.batch_create(request, option)
    )

    # 处理失败返回
    if not response.success():
        error_msg = f"client.bitable.v1.app_table_record.batch_create failed, code: {response.code}, msg: {response.msg}, log_id: {response.get_log_id()}, resp: \n{json.dumps(json.loads(response.raw.content), indent=4, ensure_ascii=False)}"
        lark.logger.error(error_msg)
        raise Exception(error_msg)

    # 处理业务结果
    result_json = lark.JSON.marshal(response.data, indent=4)
    result_dict = json.loads(result_json, object_pairs_hook=collections.OrderedDict)

    if len(result_dict["records"]) == 1:
        return result_dict["records"][0]["record_id"]  # 返回 record_id: string
    else:
        return [
            record["record_id"] for record in result_dict["records"]
        ]  # 返回 record_ids: string[]


# 将数据导入飞书表格
def import_data_to_feishu_table(
    client, args_input, plan_data, input_data, table_list=None
):
    std_table_list = ["plan", "plan_daily", "plan_meal"]
    if table_list is None:
        table_list = std_table_list
    elif isinstance(table_list, str):
        table_list = [table_list]
    elif isinstance(table_list, list):
        for table in table_list:
            if table not in std_table_list:
                raise ValueError(f"Invalid table: {table}")
    else:
        raise ValueError(f"Invalid table_list: {table_list}")

    new_plan_record_id = None
    new_plan_daily_record_ids = None
    if "plan" in table_list:
        warnings_str = "\n".join(plan_data["warnings"])
        avg_daily_price_str = plan_data["avg_daily_price"]
        avg_daily_nutrition_str = json.dumps(
            plan_data["avg_daily_nutrition"], ensure_ascii=False, indent=4
        )
        sys_config_str = json.dumps(
            input_data["sys_config"], ensure_ascii=False, indent=4
        )
        meal_config_str = "\n".join(
            [
                f"{item['餐时段']}-{item['菜品类别']}-{item['数量']}"
                for item in input_data["meal_config"]
            ]
        )
        nutrition_std_str = "\n".join(
            [
                f"{item['营养素名称']}-{item['标准值']}"
                for item in input_data["nutrition_std"]
            ]
        )
        meal_nutrition_std_str = "\n".join(
            [
                f"{item['餐时段']}-{item['营养素名称']}-{item['标准值']}"
                for item in input_data["meal_nutrition_std"]
            ]
        )
        new_plan_record_id = add_feishu_records(
            client,
            args_input.app_token,
            args_input.plan_table_id,
            args_input.user_access_token,
            {
                "警告信息": warnings_str,
                "平均每日价格(当前值/标准值)": avg_daily_price_str,
                "平均每日营养(当前值/标准值)": avg_daily_nutrition_str,
                "系统配置": sys_config_str,
                "餐类配置": meal_config_str,
                "每餐营养标准": meal_nutrition_std_str,
                "每日营养标准": nutrition_std_str,
            },
        )
    if "plan_daily" in table_list:
        plan_daily_records = []
        for meal_plan_day in plan_data["meal_plan"]:
            plan_daily_record = {
                "天数": meal_plan_day["day"],
                "价格(当前值/标准值)": meal_plan_day["价格(当前值/标准值)"],
                "营养(当前值/标准值)": json.dumps(
                    meal_plan_day["营养(当前值/标准值)"], ensure_ascii=False, indent=4
                ),
            }
            if new_plan_record_id:
                plan_daily_record["08-排餐方案-总体"] = [new_plan_record_id]
            plan_daily_records.append(plan_daily_record)
        new_plan_daily_record_ids = add_feishu_records(
            client,
            args_input.app_token,
            args_input.plan_daily_table_id,
            args_input.user_access_token,
            plan_daily_records,
        )
        if not isinstance(new_plan_daily_record_ids, list):
            new_plan_daily_record_ids = [new_plan_daily_record_ids]
    if "plan_meal" in table_list:
        plan_meal_records = []
        for day_index, meal_plan_day in enumerate(plan_data["meal_plan"]):
            for meal_plan_meal_moment, meal_plan_dishes in meal_plan_day[
                "meals"
            ].items():
                for meal_plan_dish in meal_plan_dishes:
                    plan_meal_record = {
                        "餐时段": meal_plan_meal_moment,
                        "菜品ID": [meal_plan_dish["菜品ID"]],
                        "菜品当前定价": meal_plan_dish["最终定价"],
                    }
                    if new_plan_daily_record_ids:
                        plan_meal_record["09-排餐方案-每天"] = [
                            new_plan_daily_record_ids[day_index]
                        ]
                    if new_plan_record_id:
                        plan_meal_record["08-排餐方案-总体"] = [new_plan_record_id]
                    plan_meal_records.append(plan_meal_record)
        add_feishu_records(
            client,
            args_input.app_token,
            args_input.plan_meal_table_id,
            args_input.user_access_token,
            plan_meal_records,
        )


"""
Each file needs to export a function named `handler`. This function is the entrance to the Tool.

Parameters:
args: parameters of the entry function.
args.input - input parameters, you can get test input value by args.input.xxx.
args.logger - logger instance used to print logs, injected by runtime.

Remember to fill in input/output in Metadata, it helps LLM to recognize and use tool.

Return:
The return data of the function, which should match the declared output parameters.
"""
def handler(args: Args[Input])->Output:
    client = create_client()

    # 获取输入数据
    try:
        input_data = get_input_data(
            client,
            args.input,
            return_data=[
                "dishes",  # 01-菜品管理
                "meal_config",  # 05-餐类配置
                "nutrition_std",  # 95-营养标准-每日
                "meal_nutrition_std",  # 06-营养标准-每餐
                "sys_config",  # 07-系统配置
            ],
        )
    except Exception as e:
        args.logger.error(f"获取输入数据时发生错误: {str(e)}")
        return {"message": f"获取输入数据失败: {str(e)}"}

    args.logger.info(input_data)

    # input_data = {
    #     "dishes": dishes,
    #     "meal_config": meal_config,
    #     "nutrition_std": nutrition_std,
    #     "meal_nutrition_std": meal_nutrition_std,
    #     "sys_config": sys_config,
    # }

    # 最大配餐天数为40天
    if input_data["sys_config"]["配餐天数"] > 40:
        args.logger.error("配餐天数不能超过40天")
        return {"message": "配餐天数不能超过40天"}

    try:
        result = generate_meal_plan(**input_data)
    except Exception as e:
        args.logger.error(f"生成配餐计划时发生错误: {str(e)}")
        return {"message": f"配餐计划生成失败: {str(e)}"}

    # 打印配餐计划
    result_json = json.dumps(result, ensure_ascii=False, indent=4)
    args.logger.info(f"生成的配餐计划: \n{result_json}")

    try:
        # 将配餐计划导入飞书表格
        import_data_to_feishu_table(
            client,
            args.input,
            result,
            input_data,
            table_list=[
                "plan",  # 08-排餐方案-总体
                "plan_daily",  # 09-排餐方案-每天
                "plan_meal",  # 10-排餐方案-每餐
            ],
        )
    except Exception as e:
        args.logger.error(f"导入配餐计划时发生错误: {str(e)}")
        return {"message": f"配餐计划导入失败: {str(e)}"}

    return {"message": "配餐计划生成成功"}
