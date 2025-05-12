"""
AWS Bedrock集成模块

该模块提供了与AWS Bedrock服务通信的客户端实现，允许OpenManus使用AWS提供的大型语言模型。
该模块充当了一个适配器角色，将OpenAI兼容的API格式转换为AWS Bedrock需要的格式，
并将其响应转换回 OpenAI 格式，使应用程序可以无缝切换不同的模型提供商。

支持两种模式的调用：
1. 标准调用（一次性返回完整答案）
2. 流式调用（渐进式接收和处理响应）

还支持工具调用功能，可以让模型通过函数调用执行特定操作。
"""

import json
import sys
import time
import uuid
from datetime import datetime
from typing import Dict, List, Literal, Optional

import boto3


# 全局变量，用于跟踪多个函数调用之间的当前工具使用ID
# 临时解决方案，在各个方法之间传递工具使用ID
CURRENT_TOOLUSE_ID = None


# 处理OpenAI格式响应的类
class OpenAIResponse:
    """实现OpenAI格式的响应对象。
    
    这个类提供了一种方式来将普通的字典数据转换为拥有属性访问方式的对象，
    从而模拟 OpenAI API 的响应格式。这样可以保持与 OpenAI API 的兼容性，
    使得将 Bedrock 的响应无缝集成到项目中。
    """
    def __init__(self, data):
        """初始化响应对象并递归转换嵌套的字典和列表。
        
        将所有字典键转换为对象属性，嵌套字典也会递归转换为OpenAIResponse对象。
        
        参数:
            data: 需要转换的字典数据
        """
        # 递归将嵌套的字典和列表转换为OpenAIResponse对象
        for key, value in data.items():
            if isinstance(value, dict):
                value = OpenAIResponse(value)
            elif isinstance(value, list):
                value = [
                    OpenAIResponse(item) if isinstance(item, dict) else item
                    for item in value
                ]
            setattr(self, key, value)

    def model_dump(self, *args, **kwargs):
        """将对象转换为字典并添加时间戳。
        
        这个方法模拟Pydantic的model_dump方法，用于将对象转换回字典格式。
        
        返回:
            dict: 包含所有属性的字典，并添加created_at时间戳
        """
        # 将对象转换为字典并添加时间戳
        data = self.__dict__
        data["created_at"] = datetime.now().isoformat()
        return data


# 与Amazon Bedrock交互的主要客户端类
class BedrockClient:
    """与Amazon Bedrock服务交互的主要客户端类。
    
    这个类提供了与AWS Bedrock服务进行通信的入口点，初始化boto3客户端并设置聊天功能。
    它由OpenManus项目使用，作为访问AWS所提供的大型语言模型的通道。
    """ 
    def __init__(self):
        """初始化Bedrock客户端。
        
        在使用前需要配置AWS环境变量或凭证。如果初始化失败，将退出程序。
        """
        # 初始化Bedrock客户端，需要提前配置AWS环境
        try:
            self.client = boto3.client("bedrock-runtime")
            self.chat = Chat(self.client)
        except Exception as e:
            print(f"Error initializing Bedrock client: {e}")
            sys.exit(1)


# 聊天接口类
class Chat:
    """聊天功能的接口类。
    
    这个类模拟了OpenAI的客户端结构，提供了一个简单的接口来访问Completions功能。
    它充当了一个中间层，使得API结构与OpenAI保持一致。
    """
    def __init__(self, client):
        """初始化聊天接口。
        
        参数:
            client: boto3创建的bedrock-runtime客户端
        """
        self.completions = ChatCompletions(client)


