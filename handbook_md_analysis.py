"""
招生信息Markdown文档分析
"""
# pylint: disable=invalid-name
import argparse
import datetime
import os
import sys
import glob
from typing import List

from agents import Agent, Runner, trace
from dotenv import load_dotenv
from logging_config import setup_logger

# 设置日志记录器
logger = setup_logger(logger_name="md_analysis", log_level="INFO")


class MDAnalysisTools:
    """Markdown分析工具类"""

    def __init__(self):
        """初始化工具类"""

    def load_markdown_file(self, markdown_file_path: str) -> str:
        """加载Markdown文件内容"""
        try:
            with open(markdown_file_path, "r", encoding="utf-8") as f:
                md_content = f.read()
            logger.debug(f"成功加载文件：{markdown_file_path}")
            return md_content
        except FileNotFoundError:
            logger.error(f"文件不存在：{markdown_file_path}")
            return "Markdown文件不存在，请检查文件路径是否正确。"
        except Exception as e:
            logger.error(f"读取文件时发生错误：{markdown_file_path}, 错误：{e}")
            return f"读取Markdown文件时发生错误：{e}"

    def save_report_to_file(self, report_content: str, report_file_path: str) -> str:
        """保存报告到文件"""
        try:
            # 如果文件夹不存在则创建文件夹
            os.makedirs(os.path.dirname(report_file_path), exist_ok=True)

            with open(report_file_path, "w", encoding="utf-8") as f:
                f.write(report_content)

            logger.info(f"报告已保存到：{report_file_path}")
            return "保存成功"
        except Exception as e:
            logger.error(f"保存报告时发生错误：{report_file_path}, 错误：{e}")
            return f"保存报告时发生错误：{e}"


class ServiceConfig:
    """配置类，用于管理所有配置信息（单例模式）"""
    _instance = None
    _initialized = False

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(ServiceConfig, cls).__new__(cls)
        return cls._instance

    def __init__(self):
        if self._initialized:
            return

        load_dotenv()

        # 加载模型配置
        self.model = os.getenv("OPENAI_MODEL", "gpt-4o")
        self.model_mini = os.getenv("OPENAI_MODEL_MINI", "gpt-4o-mini")

        # 检查配置信息
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            logger.error("OPENAI_API_KEY 环境变量未设置")
            raise ValueError("未设置OpenAI API密钥。请在.env文件中设置OPENAI_API_KEY环境变量。")

        # 检查并加载翻译术语文件
        translate_terms_file = 'translate_terms.txt'
        if not os.path.exists(translate_terms_file):
            raise ValueError(f"错误：翻译术语文件 {translate_terms_file} 不存在")

        with open(translate_terms_file, 'r', encoding='utf-8') as f:
            self.translate_terms = f.read().strip()
            if not self.translate_terms:
                raise ValueError(f"错误：翻译术语文件 {translate_terms_file} 为空")

        logger.info(f'SETUP INFO = MODEL: {self.model}, MODEL_MINI: {self.model_mini}')
        self._initialized = True


