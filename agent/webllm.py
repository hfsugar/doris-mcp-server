import asyncio

from mcp import Tool
from openai import OpenAI
from datetime import datetime
import json

from doris_mcp_client.client import create_http_client, DorisUnifiedClient

client = OpenAI(
    api_key="sk-obi3BNoCn-0GBC8HXUOOog",
    base_url="http://10.56.48.89:8400/",  # 填写DashScope SDK的base_url
)


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
    # print(tools)
    # print(tools2)
    formatted_tools = [format_tool_json(tool) for tool in tools]
    # print(json.dumps(formatted_tools, indent=2))
    completion = client.chat.completions.create(
        model="qwen3-ai",
        messages=messages,
        tools=formatted_tools,
    )

    return completion


async def call_with_messages(doris_client: DorisUnifiedClient):
    print("\n")
    print("-" * 60)
    messages = []
    while True:
        user_input = input("请输入（0退出）: ")
        if user_input == "0":
            break
        messages.append(({"role": "user", "content": user_input}))
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
            messages.append(assistant_output)
        # 如果需要调用工具，则进行模型的多轮调用，直到模型判断无需调用工具
        while assistant_output.tool_calls != None:
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