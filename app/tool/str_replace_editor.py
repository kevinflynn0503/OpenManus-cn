"""具有沙箱支持的文件和目录操作工具。

该模块提供了一个强大的文件编辑器工具，允许查看、创建和编辑文件。
支持两种文件操作模式：本地文件系统操作和沙箱环境中的文件操作。
主要特点包括字符串替换功能、文件历史记录和撤销编辑功能。
"""

from collections import defaultdict
from pathlib import Path
from typing import Any, DefaultDict, List, Literal, Optional, get_args

from app.config import config
from app.exceptions import ToolError
from app.tool import BaseTool
from app.tool.base import CLIResult, ToolResult
from app.tool.file_operators import (
    FileOperator,  # 文件操作抽象基类
    LocalFileOperator,  # 本地文件系统操作器
    PathLike,  # 路径类型接口
    SandboxFileOperator,  # 沙箱环境文件操作器
)


# 定义可用的命令类型
# view: 查看文件或目录
# create: 创建文件
# str_replace: 替换文件中的字符串
# insert: 在指定位置插入内容
# undo_edit: 撤销上次编辑
Command = Literal[
    "view",
    "create",
    "str_replace",
    "insert",
    "undo_edit",
]

# 常量定义
SNIPPET_LINES: int = 4  # 代码片段显示的行数
MAX_RESPONSE_LEN: int = 16000  # 最大响应长度限制
TRUNCATED_MESSAGE: str = (
    "<response clipped><NOTE>To save on context only part of this file has been shown to you. "
    "You should retry this tool after you have searched inside the file with `grep -n` "
    "in order to find the line numbers of what you are looking for.</NOTE>"
)  # 内容被截断时的提示消息

# Tool description
_STR_REPLACE_EDITOR_DESCRIPTION = """Custom editing tool for viewing, creating and editing files
* State is persistent across command calls and discussions with the user
* If `path` is a file, `view` displays the result of applying `cat -n`. If `path` is a directory, `view` lists non-hidden files and directories up to 2 levels deep
* The `create` command cannot be used if the specified `path` already exists as a file
* If a `command` generates a long output, it will be truncated and marked with `<response clipped>`
* The `undo_edit` command will revert the last edit made to the file at `path`

Notes for using the `str_replace` command:
* The `old_str` parameter should match EXACTLY one or more consecutive lines from the original file. Be mindful of whitespaces!
* If the `old_str` parameter is not unique in the file, the replacement will not be performed. Make sure to include enough context in `old_str` to make it unique
* The `new_str` parameter should contain the edited lines that should replace the `old_str`
"""


def maybe_truncate(
    content: str, truncate_after: Optional[int] = MAX_RESPONSE_LEN
) -> str:
    """如果内容超过指定长度，则截断内容并附加通知。
    
    该函数用于防止返回过长的文件内容，超过限制的内容将被截断并添加提示信息。
    
    参数:
        content: 要检查的内容字符串
        truncate_after: 截断限制，默认为MAX_RESPONSE_LEN常量值
        
    返回:
        str: 可能被截断的内容字符串
    """
    # 如果没有设置截断限制或内容长度在限制之内，直接返回原内容
    if not truncate_after or len(content) <= truncate_after:
        return content
    # 截断内容并添加提示信息
    return content[:truncate_after] + TRUNCATED_MESSAGE


