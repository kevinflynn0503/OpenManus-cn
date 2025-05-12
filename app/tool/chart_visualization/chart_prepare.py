"""
图表可视化准备工具模块

这个模块提供了VisualizationPrepare工具类，用于准备数据可视化所需的元数据和数据文件。
它继承了NormalPythonExecute类，允许用户执行Python代码来处理数据并生成用于图表可视化的JSON元数据。
这个工具支持两种模式：可视化准备和洞见选择。
"""

from app.tool.chart_visualization.python_execute import NormalPythonExecute  # 导入正常Python执行工具


class VisualizationPrepare(NormalPythonExecute):
    """
    图表生成准备工具类
    
    这个类继承了NormalPythonExecute，用于准备数据可视化所需的数据和元数据。
    它允许用户写Python代码来加载、清洁和转换数据，生成CSV文件，并创建包含图表描述和数据路径的JSON配置文件。
    这个工具可以用于生成可视化数据或选择图表洞见，为后续的data_visualization工具提供输入。
    """

    # 工具名称
    name: str = "visualization_preparation"
    # 工具描述
    description: str = "Using Python code to generates metadata of data_visualization tool. Outputs: 1) JSON Information. 2) Cleaned CSV data files (Optional)."    # 工具参数定义
    parameters: dict = {
        "type": "object",
        "properties": {
            "code_type": {
                "description": "code type, visualization: csv -> chart; insight: choose insight into chart",
                "type": "string",
                "default": "visualization",  # 默认为可视化模式
                "enum": ["visualization", "insight"],  # visualization用于生成可视化数据，insight用于选择图表洞见
            },
            "code": {
                "type": "string",
                "description": """Python code for data_visualization prepare.
## Visualization Type
1. Data loading logic
2. Csv Data and chart description generate
2.1 Csv data (The data you want to visulazation, cleaning / transform from origin data, saved in .csv)
2.2 Chart description of csv data (The chart title or description should be concise and clear. Examples: 'Product sales distribution', 'Monthly revenue trend'.)
3. Save information in json file.( format: {"csvFilePath": string, "chartTitle": string}[])
## Insight Type
1. Select the insights from the data_visualization results that you want to add to the chart.
2. Save information in json file.( format: {"chartPath": string, "insights_id": number[]}[])
# Note
1. You can generate one or multiple csv data with different visualization needs.
2. Make each chart data esay, clean and different.
3. Json file saving in utf-8 with path print: print(json_path)
""",
            },
        },
        "required": ["code", "code_type"],  # 必需参数
    }
