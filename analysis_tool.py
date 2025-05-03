import os
import time

from agents import Agent, Runner
from logging_config import setup_logger

logger = setup_logger(logger_name="AnalysisTool", log_level="INFO")


class AnalysisTool:
    """分析工具类，用于处理Markdown文档分析"""

    def __init__(self, model_name: str = "gpt-4o", analysis_questions: str = "", translate_terms: str = ""):
        """初始化分析工具类
        
        分析工具需要在环境变量中设置OPENAI_API_KEY请确认.env文件中已经设置
        """
        if not os.getenv("OPENAI_API_KEY"):
            raise ValueError("OPENAI_API_KEY 环境变量未设置")

        self.model_name = model_name
        self.analysis_questions = analysis_questions
        self.translate_terms = translate_terms

    def _analyze_markdown(self, md_content: str) -> str:
        """使用OpenAI分析Markdown内容"""
        logger.info("分析Markdown内容...")

        analyzer_agent = Agent(name="Markdown_Analyzer_Agent",
                               instructions=f"""你是一位严谨的日本留学信息专家,你根据用户最初输入的完整Markdown内容继续以下工作流：
0. Markdown原文可能很长，因为有些Markdown包含了大量和留学生入学无关的信息，可以先将这部分信息排除再进行分析
 - 但是要注意，有些学校可能不会直接使用'外国人留学生'这样的说法，但他们事实上招收留学生，如：
   - 允许没有日本国籍的人报名
   - 允许报名者在海外接受中小学教育
   - 允许使用EJU（日本留学生考试）的成绩报名
 - 有些学校的部分专业对外国人和日本人一视同仁，允许日本人报名的专业同时也允许外国人报名，这类专业视同招收留学生
1. 仔细分析该文档内容,并对以下问题逐一用中文给出准确的回答。如果信息不确定,请明确指出。
    - 回答问题时请务必按照问题的顺序逐一回答（在每个问题的回答后添附相关的原文引用）
    - 输出的结果中不需要包含任何额外的信息，只需要回答问题即可
    - 输出的结果中不要包含任何文档路径相关的信息
    - 请严格按照文档来回答问题，不要进行任何额外的推测或猜测！
2. 分析报告包含每个问题以及对应的回答，请严格按照问题顺序依次回答。
3. 请仅将你的分析结果的正文直接返回，不要带有任何的说明性文字。

你要回答的问题是：
{self.analysis_questions}

请注意：
 - 用户需要的是完整的分析结果，不要仅仅提供原文的引用
 - 不要进行寒暄，直接开始工作
 - 不要在回答中包含任何额外的信息，只需要直接开始回答问题即可
 - 每一个问题都要回答，如果信息不确定，就明确指出"无法确定"，不要跳过任何问题
 - 所有的问题都请针对'打算报考学部（本科）的外国人留学生'的状况来回答，不要将其他招生对象的情况包含进来

{self.translate_terms}
""",
                               model=self.model_name)

        input_items = [{"role": "user", "content": f"""请根据以下Markdown内容进行分析：

{md_content}

-----------

请直接返回分析结果。务必尊从系统提示词中的要求来进行分析。"""}]

        result = Runner.run_sync(analyzer_agent, input_items)
        return result.final_output

    def _review_analysis(self, md_content: str, analysis_result: str) -> str:
        """使用OpenAI审核分析结果"""
        logger.info("审核分析结果...")

        review_agent = Agent(name="Review_Agent",
                             instructions=f"""你是一位严谨的校对人员,你根据用户输入的Markdown原文对用户输入的分析结果进行校对。
你的工作流程如下：
0. Markdown原文可能很长，因为有些Markdown包含了大量和留学生入学无关的信息，可以先将这部分信息排除再进行分析
1. 逐一核对,针对其中不相符的情况直接对分析结果进行修正。
    - 不论你是否发现错误，请输出修正后的完整分析结果，每个问题所关联的原文的引用需要保留；
    - 请严格按照用户输入的原始文档来校对和修正分析结果，不要进行任何额外的推测或猜测！
2. 确认是否有语法错误，针对其中的中文部分和日语部分的语法错误分别进行修正。
3. 请仅将你的分析结果的正文直接返回，不要带有任何的说明性文字。

请注意：
 - 并不是要你重新回答问题，而是要你根据原始文档来校对分析结果
 - 用户需要的是完整的分析结果，不要仅仅提供原文的引用
 - 不要进行寒暄，直接开始工作。
 - 所有的问题都是针对'打算报考学部（本科）的外国人留学生'的状况来回答的，请不要将其他招生对象的情况包含进来

{self.translate_terms}
""",
                             model=self.model_name)

        input_items = [{
            "role": "user",
            "content": f"""请根据以下原始文档内容对分析结果进行校对：

原始文档：
{md_content}

分析结果：
{analysis_result}

-----------

请直接返回校对后的分析结果。务必尊从系统提示词中的要求来进行校对。"""
        }]

        result = Runner.run_sync(review_agent, input_items)
        return result.final_output

    def _generate_report(self, analysis_result: str) -> str:
        """使用OpenAI生成最终报告"""
        logger.info("生成最终报告...")

        report_agent = Agent(name="Report_Agent",
                             instructions="""你是专业的编辑，你的工作是将用户输入的分析结果整理成Markdown格式的最终报告。
你的工作流程如下：
1. 基于用户输入的分析结果，整理成Markdown格式的最终报告，不需要再对Markdown文档的原文进行分析，也不要进行任何推测；
    - 报告标题：
        - 报告H1标题为：「大学名称」私费外国人留学生招生信息分析报告
        - 接下来每个问题都是一个H2标题，问题的回答紧跟在H2标题下
    - 每一个问题本身（文字）进行适当缩减，特别是"该文档…"之类的文字都要进行缩减，但保持顺序不变；
    - 最终的报告中不需要包含任何文档路径、分析时间、特别提示等额外信息；
    - 如果问题的回答有关联原文的引用的，保留引用内容，如果没有的也不需要额外添加说明；
    - 你整理的最终报告用于给人类用户阅读，请尽可能使用表格、加粗、斜体等Markdown格式来使报告更易读；
2. 针对每一个问题的回答如果设计多个学科专业分别作答的，可以考虑使用表格来呈现

请注意：
    - 不要在Markdown文档的开头或结尾再附加其他的说明性文字.
    - 报告中不应该包含任何的链接。
    - 不要在你输出的内容前后再额外使用"```markdown"之类的定界符！

关于Markdown的语法格式，特别注意以下要求：
1. 表格前后的空行要保留
2. 列表前后的空行要保留
3. 标题前后的空行要保留
4. 表格的排版（特别是合并单元格）要与原文（图片）完全一致
5. 根据Markdown的语法，需要添加空格的地方，请务必添加空格；但不要在表格的单元格内填充大量的空格，需要的话填充一个空格即可
总之，要严格的践行Markdown的语法要求，不要只是看上去像，其实有不少语法错误
""",
                             model=self.model_name)

        input_items = [{"role": "user", "content": f"""请将以下分析结果整理成Markdown格式的最终报告：

{analysis_result}

-----------

请直接返回最终报告。务必尊从系统提示词中的要求来生成报告。"""}]

        result = Runner.run_sync(report_agent, input_items)
        return result.final_output

    def md2report(self, md_content: str) -> str:
        """
        将Markdown文档转换为分析报告
        
        注意，所有的原始错误将被直接传给调用者，不会进行任何的捕获
        
        Args:
            md_content (str): Markdown文本

        Returns:
            str: 转换后的分析报告
        """
        start_time = time.time()

        # 1. 分析Markdown内容
        analysis_start = time.time()
        analysis_result = self._analyze_markdown(md_content)
        analysis_time = time.time() - analysis_start

        # 2. 审核分析结果
        review_start = time.time()
        reviewed_result = self._review_analysis(md_content, analysis_result)
        review_time = time.time() - review_start

        # 3. 生成最终报告
        report_start = time.time()
        final_report = self._generate_report(reviewed_result)
        report_time = time.time() - report_start

        total_time = time.time() - start_time
        logger.info(f"分析步骤耗时: {analysis_time:.2f}秒，审核步骤耗时: {review_time:.2f}秒，报告生成步骤耗时: {report_time:.2f}秒，总耗时: {total_time:.2f}秒")

        return final_report
