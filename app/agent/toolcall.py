"""工具调用代理模块

这个模块实现了 ToolCallAgent 类，这是一个专门用于处理工具/函数调用的代理类。
它继承自 ReActAgent，并增强了工具调用的抽象处理。
这个类是 Manus 代理的父类，提供了工具调用的核心逻辑。
"""

import asyncio
import json
from typing import Any, List, Optional, Union

from pydantic import Field

from app.agent.react import ReActAgent
from app.exceptions import TokenLimitExceeded
from app.logger import logger
from app.prompt.toolcall import NEXT_STEP_PROMPT, SYSTEM_PROMPT
from app.schema import TOOL_CHOICE_TYPE, AgentState, Message, ToolCall, ToolChoice
from app.tool import CreateChatCompletion, Terminate, ToolCollection


TOOL_CALL_REQUIRED = "Tool calls required but none provided"  # 必需工具调用但未提供的错误消息


class ToolCallAgent(ReActAgent):
    """用于处理工具/函数调用的基础代理类，增强了抽象处理能力。
    
    这个类的主要职责是处理与语言模型的交互，和工具调用的执行与结果处理。
    它实现了不同的工具选择模式（自动、必需或禁用）并支持特殊工具的处理。
    """

    name: str = "toolcall"  # 代理名称
    description: str = "an agent that can execute tool calls."

    # 从提示词模块加载系统提示词和下一步提示词
    system_prompt: str = SYSTEM_PROMPT
    next_step_prompt: str = NEXT_STEP_PROMPT

    # 默认可用工具集合，包含创建聊天完成和终止工具
    available_tools: ToolCollection = ToolCollection(
        CreateChatCompletion(), Terminate()
    )
    # 工具选择模式：AUTO-自动模式，可以选择使用或不使用工具
    tool_choices: TOOL_CHOICE_TYPE = ToolChoice.AUTO  # type: ignore
    # 特殊工具名称列表，这些工具具有特殊处理逻辑
    special_tool_names: List[str] = Field(default_factory=lambda: [Terminate().name])

    # 当前工具调用列表
    tool_calls: List[ToolCall] = Field(default_factory=list)
    # 当前 base64 编码图像，用于在工具消息中传递图像数据
    _current_base64_image: Optional[str] = None

    # 最大步骤数和最大观察结果长度
    max_steps: int = 30
    max_observe: Optional[Union[int, bool]] = None  # 观察结果的最大长度限制

    async def think(self) -> bool:
        """处理当前状态并使用工具决定下一步操作。
        
        这个方法实现了 ReAct 模式的“思考”阶段，它将当前状态和历史记录发送给语言模型，
        获取模型的思考和可能的工具调用，并处理不同工具选择模式下的逻辑。
        
        返回:
            bool: 如果需要继续执行返回 True，否则返回 False。
        """
        # 如果有下一步提示，将其作为用户消息添加到内存中
        if self.next_step_prompt:
            user_msg = Message.user_message(self.next_step_prompt)
            self.messages += [user_msg]

        try:
            # 使用工具选项获取语言模型响应
            response = await self.llm.ask_tool(
                messages=self.messages,  # 历史消息
                system_msgs=(  # 系统提示词（如果有）
                    [Message.system_message(self.system_prompt)]
                    if self.system_prompt
                    else None
                ),
                tools=self.available_tools.to_params(),  # 可用工具参数
                tool_choice=self.tool_choices,  # 工具选择模式
            )
        except ValueError:
            # 直接传递值错误供调用者处理
            raise
        except Exception as e:
            # 检查这是否是包含 TokenLimitExceeded 的 RetryError
            if hasattr(e, "__cause__") and isinstance(e.__cause__, TokenLimitExceeded):
                token_limit_error = e.__cause__
                logger.error(
                    f"🚨 Token limit error (from RetryError): {token_limit_error}"
                )
                # 向内存添加令牌限制错误消息
                self.memory.add_message(
                    Message.assistant_message(
                        f"Maximum token limit reached, cannot continue execution: {str(token_limit_error)}"
                    )
                )
                # 设置代理状态为完成
                self.state = AgentState.FINISHED
                return False
            # 重新抛出其他异常
            raise

        # 从响应中提取工具调用和内容
        self.tool_calls = tool_calls = (
            response.tool_calls if response and response.tool_calls else []
        )
        content = response.content if response and response.content else ""

        # 记录响应信息
        logger.info(f"✨ {self.name}'s thoughts: {content}")
        logger.info(
            f"🛠️ {self.name} selected {len(tool_calls) if tool_calls else 0} tools to use"
        )
        if tool_calls:
            logger.info(
                f"🧰 Tools being prepared: {[call.function.name for call in tool_calls]}"
            )
            logger.info(f"🔧 Tool arguments: {tool_calls[0].function.arguments}")

        try:
            # 检查响应是否有效
            if response is None:
                raise RuntimeError("No response received from the LLM")

            # 处理不同的工具选择模式
            if self.tool_choices == ToolChoice.NONE:  # 禁用工具模式
                if tool_calls:
                    # 如果模型尝试使用工具而工具不可用，记录警告
                    logger.warning(
                        f"🤔 Hmm, {self.name} tried to use tools when they weren't available!"
                    )
                if content:  # 如果有内容，添加助手消息并继续
                    self.memory.add_message(Message.assistant_message(content))
                    return True
                # 如果没有内容，返回 False不继续执行
                return False

            # 创建并添加助手消息（基于是否有工具调用使用不同的消息格式）
            assistant_msg = (
                Message.from_tool_calls(content=content, tool_calls=self.tool_calls)
                if self.tool_calls
                else Message.assistant_message(content)
            )
            self.memory.add_message(assistant_msg)

            # 如果必须使用工具但没有工具调用，返回 True（将在act()中处理）
            if self.tool_choices == ToolChoice.REQUIRED and not self.tool_calls:
                return True  # 将在 act() 中处理

            # 对于'自动'模式，如果没有工具调用但有内容，继续执行
            if self.tool_choices == ToolChoice.AUTO and not self.tool_calls:
                return bool(content)

            # 根据是否有工具调用决定是否继续执行
            return bool(self.tool_calls)
        except Exception as e:
            # 处理思考过程中的异常
            logger.error(f"🚨 Oops! The {self.name}'s thinking process hit a snag: {e}")
            self.memory.add_message(
                Message.assistant_message(
                    f"Error encountered while processing: {str(e)}"
                )
            )
            return False

    async def act(self) -> str:
        """执行工具调用并处理其结果。
        
        这个方法实现了 ReAct 模式的“行动”阶段，负责执行先前思考阶段中产生的工具调用，
        并将结果添加到代理的内存中。这就完成了思考-行动-观察的循环。
        
        返回:
            str: 所有工具执行结果的组合字符串。
        
        异常:
            ValueError: 如果要求工具调用但没有提供。
        """
        # 如果没有工具调用
        if not self.tool_calls:
            # 如果工具调用是必需的，抛出异常
            if self.tool_choices == ToolChoice.REQUIRED:
                raise ValueError(TOOL_CALL_REQUIRED)

            # 如果没有工具调用，返回最后一条消息的内容
            return self.messages[-1].content or "No content or commands to execute"

        # 收集所有工具调用的结果
        results = []
        for command in self.tool_calls:
            # 为每个工具调用重置 base64_image
            self._current_base64_image = None

            # 执行工具并获取结果
            result = await self.execute_tool(command)

            # 如果设置了最大观察长度，限制结果长度
            if self.max_observe:
                result = result[: self.max_observe]

            # 记录工具执行结果
            logger.info(
                f"🎯 Tool '{command.function.name}' completed its mission! Result: {result}"
            )

            # 将工具响应添加到内存中，作为观察结果
            tool_msg = Message.tool_message(
                content=result,  # 工具执行结果
                tool_call_id=command.id,  # 工具调用ID，用于关联工具调用和其结果
                name=command.function.name,  # 工具名称
                base64_image=self._current_base64_image,  # 图像数据（如果有）
            )
            self.memory.add_message(tool_msg)
            results.append(result)

        # 将所有工具结果组合并返回
        return "\n\n".join(results)

    async def execute_tool(self, command: ToolCall) -> str:
        """执行单个工具调用，并具有强大的错误处理能力。
        
        这个方法负责实际执行工具调用，包括参数解析、工具执行、特殊工具处理和错误处理。
        它还会处理工具返回的图像数据，并格式化结果以便于显示。
        
        参数:
            command: 要执行的工具调用对象
            
        返回:
            str: 工具执行结果或错误信息的字符串表示
        """
        # 验证命令是否有效
        if not command or not command.function or not command.function.name:
            return "Error: Invalid command format"

        # 获取工具名称
        name = command.function.name
        # 检查工具是否存在
        if name not in self.available_tools.tool_map:
            return f"Error: Unknown tool '{name}'"

        try:
            # 解析参数为JSON
            args = json.loads(command.function.arguments or "{}")

            # 执行工具
            logger.info(f"🔧 Activating tool: '{name}'...")
            result = await self.available_tools.execute(name=name, tool_input=args)

            # 处理特殊工具（如终止工具）
            await self._handle_special_tool(name=name, result=result)

            # 检查结果是否包含 base64 编码图像
            if hasattr(result, "base64_image") and result.base64_image:
                # 存储 base64_image 以便在工具消息中使用
                self._current_base64_image = result.base64_image

            # 格式化结果以便显示（标准情况）
            observation = (
                f"Observed output of cmd `{name}` executed:\n{str(result)}"
                if result
                else f"Cmd `{name}` completed with no output"
            )

            return observation
        except json.JSONDecodeError:
            # 处理JSON解析错误
            error_msg = f"Error parsing arguments for {name}: Invalid JSON format"
            logger.error(
                f"📝 Oops! The arguments for '{name}' don't make sense - invalid JSON, arguments:{command.function.arguments}"
            )
            return f"Error: {error_msg}"
        except Exception as e:
            # 处理其他所有异常
            error_msg = f"⚠️ Tool '{name}' encountered a problem: {str(e)}"
            logger.exception(error_msg)
            return f"Error: {error_msg}"

    async def _handle_special_tool(self, name: str, result: Any, **kwargs):
        """处理特殊工具的执行和状态变化。
        
        某些工具（如终止工具）需要特殊处理，例如终止代理的执行。
        这个方法处理这些特殊情况。
        
        参数:
            name: 工具名称
            result: 工具执行的结果
            **kwargs: 额外参数
        """
        # 检查是否为特殊工具
        if not self._is_special_tool(name):
            return

        # 如果应该结束执行，则设置代理状态为完成
        if self._should_finish_execution(name=name, result=result, **kwargs):
            # 设置代理状态为完成
            logger.info(f"🏁 Special tool '{name}' has completed the task!")
            self.state = AgentState.FINISHED

    @staticmethod
    def _should_finish_execution(**kwargs) -> bool:
        """决定工具执行是否应该结束代理。
        
        这个静态方法用于决定工具执行后是否应该结束代理的执行。
        子类可以重写该方法以提供更复杂的逻辑。
        
        返回:
            bool: 如果应该结束执行返回 True，否则返回 False。
        """
        return True

    def _is_special_tool(self, name: str) -> bool:
        """检查工具名称是否在特殊工具列表中。
        
        特殊工具是指那些需要特殊处理的工具，如终止工具。
        
        参数:
            name: 要检查的工具名称
            
        返回:
            bool: 如果是特殊工具返回 True，否则返回 False。
        """
        # 不区分大小写检查工具名称是否在特殊工具列表中
        return name.lower() in [n.lower() for n in self.special_tool_names]

    async def cleanup(self):
        """清理代理的工具使用的资源。
        
        这个方法在代理结束执行时调用，会清理所有工具使用的资源，
        例如浏览器实例、文件句柄等。这样可以避免资源泄漏。
        """
        logger.info(f"🧹 Cleaning up resources for agent '{self.name}'...")
        # 遍历所有可用工具
        for tool_name, tool_instance in self.available_tools.tool_map.items():
            # 检查工具是否有异步清理方法
            if hasattr(tool_instance, "cleanup") and asyncio.iscoroutinefunction(
                tool_instance.cleanup
            ):
                try:
                    # 清理工具资源
                    logger.debug(f"🧼 Cleaning up tool: {tool_name}")
                    await tool_instance.cleanup()
                except Exception as e:
                    # 记录清理错误但不中断清理过程
                    logger.error(
                        f"🚨 Error cleaning up tool '{tool_name}': {e}", exc_info=True
                    )
        logger.info(f"✨ Cleanup complete for agent '{self.name}'.")

    async def run(self, request: Optional[str] = None) -> str:
        """运行代理并在完成后清理。
        
        这个方法重写了父类的 run 方法，添加了完成时的资源清理功能。
        无论执行是否成功或出现异常，都会调用 cleanup 方法清理资源。
        
        参数:
            request: 可选的用户请求字符串
            
        返回:
            str: 代理执行的结果
        """
        try:
            # 调用父类的 run 方法执行代理
            return await super().run(request)
        finally:
            # 无论执行结果如何，确保清理资源
            await self.cleanup()
