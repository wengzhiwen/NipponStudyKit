import os
import time

from agents import Agent, Runner
from logging_config import setup_logger

logger = setup_logger(logger_name="TranslateTool", log_level="INFO")


class TranslateTool:
    """翻译工具类，用于处理日语到中文的翻译"""

    def __init__(self, model_name: str = "gpt-4o", translate_terms: str = ""):
        """初始化翻译工具类
        
        翻译工具需要在环境变量中设置OPENAI_API_KEY请确认.env文件中已经设置
        """
        if not os.getenv("OPENAI_API_KEY"):
            raise ValueError("OPENAI_API_KEY 环境变量未设置")

        self.model_name = model_name
        self.translate_terms = translate_terms

    def _translate_markdown(self, md_content: str) -> str:
        """使用OpenAI翻译日语Markdown内容为中文"""
        logger.info("翻译Markdown内容为中文...")

        translator_agent = Agent(
            name="Translator",
            instructions=f"""你是一位专业的日语翻译专家，擅长将日语文本翻译成中文。
请将用户输入的日语Markdown文本翻译成中文，要求：
1. 保持原有的Markdown格式，标题、列表、表格、段落等格式要与原文完全一致
2. 翻译要准确、通顺，符合中文表达习惯
3. 专业术语要准确翻译
4. 不要添加任何额外的说明或注释
5. 直接返回翻译结果，不需要其他解释
6. 结果会被直接保存为md文件，所以请不要添加任何```markdown```之类的定界符
7. 针对学部和专业的名称，尽可能使用符合中文的表达方式来翻译，很难翻译准确的可以采用"将日文汉字变成中文汉字，假名变成英语"的方式来翻译。
   但是注意上下文中同一个学部和专业的名称，尽可能使用相同的翻译方式。
8. 所有第三方考试的名称，比如：EJU，TOEFL，TOEIC，等，使用统一的英语缩写来翻译。
9. 完整翻译全文，不要遗漏任何内容，不要添加任何解释或说明也不要进行归纳总结

{self.translate_terms}
""",
            model=self.model_name
        )

        input_items = [{
            "role": "user",
            "content": f"""请将以下日语Markdown文本翻译成中文：

{md_content}

-----------

请直接返回翻译结果。务必尊从系统提示词中的要求来进行翻译。"""
        }]

        result = Runner.run_sync(translator_agent, input_items)
        return result.final_output

    def md2zh(self, md_content: str) -> str:
        """
        将日语Markdown转换为中文Markdown
        
        注意，所有的原始错误将被直接传给调用者，不会进行任何的捕获
        
        Args:
            md_content (str): 日语Markdown文本

        Returns:
            str: 转换后的中文Markdown文本
        """
        start_time = time.time()

        translate_start = time.time()
        result = self._translate_markdown(md_content)
        translate_time = time.time() - translate_start

        total_time = time.time() - start_time
        logger.info(f"翻译步骤耗时: {translate_time:.2f}秒，总耗时: {total_time:.2f}秒")

        return result
