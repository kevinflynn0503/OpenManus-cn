# -*- coding: utf-8 -*-
"""
计划流程模块

该模块实现了流程化的任务规划和执行机制，允许系统自动创建分步骤的任务计划，
然后按顺序执行这些步骤。它支持使用不同的代理执行不同类型的任务步骤，
并根据当前进度继续执行或加入新步骤。该模块是系统中复杂任务的规划和执行核心。
"""

import json  # 用于处理JSON格式的数据
import time  # 用于生成时间戳
from enum import Enum  # 用于定义枚举类型
from typing import Dict, List, Optional, Union  # 类型提示

from pydantic import Field  # 用于定义模型字段

from app.agent.base import BaseAgent  # 基础代理类
from app.flow.base import BaseFlow  # 基础流程类
from app.llm import LLM  # 大型语言模型工具
from app.logger import logger  # 日志记录器
from app.schema import AgentState, Message, ToolChoice  # 数据模型
from app.tool import PlanningTool  # 计划工具


class PlanStepStatus(str, Enum):
    """计划步骤状态的枚举类
    
    定义了计划中各个步骤可能的状态，包括未开始、进行中、已完成和已阻塞。
    这些状态用于跟踪计划执行进度和处理各种步骤转换。
    """

    NOT_STARTED = "not_started"  # 步骤未开始
    IN_PROGRESS = "in_progress"  # 步骤正在进行中
    COMPLETED = "completed"     # 步骤已完成
    BLOCKED = "blocked"         # 步骤被阻塞

    @classmethod
    def get_all_statuses(cls) -> list[str]:
        """返回所有可能的步骤状态值的列表"""
        return [status.value for status in cls]  # 提取每个枚举成员的值

    @classmethod
    def get_active_statuses(cls) -> list[str]:
        """返回表示活跃状态的值列表（未开始或进行中）
        
        活跃状态是指需要处理或正在处理的状态，而不是终止状态如已完成或已阻塞。
        """
        return [cls.NOT_STARTED.value, cls.IN_PROGRESS.value]

    @classmethod
    def get_status_marks(cls) -> Dict[str, str]:
        """返回状态到其标记符号的映射
        
        这些符号用于在文本输出中可视化地表示每个步骤的状态。
        """
        return {
            cls.COMPLETED.value: "[✓]",   # 已完成标记（勾选符号）
            cls.IN_PROGRESS.value: "[→]", # 进行中标记（箭头符号）
            cls.BLOCKED.value: "[!]",       # 阻塞标记（感叹号）
            cls.NOT_STARTED.value: "[ ]",   # 未开始标记（空方括号）
        }


