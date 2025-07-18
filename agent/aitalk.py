__author__ = 'yinsuna'

import asyncio
import json
import logging

import streamlit as st
from mcp import client, Tool

from doris_mcp_client.client import create_http_client, DorisUnifiedClient

# define page / 定义页面
st.set_page_config(layout="wide")
st.title("🤖 AI大模型对话&对比器")

# save chat context by default / 默认可保存对话上下文
# clean chat context after click the reset button / "点击“清空所有对话”按钮后将清空上下文
reset_button = st.button("清空所有对话(Reset)")
if reset_button:
    st.session_state.messages = []

# initialize column for each model / 初始化大模型对话栏
st_all_columns = st.columns(len(models))
model_to_column_map = {}
for i, model_id in enumerate(models):
    logging.info(f"model_id = {model_id}, i = {i}")
    model_to_column_map[model_id] = st_all_columns[i]
for model_id, column in model_to_column_map.items():
    column_subheader=model_id+"("+models[model_id]+")"
    column.subheader(column_subheader)
    logging.info(f"column_subheader = {column_subheader}")

# initialize streamlit session messages / 初始化会话
if "messages" not in st.session_state:
    st.session_state.messages = []

# display chat history / 显示历史会话内容
for model_id, messages in st.session_state.messages.items():
    column = model_to_column_map[model_id]
    for message in messages:
        column.chat_message(message["role"]).write(message["content"])

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

async def run():
    doris_client = await create_http_client("http://localhost:3000/mcp")
    await doris_client.connect_and_run(call_with_messages)

# 封装模型响应函数
async def get_response(messages, doris_client):
    tools = await doris_client.list_all_tools()
    formatted_tools = [format_tool_json(tool) for tool in tools]
    completion = client.chat.completions.create(
        model="qwen3-ai",
        messages=messages,
        tools=formatted_tools,
    )

    return completion


async def call_with_messages(doris_client: DorisUnifiedClient):
    print("\n")
    print("-" * 60)
    prompt = st.chat_input()
    st.session_state.messages.append({"role": "user", "content": prompt})
    column.chat_message("user").write(prompt)
    # 模型的第一轮调用
    i = 1
    first_response = await get_response(st.session_state.messages, doris_client)
    assistant_output = first_response.choices[0].message
    print(f"\n第{i}轮大模型输出信息：{first_response}\n")
    if assistant_output.content is None:
        assistant_output.content = ""
    st.session_state.messages.append(assistant_output)
    # 如果不需要调用工具，则直接返回最终答案
    if (
            assistant_output.tool_calls == None
    ):  # 如果模型判断无需调用工具，则将assistant的回复直接打印出来，无需进行模型的第二轮调用
        print(f"无需调用工具，我可以直接回复：{assistant_output.content}")
        st.session_state.messages.append(assistant_output)
        column.chat_message("assistant").write(assistant_output)
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
        column.chat_message("assistant").write(tool_output)
        print("-" * 60)
        st.session_state.messages.append(tool_info)
        out = await get_response(st.session_state.messages, doris_client)
        assistant_output = out.choices[0].message
        if assistant_output.content is None:
            assistant_output.content = ""
        st.session_state.messages.append(assistant_output)
        i += 1
        print(f"第{i}轮大模型输出信息：{assistant_output}\n")
        column.chat_message("assistant").write(assistant_output)
    print(f"最终答案：{assistant_output.content}")
    column.chat_message("assistant").write(assistant_output.content)


# handle the prompt / 处理用户提示词
asyncio.run(run())