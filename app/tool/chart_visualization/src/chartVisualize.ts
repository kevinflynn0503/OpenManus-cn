/**
 * 图表可视化工具
 * 该模块使用VMind和VChart为数据生成交互式可视化图表并提取见解
 */

// 导入必要的依赖包
import Canvas from "canvas";  // 用于Node环境下的画布渲染
import path from "path";  // 文件路径处理工具
import fs from "fs";  // 文件系统操作
import VMind, { ChartType, DataTable } from "@visactor/vmind";  // 智能可视化生成器
import VChart from "@visactor/vchart";  // 可视化图表渲染库
import { isString } from "@visactor/vutils";  // 工具函数

/**
 * 算法类型枚举
 * 用于指定数据分析和见解提取时使用的算法
 */
enum AlgorithmType {
  OverallTrending = "overallTrend",     // 总体趋势分析
  AbnormalTrend = "abnormalTrend",      // 异常趋势分析
  PearsonCorrelation = "pearsonCorrelation",  // 皮尔透相关性分析
  SpearmanCorrelation = "spearmanCorrelation",  // 斯皮尔曼相关性分析
  ExtremeValue = "extremeValue",        // 极值分析
  MajorityValue = "majorityValue",      // 主要值分析
  StatisticsAbnormal = "statisticsAbnormal",  // 统计异常分析
  StatisticsBase = "statisticsBase",    // 基础统计分析
  DbscanOutlier = "dbscanOutlier",      // DBSCAN离群点检测
  LOFOutlier = "lofOutlier",           // 局部离群因子检测
  TurningPoint = "turningPoint",        // 拔点检测
  PageHinkley = "pageHinkley",         // Page-Hinkley变点检测
  DifferenceOutlier = "differenceOutlier",  // 差异离群点检测
  Volatility = "volatility",           // 波动性分析
}

/**
 * 生成图表的base64图像缓冲区
 * @param spec 图表规格配置
 * @param width 可选，图表宽度
 * @param height 可选，图表高度
 * @returns 图表图像的缓冲区
 */
const getBase64 = async (spec: any, width?: number, height?: number) => {
  // 关闭动画以生成静态图像
  spec.animation = false;
  // 设置图表宽度（如果提供）
  width && (spec.width = width);
  // 设置图表高度（如果提供）
  height && (spec.height = height);
  // 创建带有Node模式的VChart实例
  const cs = new VChart(spec, {
    mode: "node",           // 在Node.js环境中运行
    modeParams: Canvas,     // 使用canvas包进行渲染
    animation: false,       // 禁用动画
    dpr: 2,                // 设置设备像素比为2，提高图像质量
  });

  // 异步渲染图表
  await cs.renderAsync();

  // 获取图表的图像缓冲区
  const buffer = await cs.getImageBuffer();
  return buffer;
};

/**
 * 序列化图表规格，处理其中的函数
 * 将函数转换为字符串以便于JSON序列化
 * 
 * @param spec 要序列化的图表规格
 * @returns 序列化后的JSON字符串，函数被标记为__FUNCTION__前缀
 */
const serializeSpec = (spec: any) => {
  return JSON.stringify(spec, (key, value) => {
    // 处理函数值
    if (typeof value === "function") {
      // 将函数转换为字符串，移除换行符和多余空格
      const funcStr = value
        .toString()
        .replace(/(\r\n|\n|\r)/gm, "")  // 移除所有换行符
        .replace(/\s+/g, " ");          // 将多个空格压缩为一个

      // 添加函数标记前缀，便于后续反序列化
      return `__FUNCTION__${funcStr}`;
    }
    return value;
  });
};

/**
 * 生成包含图表的HTML页面
 * 创建一个完整的HTML页面，其中包含了VChart图表和必要的JavaScript代码
 * 
 * @param spec 图表规格
 * @param width 可选，图表容器宽度
 * @param height 可选，图表容器高度
 * @returns 完整的HTML页面字符串
 */
async function getHtmlVChart(spec: any, width?: number, height?: number) {
  return `<!DOCTYPE html>
<html>
<head>
    <title>VChart 示例</title>
    <script src="https://unpkg.com/@visactor/vchart/build/index.min.js"></script>
</head>
<body>
    <div id="chart-container" style="width: ${
      width ? `${width}px` : "100%"  // 如果指定了宽度，使用像素值，否则使用100%
    }; height: ${
      height ? `${height}px` : "100%"  // 如果指定了高度，使用像素值，否则使用100%
    };"></div>
    <script>
      // 解析带有函数的规格字符串
      function parseSpec(stringSpec) {
        return JSON.parse(stringSpec, (k, v) => {
          if (typeof v === 'string' && v.startsWith('__FUNCTION__')) {
            const funcBody = v.slice(12); // 移除标记
            try {
              return new Function('return (' + funcBody + ')')();
            } catch(e) {
              console.error('函数解析失败:', e);
              return () => {};  // 如果解析失败，返回空函数
            }
          }
          return v;
        });
      }
      // 解析序列化的图表规格
      const spec = parseSpec(\`${serializeSpec(spec)}\`);
      // 创建并渲染图表
      const chart = new VChart.VChart(spec, {
          dom: 'chart-container'  // 指定图表容器元素ID
      });
      chart.renderSync();  // 同步渲染图表
    </script>
</body>
</html>
`;  // 返回完整的HTML文档字符串
}