class PlanningFlow(BaseFlow):
    """使用代理管理任务规划和执行的流程类。
    
    PlanningFlow类实现了一个管理复杂任务规划和执行的流程框架，它可以：
    1. 创建结构化的计划和步骤
    2. 管理计划的状态和进度
    3. 为不同类型的步骤选择适当的执行代理
    4. 跟踪和更新计划执行进度
    5. 实现灵活的任务分解和继续执行
    """

    llm: LLM = Field(default_factory=lambda: LLM())  # 大语言模型实例，用于生成计划和分析
    planning_tool: PlanningTool = Field(default_factory=PlanningTool)  # 计划工具，用于管理计划和步骤
    executor_keys: List[str] = Field(default_factory=list)  # 执行器键列表，指定可用于执行步骤的代理键
    active_plan_id: str = Field(default_factory=lambda: f"plan_{int(time.time())}")  # 活跃计划ID，默认为基于时间戳的唯一ID
    current_step_index: Optional[int] = None  # 当前正在执行的步骤索引，初始为空

    def __init__(
        self, agents: Union[BaseAgent, List[BaseAgent], Dict[str, BaseAgent]], **data
    ):
        """初始化PlanningFlow实例。
        
        初始化过程处理了多种代理输入格式，设置执行器键和计划ID，
        并确保所有必要的组件都被正确初始化。
        
        Args:
            agents: 单个代理、代理列表或名称到代理的映射字典
            **data: 其他流程配置参数
        """
        # 在调用父类初始化之前处理executors参数
        if "executors" in data:
            data["executor_keys"] = data.pop("executors")  # 将executors重命名为executor_keys

        # 如果提供了plan_id，则设置为活跃计划ID
        if "plan_id" in data:
            data["active_plan_id"] = data.pop("plan_id")

        # 如果未提供计划工具，则初始化一个
        if "planning_tool" not in data:
            planning_tool = PlanningTool()
            data["planning_tool"] = planning_tool

        # 使用处理后的数据调用父类的初始化方法
        super().__init__(agents, **data)

        # 如果未指定执行器键，则使用所有代理键
        if not self.executor_keys:
            self.executor_keys = list(self.agents.keys())

    def get_executor(self, step_type: Optional[str] = None) -> BaseAgent:
        """为当前步骤获取适当的执行代理。
        
        根据步骤类型选择适当的代理来执行任务。如果可以直接匹配步骤类型和代理名称，
        则使用对应的代理。否则使用指定的执行器代理列表中的第一个可用代理。
        这个方法可以被扩展，以便更智能地根据步骤类型或要求选择代理。
        
        Args:
            step_type: 可选的步骤类型，用于匹配特定的代理
            
        Returns:
            适合执行当前步骤的代理实例
        """
        # 如果提供了步骤类型并且它与代理键匹配，则使用该代理
        if step_type and step_type in self.agents:
            return self.agents[step_type]

        # 否则使用第一个可用的执行器代理
        for key in self.executor_keys:
            if key in self.agents:
                return self.agents[key]

        # 如果没有找到可用的执行器代理，则回退到主代理
        return self.primary_agent

    async def execute(self, input_text: str) -> str:
        """使用代理执行规划流程。
        
        这是计划流程的主要执行方法，它管理整个计划的创建和执行过程。
        首先，如果提供了输入文本，它会创建一个初始计划。然后，它会循环执行以下步骤：
        1. 获取当前需要执行的步骤
        2. 为该步骤选择适当的执行代理
        3. 执行步骤并收集结果
        4. 更新步骤状态
        5. 检查是否需要终止执行
        
        Args:
            input_text: 用户输入文本，用于创建初始计划
            
        Returns:
            执行结果的文本表示
        """
        try:
            # 检查是否有可用的主代理
            if not self.primary_agent:
                raise ValueError("没有可用的主代理")

            # 如果提供了输入，则创建初始计划
            if input_text:
                await self._create_initial_plan(input_text)  # 创建初始计划

                # 验证计划是否创建成功
                if self.active_plan_id not in self.planning_tool.plans:
                    logger.error(
                        f"计划创建失败。在计划工具中找不到计划ID {self.active_plan_id}。"
                    )
                    return f"为以下输入创建计划失败: {input_text}"

            # 初始化结果字符串
            result = ""
            # 执行循环，逐步处理计划中的每个步骤
            while True:
                # 获取当前需要执行的步骤
                self.current_step_index, step_info = await self._get_current_step_info()

                # 如果没有更多步骤或计划已完成，则退出
                if self.current_step_index is None:
                    result += await self._finalize_plan()  # 执行计划结束操作
                    break

                # 使用适当的代理执行当前步骤
                step_type = step_info.get("type") if step_info else None  # 获取步骤类型
                executor = self.get_executor(step_type)  # 选择适当的执行代理
                step_result = await self._execute_step(executor, step_info)  # 执行步骤
                result += step_result + "\n"  # 添加步骤结果到总结果

                # 检查代理是否希望终止
                if hasattr(executor, "state") and executor.state == AgentState.FINISHED:
                    break  # 如果代理状态为已完成，则终止执行

            return result  # 返回最终结果
        except Exception as e:
            # 记录并返回错误信息
            logger.error(f"PlanningFlow执行错误: {str(e)}")
            return f"执行失败: {str(e)}"

    async def _create_initial_plan(self, request: str) -> None:
        """使用流程的LLM和计划工具根据请求创建初始计划。
        
        该方法使用大语言模型和计划工具根据用户请求生成结构化的任务计划。
        它首先尝试使用LLM生成一个智能的计划，如果失败则创建一个默认计划。
        
        Args:
            request: 用户请求文本，用于生成计划
        """
        logger.info(f"正在创建计划，ID为: {self.active_plan_id}")

        # 为计划创建创建一个系统消息
        system_message = Message.system_message(
            "你是一个规划助手。创建一个简洁、可执行的计划，包含明确的步骤。"
            "专注于关键里程碑而不是详细的子步骤。"
            "优化清晰度和效率。"
        )

        # 创建包含请求的用户消息
        user_message = Message.user_message(
            f"创建一个合理的计划，包含明确的步骤来完成任务: {request}"
        )

        # 使用PlanningTool调用LLM
        response = await self.llm.ask_tool(
            messages=[user_message],  # 用户消息
            system_msgs=[system_message],  # 系统消息
            tools=[self.planning_tool.to_param()],  # 计划工具参数
            tool_choice=ToolChoice.AUTO,  # 自动选择工具
        )

        # 如果有工具调用，则处理它们
        if response.tool_calls:
            for tool_call in response.tool_calls:
                if tool_call.function.name == "planning":  # 如果是计划工具
                    # 解析参数
                    args = tool_call.function.arguments
                    if isinstance(args, str):
                        try:
                            args = json.loads(args)  # 尝试将字符串参数解析为JSON
                        except json.JSONDecodeError:
                            logger.error(f"无法解析工具参数: {args}")
                            continue

                    # 确保计划ID正确设置并执行工具
                    args["plan_id"] = self.active_plan_id

                    # 通过ToolCollection执行工具而不是直接执行
                    result = await self.planning_tool.execute(**args)

                    logger.info(f"计划创建结果: {str(result)}")
                    return  # 成功创建计划后返回

        # 如果执行到这里，说明需要创建默认计划
        logger.warning("创建默认计划")

        # 使用ToolCollection创建默认计划
        await self.planning_tool.execute(
            **{
                "command": "create",  # 创建命令
                "plan_id": self.active_plan_id,  # 计划ID
                "title": f"计划: {request[:50]}{'...' if len(request) > 50 else ''}",  # 计划标题（截取前50个字符）
                "steps": ["分析请求", "执行任务", "验证结果"],  # 默认三个步骤
            }
        )

    async def _get_current_step_info(self) -> tuple[Optional[int], Optional[dict]]:
        """解析当前计划以识别第一个未完成步骤的索引和信息。
        
        该方法检查当前活跃计划，并查找第一个未完成的步骤（状态为未开始或进行中）。
        当找到活跃步骤时，将其状态标记为进行中，并返回步骤索引和信息。
        如果没有找到活跃步骤，则返回(None, None)。
        
        Returns:
            包含当前步骤索引和信息的元组，如果没有活跃步骤则为(None, None)
        """
        # 检查活跃计划ID是否有效
        if (
            not self.active_plan_id
            or self.active_plan_id not in self.planning_tool.plans
        ):
            logger.error(f"找不到ID为{self.active_plan_id}的计划")
            return None, None

        try:
            # 直接从计划工具存储中访问计划数据
            plan_data = self.planning_tool.plans[self.active_plan_id]  # 获取计划数据
            steps = plan_data.get("steps", [])  # 获取步骤列表
            step_statuses = plan_data.get("step_statuses", [])  # 获取步骤状态列表

            # 查找第一个未完成的步骤
            for i, step in enumerate(steps):
                # 确定当前步骤的状态
                if i >= len(step_statuses):  # 如果没有状态记录，则认为未开始
                    status = PlanStepStatus.NOT_STARTED.value
                else:
                    status = step_statuses[i]  # 使用记录的状态

                # 如果是活跃状态（未开始或进行中）
                if status in PlanStepStatus.get_active_statuses():
                    # 提取步骤类型/类别（如果可用）
                    step_info = {"text": step}  # 初始化步骤信息字典

                    # 尝试从文本中提取步骤类型（例如，[SEARCH]或[CODE]）
                    import re

                    # 使用正则表达式查找方括号内的大写字母或下划线
                    type_match = re.search(r"\[([A-Z_]+)\]", step)
                    if type_match:  # 如果找到类型标记
                        step_info["type"] = type_match.group(1).lower()  # 将类型转为小写并添加到信息中

                    # 将当前步骤标记为进行中
                    try:
                        # 使用计划工具标记步骤状态
                        await self.planning_tool.execute(
                            command="mark_step",  # 标记步骤命令
                            plan_id=self.active_plan_id,  # 计划ID
                            step_index=i,  # 步骤索引
                            step_status=PlanStepStatus.IN_PROGRESS.value,  # 设置为进行中状态
                        )
                    except Exception as e:
                        # 如果标记步骤出错，记录警告并直接更新状态
                        logger.warning(f"将步骤标记为进行中时出错: {e}")
                        # 如果需要，直接更新步骤状态
                        if i < len(step_statuses):  # 如果状态列表有足够的长度
                            step_statuses[i] = PlanStepStatus.IN_PROGRESS.value  # 直接更新状态
                        else:  # 如果状态列表不够长
                            # 将未定义的步骤全部设置为未开始
                            while len(step_statuses) < i:
                                step_statuses.append(PlanStepStatus.NOT_STARTED.value)
                            # 添加当前步骤的状态
                            step_statuses.append(PlanStepStatus.IN_PROGRESS.value)

                        # 更新计划数据中的状态列表
                        plan_data["step_statuses"] = step_statuses

                    # 返回当前步骤的索引和信息
                    return i, step_info

            # 如果没有找到活跃步骤
            return None, None  # 没有找到活跃步骤

        except Exception as e:
            # 记录错误并返回空结果
            logger.warning(f"查找当前步骤索引时出错: {e}")
            return None, None

    async def _execute_step(self, executor: BaseAgent, step_info: dict) -> str:
        """使用指定的代理执行当前步骤。
        
        该方法使用指定的代理执行当前计划步骤。它首先获取当前计划状态，
        然后创建一个包含计划状态和当前任务的提示，并使用代理的run方法执行该步骤。
        执行成功后，标记该步骤为已完成。
        
        Args:
            executor: 执行当前步骤的代理实例
            step_info: 当前步骤的信息字典
            
        Returns:
            步骤执行的结果文本
        """
        # 准备包含当前计划状态的代理上下文
        plan_status = await self._get_plan_text()  # 获取格式化的计划文本
        step_text = step_info.get("text", f"Step {self.current_step_index}")  # 获取步骤文本或使用默认值

        # 创建一个提示，用于指导代理执行当前步骤
        step_prompt = f"""
        当前计划状态:
        {plan_status}

        你的当前任务:
        你正在处理步骤 {self.current_step_index}: "{step_text}"

        请使用适当的工具执行该步骤。完成后，提供一个关于你所完成工作的摘要。
        """

        # 使用代理的run方法执行步骤
        try:
            # 调用代理执行步骤
            step_result = await executor.run(step_prompt)

            # 成功执行后将步骤标记为已完成
            await self._mark_step_completed()

            return step_result  # 返回步骤执行结果
        except Exception as e:
            # 捕获并记录执行错误
            logger.error(f"Error executing step {self.current_step_index}: {e}")
            return f"Error executing step {self.current_step_index}: {str(e)}"

    async def _mark_step_completed(self) -> None:
        """将当前步骤标记为已完成。
        
        该方法将当前步骤的状态更新为已完成。它首先尝试使用计划工具的API执行更新，
        如果失败，则直接在计划工具的存储中更新状态。
        """
        # 如果没有当前步骤索引，则直接返回
        if self.current_step_index is None:
            return

        try:
            # 使用计划工具API将步骤标记为已完成
            await self.planning_tool.execute(
                command="mark_step",  # 标记步骤命令
                plan_id=self.active_plan_id,  # 计划ID
                step_index=self.current_step_index,  # 步骤索引
                step_status=PlanStepStatus.COMPLETED.value,  # 步骤状态设置为已完成
            )
            # 记录成功更新的日志
            logger.info(
                f"Marked step {self.current_step_index} as completed in plan {self.active_plan_id}"
            )
        except Exception as e:
            # 如果更新失败，记录警告并尝试直接更新存储
            logger.warning(f"Failed to update plan status: {e}")
            # 直接在计划工具存储中更新步骤状态
            if self.active_plan_id in self.planning_tool.plans:
                # 获取计划数据和步骤状态列表
                plan_data = self.planning_tool.plans[self.active_plan_id]
                step_statuses = plan_data.get("step_statuses", [])

                # 确保步骤状态列表足够长
                while len(step_statuses) <= self.current_step_index:
                    step_statuses.append(PlanStepStatus.NOT_STARTED.value)  # 将缺失的步骤状态设置为未开始

                # 更新当前步骤的状态为已完成
                step_statuses[self.current_step_index] = PlanStepStatus.COMPLETED.value
                # 将更新后的状态列表写回计划数据
                plan_data["step_statuses"] = step_statuses

    async def _get_plan_text(self) -> str:
        """获取当前计划的格式化文本表示。
        
        该方法获取当前计划的格式化文本表示，用于在提示中展示计划状态。
        它首先尝试使用计划工具的API获取计划，如果失败，则直接从存储中生成计划文本。
        
        Returns:
            计划的格式化文本表示
        """
        try:
            # 尝试使用计划工具的API获取计划
            result = await self.planning_tool.execute(
                command="get", plan_id=self.active_plan_id
            )
            # 返回计划工具返回的输出或将结果转换为字符串
            return result.output if hasattr(result, "output") else str(result)
        except Exception as e:
            logger.error(f"Error getting plan: {e}")
            return self._generate_plan_text_from_storage()

    def _generate_plan_text_from_storage(self) -> str:
        """如果计划工具失败，直接从存储中生成计划文本。
        
        该方法是一个备用机制，当通过API获取计划失败时，直接从计划工具的内部存储中
        获取计划数据，并格式化为可读文本。它创建一个包含计划标题、步骤和状态的文本表示。
        
        Returns:
            计划的格式化文本表示
        """
        try:
            # 检查计划ID是否存在
            if self.active_plan_id not in self.planning_tool.plans:
                return f"Error: Plan with ID {self.active_plan_id} not found"

            plan_data = self.planning_tool.plans[self.active_plan_id]
            title = plan_data.get("title", "Untitled Plan")
            steps = plan_data.get("steps", [])
            step_statuses = plan_data.get("step_statuses", [])
            step_notes = plan_data.get("step_notes", [])

            # 确保步骤状态和注释列表的长度与步骤数量匹配
            while len(step_statuses) < len(steps):
                step_statuses.append(PlanStepStatus.NOT_STARTED.value)  # 添加默认的未开始状态
            while len(step_notes) < len(steps):
                step_notes.append("")  # 添加空注释

            # 按状态类型计算步骤数量
            status_counts = {status: 0 for status in PlanStepStatus.get_all_statuses()}  # 初始化每种状态的计数器

            # 统计各状态步骤数量
            for status in step_statuses:
                if status in status_counts:
                    status_counts[status] += 1

            completed = status_counts[PlanStepStatus.COMPLETED.value]
            total = len(steps)
            progress = (completed / total) * 100 if total > 0 else 0

            plan_text = f"Plan: {title} (ID: {self.active_plan_id})\n"
            plan_text += "=" * len(plan_text) + "\n\n"

            plan_text += (
                f"Progress: {completed}/{total} steps completed ({progress:.1f}%)\n"
            )
            plan_text += f"Status: {status_counts[PlanStepStatus.COMPLETED.value]} completed, {status_counts[PlanStepStatus.IN_PROGRESS.value]} in progress, "
            plan_text += f"{status_counts[PlanStepStatus.BLOCKED.value]} blocked, {status_counts[PlanStepStatus.NOT_STARTED.value]} not started\n\n"
            plan_text += "Steps:\n"

            status_marks = PlanStepStatus.get_status_marks()

            # 生成每个步骤的文本表示
            for i, (step, status, notes) in enumerate(
                zip(steps, step_statuses, step_notes)  # 将步骤、状态和注释配对
            ):
                # 使用状态标记来标示步骤状态
                status_mark = status_marks.get(
                    status, status_marks[PlanStepStatus.NOT_STARTED.value]  # 如果状态不存在，使用默认的未开始标记
                )

                # 添加步骤行
                plan_text += f"{i}. {status_mark} {step}\n"
                # 如果有注释，添加注释行
                if notes:
                    plan_text += f"   Notes: {notes}\n"

            return plan_text  # 返回生成的计划文本
        except Exception as e:
            logger.error(f"Error generating plan text from storage: {e}")
            return f"Error: Unable to retrieve plan with ID {self.active_plan_id}"

    async def _finalize_plan(self) -> str:
        """完成计划并使用流程的LLM直接提供摘要。
        
        该方法在所有计划步骤完成后调用，使用LLM生成对整个计划执行的摘要和最终思考。
        它首先获取当前计划状态，然后使用LLM生成摘要，并尝试将摘要保存到计划中。
        
        Returns:
            包含计划状态和摘要的文本
        """
        # 获取当前计划的文本表示
        plan_text = await self._get_plan_text()

        # 使用流程的LLM直接创建摘要
        try:
            # 创建系统消息，指示摘要任务
            system_message = Message.system_message(
                "You are a planning assistant. Your task is to summarize the completed plan."
            )

            # 创建包含计划状态的用户消息
            user_message = Message.user_message(
                f"The plan has been completed. Here is the final plan status:\n\n{plan_text}\n\nPlease provide a summary of what was accomplished and any final thoughts."
            )

            # 调用LLM生成摘要
            response = await self.llm.ask(
                messages=[user_message], system_msgs=[system_message]
            )

            return f"Plan completed:\n\n{response}"
        except Exception as e:
            logger.error(f"Error finalizing plan with LLM: {e}")

            # Fallback to using an agent for the summary
            try:
                agent = self.primary_agent
                summary_prompt = f"""
                The plan has been completed. Here is the final plan status:

                {plan_text}

                Please provide a summary of what was accomplished and any final thoughts.
                """
                summary = await agent.run(summary_prompt)
                return f"Plan completed:\n\n{summary}"
            except Exception as e2:
                logger.error(f"Error finalizing plan with agent: {e2}")
                return "Plan completed. Error generating summary."
