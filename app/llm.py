"""语言模型接口模块

这个模块实现了 LLM 类，其提供了与各种大型语言模型（OpenAI API、Azure OpenAI、AWS Bedrock）
交互的统一接口。该类负责模型调用、令牌管理、重试机制和错误处理。

模块也实现了 TokenCounter 类，用于精确计算文本和图像令牌用量，包括对多模态模型的令牌计算支持。
"""

import math
from typing import Dict, List, Optional, Union

import tiktoken
from openai import (
    APIError,
    AsyncAzureOpenAI,
    AsyncOpenAI,
    AuthenticationError,
    OpenAIError,
    RateLimitError,
)
from openai.types.chat import ChatCompletion, ChatCompletionMessage
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_random_exponential,
)

from app.bedrock import BedrockClient
from app.config import LLMSettings, config
from app.exceptions import TokenLimitExceeded
from app.logger import logger  # Assuming a logger is set up in your app
from app.schema import (
    ROLE_VALUES,
    TOOL_CHOICE_TYPE,
    TOOL_CHOICE_VALUES,
    Message,
    ToolChoice,
)


# 具有强化推理能力的模型列表
REASONING_MODELS = ["o1", "o3-mini"]
# 支持图像输入的多模态模型列表
MULTIMODAL_MODELS = [
    "gpt-4-vision-preview",
    "gpt-4o",
    "gpt-4o-mini",
    "claude-3-opus-20240229",
    "claude-3-sonnet-20240229",
    "claude-3-haiku-20240307",
]


