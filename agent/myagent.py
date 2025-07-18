import asyncio

from mcp import Tool
from openai import OpenAI
from datetime import datetime
import json
import random

from doris_mcp_client.client import create_http_client, example_http, DorisUnifiedClient

client = OpenAI(
    api_key="sk-0d0a2175e5b140018257df1b091007ea",
    base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",  # 填写DashScope SDK的base_url
)





# 定义工具列表，模型在选择使用哪个工具时会参考工具的name和description
tools2 = [
    # 工具1 获取当前时刻的时间
    {
        "type": "function",
        "function": {
            "name": "get_current_time",
            "description": "当你想知道现在的时间时非常有用。",
            # 因为获取当前时间无需输入参数，因此parameters为空字典
            "parameters": {},
        },
    },
    # 工具2 获取指定城市的天气
    {
        "type": "function",
        "function": {
            "name": "get_current_weather",
            "description": "当你想查询指定城市的天气时非常有用。",
            "parameters": {
                "type": "object",
                "properties": {
                    # 查询天气时需要提供位置，因此参数设置为location
                    "location": {
                        "type": "string",
                        "description": "城市或县区，比如北京市、杭州市、余杭区等。",
                    }
                },
                "required": ["location"],
            },
        },
    },
]


# 模拟天气查询工具。返回结果示例：“北京今天是雨天。”
def get_current_weather(arguments):
    # 定义备选的天气条件列表
    weather_conditions = ["晴天", "多云", "雨天"]
    # 随机选择一个天气条件
    random_weather = random.choice(weather_conditions)
    # 从 JSON 中提取位置信息
    location = arguments["location"]
    # 返回格式化的天气信息
    return f"{location}今天是{random_weather}。"

def format_tool_json(tool: Tool) -> dict[str, any]:
    """将Tool对象转换为指定格式的JSON"""
    result = {
        "type": "function",
        "function": {
            "name": tool.name,
            "description": tool.description,
            "parameters": {
                "type": "object",
                "properties": {k: v for k, v in tool.inputSchema["properties"].items()},
                "required": tool.inputSchema["required"] if "required" in tool.inputSchema else []
            }
        }
    }
    return result

# 查询当前时间的工具。返回结果示例：“当前时间：2024-04-15 17:15:18。“
def get_current_time():
    # 获取当前日期和时间
    current_datetime = datetime.now()
    # 格式化当前日期和时间
    formatted_time = current_datetime.strftime("%Y-%m-%d %H:%M:%S")
    # 返回格式化后的当前时间
    return f"当前时间：{formatted_time}。"

async def run():
    doris_client = await create_http_client("http://localhost:3000/mcp")
    await doris_client.connect_and_run(call_with_messages)

# 封装模型响应函数
async def get_response(messages, doris_client):
    tools = await doris_client.list_all_tools()
    formatted_tools = [format_tool_json(tool) for tool in tools]
    completion = client.chat.completions.create(
        model="qwen-plus",
        messages=messages,
        tools=formatted_tools,
    )

    return completion

# 封装模型响应函数
async def llm(messages):
    completion = client.chat.completions.create(
        model="qwen-plus",
        messages=messages,
    )

    return completion

async def call_with_messages(doris_client: DorisUnifiedClient):
    print("\n")
    user_input = input(
                "请输入："
            )
    messages_0 = [
        {'role': 'system', 'content': "提取出用户所提到的表描述，表名或者表注释"},
        {
            "content": user_input,  # 提问示例："现在几点了？" "一个小时后几点" "北京天气如何？"
            "role": "user",
        }
    ]
    tables_desc = llm(messages_0)
    db_tables = await doris_client.execute_sql(
        "SELECT TABLE_SCHEMA AS 数据库名,TABLE_NAME AS 表名, COLUMN_NAME AS 字段名,COLUMN_COMMENT AS 字段注释 FROM information_schema.COLUMNS WHERE TABLE_SCHEMA NOT IN ('information_schema','__internal_schema');")

    tables_desc.append(db_tables)
    messages_1 = [
        {'role': 'system', 'content': "提取出用户所提到的表描述，表名或者表注释"},
        {
            "content": "找出和{tables_desc}最为相关的表名".format(tables_desc),
            "role": "user",
        }
    ]
    table_schema = await doris_client.get_table_schema()
    messages = [
        {'role': 'system', 'content': "现在你是一个{dialect}生成师，需要阅读一个客户的问题，参考的数据库schema，根据参考信息的提示，生成一句可执行的SQL。"
                                      "注意："
                                      "1、不要select多余的列。"
                                      "2、生成的SQL用```sql 和```包围起来。"
                                      "3、不要在SQL语句中加入注释！！！"
                                      "【数据库schema】"
                                      "{schema_info}".format(dialect="doris sql", schema_info=table_schema)},
        {
            "content": input(
                "请输入："
            ),  # 提问示例："现在几点了？" "一个小时后几点" "北京天气如何？"
            "role": "user",
        }
    ]

    print("-" * 60)
    # 模型的第一轮调用
    i = 1
    first_response = await get_response(messages, doris_client)
    assistant_output = first_response.choices[0].message
    print(f"\n第{i}轮大模型输出信息：{first_response}\n")
    if assistant_output.content is None:
        assistant_output.content = ""
    messages.append(assistant_output)
    # 如果不需要调用工具，则直接返回最终答案
    if (
        assistant_output.tool_calls == None
    ):  # 如果模型判断无需调用工具，则将assistant的回复直接打印出来，无需进行模型的第二轮调用
        print(f"无需调用工具，我可以直接回复：{assistant_output.content}")
        return
    # 如果需要调用工具，则进行模型的多轮调用，直到模型判断无需调用工具
    while assistant_output.tool_calls != None:
        # 如果判断需要调用查询天气工具，则运行查询天气工具
        tool_info = {
            "content": "",
            "role": "tool",
            "tool_call_id": assistant_output.tool_calls[0].id,
        }
        argumens = json.loads(assistant_output.tool_calls[0].function.arguments)
        result = await doris_client.call_tool(assistant_output.tool_calls[0].function.name, argumens)
        tool_info["content"] = json.dumps(result)
        tool_output = tool_info["content"]
        print(f"工具输出信息：{tool_output}\n")
        print("-" * 60)
        messages.append(tool_info)
        out = await get_response(messages,doris_client)
        assistant_output = out.choices[0].message
        if assistant_output.content is None:
            assistant_output.content = ""
        messages.append(assistant_output)
        i += 1
        print(f"第{i}轮大模型输出信息：{assistant_output}\n")
    print(f"最终答案：{assistant_output.content}")


if __name__ == "__main__":
    asyncio.run(run())