/**
 * 获取保存文件的路径名称
 * 根据指定的目录、文件名和输出类型构建完整的文件路径
 * 如果isUpdate为false且文件已存在，会自动添加"_new"后缀避免覆盖
 * 
 * @param directory 基础目录路径
 * @param fileName 文件名(不包含扩展名)
 * @param outputType 输出类型（html、png、json或md）
 * @param isUpdate 是否更新现有文件，默认为false
 * @returns 生成的完整文件路径
 */
function getSavedPathName(
  directory: string,
  fileName: string,
  outputType: "html" | "png" | "json" | "md",
  isUpdate: boolean = false
) {
  let newFileName = fileName;
  // 如果不是更新模式且文件已存在，则添加"_new"后缀避免覆盖
  while (
    !isUpdate &&
    fs.existsSync(
      path.join(directory, "visualization", `${newFileName}.${outputType}`)
    )
  ) {
    newFileName += "_new";
  }
  // 返回完整的文件路径
  return path.join(directory, "visualization", `${newFileName}.${outputType}`);
}

/**
 * 从标准输入流读取数据
 * 该函数用于从终端的标准输入中读取数据，通常用于接收Python程序发送的数据
 * 
 * @returns 包含输入数据的Promise
 */
const readStdin = (): Promise<string> => {
  return new Promise((resolve) => {
    let input = "";
    process.stdin.setEncoding("utf-8"); // 确保编码与 Python 端一致
    process.stdin.on("data", (chunk) => (input += chunk));  // 收集数据块
    process.stdin.on("end", () => resolve(input));  // 当输入结束时解析Promise
  });
};

/**
 * 保存见解到Markdown文件并返回内容和路径
 * 将图表分析生成的见解以结构化的Markdown格式保存到文件中
 * 
 * @param path 保存见解的文件路径
 * @param title 见解的标题
 * @param insights 见解内容数组
 * @returns 包含见解路径和内容的对象，如果没有见解则返回空对象
 */
const setInsightTemplate = (
  path: string,
  title: string,
  insights: string[]
) => {
  let res = "";
  if (insights.length) {  // 如果有见解内容
    // 添加标题
    res += `## ${title} Insights`;
    // 为每个见解添加编号和内容
    insights.forEach((insight, index) => {
      res += `\n${index + 1}. ${insight}`;
    });
  }
  if (res) {  // 如果有内容要写入
    // 将结果写入到文件
    fs.writeFileSync(path, res, "utf-8");
    // 返回文件路径和内容
    return { insight_path: path, insight_md: res };
  }
  return {};  // 如果没有见解，返回空对象
};

/**
 * 保存VMind结果到本地文件
 * 将图表规格和生成的图表内容保存到指定的目录中
 * 
 * @param options 保存选项对象
 * @param options.spec 图表规格对象
 * @param options.directory 保存的目录
 * @param options.outputType 输出类型，可以是png或html
 * @param options.fileName 文件名(不包含扩展名)
 * @param options.width 可选，图表宽度
 * @param options.height 可选，图表高度
 * @param options.isUpdate 可选，是否更新现有文件
 * @returns 保存的图表文件路径
 */
async function saveChartRes(options: {
  spec: any;
  directory: string;
  outputType: "png" | "html";
  fileName: string;
  width?: number;
  height?: number;
  isUpdate?: boolean;
}) {
  const { directory, fileName, spec, outputType, width, height, isUpdate } =
    options;
  // 保存图表规格为JSON文件
  const specPath = getSavedPathName(directory, fileName, "json", isUpdate);
  fs.writeFileSync(specPath, JSON.stringify(spec, null, 2));
  
  // 获取输出文件的路径
  const savedPath = getSavedPathName(directory, fileName, outputType, isUpdate);
  
  // 根据输出类型生成相应的文件
  if (outputType === "png") {
    // 如果是PNG格式，生成图像Buffer并保存
    const base64 = await getBase64(spec, width, height);
    fs.writeFileSync(savedPath, base64);
  } else {
    // 如果是HTML格式，生成HTML字符串并保存
    const html = await getHtmlVChart(spec, width, height);
    fs.writeFileSync(savedPath, html, "utf-8");
  }
  
  // 返回保存的文件路径
  return savedPath;
}

