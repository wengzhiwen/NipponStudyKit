"""
招生信息Markdown文档分析
"""
# pylint: disable=invalid-name
import argparse
import sys
import datetime
import os
import glob
import logging
from typing import List, Dict

from autogen import (
    AfterWorkOption,
    ConversableAgent,
    LLMConfig,
    initiate_swarm_chat,
    SwarmResult,
    gather_usage_summary,
)
from dotenv import load_dotenv


class MDAnalysisTools:
    """Markdown分析工具类"""

    def __init__(self, logger: logging.Logger):
        """初始化工具类
        
        Args:
            logger (logging.Logger): 日志记录器
        """
        self.logger = logger

    def load_markdown_file(self, markdown_file_path: str) -> str:
        """加载Markdown文件内容"""
        try:
            with open(markdown_file_path, "r", encoding="utf-8") as f:
                md_content = f.read()
            self.logger.debug(f"成功加载文件：{markdown_file_path}")
            return md_content
        except FileNotFoundError:
            self.logger.error(f"文件不存在：{markdown_file_path}")
            return "Markdown文件不存在，请检查文件路径是否正确。"
        except Exception as e:
            self.logger.error(f"读取文件时发生错误：{markdown_file_path}, 错误：{e}")
            return f"读取Markdown文件时发生错误：{e}"

    def save_report_to_file(self, report_content: str, report_file_path: str) -> str:
        """保存报告到文件"""
        try:
            # 如果文件夹不存在则创建文件夹
            os.makedirs(os.path.dirname(report_file_path), exist_ok=True)

            with open(report_file_path, "w", encoding="utf-8") as f:
                f.write(report_content)

            self.logger.info(f"报告已保存到：{report_file_path}")
            return "保存成功"
        except Exception as e:
            self.logger.error(f"保存报告时发生错误：{report_file_path}, 错误：{e}")
            return f"保存报告时发生错误：{e}"


class ServiceConfig:
    """配置类，用于管理所有配置信息"""

    def __init__(self):
        load_dotenv()

        # 加载LLM配置文件路径
        self.llm_config_path = os.getenv("LLM_CONFIG_PATH", "config/llm_config.json")

        # 检查配置文件是否存在
        if not os.path.exists(self.llm_config_path):
            raise FileNotFoundError(f"LLM配置文件不存在: {self.llm_config_path}")

        # 加载LLM配置
        self.llm_config = self.load_config("STD")
        self.llm_config_mini = self.load_config("LOW_COST")

    def load_config(self, model_tag: str = "STD") -> LLMConfig:
        """从配置文件加载LLM配置"""
        filter_dict = {"tags": [model_tag]}
        return LLMConfig.from_json(path=self.llm_config_path).where(**filter_dict)