# 处理聊天补全功能的核心类
class ChatCompletions:
    """处理聊天补全功能的核心类。
    
    这个类实现了与AWS Bedrock模型进行交互的所有功能，包括格式转换、请求处理和响应解析。
    它是该模块的核心部分，处理OpenAI格式与Bedrock格式之间的相互转换。
    """
    def __init__(self, client):
        """初始化聊天补全类。
        
        参数:
            client: boto3创建的bedrock-runtime客户端
        """
        self.client = client

    def _convert_openai_tools_to_bedrock_format(self, tools):
        """将OpenAI格式的工具调用转换为Bedrock格式。
        
        这个方法负责将OpenAI API使用的函数调用格式转换为AWS Bedrock语言模型理解的工具格式。
        两种格式有结构上的差异，需要将字段名称和嵌套结构进行调整。
        
        参数:
            tools: OpenAI格式的工具调用列表
            
        返回:
            list: Bedrock格式的工具列表
        """
        # 将OpenAI函数调用格式转换为Bedrock工具格式
        bedrock_tools = []
        for tool in tools:
            if tool.get("type") == "function":
                function = tool.get("function", {})
                bedrock_tool = {
                    "toolSpec": {
                        "name": function.get("name", ""),
                        "description": function.get("description", ""),
                        "inputSchema": {
                            "json": {
                                "type": "object",
                                "properties": function.get("parameters", {}).get(
                                    "properties", {}
                                ),
                                "required": function.get("parameters", {}).get(
                                    "required", []
                                ),
                            }
                        },
                    }
                }
                bedrock_tools.append(bedrock_tool)
        return bedrock_tools

    def _convert_openai_messages_to_bedrock_format(self, messages):
        """将OpenAI格式的消息转换为Bedrock格式。
        
        这个方法实现了两种消息格式的转换，主要处理以下几种角色的消息：
        1. system（系统消息） - 作为独立的系统提示返回
        2. user（用户消息） - 转换为Bedrock的用户消息
        3. assistant（助手消息） - 转换为Bedrock的助手消息，包括工具调用
        4. tool（工具消息） - 转换为Bedrock的工具结果格式
        
        参数:
            messages: OpenAI格式的消息列表
            
        返回:
            tuple: 包含系统提示和消息列表的元组(system_prompt, bedrock_messages)
            
        抛出:
            ValueError: 如果消息角色无效
        """
        # 将OpenAI消息格式转换为Bedrock消息格式
        bedrock_messages = []  # Bedrock格式的消息列表
        system_prompt = []     # 存储系统提示消息
        # 遍历每一条消息进行转换
        for message in messages:
            # 处理系统消息（在Bedrock中作为单独的参数传递）
            if message.get("role") == "system":
                system_prompt = [{"text": message.get("content")}]
            # 处理用户消息
            elif message.get("role") == "user":
                bedrock_message = {
                    "role": message.get("role", "user"),
                    "content": [{"text": message.get("content")}],
                }
                bedrock_messages.append(bedrock_message)
            # 处理助手消息，包括工具调用
            elif message.get("role") == "assistant":
                bedrock_message = {
                    "role": "assistant",
                    "content": [{"text": message.get("content")}],
                }
                # 处理消息中的工具调用
                openai_tool_calls = message.get("tool_calls", [])
                if openai_tool_calls:
                    # 创建Bedrock格式的工具使用对象
                    bedrock_tool_use = {
                        "toolUseId": openai_tool_calls[0]["id"],
                        "name": openai_tool_calls[0]["function"]["name"],
                        "input": json.loads(
                            openai_tool_calls[0]["function"]["arguments"]
                        ),
                    }
                    # 将工具使用对象添加到消息内容中
                    bedrock_message["content"].append({"toolUse": bedrock_tool_use})
                    # 将当前工具ID存储到全局变量中，用于工具结果处理
                    global CURRENT_TOOLUSE_ID
                    CURRENT_TOOLUSE_ID = openai_tool_calls[0]["id"]
                bedrock_messages.append(bedrock_message)
            # 处理工具消息（工具执行结果）
            elif message.get("role") == "tool":
                bedrock_message = {
                    "role": "user",  # Bedrock中工具结果作为用户角色发送
                    "content": [
                        {
                            "toolResult": {
                                "toolUseId": CURRENT_TOOLUSE_ID,  # 使用全局存储的工具ID
                                "content": [{"text": message.get("content")}],
                            }
                        }
                    ],
                }
                bedrock_messages.append(bedrock_message)
            # 处理无效角色
            else:
                raise ValueError(f"Invalid role: {message.get('role')}")
        return system_prompt, bedrock_messages

    def _convert_bedrock_response_to_openai_format(self, bedrock_response):
        """将Bedrock响应格式转换为OpenAI格式。
        
        这个方法实现了从 AWS Bedrock 返回的响应格式转换到 OpenAI 兼容的格式。
        主要处理以下几个方面：
        1. 消息内容提取和合并
        2. 工具调用的格式转换
        3. 生成标准的 OpenAI 响应结构
        
        参数:
            bedrock_response: Bedrock格式的响应字典
            
        返回:
            OpenAIResponse: 转换后的OpenAI格式响应对象
        """
        # 将Bedrock响应格式转换为OpenAI格式
        
        # 消息内容提取和合并
        content = ""
        if bedrock_response.get("output", {}).get("message", {}).get("content"):
            content_array = bedrock_response["output"]["message"]["content"]
            # 将所有文本内容合并为一个字符串
            content = "".join(item.get("text", "") for item in content_array)
        # 如果没有内容，提供一个默认的点号
        if content == "":
            content = "."

        # 处理响应中的工具调用
        openai_tool_calls = []
        if bedrock_response.get("output", {}).get("message", {}).get("content"):
            # 遍历所有内容项，查找工具使用
            for content_item in bedrock_response["output"]["message"]["content"]:
                if content_item.get("toolUse"):
                    bedrock_tool_use = content_item["toolUse"]
                    # 保存工具ID到全局变量，供后续处理工具结果使用
                    global CURRENT_TOOLUSE_ID
                    CURRENT_TOOLUSE_ID = bedrock_tool_use["toolUseId"]
                    # 按OpenAI格式构造工具调用对象
                    openai_tool_call = {
                        "id": CURRENT_TOOLUSE_ID,
                        "type": "function",
                        "function": {
                            "name": bedrock_tool_use["name"],
                            "arguments": json.dumps(bedrock_tool_use["input"]),
                        },
                    }
                    openai_tool_calls.append(openai_tool_call)

        # 构造最终的OpenAI格式响应
        openai_format = {
            # 生成唯一的响应ID
            "id": f"chatcmpl-{uuid.uuid4()}",
            # 当前时间戳
            "created": int(time.time()),
            # 对象类型
            "object": "chat.completion",
            "system_fingerprint": None,
            # 选择结果列表（OpenAI格式中的标准结构）
            "choices": [
                {
                    # 结束原因
                    "finish_reason": bedrock_response.get("stopReason", "end_turn"),
                    "index": 0,
                    # 消息内容
                    "message": {
                        "content": content,
                        "role": bedrock_response.get("output", {})
                        .get("message", {})
                        .get("role", "assistant"),
                        # 工具调用，如果有的话
                        "tool_calls": openai_tool_calls
                        if openai_tool_calls != []
                        else None,
                        "function_call": None,
                    },
                }
            ],
            # 使用统计信息
            "usage": {
                "completion_tokens": bedrock_response.get("usage", {}).get(
                    "outputTokens", 0
                ),
                "prompt_tokens": bedrock_response.get("usage", {}).get(
                    "inputTokens", 0
                ),
                "total_tokens": bedrock_response.get("usage", {}).get("totalTokens", 0),
            },
        }
        # 将字典转换为 OpenAIResponse 对象并返回
        return OpenAIResponse(openai_format)

    async def _invoke_bedrock(
        self,
        model: str,
        messages: List[Dict[str, str]],
        max_tokens: int,
        temperature: float,
        tools: Optional[List[dict]] = None,
        tool_choice: Literal["none", "auto", "required"] = "auto",
        **kwargs,
    ) -> OpenAIResponse:
        """非流式调用Bedrock模型。
        
        这个方法实现了非流式模式下的Bedrock模型调用，即一次性返回完整响应。
        流程包括：
        1. 将OpenAI格式的消息转换为Bedrock格式
        2. 调用Bedrock的converse API
        3. 将响应转换回 OpenAI 格式
        
        参数:
            model: 模型标识符，例如"anthropic.claude-v2"
            messages: OpenAI格式的消息列表
            max_tokens: 生成的最大token数量
            temperature: 温度参数，控制生成的随机性
            tools: 可选，工具列表
            tool_choice: 可选，工具选择模式
            **kwargs: 其他可选参数
            
        返回:
            OpenAIResponse: OpenAI格式的响应对象
        """
        # 非流式调用Bedrock模型
        (
            system_prompt,  # 系统提示
            bedrock_messages,  # Bedrock格式的消息列表
        ) = self._convert_openai_messages_to_bedrock_format(messages)
        # 使用Bedrock的converse API发送请求
        response = self.client.converse(
            modelId=model,  # 模型标识符
            system=system_prompt,  # 系统提示
            messages=bedrock_messages,  # 消息列表
            inferenceConfig={"temperature": temperature, "maxTokens": max_tokens},  # 推理配置
            toolConfig={"tools": tools} if tools else None,  # 工具配置，如果有工具则使用
        )
        # 将Bedrock响应转换为OpenAI格式
        openai_response = self._convert_bedrock_response_to_openai_format(response)
        return openai_response

    async def _invoke_bedrock_stream(
        self,
        model: str,
        messages: List[Dict[str, str]],
        max_tokens: int,
        temperature: float,
        tools: Optional[List[dict]] = None,
        tool_choice: Literal["none", "auto", "required"] = "auto",
        **kwargs,
    ) -> OpenAIResponse:
        """流式调用Bedrock模型。
        
        这个方法实现了流式模式下的Bedrock模型调用，可以渐进式地接收和处理响应。
        流程包括：
        1. 将OpenAI格式的消息转换为Bedrock格式
        2. 调用Bedrock的converse_stream API
        3. 处理流式响应事件
        4. 将收集的响应转换回 OpenAI 格式
        
        参数:
            model: 模型标识符，例如"anthropic.claude-v2"
            messages: OpenAI格式的消息列表
            max_tokens: 生成的最大token数量
            temperature: 温度参数，控制生成的随机性
            tools: 可选，工具列表
            tool_choice: 可选，工具选择模式
            **kwargs: 其他可选参数
            
        返回:
            OpenAIResponse: OpenAI格式的响应对象
        """
        # 流式调用Bedrock模型
        (
            system_prompt,  # 系统提示
            bedrock_messages,  # Bedrock格式的消息列表
        ) = self._convert_openai_messages_to_bedrock_format(messages)
        # 使用Bedrock的converse_stream API发送流式请求
        response = self.client.converse_stream(
            modelId=model,  # 模型标识符
            system=system_prompt,  # 系统提示
            messages=bedrock_messages,  # 消息列表
            inferenceConfig={"temperature": temperature, "maxTokens": max_tokens},  # 推理配置
            toolConfig={"tools": tools} if tools else None,  # 工具配置，如果有工具则使用
        )

        # 初始化响应结构，用于存储流式响应的结果
        bedrock_response = {
            "output": {"message": {"role": "", "content": []}},  # 回复内容
            "stopReason": "",  # 停止原因
            "usage": {},  # 使用统计
            "metrics": {},  # 指标
        }
        # 用于存储文本和工具输入的中间变量
        bedrock_response_text = ""  # 文本响应的累积
        bedrock_response_tool_input = ""  # 工具输入的累积

        # 处理流式响应
        stream = response.get("stream")
        if stream:
            # 遍历每个流式事件
            for event in stream:
                # 处理消息开始事件，获取角色信息
                if event.get("messageStart", {}).get("role"):
                    bedrock_response["output"]["message"]["role"] = event[
                        "messageStart"
                    ]["role"]
                # 处理文本内容增量
                if event.get("contentBlockDelta", {}).get("delta", {}).get("text"):
                    # 累积文本内容
                    bedrock_response_text += event["contentBlockDelta"]["delta"]["text"]
                    # 打印增量内容，模拟流式输出
                    print(
                        event["contentBlockDelta"]["delta"]["text"], end="", flush=True
                    )
                # 处理内容块结束事件，添加文本内容到最终响应
                if event.get("contentBlockStop", {}).get("contentBlockIndex") == 0:
                    bedrock_response["output"]["message"]["content"].append(
                        {"text": bedrock_response_text}  # 将累积的文本添加到响应中
                    )
                # 处理工具使用的开始事件
                if event.get("contentBlockStart", {}).get("start", {}).get("toolUse"):
                    bedrock_tool_use = event["contentBlockStart"]["start"]["toolUse"]
                    # 创建工具使用对象
                    tool_use = {
                        "toolUseId": bedrock_tool_use["toolUseId"],  # 工具使用ID
                        "name": bedrock_tool_use["name"],  # 工具名称
                    }
                    # 将工具使用添加到响应内容中
                    bedrock_response["output"]["message"]["content"].append(
                        {"toolUse": tool_use}
                    )
                    # 更新全局工具使用ID
                    global CURRENT_TOOLUSE_ID
                    CURRENT_TOOLUSE_ID = bedrock_tool_use["toolUseId"]
                # 处理工具使用的输入增量
                if event.get("contentBlockDelta", {}).get("delta", {}).get("toolUse"):
                    # 累积工具输入内容
                    bedrock_response_tool_input += event["contentBlockDelta"]["delta"][
                        "toolUse"
                    ]["input"]
                    # 打印工具输入增量
                    print(
                        event["contentBlockDelta"]["delta"]["toolUse"]["input"],
                        end="",
                        flush=True,
                    )
                # 处理工具使用的结束事件，将累积的输入解析为JSON并存储
                if event.get("contentBlockStop", {}).get("contentBlockIndex") == 1:
                    bedrock_response["output"]["message"]["content"][1]["toolUse"][
                        "input"
                    ] = json.loads(bedrock_response_tool_input)  # 将JSON字符串解析为对象
        print()  # 输出换行，表示流式输出结束
        # 将收集的Bedrock响应转换为OpenAI格式
        openai_response = self._convert_bedrock_response_to_openai_format(
            bedrock_response
        )
        return openai_response

    def create(
        self,
        model: str,
        messages: List[Dict[str, str]],
        max_tokens: int,
        temperature: float,
        stream: Optional[bool] = True,
        tools: Optional[List[dict]] = None,
        tool_choice: Literal["none", "auto", "required"] = "auto",
        **kwargs,
    ) -> OpenAIResponse:
        """调用Bedrock模型生成聊天补全的主入口点。
        
        这个方法是调用Bedrock模型的主要公开接口，类似于OpenAI的chat.completions.create。
        根据流式参数决定使用流式模式还是标准模式调用模型。
        
        参数:
            model: 模型标识符，例如"anthropic.claude-v2"
            messages: OpenAI格式的消息列表
            max_tokens: 生成的最大token数量
            temperature: 温度参数，控制生成的随机性
            stream: 是否使用流式模式，默认为True
            tools: 可选，工具列表，用于工具调用功能
            tool_choice: 工具选择模式，可以是"none"/"auto"/"required"
            **kwargs: 其他可选参数
            
        返回:
            OpenAIResponse: OpenAI格式的响应对象
        """
        # 调用Bedrock模型生成聊天补全的主入口点
        bedrock_tools = []
        # 如果提供了工具，将它们转换为Bedrock格式
        if tools is not None:
            bedrock_tools = self._convert_openai_tools_to_bedrock_format(tools)
        # 根据流式参数决定使用哪种调用模式
        if stream:
            # 流式模式：渐进式返回结果
            return self._invoke_bedrock_stream(
                model,
                messages,
                max_tokens,
                temperature,
                bedrock_tools,
                tool_choice,
                **kwargs,
            )
        else:
            # 标准模式：一次性返回完整响应
            return self._invoke_bedrock(
                model,
                messages,
                max_tokens,
                temperature,
                bedrock_tools,
                tool_choice,
                **kwargs,
            )