/**
 * 生成图表并提取见解
 * 根据提供的数据集和用户提示，使用VMind生成图表并提取见解
 * 
 * @param vmind VMind实例
 * @param options 生成图表的选项
 * @param options.dataset 数据集，可以是字符串或DataTable对象
 * @param options.userPrompt 用户提示，用于指导图表生成
 * @param options.directory 保存输出的目录
 * @param options.outputType 输出类型，可以是png或html
 * @param options.fileName 输出文件名
 * @param options.width 可选，图表宽度
 * @param options.height 可选，图表高度
 * @param options.language 可选，语言设置，"en"或"zh"
 * @returns 包含图表路径、见解路径及可能的错误信息的对象
 */
async function generateChart(
  vmind: VMind,
  options: {
    dataset: string | DataTable;
    userPrompt: string;
    directory: string;
    outputType: "png" | "html";
    fileName: string;
    width?: number;
    height?: number;
    language?: "en" | "zh";
  }
) {
  // 初始化结果对象
  let res: {
    chart_path?: string;  // 生成的图表文件路径
    error?: string;       // 如果有错误，存储错误信息
    insight_path?: string; // 见解文件路径
    insight_md?: string;   // 见解Markdown内容
  } = {};
  
  // 解构选项参数
  const {
    dataset,       // 数据集
    userPrompt,    // 用户提示
    directory,     // 输出目录
    width,         // 图表宽度
    height,        // 图表高度
    outputType,    // 输出类型
    fileName,      // 文件名
    language,      // 语言设置
  } = options;
  try {
    // 获取图表规格并保存到本地文件
    // 如果数据集是字符串，将其解析为JSON对象
    const jsonDataset = isString(dataset) ? JSON.parse(dataset) : dataset;
    // 调用VMind生成图表
    const { spec, error, chartType } = await vmind.generateChart(
      userPrompt,       // 用户提示指导图表生成
      undefined,        // 不指定特定的模型
      jsonDataset,      // 数据集
      {
        enableDataQuery: false,  // 禁用数据查询
        theme: "light",         // 使用浅色主题
      }
    );
    // 如果出错或规格为空，返回错误信息
    if (error || !spec) {
      return {
        error: error || "Spec of Chart was Empty!",
      };
    }

    // 设置图表标题为用户提示
    spec.title = {
      text: userPrompt,
    };
    // 确保输出目录存在，如果不存在则创建
    if (!fs.existsSync(path.join(directory, "visualization"))) {
      fs.mkdirSync(path.join(directory, "visualization"));
    }
    // 获取规格文件的保存路径
    const specPath = getSavedPathName(directory, fileName, "json");
    // 保存图表并获取生成的文件路径
    res.chart_path = await saveChartRes({
      directory,  // 目录
      spec,       // 图表规格
      width,      // 宽度
      height,     // 高度
      fileName,   // 文件名
      outputType,  // 输出类型
    });

    // 获取图表见解并保存到本地
    const insights = [];
    // 检查图表类型是否支持见解提取
    if (
      chartType &&
      [
        ChartType.BarChart,     // 柱状图
        ChartType.LineChart,    // 折线图
        ChartType.AreaChart,    // 面积图
        ChartType.ScatterPlot,  // 散点图
        ChartType.DualAxisChart, // 双轴图
      ].includes(chartType)
    ) {
      // 使用VMind获取图表见解
      const { insights: vmindInsights } = await vmind.getInsights(spec, {
        maxNum: 6,  // 最多获取6条见解
        algorithms: [  // 使用的算法列表
          AlgorithmType.OverallTrending,     // 总体趋势
          AlgorithmType.AbnormalTrend,       // 异常趋势
          AlgorithmType.PearsonCorrelation,  // 皮尔逊相关性
          AlgorithmType.SpearmanCorrelation, // 斯皮尔曼相关性
          AlgorithmType.StatisticsAbnormal,   // 统计异常
          AlgorithmType.LOFOutlier,          // 局部离群因子
          AlgorithmType.DbscanOutlier,        // DBSCAN离群点
          AlgorithmType.MajorityValue,        // 主要值
          AlgorithmType.PageHinkley,          // Page-Hinkley变点检测
          AlgorithmType.TurningPoint,         // 拔点
          AlgorithmType.StatisticsBase,       // 基础统计
          AlgorithmType.Volatility,           // 波动性
        ],
        usePolish: false,  // 不使用文本优化
        language: language === "en" ? "english" : "chinese",  // 根据设置使用相应语言
      });
      // 将获取到的见解添加到见解数组
      insights.push(...vmindInsights);
    }
    // 提取见解的纯文本内容
    const insightsText = insights
      .map((insight) => insight.textContent?.plainText)  // 提取纯文本
      .filter((insight) => !!insight) as string[];      // 过滤空值
    // 将见解保存到规格对象中
    spec.insights = insights;
    // 将更新后的规格写回文件
    fs.writeFileSync(specPath, JSON.stringify(spec, null, 2));
    // 将见解保存为Markdown并更新结果对象
    res = {
      ...res,
      ...setInsightTemplate(
        getSavedPathName(directory, fileName, "md"),  // 见解文件路径
        userPrompt,                                  // 用于标题的用户提示
        insightsText                                 // 见解文本数组
      ),
    };
  } catch (error: any) {
    res.error = error.toString();
  } finally {
    return res;
  }
}