class TokenCounter:
    """令牌计算器类，用于精确计算文本和图像的令牌用量。
    
    这个类实现了复杂的令牌计算逻辑，包括：
    1. 文本令牌计算（使用 tiktoken 库）
    2. 图像令牌计算（分低细节和高细节模式）
    3. 离散消息的令牌计算，包括角色、工具调用等
    
    这个类的预算与 OpenAI 的官方文档中的模型令牌计算方法一致。
    它特别支持对多模态消息（包含图像）的令牌计算。
    """
    # 令牌计算常量
    BASE_MESSAGE_TOKENS = 4  # 每条消息的基础令牌数
    FORMAT_TOKENS = 2       # 格式化令牌数
    LOW_DETAIL_IMAGE_TOKENS = 85  # 低细节图像的固定令牌数
    HIGH_DETAIL_TILE_TOKENS = 170  # 高细节图像块的令牌数

    # Image processing constants
    MAX_SIZE = 2048
    HIGH_DETAIL_TARGET_SHORT_SIDE = 768
    TILE_SIZE = 512

    def __init__(self, tokenizer):
        self.tokenizer = tokenizer

    def count_text(self, text: str) -> int:
        """计算文本字符串的令牌数量。
        
        这个方法使用模型的分词器来计算给定文本中的令牌数量。
        如果文本为空，直接返回0。
        
        参数:
            text: 要计算令牌数量的文本字符串
            
        返回:
            int: 令牌数量
        """
        return 0 if not text else len(self.tokenizer.encode(text))

    def count_image(self, image_item: dict) -> int:
        """
        计算图像的令牌数量，基于图像的详细度级别和尺寸。
        
        该方法根据图像的详细度级别和尺寸来计算图像使用的令牌数量。
        它遵循OpenAI的多模态令牌计算规则，支持低、中、高三种详细度级别。
        
        对于“低”详细度: 固定85令牌
        对于“高”详细度:
        1. 缩放以适应2048x2048正方形
        2. 缩放最短边至768像素
        3. 计算512像素块的数量（每块170令牌）
        4. 添加85令牌的基础数量
        
        参数:
            image_item: 包含图像信息的字典，可能包含详细度和尺寸信息
            
        返回:
            int: 图像的令牌数量
        """
        detail = image_item.get("detail", "medium")

        # For low detail, always return fixed token count
        if detail == "low":
            return self.LOW_DETAIL_IMAGE_TOKENS

        # For medium detail (default in OpenAI), use high detail calculation
        # OpenAI doesn't specify a separate calculation for medium

        # For high detail, calculate based on dimensions if available
        if detail == "high" or detail == "medium":
            # If dimensions are provided in the image_item
            if "dimensions" in image_item:
                width, height = image_item["dimensions"]
                return self._calculate_high_detail_tokens(width, height)

        return (
            self._calculate_high_detail_tokens(1024, 1024) if detail == "high" else 1024
        )

    def _calculate_high_detail_tokens(self, width: int, height: int) -> int:
        """根据图像尺寸计算高详细度图像的令牌数量。
        
        这个内部方法实现高详细度图像的令牌计算算法。算法按照以下步骤进行：
        1. 将图像缩放到最大尺寸范围内（MAX_SIZE x MAX_SIZE）
        2. 将最短边缩放到指定的目标尺寸（HIGH_DETAIL_TARGET_SHORT_SIDE）
        3. 计算图像分割成TILE_SIZE大小的块数
        4. 根据块数和每块的令牌数量计算总令牌数
        
        参数:
            width: 图像宽度（像素）
            height: 图像高度（像素）
            
        返回:
            int: 计算得到的令牌数量
        """
        # Step 1: Scale to fit in MAX_SIZE x MAX_SIZE square
        if width > self.MAX_SIZE or height > self.MAX_SIZE:
            scale = self.MAX_SIZE / max(width, height)
            width = int(width * scale)
            height = int(height * scale)

        # Step 2: Scale so shortest side is HIGH_DETAIL_TARGET_SHORT_SIDE
        scale = self.HIGH_DETAIL_TARGET_SHORT_SIDE / min(width, height)
        scaled_width = int(width * scale)
        scaled_height = int(height * scale)

        # Step 3: Count number of 512px tiles
        tiles_x = math.ceil(scaled_width / self.TILE_SIZE)
        tiles_y = math.ceil(scaled_height / self.TILE_SIZE)
        total_tiles = tiles_x * tiles_y

        # Step 4: Calculate final token count
        return (
            total_tiles * self.HIGH_DETAIL_TILE_TOKENS
        ) + self.LOW_DETAIL_IMAGE_TOKENS

    def count_content(self, content: Union[str, List[Union[str, dict]]]) -> int:
        """计算消息内容的令牌数量。
        
        这个方法能够处理不同类型的消息内容，包括单一文本字符串和复杂的多模态内容列表。
        对于复杂的多模态内容（包含文本和图像），它会递归计算每个元素的令牌数量并累加。
        
        参数:
            content: 消息内容，可以是字符串或内容列表（混合文本和图像）
            
        返回:
            int: 内容的总令牌数量
        """
        if not content:
            return 0

        if isinstance(content, str):
            return self.count_text(content)

        token_count = 0
        for item in content:
            if isinstance(item, str):
                token_count += self.count_text(item)
            elif isinstance(item, dict):
                if "text" in item:
                    token_count += self.count_text(item["text"])
                elif "image_url" in item:
                    token_count += self.count_image(item)
        return token_count

    def count_tool_calls(self, tool_calls: List[dict]) -> int:
        """计算工具调用的令牌数量。
        
        该方法计算工具调用对象列表的令牌数量。工具调用对象通常包含函数名称
        和参数字符串，这两部分都需要单独计算令牌数量并累加。
        
        参数:
            tool_calls: 工具调用对象的列表，通常包含函数名称和参数
            
        返回:
            int: 所有工具调用的总令牌数量
        """
        token_count = 0
        for tool_call in tool_calls:
            if "function" in tool_call:
                function = tool_call["function"]
                token_count += self.count_text(function.get("name", ""))
                token_count += self.count_text(function.get("arguments", ""))
        return token_count

    def count_message_tokens(self, messages: List[dict]) -> int:
        """计算消息列表中的总令牌数量。
        
        这个方法实现了完整的消息令牌计算逻辑，包括基础格式令牌、每条消息的基础令牌、
        角色令牌、内容令牌、工具调用令牌以及其他元数据字段的令牌。该计算遵循
        OpenAI的官方文档中的模型令牌计算方法。
        
        参数:
            messages: 要计算令牌数量的消息列表，每条消息都是一个字典
            
        返回:
            int: 消息列表的总令牌数量
        """
        total_tokens = self.FORMAT_TOKENS  # Base format tokens

        for message in messages:
            tokens = self.BASE_MESSAGE_TOKENS  # Base tokens per message

            # Add role tokens
            tokens += self.count_text(message.get("role", ""))

            # Add content tokens
            if "content" in message:
                tokens += self.count_content(message["content"])

            # Add tool calls tokens
            if "tool_calls" in message:
                tokens += self.count_tool_calls(message["tool_calls"])

            # Add name and tool_call_id tokens
            tokens += self.count_text(message.get("name", ""))
            tokens += self.count_text(message.get("tool_call_id", ""))

            total_tokens += tokens

        return total_tokens


