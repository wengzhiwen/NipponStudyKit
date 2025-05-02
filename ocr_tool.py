import base64
import os
import time

from agents import Agent, Runner, TResponseInputItem
from logging_config import setup_logger

logger = setup_logger(logger_name="OCRTool", log_level="INFO")


class OCRTool:
    """OCR工具类，用于处理图像OCR识别"""

    def __init__(self, ocr_model_name: str = "gpt-4o-mini"):
        """初始化OCR工具类
        
        OCR工具需要在环境变量中设置OPENAI_API_KEY请确认.env文件中已经设置
        """
        if not os.getenv("OPENAI_API_KEY"):
            raise ValueError("OPENAI_API_KEY 环境变量未设置")

        self.model_name = ocr_model_name

    def _perform_ocr(self, image_path):
        """使用OpenAI Vision模型进行OCR"""
        logger.info(f"使用OpenAI Vision对{image_path}进行OCR...")

        try:
            ocr_agent = Agent(name="OCR Agent",
                              instructions="""你是一个专业的OCR文本识别专家。
请仔细观察图像中的文本内容，并尽可能准确地提取所有文本和表格。
输出应该保持原始文本的格式和结构，包括格式（加粗、斜体、下划线、表格）、段落和标题。
针对表格的提取，可以采用markdown的语法来表示，特别注意表格的列数（有些表格首行有空单元格，也要算作一列）

请注意：
1. 仅提取图像中的实际文本，不要添加任何解释或说明
2. 保持原始日语文本，不要翻译
3. 尽可能保持原始格式结构，特别是表格，要准确的提取表格中的所有文字
4. 忽略所有的纯图形内容（比如：logo，地图等，包括页面上的水印）
5. 忽略所有的页眉和页脚，但保留原文中每页的页码（如果原文中有），严格按照原文中标注的页码来提取（不论原文是否有错）
6. 如果遇到空白页或整页都是没有意义的内容，请返回：EMPTY_PAGE
""",
                              model=self.model_name)

            with open(image_path, 'rb') as f:
                image_data = f.read()
            base64_image = base64.b64encode(image_data).decode('utf-8')

            input_items: list[TResponseInputItem] = [{
                "role":
                "user",
                "content": [{
                    "type": "input_text",
                    "text": "请识别这个图像中的所有文字内容，保持原始格式。"
                }, {
                    "type": "input_image",
                    "image_url": f"data:image/png;base64,{base64_image}"
                }]
            }]

            result = Runner.run_sync(ocr_agent, input_items)

            if not result.final_output.strip():
                raise ValueError("OpenAI Vision未能提取任何文本")

            return result.final_output
        except Exception as e:
            logger.error(f"OpenAI Vision OCR错误: {e}")
            return None  # 返回None而不是空字符串，表示OCR失败

    def _format_to_markdown(self, text_content, image_path):
        """使用OpenAI格式化OCR文本为markdown"""
        logger.info("格式化OCR文本为markdown...")

        # 创建格式化代理
        format_agent = Agent(name="Markdown Formatter",
                             instructions="""你是一个专业的文本格式化专家。
请将OCR出来的文本重新组织成Markdown格式。
输出应该保持原始文本的格式和结构，包括格式（加粗、斜体、下划线、表格）、段落和标题。

请注意：
1. 保持除非OCR结果有明显的识别错误，否则不要修改OCR结果，更不要添加任何解释或说明，也不要进行归纳总结
2. 保持原始日语文本，不要翻译
3. 尽可能保持原始格式结构，特别是表格，要准确的提取不同的
4. OCR时已经要求忽略页眉、页脚，仅保留原文中的页码，请保持
如有原文有页码的话，页码一律独立一行，前后空行，以 【数字 + ページ】 的形式表现
5. OCR时已经要求忽略所有的纯图形内容（比如：logo，地图等，包括页面上的水印），请保持；特别注意不要以Base64的编码来处理任何纯图形内容
6. 如果文本中包含大量无意义的信息，请删除他们
7. 对于像目录这样的内容，可能会包含大量的「..........」或事「-------------」这样的符号，如果只是为了表达页码的话请将其长度现在6个点也就是「......」
8. 如果有URL信息，请保持完整的URL信息，但不要用Markdown的链接格式来处理URL，保留纯文本状态即可
9. 如果遇到空白页或整页都是没有意义的内容，请返回：EMPTY_PAGE
10. 结果会被直接保存为md文件，所以请不要添加任何```markdown```之类的定界符

关于Markdown的语法格式，特别注意以下要求：
1. 表格前后的空行要保留
2. 列表前后的空行要保留
3. 标题前后的空行要保留
4. 表格的排版（特别是合并单元格）要与原文（图片）完全一致
5. 根据Markdown的语法，需要添加空格的地方，请务必添加空格；但不要在表格的单元格内填充大量的空格，需要的话填充一个空格即可
总之，要严格的践行Markdown的语法要求，不要只是看上去像，其实有不少语法错误
""",
                             model=self.model_name)

        with open(image_path, 'rb') as f:
            image_data = f.read()
        base64_image = base64.b64encode(image_data).decode('utf-8')

        input_items = [{
            "role":
            "user",
            "content": [{
                "type": "input_text",
                "text": f"请将以下OCR文本重新组织成Markdown格式：\n\n{text_content} \n\n-----------\n\n务必尊从系统提示词中的要求来进行格式化。"
            }, {
                "type": "input_image",
                "image_url": f"data:image/png;base64,{base64_image}"
            }]
        }]

        result = Runner.run_sync(format_agent, input_items)

        result.final_output = result.final_output.replace("``` Markdown", "")
        result.final_output = result.final_output.replace("``` markdown", "")
        result.final_output = result.final_output.replace("```Markdown", "")
        result.final_output = result.final_output.replace("```markdown", "")
        result.final_output = result.final_output.replace("```", "")
        return result.final_output

    def img2md(self, image_path) -> str:
        """
        将图像转换为markdown
        
        注意，所有的原始错误将被直接传给调用者，不会进行任何的捕获
        
        Args:
            image_path (str): 图像路径

        Returns:
            str: 转换后的markdown文本
        """
        start_time = time.time()

        ocr_start = time.time()
        text_content = self._perform_ocr(image_path)
        ocr_time = time.time() - ocr_start

        format_start = time.time()
        result = self._format_to_markdown(text_content, image_path)
        format_time = time.time() - format_start

        total_time = time.time() - start_time
        logger.info(f"OCR步骤耗时: {ocr_time:.2f}秒，格式化步骤耗时: {format_time:.2f}秒，总耗时: {total_time:.2f}秒")

        return result
