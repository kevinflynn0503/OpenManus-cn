"""
图表可视化模块的Python代码执行工具

这个模块提供了NormalPythonExecute类，该类继承自PythonExecute并定制了图表可视化相关的代码执行功能。
它支持数据处理、数据报告和其他正常任务，但不直接进行可视化。
这个工具是图表可视化模块的基础组件，为其他工具（如VisualizationPrepare）提供了基础功能。
"""

from app.config import config  # 导入应用配置
from app.tool.python_execute import PythonExecute  # 导入基础Python执行工具


class NormalPythonExecute(PythonExecute):
    """
    一个带超时和安全限制的Python代码执行工具。
    
    这个类继承自PythonExecute，为图表可视化模块提供了定制的Python代码执行功能。
    它支持三种主要工作模式：
    1. 数据处理（process）：用于数据清洁、转换和准备
    2. 数据报告（report）：用于生成文本化的数据分析报告
    3. 其他任务（others）：用于执行其他类型的Python代码
    
    与PythonExecute不同，这个类特别定制了与数据分析相关的描述和提示，作为图表可视化流程的一部分。
    """

    # 工具名称
    name: str = "python_execute"
    # 工具描述
    description: str = """执行Python代码进行深入数据分析 / 数据报告（任务结论） / 其他正常任务，但不直接进行可视化。"""
    # 工具参数定义
    parameters: dict = {
        "type": "object",
        "properties": {
            "code_type": {
                "description": "代码类型，数据处理 / 数据报告 / 其他",
                "type": "string",
                "default": "process",  # 默认为数据处理模式
                "enum": ["process", "report", "others"],  # process用于数据处理，report用于生成报告，others用于其他任务
            },
            "code": {
                "type": "string",
                "description": """要执行的Python代码。
# 注意
1. 代码应生成全面的基于文本的报告，包含数据集概述、列详细信息、基本统计、派生指标、时间序列比较、异常值和关键洞见。
2. 使用print()输出所有分析结果（包括“数据集概述”或“预处理结果”等部分），以便清晰可见，并同时保存它们
3. 将所有报告 / 处理后的文件 / 每个分析结果保存在工作空间目录中：{directory}
4. 数据报告需要内容丰富，包括您的整体分析过程和相应的数据可视化。
5. 您可以逐步调用此工具进行数据分析，从概述到深入，并同时保存数据报告""".format(
                    directory=config.workspace_root  # 使用配置中的工作空间根目录
                ),
            },
        },
        "required": ["code"],  # 必需参数
    }

    async def execute(self, code: str, code_type: str | None = None, timeout=5):
        """执行Python代码并返回结果。
        
        这个方法重写了父类PythonExecute的execute方法，支持指定代码类型，
        但实际上直接调用了父类的方法进行代码执行。
        
        参数:
            code: 要执行的Python代码字符串
            code_type: 可选的代码类型（process/report/others），当前未使用
            timeout: 执行超时时间（秒），默认为5秒
            
        返回:
            执行结果的字典，包含成功状态和输出内容
        """
        # 直接调用父类的execute方法，忽略code_type参数
        return await super().execute(code, timeout)