class MDAnalysisService:
    """Markdown分析服务类，负责处理所有Markdown文档分析相关的功能"""

    def __init__(self, config: ServiceConfig, logger: logging.Logger):
        """初始化服务
        
        Args:
            config (ServiceConfig): 服务配置
            logger (logging.Logger): 日志记录器
        """
        self.config = config
        self.logger = logger
        self.tools = MDAnalysisTools(logger)

        # 初始化所有agent为None
        self.markdown_analyzer_agent: ConversableAgent = None
        self.review_agent: ConversableAgent = None
        self.report_agent: ConversableAgent = None

    def init_agents(self) -> None:
        """初始化所有需要的agents"""

        def finish_report(report_content: str, context_variables: Dict) -> SwarmResult:
            """报告生成完成后的回调函数"""
            report_file_path = context_variables["report_file_path"]
            self.tools.save_report_to_file(report_content, report_file_path)
            return SwarmResult(agent=AfterWorkOption.TERMINATE, context_variables=context_variables)

        # 创建分析agent
        self.markdown_analyzer_agent = ConversableAgent(
            name="Markdown_Analyzer_Agent",
            llm_config=self.config.llm_config,
            human_input_mode="NEVER",
            description="日本大学留学生招生信息分析Agent",
            system_message="""你是一位严谨的日本留学信息专家,你根据用户最初输入的完整Markdown内容继续以下工作流：
0. Markdown原文可能很长，因为有些Markdown包含了大量和留学生入学无关的信息，可以先将这部分信息排除再进行分析
1. 仔细分析该文档内容,并对task中给出的问题逐一用中文给出准确的回答。如果信息不确定,请明确指出。
    - 回答问题时请务必按照问题的顺序逐一回答（每个回答后附上对原文的引用）
    - 输出的结果中不需要包含任何额外的信息，只需要回答问题即可
    - 输出的结果中不要包含任何文档路径相关的信息
    - 请严格按照文档来回答问题，不要进行任何额外的推测或猜测！
2. 请仅将你的分析结果的正文直接返回，不要带有任何的说明性文字。

请注意：
 - 用户需要的是完整的分析结果，不要仅仅提供原文的引用
 - 不要进行寒暄，直接开始工作。
 - 不要在回答中包含任何额外的信息，只需要直接开始回答问题即可。""",
        )

        # 创建审核agent
        self.review_agent = ConversableAgent(
            name="Review_Agent",
            llm_config=self.config.llm_config,
            human_input_mode="NEVER",
            description="分析结果检查Agent",
            system_message="""你是一位严谨的校对人员,你根据用户输入的Markdown原文对用户输入的分析结果进行校对。
你的工作流程如下：
0. Markdown原文可能很长，因为有些Markdown包含了大量和留学生入学无关的信息，可以先将这部分信息排除再进行分析
1. 逐一核对,针对其中不相符的情况直接对分析结果进行修正。
    - 不论你是否发现错误，请将修正后的完整分析结果告诉大家，每个问题所关联的原文的引用需要保留；
    - 请严格按照用户输入的文档来校对和修正，不要进行任何额外的推测或猜测！
2. 确认是否有语法错误，针对其中的中文部分和日语部分的语法错误分别进行修正。
3. 请仅将你的分析结果的正文直接返回，不要带有任何的说明性文字。

请注意：
 - 用户需要的是完整的分析结果，不要仅仅提供原文的引用
 - 不要进行寒暄，直接开始工作。
 - 不要在回答中包含任何额外的信息，只需要直接开始回答问题即可。""",
        )

        # 创建报告生成agent
        self.report_agent = ConversableAgent(
            name="Report_Agent",
            llm_config=self.config.llm_config_mini,
            human_input_mode="NEVER",
            description="报告生成Agent",
            system_message="""你是专业的编辑，你的工作是将用户输入的分析结果整理成Markdown格式的最终报告。
你的工作流程如下：
1. 基于用户输入的分析结果，整理成Markdown格式的最终报告，不需要再对Markdown文档的原文进行分析，也不要进行任何推测；
    - 报告标题：
        - 报告H1标题为：「大学名称」私费外国人留学生招生信息分析报告
        - 接下来每个问题都是一个H2标题，问题的回答紧跟在H2标题下
    - 每一个问题本身（文字）进行适当缩减，特别是"该文档…"之类的文字都要进行缩减，但保持顺序不变；
    - 最终的报告中不需要包含任何文档路径、分析时间、特别提示等额外信息；
    - 如果问题的回答有关联原文的引用的，保留引用内容，如果没有的也不需要额外添加说明；
    - 你整理的最终报告用于给人类用户阅读，请尽可能使用表格、加粗、斜体等Markdown格式来使报告更易读；

2. 工作结束后请调用finish_report工具，将最终的报告传递给他。

请注意：
    - 不要在Markdown文档的开头或结尾再附加其他的说明性文字.
    - 不要在你输出的内容前后再额外使用"```markdown"之类的定界符！""",
            functions=[finish_report],
        )

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
                                        self.logger.info(f"跳过已有完整报告的文件：{full_path}")
                                        continue

                            md_files.append(full_path)

        self.logger.info(f"共有{len(md_files)}个Markdown文件需要处理...")
        return md_files

    def backup_existing_report(self, output_file_path: str) -> None:
        """如果报告文件已存在，将其备份"""
        if os.path.exists(output_file_path):
            bak_file_path = output_file_path + "." + datetime.datetime.now().strftime("%Y%m%d%H%M%S") + ".bak"
            os.rename(output_file_path, bak_file_path)

    def process_single_file(self, markdown_file_path: str, questions: str) -> None:
        """处理单个Markdown文件"""
        self.logger.info(f"开始处理：{markdown_file_path}")

        md_content = self.tools.load_markdown_file(markdown_file_path)

        report_file_path = markdown_file_path.replace(".md", "_report.md")
        self.backup_existing_report(report_file_path)

        # 设置输出重定向
        output_dir = os.path.dirname(report_file_path)
        os.makedirs(output_dir, exist_ok=True)
        output_file = os.path.join(output_dir, f"{os.path.basename(report_file_path)}.stdout.log")

        # 保存原始的stdout
        old_stdout = sys.stdout

        try:
            # 重定向stdout到文件
            with open(output_file, 'w', encoding='utf-8') as f:
                sys.stdout = f

                # 第一步：运行markdown_analyzer_agent的分析
                # 准备分析提示
                analysis_prompt = f"""请分析以下Markdown文档内容。
文档内容是日语，但请用简体中文回答以下问题：

{questions}

---
文档内容：

{md_content}

请基于整个文档回答上述问题。
请注意：
1. 回答时请引用原文相关内容；
2. 如果某些问题在文档中确实找不到答案，请明确指出。"""

                chat_result, _, _  = initiate_swarm_chat(
                    initial_agent=self.markdown_analyzer_agent,
                    agents=[self.markdown_analyzer_agent],
                    messages=analysis_prompt,
                    after_work=AfterWorkOption.TERMINATE,
                    max_rounds=2
                )

                analysis_result = chat_result.chat_history[-1]["content"]
                self.logger.info(f"分析结果：{analysis_result[:20]}")

                # 第二步：运行review_agent的审核
                # 准备审核提示
                review_prompt = f"""请审核以下分析结果。
文档内容是日语，分析结果是中文的。

原始文档内容：

{md_content}

---

分析结果：

{analysis_result}

请对上述分析结果进行审核。"""

                chat_result, _, _  = initiate_swarm_chat(
                    initial_agent=self.review_agent,
                    agents=[self.review_agent],
                    messages=review_prompt,
                    after_work=AfterWorkOption.TERMINATE,
                    max_rounds=2
                )

                review_result = chat_result.chat_history[-1]["content"]
                self.logger.info(f"审核结果：{review_result[:20]}")

                # 第三步：运行report_agent的报告生成
                context_variables = {"report_file_path": report_file_path}
                _, _, _  = initiate_swarm_chat(
                    initial_agent=self.report_agent,
                    agents=[self.report_agent],
                    messages=review_result,
                    context_variables=context_variables,
                    max_rounds=4
                )

                # 获取成本信息
                usage_summary = gather_usage_summary([self.markdown_analyzer_agent, self.review_agent, self.report_agent])
                self.logger.debug(f"[cost: {usage_summary['usage_excluding_cached_inference']['total_cost']}]")

        finally:
            # 恢复原始的stdout
            sys.stdout = old_stdout

    def process_all_files(self, base_folder: str, review_mode: bool = False) -> None:
        """处理所有Markdown文件
        
        Args:
            base_folder (str): 基础文件夹路径
            review_mode (bool): 是否为review模式，默认为False
        """
        # 读取分析问题
        with open("md_analysis_questions.txt", "r", encoding="utf-8") as f:
            questions = f.read()

        # 查找所有需要处理的Markdown文件
        md_files = self.find_markdown_files(base_folder, review_mode)

        # 处理每个文件
        for markdown_file_path in md_files:
            # 为每个文件重新初始化agents
            self.init_agents()
            self.process_single_file(markdown_file_path, questions)
            self.logger.info(f"处理完成：{markdown_file_path}")


