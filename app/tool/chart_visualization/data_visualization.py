"""
数据可视化工具模块

这个模块提供了DataVisualization工具类，用于生成统计图表和图表洞见分析。
它可以基于预先准备的JSON数据创建交互式图表（HTML）或静态图表（PNG），
并可选择性地添加数据洞见分析。该工具支持中文和英文输出。
"""

import asyncio
import json
import os
from typing import Any, Hashable

import pandas as pd  # 用于处理表格数据
from pydantic import Field, model_validator

from app.config import config  # 应用配置
from app.llm import LLM  # 语言模型接口
from app.logger import logger  # 日志模块
from app.tool.base import BaseTool  # 基础工具类


class DataVisualization(BaseTool):
    """
    数据可视化工具类，用于生成统计图表和图表洞见分析。
    
    这个类实现了BaseTool接口，提供了基于预先准备的JSON数据生成交互式或静态图表的功能。
    它可以生成各种类型的数据可视化图表，包括折线图、柱状图、饼图等，并可选择性地添加数据洞见分析。
    这个工具使用语言模型来生成图表洞见，并支持中文和英文输出。
    """
    # 工具名称
    name: str = "data_visualization"
    # 工具描述，用于向语言模型提供工具功能介绍
    description: str = """使用来自visualization_preparation工具的JSON信息可视化统计图表或添加图表洞见。您可以按照以下步骤操作：
1. 可视化统计图表
2. 根据第1步选择图表洞见（可选）
输出：
1. 图表（png/html）
2. 图表洞见（.md）（可选）"""
    # 工具参数模式定义
    parameters: dict = {
        "type": "object",
        "properties": {
            "json_path": {
                "type": "string",
                "description": """以".json"结尾的json信息文件路径""",
            },
            "output_type": {
                "description": "渲染格式（html=交互式）",
                "type": "string",
                "default": "html",
                "enum": ["png", "html"],  # png为静态图片，html为交互式图表
            },
            "tool_type": {
                "description": "可视化图表或添加洞见",
                "type": "string",
                "default": "visualization",
                "enum": ["visualization", "insight"],  # visualization为只生成图表，insight为生成图表洞见
            },
            "language": {
                "description": "英语(en) / 中文(zh)",
                "type": "string",
                "default": "en",
                "enum": ["zh", "en"],  # 设置输出语言
            },
        },
        "required": ["code"],  # 必需参数
    }
    # 语言模型实例，用于生成图表洞见
    llm: LLM = Field(default_factory=LLM, description="语言模型实例")

    @model_validator(mode="after")
    def initialize_llm(self):
        """如果未提供语言模型实例，则使用默认设置初始化语言模型。
        
        这个方法在类初始化后执行，用于确保语言模型实例存在并有效。
        如果没有提供语言模型或提供的不是LLM类型，则创建一个新的LLM实例。
        
        返回:
            self: 更新后的当前对象实例
        """
        # 如果没有语言模型或语言模型类型不正确，创建新的LLM实例
        if self.llm is None or not isinstance(self.llm, LLM):
            # 使用当前工具名称作为配置名称初始化LLM
            self.llm = LLM(config_name=self.name.lower())
        return self

    def get_file_path(
        self,
        json_info: list[dict[str, str]],
        path_str: str,
        directory: str = None,
    ) -> list[str]:
        """获取完整的文件路径列表。
        
        这个方法从提供的JSON信息中提取文件路径，并检查这些路径是否存在。
        如果提供的是相对路径，则会尝试将其与工作空间根目录或指定目录组合。
        
        参数:
            json_info: 包含文件路径信息的字典列表
            path_str: 字典中表示文件路径的键名
            directory: 可选的目录前缀，用于解析相对路径
            
        返回:
            有效文件路径的列表
            
        异常:
            Exception: 如果文件或目录不存在
        """
        # 初始化结果列表
        res = []
        # 遍历JSON信息中的每个项
        for item in json_info:
            # 检查原始路径是否存在
            if os.path.exists(item[path_str]):
                res.append(item[path_str])
            # 如果原始路径不存在，尝试与工作空间根目录或指定目录组合
            elif os.path.exists(
                os.path.join(f"{directory or config.workspace_root}", item[path_str])
            ):
                # 将组合后的完整路径添加到结果列表
                res.append(
                    os.path.join(
                        f"{directory or config.workspace_root}", item[path_str]
                    )
                )
            # 如果文件或目录不存在，抛出异常
            else:
                raise Exception(f"No such file or directory: {item[path_str]}")
        return res

    def success_output_template(self, result: list[dict[str, str]]) -> str:
        content = ""
        if len(result) == 0:
            return "Is EMPTY!"
        for item in result:
            content += f"""## {item['title']}\nChart saved in: {item['chart_path']}"""
            if "insight_path" in item and item["insight_path"] and "insight_md" in item:
                content += "\n" + item["insight_md"]
            else:
                content += "\n"
        return f"Chart Generated Successful!\n{content}"

    async def data_visualization(
        self, json_info: list[dict[str, str]], output_type: str, language: str
    ) -> str:
        data_list = []
        csv_file_path = self.get_file_path(json_info, "csvFilePath")
        for index, item in enumerate(json_info):
            df = pd.read_csv(csv_file_path[index], encoding="utf-8")
            df = df.astype(object)
            df = df.where(pd.notnull(df), None)
            data_dict_list = df.to_json(orient="records", force_ascii=False)

            data_list.append(
                {
                    "file_name": os.path.basename(csv_file_path[index]).replace(
                        ".csv", ""
                    ),
                    "dict_data": data_dict_list,
                    "chartTitle": item["chartTitle"],
                }
            )
        tasks = [
            self.invoke_vmind(
                dict_data=item["dict_data"],
                chart_description=item["chartTitle"],
                file_name=item["file_name"],
                output_type=output_type,
                task_type="visualization",
                language=language,
            )
            for item in data_list
        ]

        results = await asyncio.gather(*tasks)
        error_list = []
        success_list = []
        for index, result in enumerate(results):
            csv_path = csv_file_path[index]
            if "error" in result and "chart_path" not in result:
                error_list.append(f"Error in {csv_path}: {result['error']}")
            else:
                success_list.append(
                    {
                        **result,
                        "title": json_info[index]["chartTitle"],
                    }
                )
        if len(error_list) > 0:
            return {
                "observation": f"# Error chart generated{'\n'.join(error_list)}\n{self.success_output_template(success_list)}",
                "success": False,
            }
        else:
            return {"observation": f"{self.success_output_template(success_list)}"}

    async def add_insighs(
        self, json_info: list[dict[str, str]], output_type: str
    ) -> str:
        data_list = []
        chart_file_path = self.get_file_path(
            json_info, "chartPath", os.path.join(config.workspace_root, "visualization")
        )
        for index, item in enumerate(json_info):
            if "insights_id" in item:
                data_list.append(
                    {
                        "file_name": os.path.basename(chart_file_path[index]).replace(
                            f".{output_type}", ""
                        ),
                        "insights_id": item["insights_id"],
                    }
                )
        tasks = [
            self.invoke_vmind(
                insights_id=item["insights_id"],
                file_name=item["file_name"],
                output_type=output_type,
                task_type="insight",
            )
            for item in data_list
        ]
        results = await asyncio.gather(*tasks)
        error_list = []
        success_list = []
        for index, result in enumerate(results):
            chart_path = chart_file_path[index]
            if "error" in result and "chart_path" not in result:
                error_list.append(f"Error in {chart_path}: {result['error']}")
            else:
                success_list.append(chart_path)
        success_template = (
            f"# Charts Update with Insights\n{','.join(success_list)}"
            if len(success_list) > 0
            else ""
        )
        if len(error_list) > 0:
            return {
                "observation": f"# Error in chart insights:{'\n'.join(error_list)}\n{success_template}",
                "success": False,
            }
        else:
            return {"observation": f"{success_template}"}

    async def execute(
        self,
        json_path: str,
        output_type: str | None = "html",
        tool_type: str | None = "visualization",
        language: str | None = "en",
    ) -> str:
        try:
            logger.info(f"📈 data_visualization with {json_path} in: {tool_type} ")
            with open(json_path, "r", encoding="utf-8") as file:
                json_info = json.load(file)
            if tool_type == "visualization":
                return await self.data_visualization(json_info, output_type, language)
            else:
                return await self.add_insighs(json_info, output_type)
        except Exception as e:
            return {
                "observation": f"Error: {e}",
                "success": False,
            }

    async def invoke_vmind(
        self,
        file_name: str,
        output_type: str,
        task_type: str,
        insights_id: list[str] = None,
        dict_data: list[dict[Hashable, Any]] = None,
        chart_description: str = None,
        language: str = "en",
    ):
        llm_config = {
            "base_url": self.llm.base_url,
            "model": self.llm.model,
            "api_key": self.llm.api_key,
        }
        vmind_params = {
            "llm_config": llm_config,
            "user_prompt": chart_description,
            "dataset": dict_data,
            "file_name": file_name,
            "output_type": output_type,
            "insights_id": insights_id,
            "task_type": task_type,
            "directory": str(config.workspace_root),
            "language": language,
        }
        # build async sub process
        process = await asyncio.create_subprocess_exec(
            "npx",
            "ts-node",
            "src/chartVisualize.ts",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=os.path.dirname(__file__),
        )
        input_json = json.dumps(vmind_params, ensure_ascii=False).encode("utf-8")
        try:
            stdout, stderr = await process.communicate(input_json)
            stdout_str = stdout.decode("utf-8")
            stderr_str = stderr.decode("utf-8")
            if process.returncode == 0:
                return json.loads(stdout_str)
            else:
                return {"error": f"Node.js Error: {stderr_str}"}
        except Exception as e:
            return {"error": f"Subprocess Error: {str(e)}"}