class StrReplaceEditor(BaseTool):
    """一个用于查看、创建和编辑文件的工具，支持沙箱环境。
    
    该工具提供了一组编辑功能，可以在本地文件系统或沙箱环境中操作文件。
    它支持查看文件和目录内容、创建新文件、使用字符串替换编辑文件内容，
    以及维护编辑历史以支持撤销操作。
    """

    name: str = "str_replace_editor"  # 工具名称
    description: str = _STR_REPLACE_EDITOR_DESCRIPTION  # 工具描述
    parameters: dict = {
        "type": "object",
        "properties": {
            "command": {
                "description": "The commands to run. Allowed options are: `view`, `create`, `str_replace`, `insert`, `undo_edit`.",
                "enum": ["view", "create", "str_replace", "insert", "undo_edit"],
                "type": "string",
            },
            "path": {
                "description": "Absolute path to file or directory.",
                "type": "string",
            },
            "file_text": {
                "description": "Required parameter of `create` command, with the content of the file to be created.",
                "type": "string",
            },
            "old_str": {
                "description": "Required parameter of `str_replace` command containing the string in `path` to replace.",
                "type": "string",
            },
            "new_str": {
                "description": "Optional parameter of `str_replace` command containing the new string (if not given, no string will be added). Required parameter of `insert` command containing the string to insert.",
                "type": "string",
            },
            "insert_line": {
                "description": "Required parameter of `insert` command. The `new_str` will be inserted AFTER the line `insert_line` of `path`.",
                "type": "integer",
            },
            "view_range": {
                "description": "Optional parameter of `view` command when `path` points to a file. If none is given, the full file is shown. If provided, the file will be shown in the indicated line number range, e.g. [11, 12] will show lines 11 and 12. Indexing at 1 to start. Setting `[start_line, -1]` shows all lines from `start_line` to the end of the file.",
                "items": {"type": "integer"},
                "type": "array",
            },
        },
        "required": ["command", "path"],  # 必需参数
    }
    _file_history: DefaultDict[PathLike, List[str]] = defaultdict(list)  # 文件编辑历史记录
    _local_operator: LocalFileOperator = LocalFileOperator()
    _sandbox_operator: SandboxFileOperator = SandboxFileOperator()

    # def _get_operator(self, use_sandbox: bool) -> FileOperator:
    def _get_operator(self) -> FileOperator:
        """根据执行模式获取适当的文件操作器。
        
        根据全局配置中的sandbox设置，决定使用沙箱环境文件操作器还是本地文件系统操作器。
        沙箱环境提供了一个安全的文件操作环境，防止对系统关键文件的意外修改。
        
        返回:
            FileOperator: 适用于当前环境的文件操作器实例
        """
        return (
            self._sandbox_operator  # 如果启用了沙箱模式，使用沙箱文件操作器
            if config.sandbox.use_sandbox
            else self._local_operator  # 否则使用本地文件系统操作器
        )

    async def execute(
        self,
        *,
        command: Command,
        path: str,
        file_text: str | None = None,
        view_range: list[int] | None = None,
        old_str: str | None = None,
        new_str: str | None = None,
        insert_line: int | None = None,
        **kwargs: Any,
    ) -> str:
        """执行文件操作命令。
        
        这是工具的主要入口点，用于根据提供的命令和参数执行相应的文件操作。
        它将验证路径和参数，然后调用适当的子方法来完成具体操作。
        
        参数:
            command: 要执行的命令（view/create/str_replace/insert/undo_edit）
            path: 目标文件或目录的路径
            file_text: 创建文件时的文件内容
            view_range: 查看文件时的行范围
            old_str: 要替换的原字符串
            new_str: 新的替换字符串或要插入的内容
            insert_line: 插入操作的目标行号
            **kwargs: 其他额外参数
            
        返回:
            str: 操作结果的字符串表示
            
        异常:
            ToolError: 当命令或参数无效时抛出
        """
        # 获取适当的文件操作器
        operator = self._get_operator()

        # 验证路径和命令组合
        await self.validate_path(command, Path(path), operator)

        # 根据命令执行相应的操作
        if command == "view":
            # 查看文件或目录
            result = await self.view(path, view_range, operator)
        elif command == "create":
            # 创建文件
            if file_text is None:
                raise ToolError("Parameter `file_text` is required for command: create")
            # 写入文件内容
            await operator.write_file(path, file_text)
            # 添加到文件历史记录
            self._file_history[path].append(file_text)
            result = ToolResult(output=f"File created successfully at: {path}")
        elif command == "str_replace":
            # 字符串替换
            if old_str is None:
                raise ToolError(
                    "Parameter `old_str` is required for command: str_replace"
                )
            result = await self.str_replace(path, old_str, new_str, operator)
        elif command == "insert":
            # 插入内容
            if insert_line is None:
                raise ToolError(
                    "Parameter `insert_line` is required for command: insert"
                )
            if new_str is None:
                raise ToolError("Parameter `new_str` is required for command: insert")
            result = await self.insert(path, insert_line, new_str, operator)
        elif command == "undo_edit":
            # 撤销编辑
            result = await self.undo_edit(path, operator)
        else:
            # 这应该由类型检查捕获，但我们包含它以确保安全
            raise ToolError(
                f'Unrecognized command {command}. The allowed commands for the {self.name} tool are: {", ".join(get_args(Command))}'
            )

        return str(result)

    async def validate_path(
        self, command: str, path: Path, operator: FileOperator
    ) -> None:
        """根据执行环境验证路径和命令组合。
        
        检查给定的路径是否适用于指定的命令，例如不能覆盖现有文件或访问不存在的文件。
        还会检查路径是否为绝对路径以确保安全性。
        
        参数:
            command: 要执行的命令
            path: 要验证的路径
            operator: 要使用的文件操作器
            
        异常:
            ToolError: 当路径验证失败时抛出
        """
        # 检查路径是否为绝对路径
        if not path.is_absolute():
            raise ToolError(f"The path {path} is not an absolute path")

        # Only check if path exists for non-create commands
        if command != "create":
            if not await operator.exists(path):
                raise ToolError(
                    f"The path {path} does not exist. Please provide a valid path."
                )

            # 检查路径是否为目录
            is_dir = await operator.is_directory(path)
            if is_dir and command != "view":
                # 如果是目录但命令不是view，则抛出错误
                # 目录只能用view命令查看，不能进行其他操作
                raise ToolError(
                    f"The path {path} is a directory and only the `view` command can be used on directories"
                )

        # 检查创建命令的文件是否已存在
        elif command == "create":
            exists = await operator.exists(path)
            if exists:
                # 如果文件已存在，则不能使用create命令覆盖
                # create命令仅用于创建新文件
                raise ToolError(
                    f"File already exists at: {path}. Cannot overwrite files using command `create`."
                )

    async def view(
        self,
        path: PathLike,
        view_range: Optional[List[int]] = None,
        operator: FileOperator = None,
    ) -> CLIResult:
        """显示文件或目录内容。
        
        查看指定路径的内容，可以是文件或目录。如果是文件，可以指定查看的行范围。
        
        参数:
            path: 要查看的文件或目录路径
            view_range: 可选的行范围限制 [开始行, 结束行]，仅适用于文件
            operator: 文件操作器实例
            
        返回:
            CLIResult: 包含查看结果的命令行结果对象
            
        异常:
            ToolError: 当参数无效或操作失败时抛出
        """
        # 确定路径是否为目录
        is_dir = await operator.is_directory(path)

        if is_dir:
            # 目录处理逻辑
            if view_range:
                # 不允许对目录使用view_range参数
                raise ToolError(
                    "The `view_range` parameter is not allowed when `path` points to a directory."
                )

            # 调用目录查看方法
            return await self._view_directory(path, operator)
        else:
            # 文件处理逻辑
            # 调用文件查看方法，可以包含行范围参数
            return await self._view_file(path, operator, view_range)

    @staticmethod
    async def _view_directory(path: PathLike, operator: FileOperator) -> CLIResult:
        """显示目录内容。
        
        查看指定目录下的文件和子目录，最多显示两级深度，不包括隐藏项。
        使用系统的find命令实现。
        
        参数:
            path: 要查看的目录路径
            operator: 文件操作器实例，用于执行命令
            
        返回:
            CLIResult: 包含目录内容的命令行结果对象
        """
        # 构造find命令，最大深度为2，排除隐藏文件（以.开头的文件）
        find_cmd = f"find {path} -maxdepth 2 -not -path '*/\\.*'"

        # 使用操作器执行命令
        returncode, stdout, stderr = await operator.run_command(find_cmd)

        if not stderr:
            # 如果没有错误，格式化输出信息
            stdout = (
                f"Here's the files and directories up to 2 levels deep in {path}, "
                f"excluding hidden items:\n{stdout}\n"
            )

        # 返回命令结果
        return CLIResult(output=stdout, error=stderr)

    async def _view_file(
        self,
        path: PathLike,
        operator: FileOperator,
        view_range: Optional[List[int]] = None,
    ) -> CLIResult:
        """显示文件内容，可选择指定行范围。
        
        读取指定文件的内容并返回。如果提供了行范围，则只返回指定的行。
        行号从1开始计数（而不是从0）。
        
        参数:
            path: 要查看的文件路径
            operator: 文件操作器实例
            view_range: 可选的行范围限制 [开始行, 结束行]，如果结束行为-1则表示到文件末尾
            
        返回:
            CLIResult: 包含文件内容的命令行结果对象
            
        异常:
            ToolError: 当行范围无效时抛出
        """
        # 读取文件内容
        file_content = await operator.read_file(path)
        init_line = 1  # 默认的起始行号

        # 如果指定了查看范围，应用范围限制
        if view_range:
            # 验证view_range格式：必须是包含两个整数的列表
            if len(view_range) != 2 or not all(isinstance(i, int) for i in view_range):
                raise ToolError(
                    "Invalid `view_range`. It should be a list of two integers."
                )

            # 将文件内容分割为行
            file_lines = file_content.split("\n")
            n_lines_file = len(file_lines)  # 文件总行数
            init_line, final_line = view_range  # 解析起始行和结束行

            # 验证行范围的有效性
            # 检查起始行是否在有效范围内（1到文件总行数）
            if init_line < 1 or init_line > n_lines_file:
                raise ToolError(
                    f"Invalid `view_range`: {view_range}. Its first element `{init_line}` should be "
                    f"within the range of lines of the file: {[1, n_lines_file]}"
                )
            # 检查结束行是否超过文件总行数
            if final_line > n_lines_file:
                raise ToolError(
                    f"Invalid `view_range`: {view_range}. Its second element `{final_line}` should be "
                    f"smaller than the number of lines in the file: `{n_lines_file}`"
                )
            # 检查结束行是否小于起始行（除非结束行为-1，表示到文件末尾）
            if final_line != -1 and final_line < init_line:
                raise ToolError(
                    f"Invalid `view_range`: {view_range}. Its second element `{final_line}` should be "
                    f"larger or equal than its first `{init_line}`"
                )

            # 应用行范围筛选
            # 如果结束行为-1，则表示从起始行到文件末尾
            if final_line == -1:
                file_content = "\n".join(file_lines[init_line - 1 :])  # 从起始行到末尾
            else:
                # 否则从起始行到指定的结束行（注意Python切片是不包含结束索引的）
                file_content = "\n".join(file_lines[init_line - 1 : final_line])

        # 格式化并返回结果
        # 使用_make_output方法处理输出格式，包括标题和行号信息
        return CLIResult(
            output=self._make_output(file_content, str(path), init_line=init_line)
        )

    async def str_replace(
        self,
        path: PathLike,
        old_str: str,
        new_str: Optional[str] = None,
        operator: FileOperator = None,
    ) -> CLIResult:
        """在文件中将唯一的字符串替换为新字符串。
        
        将文件中的特定字符串替换为新的字符串。要求旧字符串在文件中必须是唯一的，
        否则将抛出错误。如果新字符串为None，则使用空字符串替代（即删除旧字符串）。
        
        参数:
            path: 要操作的文件路径
            old_str: 要替换的旧字符串
            new_str: 替换成的新字符串，如果为None则删除旧字符串
            operator: 文件操作器实例
            
        返回:
            CLIResult: 包含替换结果的命令行结果对象
            
        异常:
            ToolError: 当旧字符串不存在或在文件中出现多次时抛出
        """
        # 读取文件内容并将制表符展开为空格
        # expandtabs方法将制表符(\t)转换为空格，确保一致的格式化
        file_content = (await operator.read_file(path)).expandtabs()
        old_str = old_str.expandtabs()  # 也展开旧字符串中的制表符
        new_str = new_str.expandtabs() if new_str is not None else ""  # 如果新字符串为None，则使用空字符串

        # 检查旧字符串在文件中是否唯一
        occurrences = file_content.count(old_str)  # 计算旧字符串出现的次数
        if occurrences == 0:
            # 如果旧字符串没有出现，抛出错误
            raise ToolError(
                f"No replacement was performed, old_str `{old_str}` did not appear verbatim in {path}."
            )
        elif occurrences > 1:
            # 如果旧字符串出现多次，找出所有出现的行号
            file_content_lines = file_content.split("\n")
            lines = [
                idx + 1  # 行号从1开始，而不是从0开始
                for idx, line in enumerate(file_content_lines)
                if old_str in line  # 检查每一行是否包含旧字符串
            ]
            # 抛出错误，指出字符串出现的所有行号
            raise ToolError(
                f"No replacement was performed. Multiple occurrences of old_str `{old_str}` "
                f"in lines {lines}. Please ensure it is unique"
            )

        # 将旧字符串替换为新字符串
        # 由于前面的检查确保了旧字符串只出现一次，所以这里只会进行一次替换
        new_file_content = file_content.replace(old_str, new_str)

        # 将新内容写入文件
        await operator.write_file(path, new_file_content)

        # 保存原始内容到历史记录中，以便支持撤销操作
        self._file_history[path].append(file_content)

        # 创建编辑部分的代码片段以显示变更
        # 计算替换发生的行号
        replacement_line = file_content.split(old_str)[0].count("\n")
        # 计算片段的起始行（替换行前几行）
        start_line = max(0, replacement_line - SNIPPET_LINES)
        # 计算片段的结束行（替换行后几行）
        end_line = replacement_line + SNIPPET_LINES + new_str.count("\n")
        # 提取替换前后的一段代码片段
        snippet = "\n".join(new_file_content.split("\n")[start_line : end_line + 1])

        # 准备成功消息
        success_msg = f"The file {path} has been edited. "  # 文件已编辑的基本提示
        # 添加格式化的代码片段，包括标题和行号
        success_msg += self._make_output(
            snippet, f"a snippet of {path}", start_line + 1
        )
        # 添加提示用户检查变更的消息
        success_msg += "Review the changes and make sure they are as expected. Edit the file again if necessary."

        # 返回命令结果
        return CLIResult(output=success_msg)

    async def insert(
        self,
        path: PathLike,
        insert_line: int,
        new_str: str,
        operator: FileOperator = None,
    ) -> CLIResult:
        """在文件的特定行插入文本。
        
        在指定文件的特定行号处插入新的文本内容。对于多行文本，
        将在指定位置插入所有行。行号从0开始计数。
        
        参数:
            path: 要编辑的文件路径
            insert_line: 插入位置的行号（从0开始）
            new_str: 要插入的新文本
            operator: 文件操作器实例
            
        返回:
            CLIResult: 包含插入结果的命令行结果对象
            
        异常:
            ToolError: 当插入行号无效时抛出
        """
        # 读取并准备文件内容
        file_text = (await operator.read_file(path)).expandtabs()  # 读取文件并展开制表符
        new_str = new_str.expandtabs()  # 同样展开要插入文本中的制表符
        file_text_lines = file_text.split("\n")  # 将文件内容分割为行
        n_lines_file = len(file_text_lines)  # 计算文件总行数

        # 验证插入行的有效性
        # 插入行必须在文件行数范围内（0到文件行数）
        if insert_line < 0 or insert_line > n_lines_file:
            raise ToolError(
                f"Invalid `insert_line` parameter: {insert_line}. It should be within "
                f"the range of lines of the file: {[0, n_lines_file]}"
            )

        # 执行插入操作
        new_str_lines = new_str.split("\n")  # 将要插入的文本分割为行
        # 构建新的文件内容：插入点前的行 + 新文本行 + 插入点后的行
        new_file_text_lines = (
            file_text_lines[:insert_line]  # 插入点前的行
            + new_str_lines  # 要插入的新行
            + file_text_lines[insert_line:]  # 插入点后的行
        )

        # 创建代码片段以预览变化
        # 包含插入点前几行、插入的新行和插入点后几行
        snippet_lines = (
            file_text_lines[max(0, insert_line - SNIPPET_LINES) : insert_line]  # 插入点前的几行
            + new_str_lines  # 插入的新行
            + file_text_lines[insert_line : insert_line + SNIPPET_LINES]  # 插入点后的几行
        )

        # 将行列表连接成文本并写入文件
        new_file_text = "\n".join(new_file_text_lines)  # 将新行列表连接成完整文件内容
        snippet = "\n".join(snippet_lines)  # 将片段行列表连接成预览片段

        # 写入新内容到文件
        await operator.write_file(path, new_file_text)
        # 保存原始文件内容到历史记录中，以支持撤销操作
        self._file_history[path].append(file_text)

        # 准备成功消息
        success_msg = f"The file {path} has been edited. "  # 基本编辑成功提示
        # 添加格式化的代码片段，包括标题和行号
        success_msg += self._make_output(
            snippet,
            "a snippet of the edited file",
            max(1, insert_line - SNIPPET_LINES + 1),  # 确保行号从1开始
        )
        # 添加编辑后的建议和提示
        success_msg += "Review the changes and make sure they are as expected (correct indentation, no duplicate lines, etc). Edit the file again if necessary."

        # 返回命令结果
        return CLIResult(output=success_msg)

    async def undo_edit(
        self, path: PathLike, operator: FileOperator = None
    ) -> CLIResult:
        """撤销对文件的最后一次编辑。
        
        将文件恢复到上一次编辑前的状态。每次编辑操作（如str_replace或insert）
        都会将原始内容保存到历史记录中，使得可以通过此方法撤销变更。
        
        参数:
            path: 要撤销编辑的文件路径
            operator: 文件操作器实例
            
        返回:
            CLIResult: 包含撤销结果的命令行结果对象
            
        异常:
            ToolError: 当没有可用的编辑历史时抛出
        """
        # 检查是否有编辑历史
        if not self._file_history[path]:
            raise ToolError(f"No edit history found for {path}.")

        old_text = self._file_history[path].pop()
        await operator.write_file(path, old_text)

        return CLIResult(
            output=f"Last edit to {path} undone successfully. {self._make_output(old_text, str(path))}"
        )

    def _make_output(
        self,
        file_content: str,
        file_descriptor: str,
        init_line: int = 1,
        expand_tabs: bool = True,
    ) -> str:
        """Format file content for display with line numbers."""
        file_content = maybe_truncate(file_content)
        if expand_tabs:
            file_content = file_content.expandtabs()

        # Add line numbers to each line
        file_content = "\n".join(
            [
                f"{i + init_line:6}\t{line}"
                for i, line in enumerate(file_content.split("\n"))
            ]
        )

        return (
            f"Here's the result of running `cat -n` on {file_descriptor}:\n"
            + file_content
            + "\n"
        )
