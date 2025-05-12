"""
OpenManus项目安装配置文件

这个文件控制OpenManus项目的安装配置，包括依赖关系、版本定义、元数据
和命令行入口点。使用setuptools来管理包的构建和安装过程。
"""

from setuptools import find_packages, setup  # 导入安装工具函数


# 读取README.md文件作为长描述
with open("README.md", "r", encoding="utf-8") as fh:
    long_description = fh.read()  # 读取项目详细描述

# 配置安装参数
setup(
    name="openmanus",                      # 包名称
    version="0.1.0",                       # 包版本
    author="mannaandpoem and OpenManus Team",  # 作者
    author_email="mannaandpoem@gmail.com",    # 作者邮箱
    description="A versatile agent that can solve various tasks using multiple tools",  # 简短描述
    long_description=long_description,      # 长描述（来自README.md）
    long_description_content_type="text/markdown",  # 长描述的格式
    url="https://github.com/mannaandpoem/OpenManus",  # 项目仓库URL
    packages=find_packages(),              # 自动查找所有包
    # 项目依赖列表，包含具体版本要求
    install_requires=[
        "pydantic~=2.10.4",                # 数据验证库
        "openai>=1.58.1,<1.67.0",           # OpenAI API客户端
        "tenacity>=9.0,<9.2",                 # 重试机制
        "pyyaml~=6.0.2",                   # YAML处理
        "loguru~=0.7.3",                   # 日志处理
        "numpy",                           # 数值计算
        "datasets>=3.2,<3.7",              # 数据集管理
        "html2text>=2024.2.26,<2025.5.0",            # HTML到文本转换
        "gymnasium>=1.0,<1.2",             # 强化学习环境
        "pillow>=10.4,<11.3",              # 图像处理
        "browsergym~=0.13.3",              # 浏览器环境
        "uvicorn~=0.34.0",                 # ASGI服务器
        "unidiff~=0.7.5",                  # 差异处理
        "browser-use~=0.1.40",             # 浏览器控制
        "googlesearch-python~=1.3.0",      # Google搜索工具
        "aiofiles~=24.1.0",                # 异步文件操作
        "pydantic_core>=2.27.2,<2.28.0",    # Pydantic核心
        "colorama~=0.4.6",                  # 终端彩色输出
    ],
    # 项目分类标签，用于PyPI分类
    classifiers=[
        "Programming Language :: Python :: 3",        # Python 3兼容
        "Programming Language :: Python :: 3.12",      # Python 3.12兼容
        "License :: OSI Approved :: MIT License",      # MIT许可证
        "Operating System :: OS Independent",          # 跨平台
    ],
    python_requires=">=3.12",             # 要求Python 3.12或更高版本
    # 命令行入口点配置
    entry_points={
        "console_scripts": [
            "openmanus=main:main",             # 创建openmanus命令，指向main.py的main函数
        ],
    },
)