class MDAnalysisService:
    """Markdown分析服务类，负责处理所有Markdown文档分析相关的功能"""

    def __init__(self, config: ServiceConfig):
        """初始化服务
        
        Args:
            config (ServiceConfig): 服务配置
        """
        self.config = config
        self.tools = MDAnalysisTools()

        # 读取分析问题
        try:
            with open("md_analysis_questions.txt", "r", encoding="utf-8") as f:
                self.questions = f.read()
        except FileNotFoundError as e:
            logger.error("无法找到md_analysis_questions.txt文件")
            raise ValueError("找不到分析问题文件(md_analysis_questions.txt)。请确保该文件存在于程序目录中。") from e
        except Exception as e:
            logger.error(f"读取md_analysis_questions.txt文件时发生错误: {e}")
            raise ValueError(f"读取分析问题文件时发生问题: {e}") from e

        logger.debug(f"准备针对文档对以下问题进行分析: \n{self.questions}")

        # 初始化代理
        self._init_agents()

    def _init_agents(self):
        """初始化所有代理"""
        # 创建分析代理
        self.markdown_analyzer_agent = Agent(name="Markdown_Analyzer_Agent",
                                             model=self.config.model,
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
{self.questions}

请注意：
 - 用户需要的是完整的分析结果，不要仅仅提供原文的引用
 - 不要进行寒暄，直接开始工作
 - 不要在回答中包含任何额外的信息，只需要直接开始回答问题即可
 - 每一个问题都要回答，如果信息不确定，就明确指出"无法确定"，不要跳过任何问题
 - 所有的问题都请针对'打算报考学部（本科）的外国人留学生'的状况来回答，不要将其他招生对象的情况包含进来

{self.config.translate_terms}
""")

        # 创建审核代理
        self.review_agent = Agent(name="Review_Agent",
                                  model=self.config.model,
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

{self.config.translate_terms}
""")

        # 创建报告生成代理
        self.report_agent = Agent(name="Report_Agent",
                                  model=self.config.model_mini,
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
""")

        # 创建编排代理
        self.orchestrator_agent = Agent(name="Orchestrator_Agent",
                                        model=self.config.model,
                                        instructions="你是一个工作流编排代理，负责协调招生信息文档分析、审核和报告生成的整个流程。根据用户提供的文档内容，选择合适的工具执行分析流程。",
                                        tools=[
                                            self.markdown_analyzer_agent.as_tool(tool_name="analyze_markdown", tool_description="分析日本大学招生Markdown文档并回答特定问题"),
                                            self.review_agent.as_tool(tool_name="review_analysis", tool_description="审核分析结果，确保其准确性和质量"),
                                            self.report_agent.as_tool(tool_name="generate_report", tool_description="将审核后的分析结果整理成最终的Markdown格式报告")
                                        ])

    def find_markdown_files(self, base_folder: str, review_mode: bool = False) -> List[str]:
        """在指定文件夹中查找需要处理的Markdown文件
        
        Args:
            base_folder (str): 基础文件夹路径
            review_mode (bool): 是否为review模式，默认为False
        """
        base_dirs = glob.glob(base_folder)
        md_files = []

        for base_dir in base_dirs:
            for root, _, files in os.walk(base_dir):
                for file in files:
                    if file.endswith(".md"):
                        # 跳过scan_开头的文件
                        if file.startswith("scan_"):
                            logger.debug(f"跳过scan_开头的文件：{file}")
                            continue

                        if "_中文" not in file and "_report" not in file:
                            full_path = os.path.join(root, file)

                            if review_mode:
                                # 检查是否存在对应的report文件
                                report_file = full_path.replace(".md", "_report.md")
                                if os.path.exists(report_file):
                                    # 检查report文件的行数
                                    with open(report_file, 'r', encoding='utf-8') as f:
                                        line_count = sum(1 for _ in f)
                                    if line_count >= 10:
                                        logger.info(f"跳过已有完整报告的文件：{full_path}")
                                        continue

                            md_files.append(full_path)

        logger.info(f"共有{len(md_files)}个Markdown文件需要处理...")
        return md_files

    def backup_existing_report(self, output_file_path: str) -> None:
        """如果报告文件已存在，将其备份"""
        if os.path.exists(output_file_path):
            bak_file_path = output_file_path + "." + datetime.datetime.now().strftime("%Y%m%d%H%M%S") + ".bak"
            os.rename(output_file_path, bak_file_path)

    def process_single_file(self, markdown_file_path: str) -> bool:
        """处理单个Markdown文件
        
        Args:
            markdown_file_path (str): Markdown文件路径
            
        Returns:
            bool: 处理是否成功
        """
        logger.info(f"开始处理：{markdown_file_path}")
        start_time = datetime.datetime.now()

        try:
            # 1. 加载Markdown文件内容
            md_content = self.tools.load_markdown_file(markdown_file_path)

            # 检查内容是否为错误消息
            if md_content.startswith("Markdown文件不存在") or md_content.startswith("读取Markdown文件时发生错误"):
                logger.error(f"无法加载文件内容: {md_content}")
                return False

            # 检查文件内容是否为空
            if not md_content.strip():
                logger.warning(f"文件内容为空：{markdown_file_path}")
                return False

            # 2. 准备输出文件路径
            report_file_path = markdown_file_path.replace(".md", "_report.md")
            try:
                self.backup_existing_report(report_file_path)
            except Exception as e:
                logger.warning(f"备份已有报告失败，将覆盖原文件：{e}")

            # 3. 构建初始提示
            logger.debug(f"文件大小: {len(md_content)} 字符")
            initial_prompt = f"""请根据接下来提供的日本大学招生信息Markdown文档内容，对以下问题进行分析：
{self.questions}

请完成以下三个步骤:
1. 使用analyze_markdown工具分析文档内容
2. 使用review_analysis工具对分析结果进行审核校对
3. 使用generate_report工具生成最终Markdown格式报告

以下是要被分析的文档内容:
{md_content}
"""

            # 4. 使用trace捕获整个流程
            with trace("招生信息文档分析"):
                try:
                    # 运行编排代理
                    logger.debug("开始运行AI代理分析文档...")
                    result = Runner.run_sync(self.orchestrator_agent, initial_prompt)

                    # 检查结果是否有效
                    if not result or not hasattr(result, 'final_output') or not result.final_output:
                        logger.error(f"AI分析失败：返回结果无效 - {markdown_file_path}")
                        return False

                    # 保存最终报告
                    final_report = result.final_output
                    save_result = self.tools.save_report_to_file(final_report, report_file_path)

                    if save_result != "保存成功":
                        logger.error(f"保存报告失败：{save_result}")
                        return False

                except Exception as e:
                    logger.error(f"AI代理处理过程出错：{markdown_file_path} - {str(e)}")
                    return False

            # 5. 计算处理时间并记录
            end_time = datetime.datetime.now()
            process_time = (end_time - start_time).total_seconds()
            logger.info(f"处理完成：{markdown_file_path} - 耗时: {process_time:.2f}秒")
            return True

        except Exception as e:
            logger.error(f"处理文件时发生未预期错误：{markdown_file_path} - {str(e)}")
            return False

    def process_all_files(self, base_folder: str, review_mode: bool = False) -> None:
        """处理所有Markdown文件
        
        Args:
            base_folder (str): 基础文件夹路径
            review_mode (bool): 是否为review模式，默认为False
        """
        # 查找所有需要处理的Markdown文件
        md_files = self.find_markdown_files(base_folder, review_mode)

        if not md_files:
            logger.warning(f"在{base_folder}中未找到需要处理的Markdown文件")
            return

        # 线性处理每个文件
        success_count = 0
        failed_files = []

        for i, file_path in enumerate(md_files, 1):
            logger.info(f"处理文件 [{i}/{len(md_files)}]: {file_path}")
            success = self.process_single_file(file_path)

            if success:
                success_count += 1
            else:
                failed_files.append(file_path)

        # 汇总处理结果
        if failed_files:
            logger.warning(f"处理完成：共 {len(md_files)} 个文件，成功 {success_count} 个，失败 {len(failed_files)} 个")
            for fail_file in failed_files:
                logger.warning(f"失败文件：{fail_file}")
        else:
            logger.info(f"处理完成：全部 {len(md_files)} 个文件处理成功")


def main(base_folder: str, review_mode: bool) -> None:
    """主函数，协调整个分析过程
    
    Args:
        base_folder (str): 要处理的文件夹路径
        review_mode (bool): 是否为review模式，默认为False
    """
    try:
        # 初始化配置
        config = ServiceConfig()

        # 创建服务实例
        service = MDAnalysisService(config)

        # 处理所有文件
        service.process_all_files(base_folder, review_mode)
    except ValueError as e:
        # 处理已知的配置和初始化错误
        logger.error(f"程序初始化失败: {e}")
        sys.exit(1)
    except Exception as e:
        # 处理未预期的运行时错误
        logger.error(f"程序运行过程中发生未预期的错误: {e}")
        sys.exit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='招生信息Markdown文档分析')
    parser.add_argument('input_folder', nargs='?', default="pdf_with_md", help='保存每个学校的资料文件夹的根目录。如果不指定，将使用默认值：pdf_with_md')
    parser.add_argument('--review', action='store_true', help='review模式：只处理没有报告或报告内容少于10行的文件')
    args = parser.parse_args()

    input_folder = args.input_folder

    if not os.path.exists(input_folder):
        logger.error(f'指定的文件夹不存在：{input_folder}')
        print('Usage: python md_analysis.py <input_folder> [--review]')
        sys.exit(1)

    logger.info(f"开始处理：{input_folder}")
    main(input_folder, args.review)
