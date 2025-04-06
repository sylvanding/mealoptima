# type: ignore

# from runtime import Args
# from typings.meal_planner_lark.meal_planner_lark import Input, Output

import json, collections
import lark_oapi as lark  # lark-oapi v1.4.12
from lark_oapi.api.bitable.v1 import *

from easydict import EasyDict as edict
import logging

from meal_planner_lib.meal_planner import generate_meal_plan
from meal_planner_lib.example_data_2 import *


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


def handler(args):
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


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    args = edict()
    args.input = edict()
    args.logger = logging.getLogger()
    args.input.app_token = "PgDqbJoYoaTjtNskSEkcv9WJn1d"
    args.input.dishes_table_id = "tblaJ81rpxNpToh5"
    args.input.meal_config_table_id = "tbl5nmeBDFE68SVB"
    args.input.nutrition_std_table_id = "tblS33TCJvoEKlR2"
    args.input.meal_nutrition_std_table_id = "tblSwvNEzVciVDwQ"
    args.input.sys_config_table_id = "tblPJqlBBmCSp2fG"
    args.input.plan_table_id = "tblmnGQVnYVKYa0Y"
    args.input.plan_daily_table_id = "tblHCDc76F9JFpJk"
    args.input.plan_meal_table_id = "tblfl0qz6J090E6E"
    args.input.user_access_token = "t-g00444knML4D7PB4LCYBZHH7JZSLSHCOIHKCCXJW"
    handler(args)
