"""
Python代码执行工具模块

这个模块提供了PythonExecute工具，允许在受控的环境中安全地执行Python代码。
它使用多进程来隔离代码执行，并支持超时控制和输出捕获。
这个工具为代理提供了执行动态Python代码的能力，对于数据处理、计算和可视化等任务非常有用。
"""

import multiprocessing
import sys
from io import StringIO
from typing import Dict

from app.tool.base import BaseTool


class PythonExecute(BaseTool):
    """一个带超时和安全限制的Python代码执行工具。
    
    这个工具允许在隔离的环境中安全地执行Python代码。它使用多进程来隔离代码执行，
    防止不安全的代码影响主程序。它还支持超时控制，确保代码不会无限运行。
    输出捕获限于打印到标准输出的内容，函数返回值不会被捕获。
    """

    # 工具名称
    name: str = "python_execute"
    # 工具描述，用于语言模型理解工具的用途
    description: str = "Executes Python code string. Note: Only print outputs are visible, function return values are not captured. Use print statements to see results."
    # 工具参数模式，定义了需要提供的代码参数
    parameters: dict = {
        "type": "object",
        "properties": {
            "code": {
                "type": "string",
                "description": "The Python code to execute.",
            },
        },
        "required": ["code"],
    }

    def _run_code(self, code: str, result_dict: dict, safe_globals: dict) -> None:
        """在子进程中安全执行 Python 代码。
        
        这个内部方法在子进程中执行，并捕获所有标准输出和异常。
        它通过重定向sys.stdout来捕获print输出，并将结果存储在共享的result_dict中。
        
        参数:
            code: 要执行的Python代码字符串
            result_dict: 存储执行结果的共享字典
            safe_globals: 用于代码执行的全局变量环境
        """
        # 保存原始的标准输出
        original_stdout = sys.stdout
        try:
            # 创建字符串缓冲区来捕获输出
            output_buffer = StringIO()
            # 重定向标准输出到缓冲区
            sys.stdout = output_buffer
            # 执行代码，使用提供的全局环境
            exec(code, safe_globals, safe_globals)
            # 将输出结果保存到结果字典
            result_dict["observation"] = output_buffer.getvalue()
            result_dict["success"] = True
        except Exception as e:
            # 捕获所有异常并将其作为错误消息保存
            result_dict["observation"] = str(e)
            result_dict["success"] = False
        finally:
            # 恢复原始的标准输出
            sys.stdout = original_stdout

    async def execute(
        self,
        code: str,
        timeout: int = 5,
    ) -> Dict:
        """
        使用超时控制执行提供的Python代码。
        
        这个方法在单独的进程中安全地执行Python代码，并限制执行时间。
        它使用multiprocessing模块来创建隔离的执行环境，并在代码超时时终止进程。

        参数:
            code (str): 要执行的Python代码字符串
            timeout (int): 执行超时时间（秒），默认为5秒

        返回:
            Dict: 包含执行输出或错误消息的字典，以及成功状态标志
        """

        # 使用多进程管理器创建可在进程间共享的数据
        with multiprocessing.Manager() as manager:
            # 创建用于存储结果的共享字典
            result = manager.dict({"observation": "", "success": False})
            
            # 准备安全的全局变量环境
            if isinstance(__builtins__, dict):
                safe_globals = {"__builtins__": __builtins__}
            else:
                safe_globals = {"__builtins__": __builtins__.__dict__.copy()}
                
            # 创建子进程来执行代码
            proc = multiprocessing.Process(
                target=self._run_code, args=(code, result, safe_globals)
            )
            # 启动子进程
            proc.start()
            # 等待子进程执行，最多等待timeout秒
            proc.join(timeout)

            # 如果超时后进程仍在运行，则终止它
            if proc.is_alive():
                # 终止进程
                proc.terminate()
                # 等待进程终止（最多1秒）
                proc.join(1)
                # 返回超时错误信息
                return {
                    "observation": f"Execution timeout after {timeout} seconds",
                    "success": False,
                }
            # 返回执行结果
            return dict(result)