/**
 * 根据选定的见解更新图表
 * 从之前生成的图表规格中选择特定的见解，并基于这些见解更新图表
 * 
 * @param vmind VMind实例
 * @param options 更新选项
 * @param options.directory 图表文件目录
 * @param options.outputType 输出类型（png或html）
 * @param options.fileName 文件名
 * @param options.insightsId 要应用的见解ID数组
 * @returns 包含更新后图表路径或错误信息的对象
 */
async function updateChartWithInsight(
  vmind: VMind,
  options: {
    directory: string;
    outputType: "png" | "html";
    fileName: string;
    insightsId: number[];
  }
) {
  // 解构选项
  const { directory, outputType, fileName, insightsId } = options;
  // 初始化结果对象
  let res: { error?: string; chart_path?: string } = {};
  try {
    // 以更新模式获取规格文件路径
    const specPath = getSavedPathName(directory, fileName, "json", true);
    // 读取并解析规格文件
    const spec = JSON.parse(fs.readFileSync(specPath, "utf8"));
    // LLM的见解索引从1开始，而数组从0开始，需要调整
    const insights = (spec.insights || []).filter(
      (_insight: any, index: number) => insightsId.includes(index + 1)
    );
    // 根据选定的见解更新图表规格
    const { newSpec, error } = await vmind.updateSpecByInsights(spec, insights);
    if (error) {
      throw error;
    }
    // 保存更新后的图表
    res.chart_path = await saveChartRes({
      spec: newSpec,  // 新的图表规格
      directory,      // 目录
      outputType,     // 输出类型
      fileName,       // 文件名
      isUpdate: true,  // 使用更新模式
    });
  } catch (error: any) {
    // 捕获并记录错误
    res.error = error.toString();
  } finally {
    // 返回结果
    return res;
  }
}

/**
 * 主函数，处理图表可视化请求
 * 读取标准输入的JSON数据，初始化VMind并根据任务类型执行相应操作
 */
async function executeVMind() {
  // 读取来自标准输入的数据
  const input = await readStdin();
  // 解析JSON数据
  const inputData = JSON.parse(input);
  let res;
  
  // 从输入数据中解构参数，并提供默认值
  const {
    llm_config,                           // LLM配置
    width,                                // 图表宽度
    dataset = [],                         // 数据集，默认为空数组
    height,                               // 图表高度
    directory,                            // 输出目录
    user_prompt: userPrompt,              // 用户提示
    output_type: outputType = "png",      // 输出类型，默认为PNG
    file_name: fileName,                  // 输出文件名
    task_type: taskType = "visualization", // 任务类型，默认为可视化
    insights_id: insightsId = [],          // 见解ID数组，默认为空
    language = "en",                      // 语言，默认为英语
  } = inputData;
  
  // 从 LLM 配置中提取必要的参数
  const { base_url: baseUrl, model, api_key: apiKey } = llm_config;
  
  // 初始化 VMind 实例
  const vmind = new VMind({
    url: `${baseUrl}/chat/completions`,   // API端点
    model,                                // 使用的模型
    headers: {                           // 请求头部
      "api-key": apiKey,                  // 使用API密钥
      Authorization: `Bearer ${apiKey}`,   // 授权头
    },
  });
  
  // 根据任务类型执行不同的操作
  if (taskType === "visualization") {
    // 如果是可视化任务，生成新图表
    res = await generateChart(vmind, {
      dataset,      // 数据集
      userPrompt,   // 用户提示
      directory,    // 目录
      outputType,   // 输出类型
      fileName,     // 文件名
      width,        // 宽度
      height,       // 高度
      language,     // 语言
    });
  } else if (taskType === "insight" && insightsId.length) {
    // 如果是见解任务且有选择的见解ID，更新现有图表
    res = await updateChartWithInsight(vmind, {
      directory,    // 目录
      fileName,     // 文件名
      outputType,   // 输出类型
      insightsId,   // 见解ID数组
    });
  }
  
  // 将结果输出到标准输出
  console.log(JSON.stringify(res));
}

// 执行主函数
executeVMind();