class LLM:
    """语言模型类，提供了与各种 LLM API 交互的统一接口。
    
    这个类实现了单例模式，根据配置名称维护不同的 LLM 实例。
    它负责模型调用、令牌管理、重试机制和错误处理。
    支持多种服务提供商（OpenAI、Azure OpenAI、AWS Bedrock）和模型类型。
    支持文本和多模态（图像）输入，以及工具调用功能。
    """
    # 类级字典，存储不同配置的 LLM 实例
    _instances: Dict[str, "LLM"] = {}

    def __new__(
        cls, config_name: str = "default", llm_config: Optional[LLMSettings] = None
    ):
        """实现单例模式，根据配置名称返回现有实例或创建新实例。
        
        参数:
            config_name: 配置名称，用于区分不同的 LLM 实例
            llm_config: 可选的 LLM 配置，如果未提供将使用默认配置
            
        返回:
            LLM: 已配置的 LLM 实例
        """
        # 如果配置名称不存在在实例字典中，创建新实例
        if config_name not in cls._instances:
            instance = super().__new__(cls)
            instance.__init__(config_name, llm_config)
            cls._instances[config_name] = instance
        # 返回现有实例
        return cls._instances[config_name]

    def __init__(
        self, config_name: str = "default", llm_config: Optional[LLMSettings] = None
    ):
        """初始化 LLM 实例，设置模型参数和 API 客户端。
        
        参数:
            config_name: 配置名称，用于从配置中获取特定的 LLM 设置
            llm_config: 可选的 LLM 配置对象，如果未提供将使用默认配置
        """
        # 只在首次初始化时设置属性，防止重复初始化
        if not hasattr(self, "client"):  # Only initialize if not already initialized
            # 从配置中获取 LLM 设置
            llm_config = llm_config or config.llm
            llm_config = llm_config.get(config_name, llm_config["default"])
            # 设置模型参数
            self.model = llm_config.model
            self.max_tokens = llm_config.max_tokens
            self.temperature = llm_config.temperature
            self.api_type = llm_config.api_type
            self.api_key = llm_config.api_key
            self.api_version = llm_config.api_version
            self.base_url = llm_config.base_url

            # Add token counting related attributes
            self.total_input_tokens = 0
            self.total_completion_tokens = 0
            self.max_input_tokens = (
                llm_config.max_input_tokens
                if hasattr(llm_config, "max_input_tokens")
                else None
            )

            # Initialize tokenizer
            try:
                self.tokenizer = tiktoken.encoding_for_model(self.model)
            except KeyError:
                # If the model is not in tiktoken's presets, use cl100k_base as default
                self.tokenizer = tiktoken.get_encoding("cl100k_base")

            if self.api_type == "azure":
                self.client = AsyncAzureOpenAI(
                    base_url=self.base_url,
                    api_key=self.api_key,
                    api_version=self.api_version,
                )
            elif self.api_type == "aws":
                self.client = BedrockClient()
            else:
                self.client = AsyncOpenAI(api_key=self.api_key, base_url=self.base_url)

            self.token_counter = TokenCounter(self.tokenizer)

    def count_tokens(self, text: str) -> int:
        """计算文本中的令牌数量。
        
        这个方法使用当前模型的分词器来计算给定文本中的令牌数量。
        
        参数:
            text: 要计算的文本字符串
            
        返回:
            int: 令牌数量
        """
        if not text:
            return 0
        return len(self.tokenizer.encode(text))

    def count_message_tokens(self, messages: List[dict]) -> int:
        """计算消息列表中的令牌数量。
        
        使用 TokenCounter 实例计算消息列表中的总令牌数，
        包括角色、内容、图像和工具调用等内容。
        
        参数:
            messages: 要计算的消息列表
            
        返回:
            int: 总令牌数量
        """
        return self.token_counter.count_message_tokens(messages)

    def update_token_count(self, input_tokens: int, completion_tokens: int = 0) -> None:
        """更新令牌使用计数。
        
        记录并累加输入和输出的令牌数量，并记录到日志。
        这个方法用于跟踪模型使用情况和限制检查。
        
        参数:
            input_tokens: 输入令牌数量
            completion_tokens: 输出令牌数量（可选）
        """
        # 跟踪令牌使用情况
        self.total_input_tokens += input_tokens
        self.total_completion_tokens += completion_tokens
        # 记录详细的令牌使用情况
        logger.info(
            f"Token usage: Input={input_tokens}, Completion={completion_tokens}, "
            f"Cumulative Input={self.total_input_tokens}, Cumulative Completion={self.total_completion_tokens}, "
            f"Total={input_tokens + completion_tokens}, Cumulative Total={self.total_input_tokens + self.total_completion_tokens}"
        )

    def check_token_limit(self, input_tokens: int) -> bool:
        """检查是否超过令牌限制。
        
        根据配置的最大输入令牌限制，检查是否超过限制。
        如果没有设置限制，总是返回 True。
        
        参数:
            input_tokens: 要检查的输入令牌数量
            
        返回:
            bool: 如果未超过限制返回 True，否则返回 False
        """
        # 如果设置了最大令牌限制，检查是否超过
        if self.max_input_tokens is not None:
            return (self.total_input_tokens + input_tokens) <= self.max_input_tokens
        # 如果没有设置限制，总是返回 True
        return True

    def get_limit_error_message(self, input_tokens: int) -> str:
        """生成令牌超限的错误消息。
        
        当超过设置的令牌限制时，生成详细的错误消息，
        包含当前使用情况和限制信息。
        
        参数:
            input_tokens: 输入令牌数量
            
        返回:
            str: 错误消息字符串
        """
        # 如果超过限制，返回详细的错误消息
        if (
            self.max_input_tokens is not None
            and (self.total_input_tokens + input_tokens) > self.max_input_tokens
        ):
            return f"Request may exceed input token limit (Current: {self.total_input_tokens}, Needed: {input_tokens}, Max: {self.max_input_tokens})"

        # 默认错误消息
        return "Token limit exceeded"

    @staticmethod
    def format_messages(
        messages: List[Union[dict, Message]], supports_images: bool = False
    ) -> List[dict]:
        """
        将消息转换为 OpenAI API 格式。

        这个静态方法负责将各种格式的消息（dict 或 Message 对象）转换为
        OpenAI API 支持的消息格式。它还处理图像附件，将 base64 编码的图像
        转换为多模态模型支持的格式。

        参数:
            messages: 消息列表，可以是字典或 Message 对象
            supports_images: 标志，指示目标模型是否支持图像输入

        返回:
            List[dict]: 格式化后的 OpenAI 格式消息列表

        异常:
            ValueError: 如果消息无效或缺失必要字段
            TypeError: 如果提供了不支持的消息类型

        示例:
            >>> msgs = [
            ...     Message.system_message("You are a helpful assistant"),
            ...     {"role": "user", "content": "Hello"},
            ...     Message.user_message("How are you?")
            ... ]
            >>> formatted = LLM.format_messages(msgs)
        """
        # 初始化格式化后的消息列表
        formatted_messages = []

        # 遍历所有输入消息
        for message in messages:
            # 将Message对象转换为字典格式，以统一处理
            if isinstance(message, Message):
                message = message.to_dict()

            # 检查消息是否是字典格式
            if isinstance(message, dict):
                # 确保消息字典包含必需的role字段
                if "role" not in message:
                    raise ValueError("Message dict must contain 'role' field")

                # 处理base64编码的图像，前提是模型支持图像且消息中包含图像
                if supports_images and message.get("base64_image"):
                    # 初始化或转换content字段为适当的多模态格式
                    # 如果没有content，创建空列表
                    if not message.get("content"):
                        message["content"] = []
                    # 如果内容是字符串，将其转为文本对象的列表
                    elif isinstance(message["content"], str):
                        message["content"] = [
                            {"type": "text", "text": message["content"]}
                        ]
                    # 如果内容是列表，确保每个元素都是适当的格式
                    elif isinstance(message["content"], list):
                        # 将列表中的字符串项转换为正确的文本对象
                        message["content"] = [
                            (
                                {"type": "text", "text": item}  # 如果是字符串，转为文本对象
                                if isinstance(item, str)
                                else item  # 如果已经是对象，保持不变
                            )
                            for item in message["content"]
                        ]

                    # 将图像添加到内容中，使用data URI格式传送base64编码的图像
                    message["content"].append(
                        {
                            "type": "image_url",  # 指定类型为图像
                            "image_url": {
                                "url": f"data:image/jpeg;base64,{message['base64_image']}"  # 构造data URI
                            },
                        }
                    )

                    # 删除原始base64_image字段，因为它已经被转换并添加到内容中
                    del message["base64_image"]
                # 如果模型不支持图像但消息中有图像，优雅地处理
                elif not supports_images and message.get("base64_image"):
                    # 只删除base64_image字段，保留文本内容
                    del message["base64_image"]

                # 只添加包含content或tool_calls字段的消息
                if "content" in message or "tool_calls" in message:
                    formatted_messages.append(message)
                # 如果消息既没有内容也没有工具调用，不添加到格式化消息列表
            else:
                # 如果消息不是Message对象也不是字典，抛出异常
                raise TypeError(f"Unsupported message type: {type(message)}")

        # 验证所有消息都有有效的role字段
        for msg in formatted_messages:
            # 检查role是否在允许的角色列表中（系统、用户、助手、工具）
            if msg["role"] not in ROLE_VALUES:
                raise ValueError(f"Invalid role: {msg['role']}")

        # 返回格式化后的消息列表，可直接用于API调用
        return formatted_messages

    @retry(
        wait=wait_random_exponential(min=1, max=60),  # 指数退避策略，等待时间从 1s 到 60s
        stop=stop_after_attempt(6),                 # 最多重试 6 次
        retry=retry_if_exception_type(
            (OpenAIError, Exception, ValueError)      # 哪些异常需要重试，不包括 TokenLimitExceeded
        ),
    )
    async def ask(
        self,
        messages: List[Union[dict, Message]],
        system_msgs: Optional[List[Union[dict, Message]]] = None,
        stream: bool = True,
        temperature: Optional[float] = None,
    ) -> str:
        """
        向语言模型发送请求并获取响应。
        
        这是与语言模型交互的核心方法，负责处理消息格式化、令牌计算、API 调用
        和错误处理。该方法通过 @retry 装饰器实现了强大的重试机制，可以处理
        网络问题、限流和服务器错误。

        参数:
            messages: 对话消息列表，包含用户和助手消息
            system_msgs: 可选的系统消息列表，会添加到请求的开头
            stream: 是否流式获取响应，可加快响应速度
            temperature: 采样温度，控制输出的创造性/随机性

        返回:
            str: 生成的响应文本

        异常:
            TokenLimitExceeded: 如果超过令牌限制
            ValueError: 如果消息无效或响应为空
            OpenAIError: 如果 API 调用在重试后仍然失败
            Exception: 其他意外错误
        """
        try:
            # 检查模型是否支持图像输入，这影响消息格式化方式
            supports_images = self.model in MULTIMODAL_MODELS

            # 格式化系统和用户消息，并考虑图像支持
            if system_msgs:
                # 如果提供了系统消息，先格式化系统消息
                system_msgs = self.format_messages(system_msgs, supports_images)
                # 将系统消息添加到格式化后的用户消息之前
                messages = system_msgs + self.format_messages(messages, supports_images)
            else:
                # 如果没有系统消息，只格式化用户消息
                messages = self.format_messages(messages, supports_images)

            # 计算输入令牌数量，用于限制检查和记录
            input_tokens = self.count_message_tokens(messages)

            # 检查是否超过设置的令牌限制
            if not self.check_token_limit(input_tokens):
                # 生成包含详细信息的限制错误消息
                error_message = self.get_limit_error_message(input_tokens)
                # 抛出特殊异常，该异常不会被重试机制重试
                raise TokenLimitExceeded(error_message)

            # 准备API请求参数
            params = {
                "model": self.model,  # 要使用的模型名称
                "messages": messages,  # 格式化后的消息列表
            }

            # 根据模型类型添加特定参数
            if self.model in REASONING_MODELS:  # 对于具有强化推理功能的模型
                params["max_completion_tokens"] = self.max_tokens  # 使用max_completion_tokens参数
            else:  # 对于标准模型
                params["max_tokens"] = self.max_tokens  # 使用max_tokens参数
                params["temperature"] = (
                    temperature if temperature is not None else self.temperature  # 使用提供的温度或默认温度
                )

            if not stream:
                # 非流式请求处理
                response = await self.client.chat.completions.create(
                    **params, stream=False  # 明确指定非流式模式
                )

                # 检查响应是否有效
                if not response.choices or not response.choices[0].message.content:
                    raise ValueError("Empty or invalid response from LLM")

                # 更新令牌计数，记录入口和输出令牌使用情况
                self.update_token_count(
                    response.usage.prompt_tokens, response.usage.completion_tokens
                )

                # 返回模型生成的内容
                return response.choices[0].message.content

            # 流式请求处理，在请求前预先更新估计的令牌计数
            # 流式响应不会提供准确的令牌统计，所以预先记录输入令牌
            self.update_token_count(input_tokens)

            # 发送流式请求
            response = await self.client.chat.completions.create(**params, stream=True)

            # 初始化集合变量
            collected_messages = []  # 收集的消息块列表
            completion_text = ""  # 完整的生成文本
            # 异步遍历响应流
            async for chunk in response:
                # 提取当前块的内容，如果为空则用空字符串替代
                chunk_message = chunk.choices[0].delta.content or ""
                collected_messages.append(chunk_message)  # 添加到收集列表
                completion_text += chunk_message  # 添加到完整文本
                # 实时打印到控制台，无换行，立即刷新
                print(chunk_message, end="", flush=True)

            print()  # 流式结束后打印换行
            # 组合所有收集的消息块并去除前后空白
            full_response = "".join(collected_messages).strip()
            # 检查响应是否为空
            if not full_response:
                raise ValueError("Empty response from streaming LLM")

            # 估算流式响应的令牌数量
            completion_tokens = self.count_tokens(completion_text)
            logger.info(
                f"Estimated completion tokens for streaming response: {completion_tokens}"
            )
            # 累加输出令牌数量
            self.total_completion_tokens += completion_tokens

            # 返回完整响应
            return full_response

        except TokenLimitExceeded:
            # 令牌限制异常直接重新抛出，不进行额外的日志记录
            # 这是因为该异常是有意设计的逻辑控制，而非意外错误
            raise
        except ValueError:
            # 数据验证错误，如消息格式错误或响应为空
            logger.exception(f"Validation error")
            raise
        except OpenAIError as oe:
            # 处理OpenAI API特定的错误
            logger.exception(f"OpenAI API error")
            # 根据具体错误类型提供更详细的日志
            if isinstance(oe, AuthenticationError):
                # 身份验证错误，可能是 API 密钥无效
                logger.error("Authentication failed. Check API key.")
            elif isinstance(oe, RateLimitError):
                # 超出速率限制，建议增加重试次数或调整重试策略
                logger.error("Rate limit exceeded. Consider increasing retry attempts.")
            elif isinstance(oe, APIError):
                # 其他 API 错误
                logger.error(f"API error: {oe}")
            # 将错误继续向上抛出，由调用者处理
            raise
        except Exception:
            # 处理所有其他未预期错误，如网络问题、系统错误等
            logger.exception(f"Unexpected error in ask")
            raise

    @retry(
        wait=wait_random_exponential(min=1, max=60),  # 指数退避策略，等待时间从 1s 到 60s
        stop=stop_after_attempt(6),                 # 最多重试 6 次
        retry=retry_if_exception_type(
            (OpenAIError, Exception, ValueError)      # 哪些异常需要重试，不包括 TokenLimitExceeded
        ),
    )
    async def ask_with_images(
        self,
        messages: List[Union[dict, Message]],
        images: List[Union[str, dict]],
        system_msgs: Optional[List[Union[dict, Message]]] = None,
        stream: bool = False,
        temperature: Optional[float] = None,
    ) -> str:
        """
        向语言模型发送包含图像的提示并获取响应。
        
        这个方法专门用于处理多模态请求，允许将图像与文本提示一起发送给支持
        图像输入的语言模型（如 GPT-4V、Claude-3 等）。它会自动将消息和图像转换为
        API 所需的多模态格式，并处理图像的不同输入格式（URL、数据字典等）。
        
        这个方法会首先检查模型是否支持图像输入，然后将图像添加到最后一条用户
        消息中，并处理令牌计数和流式输出等特性。
        
        参数:
            messages: 对话消息列表
            images: 图像 URL 或图像数据字典的列表
            system_msgs: 可选的系统消息，将添加到消息列表的开头
            stream: 是否使用流式响应
            temperature: 采样温度，控制输出的创造性/随机性
        
        返回:
            str: 生成的响应文本
        
        抛出:
            TokenLimitExceeded: 如果超过令牌限制
            ValueError: 如果消息无效或响应为空
            OpenAIError: 如果 API 调用在重试后仍然失败
            Exception: 其他意外错误
        """
        try:
            # For ask_with_images, we always set supports_images to True because
            # this method should only be called with models that support images
            if self.model not in MULTIMODAL_MODELS:
                raise ValueError(
                    f"Model {self.model} does not support images. Use a model from {MULTIMODAL_MODELS}"
                )

            # 使用图像支持标志格式化消息，从而允许包含图像附件
            formatted_messages = self.format_messages(messages, supports_images=True)

            # 确保最后一条消息来自用户，只有用户消息才能附加图像
            if not formatted_messages or formatted_messages[-1]["role"] != "user":
                raise ValueError(
                    "The last message must be from the user to attach images"
                )

            # 处理最后一条用户消息，以包含图像
            last_message = formatted_messages[-1]

            # 将内容转换为多模态格式（如果需要）
            # 如果原来的内容是字符串，将其转换为包含文本对象的列表
            # 如果已经是列表，则保持不变，否则创建空列表
            content = last_message["content"]
            multimodal_content = (
                [{"type": "text", "text": content}]  # 将纯文本转为文本对象
                if isinstance(content, str)
                else content  # 如果已经是列表格式，直接使用
                if isinstance(content, list)
                else []  # 其他情况创建空列表
            )

            # 将图像添加到内容中
            for image in images:
                # 处理不同格式的图像输入
                if isinstance(image, str):  # 如果是字符串URL
                    multimodal_content.append(
                        {"type": "image_url", "image_url": {"url": image}}
                    )
                elif isinstance(image, dict) and "url" in image:  # 如果是包含url键的字典
                    multimodal_content.append({"type": "image_url", "image_url": image})
                elif isinstance(image, dict) and "image_url" in image:  # 如果是已经格式化的图像对象
                    multimodal_content.append(image)
                else:  # 不支持的图像格式
                    raise ValueError(f"Unsupported image format: {image}")

            # 使用多模态内容更新消息
            last_message["content"] = multimodal_content

            # 如果提供了系统消息，将其添加到消息列表的开头
            if system_msgs:
                all_messages = (
                    self.format_messages(system_msgs, supports_images=True)  # 格式化系统消息
                    + formatted_messages  # 连接到已格式化的用户/助手消息
                )
            else:
                all_messages = formatted_messages

            # 计算令牌数量并检查限制
            input_tokens = self.count_message_tokens(all_messages)
            if not self.check_token_limit(input_tokens):
                # 如果超过令牌限制，抛出TokenLimitExceeded异常
                raise TokenLimitExceeded(self.get_limit_error_message(input_tokens))

            # 设置API参数
            params = {
                "model": self.model,
                "messages": all_messages,
                "stream": stream,
            }

            # 根据模型类型添加特定参数
            if self.model in REASONING_MODELS:  # 对于强化推理模型（如o1, o3-mini）
                params["max_completion_tokens"] = self.max_tokens  # 使用max_completion_tokens参数
            else:  # 对于其他模型
                params["max_tokens"] = self.max_tokens  # 使用标准max_tokens参数
                params["temperature"] = (
                    temperature if temperature is not None else self.temperature  # 使用提供的温度或默认温度
                )

            # 处理非流式请求
            if not stream:
                # 发送同步请求并等待完整响应
                response = await self.client.chat.completions.create(**params)

                # 检查响应是否有效
                if not response.choices or not response.choices[0].message.content:
                    raise ValueError("Empty or invalid response from LLM")

                # 更新令牌计数，使用API返回的确切令牌数
                self.update_token_count(response.usage.prompt_tokens)
                return response.choices[0].message.content

            # 处理流式请求
            # 在请求前更新计算的令牌数，因为流式响应不会返回统计数据
            self.update_token_count(input_tokens)
            response = await self.client.chat.completions.create(**params)

            # 初始化收集消息的列表
            collected_messages = []
            # 异步遍历流式响应的每个块
            async for chunk in response:
                # 提取从块中获取的内容，如果为空则使用空字符串
                chunk_message = chunk.choices[0].delta.content or ""
                collected_messages.append(chunk_message)
                # 直接打印到控制台，实现实时显示
                print(chunk_message, end="", flush=True)

            print()  # 流式响应完成后打印换行
            # 将所有收集的块连接起来得到完整响应
            full_response = "".join(collected_messages).strip()

            # 检查响应是否为空
            if not full_response:
                raise ValueError("Empty response from streaming LLM")

            return full_response

        except TokenLimitExceeded:
            raise
        except ValueError as ve:
            logger.error(f"Validation error in ask_with_images: {ve}")
            raise
        except OpenAIError as oe:
            logger.error(f"OpenAI API error: {oe}")
            if isinstance(oe, AuthenticationError):
                logger.error("Authentication failed. Check API key.")
            elif isinstance(oe, RateLimitError):
                logger.error("Rate limit exceeded. Consider increasing retry attempts.")
            elif isinstance(oe, APIError):
                logger.error(f"API error: {oe}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error in ask_with_images: {e}")
            raise

    @retry(
        wait=wait_random_exponential(min=1, max=60),  # 指数退避策略，等待时间从 1s 到 60s
        stop=stop_after_attempt(6),                 # 最多重试 6 次
        retry=retry_if_exception_type(
            (OpenAIError, Exception, ValueError)      # 哪些异常需要重试，不包括 TokenLimitExceeded
        ),  
    )
    async def ask_tool(
        self,
        messages: List[Union[dict, Message]],
        system_msgs: Optional[List[Union[dict, Message]]] = None,
        timeout: int = 300,
        tools: Optional[List[dict]] = None,
        tool_choice: TOOL_CHOICE_TYPE = ToolChoice.AUTO,  # type: ignore
        temperature: Optional[float] = None,
        **kwargs,
    ) -> ChatCompletionMessage | None:
        """
        使用函数/工具调用功能向语言模型发送请求并获取响应。
        
        这个方法允许调用语言模型的工具调用功能，使模型可以生成结构化的函数调用响应。
        它适用于需要模型生成API调用、JSON结构或其他工具调用的场景，如构建代理、
        利用数据库查询或执行复杂的多步骤任务。
        
        该方法具有强大的错误处理和重试机制，可以处理网络问题、API限流和其他服务器错误。
        它允许控制模型的工具选择策略，可以是自动选择、强制使用指定工具或强制不使用工具。
        
        参数:
            messages: 对话消息列表
            system_msgs: 可选的系统消息，添加到开头
            timeout: 请求超时时间（秒）
            tools: 可用工具列表
            tool_choice: 工具选择策略（自动、强制指定或不使用）
            temperature: 采样温度，控制输出的创造性
            **kwargs: 其他完成参数
        
        返回:
            ChatCompletionMessage: 模型的响应，可能包含工具调用或文本内容
        
        抛出:
            TokenLimitExceeded: 如果超过令牌限制
            ValueError: 如果工具、工具选择或消息无效
            OpenAIError: 如果 API 调用在重试后仍然失败
            Exception: 其他意外错误
        """
        try:
            # 验证工具选择策略参数是否有效
            # 工具选择策略必须是已定义的某一类型：自动、必选特定工具或不使用工具
            if tool_choice not in TOOL_CHOICE_VALUES:
                raise ValueError(f"Invalid tool_choice: {tool_choice}")

            # 检查当前模型是否支持图像，这影响消息格式化
            supports_images = self.model in MULTIMODAL_MODELS

            # 格式化消息列表，处理系统消息和普通消息
            if system_msgs:
                # 如果有系统消息，先格式化系统消息
                system_msgs = self.format_messages(system_msgs, supports_images)
                # 将系统消息添加到普通消息之前
                messages = system_msgs + self.format_messages(messages, supports_images)
            else:
                # 如果没有系统消息，只格式化普通消息
                messages = self.format_messages(messages, supports_images)

            # 计算消息的令牌数量
            input_tokens = self.count_message_tokens(messages)

            # 如果有工具定义，计算工具描述的令牌数量
            tools_tokens = 0
            if tools:
                for tool in tools:
                    # 将每个工具转换为字符串并计算令牌数
                    tools_tokens += self.count_tokens(str(tool))

            # 将工具令牌数添加到总令牌数中
            input_tokens += tools_tokens

            # 检查是否超过令牌限制
            if not self.check_token_limit(input_tokens):
                error_message = self.get_limit_error_message(input_tokens)
                # 抛出特殊异常，该异常不会被重试机制重试
                raise TokenLimitExceeded(error_message)

            # 如果提供了工具，验证工具格式是否正确
            if tools:
                for tool in tools:
                    # 每个工具必须是字典且必须有type字段（工具类型）
                    if not isinstance(tool, dict) or "type" not in tool:
                        raise ValueError("Each tool must be a dict with 'type' field")

            # 设置API请求参数
            params = {
                "model": self.model,  # 使用的模型
                "messages": messages,  # 格式化后的消息列表
                "tools": tools,  # 工具定义
                "tool_choice": tool_choice,  # 工具选择策略
                "timeout": timeout,  # 请求超时时间
                **kwargs,  # 其他额外参数
            }

            # 根据模型类型添加特定参数
            if self.model in REASONING_MODELS:  # 对于强化推理模型
                params["max_completion_tokens"] = self.max_tokens  # 使用max_completion_tokens参数
            else:  # 对于其他模型
                params["max_tokens"] = self.max_tokens  # 使用标准max_tokens参数
                params["temperature"] = (
                    temperature if temperature is not None else self.temperature  # 设置温度参数
                )

            # 工具调用请求始终使用非流式模式，因为需要完整的结构化输出
            params["stream"] = False  # 工具调用始终使用非流式请求
            # 发送请求并等待响应
            response: ChatCompletion = await self.client.chat.completions.create(
                **params
            )

            # 检查响应是否有效
            if not response.choices or not response.choices[0].message:
                print(response)  # 输出原始响应用于调试
                # 返回None而不是抛出异常，允许调用者处理无效响应
                return None

            # 更新令牌计数，包括输入和完成的令牌
            self.update_token_count(
                response.usage.prompt_tokens, response.usage.completion_tokens
            )

            # 返回模型的响应消息，可能包含工具调用
            return response.choices[0].message

        except TokenLimitExceeded:
            # 令牌限制异常直接重新抛出，不进行额外的日志记录
            # 这是因为该异常是有意主动抛出的，不是API调用失败
            raise
        except ValueError as ve:
            # 如果是数据验证错误（参数错误、格式错误等），记录错误信息并重新抛出
            logger.error(f"Validation error in ask_tool: {ve}")
            raise
        except OpenAIError as oe:
            # 处理OpenAI API特定的错误，并提供更详细的错误信息
            logger.error(f"OpenAI API error: {oe}")
            # 根据错误类型进行特定处理
            if isinstance(oe, AuthenticationError):
                # 身份验证错误，可能是API密钥无效或过期
                logger.error("Authentication failed. Check API key.")
            elif isinstance(oe, RateLimitError):
                # 超出速率限制，建议增加重试次数或改进重试策略
                logger.error("Rate limit exceeded. Consider increasing retry attempts.")
            elif isinstance(oe, APIError):
                # 其他API相关错误
                logger.error(f"API error: {oe}")
            # 将错误继续向上传递，由调用者处理
            raise
        except Exception as e:
            # 处理所有其他未预期的错误，如网络问题、系统错误等
            logger.error(f"Unexpected error in ask_tool: {e}")
            # 将错误继续向上传递，由调用者处理
            raise
