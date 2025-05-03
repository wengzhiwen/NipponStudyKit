import os
import time
import json
import re

from agents import Agent, Runner
from logging_config import setup_logger

logger = setup_logger(logger_name="RenameAnalysisTool", log_level="INFO")


class RenameAnalysisTool:
    """重命名分析工具类，用于分析招生信息并生成文件夹名"""

    def __init__(self, model_name: str = "gpt-4o"):
        """初始化重命名分析工具类
        
        分析工具需要在环境变量中设置OPENAI_API_KEY请确认.env文件中已经设置
        """
        if not os.getenv("OPENAI_API_KEY"):
            raise ValueError("OPENAI_API_KEY 环境变量未设置")

        self.model_name = model_name

    def _analyze_markdown(self, md_content: str) -> str:
        """使用OpenAI分析招生信息"""
        logger.info("分析招生信息...")

        analyze_agent = Agent(
            name="Admission Analyzer",
            instructions="""你是一位专业的大学招生信息分析专家，擅长分析大学招生信息。
请根据输入的Markdown文本进行分析并提取以下信息，以JSON格式返回。

请严格按照以下JSON格式返回（必须是合法的JSON格式，不要添加任何其他说明文字）：
{
    "大学名称": "大学的日语全名",
    "报名截止日期": "YYYY/MM/DD格式，如果有多个日期选择最晚的，无法确认则返回2099/01/01"
}

请注意：
1. 大学名称必须是完整的日语名称，如果输入的文档是该大学的某一学部专用的信息，则返回大学日语全称及学部日语全称，如〇〇大学〇〇学部
2. 报名截止日期必须是YYYY/MM/DD格式
3. 如果有多个报名截止日期，选择最晚的那个
4. 如果无法确定报名截止日期，返回2099/01/01
5. 返回的必须是合法的JSON格式，不要添加任何其他说明文字
""",
            model=self.model_name
        )

        input_items = [{
            "role": "user",
            "content": md_content + "\n\n请确保返回的是合法的JSON格式，不要包含任何其他说明文字。"
        }]

        result = Runner.run_sync(analyze_agent, input_items)
        return result.final_output

    def md2report(self, md_content: str) -> tuple[str, str]:
        """
        将日语Markdown转换为大学名称和报名截止日期
        
        注意，所有的原始错误将被直接传给调用者，不会进行任何的捕获
        
        Args:
            md_content (str): 日语Markdown文本

        Returns:
            tuple[str, str]: (大学名称, 报名截止日期)
        """
        start_time = time.time()

        analyze_start = time.time()
        result = self._analyze_markdown(md_content)
        analyze_time = time.time() - analyze_start

        # 验证返回的是否为有效的JSON
        try:
            info_dict = json.loads(result)
        except json.JSONDecodeError as e:
            # 如果不是有效的JSON，尝试提取JSON部分
            json_match = re.search(r'\{.*\}', result, re.DOTALL)
            if json_match:
                json_str = json_match.group()
                try:
                    info_dict = json.loads(json_str)
                except json.JSONDecodeError as exc:
                    logger.error(f"无法提取有效的JSON: {result}")
                    raise ValueError("无法提取有效的JSON") from exc
            else:
                logger.error(f"响应中没有有效的JSON: {result}")
                raise ValueError("响应中没有有效的JSON") from e

        # 验证必要的字段是否存在
        if "大学名称" not in info_dict or "报名截止日期" not in info_dict:
            raise ValueError("JSON中缺少必要的字段：大学名称或报名截止日期")

        total_time = time.time() - start_time
        logger.info(f"分析步骤耗时: {analyze_time:.2f}秒，总耗时: {total_time:.2f}秒")

        return info_dict["大学名称"], info_dict["报名截止日期"]