def setup_logger() -> logging.Logger:
    """设置日志记录器
    
    Returns:
        logging.Logger: 配置好的日志记录器
    """
    # 创建logger实例
    app_logger = logging.getLogger("md_analysis")

    # 设置日志级别
    level = os.getenv("LOG_LEVEL", "INFO")
    app_logger.setLevel(getattr(logging, level))

    # 防止日志重复
    if app_logger.hasHandlers():
        app_logger.handlers.clear()

    # 创建格式化器
    formatter = logging.Formatter(fmt="%(asctime)s [%(levelname)s] %(name)s: %(message)s", datefmt="%Y-%m-%d %H:%M:%S")

    # 创建并配置文件处理器
    log_dir = "log"
    os.makedirs(log_dir, exist_ok=True)
    log_file = os.path.join(log_dir, f"md_analysis_{datetime.datetime.now().strftime('%Y%m%d')}.log")

    file_handler = logging.FileHandler(log_file, mode='a', encoding='utf-8')
    file_handler.setFormatter(formatter)
    file_handler.setLevel(getattr(logging, level))

    # 创建并配置控制台处理器
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    console_handler.setLevel(getattr(logging, level))

    # 添加处理器到logger
    app_logger.addHandler(file_handler)
    app_logger.addHandler(console_handler)

    # 设置不传播到父logger
    app_logger.propagate = False

    return app_logger


def main(base_folder: str, logger: logging.Logger, review_mode: bool) -> None:
    """主函数，协调整个分析过程
    
    Args:
        base_folder (str): 要处理的文件夹路径
        logger (logging.Logger): 日志记录器
        review_mode (bool): 是否为review模式，默认为False
    """
    # 初始化配置
    config = ServiceConfig()

    # 创建服务实例
    service = MDAnalysisService(config, logger)

    # 处理所有文件
    service.process_all_files(base_folder, review_mode)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='招生信息Markdown文档分析')
    parser.add_argument('input_folder', nargs='?', default="pdf_with_md", help='保存每个学校的资料文件夹的根目录。如果不指定，将使用默认值：pdf_with_md')
    parser.add_argument('--review', action='store_true', help='review模式：只处理没有报告或报告内容少于10行的文件')
    args = parser.parse_args()

    input_folder = args.input_folder

    # 设置logger
    logger = setup_logger()

    if not os.path.exists(input_folder):
        logger.error(f'指定的文件夹不存在：{input_folder}')
        print('Usage: python md_analysis.py <input_folder> [--review]')
        sys.exit(1)

    logger.info(f"开始处理：{input_folder}")
    main(input_folder, logger, args.review)
