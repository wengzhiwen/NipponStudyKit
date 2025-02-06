import argparse
import sys
from autogen import ConversableAgent, GroupChat, GroupChatManager, UserProxyAgent, register_function
import datetime
import os
import glob
from dotenv import load_dotenv
import logging

load_dotenv()

llm_config = {
    "config_list": [{
        "model": os.getenv("OPENROUTER_MODEL_FOR_ANALYSIS"),
        "api_key": os.getenv("OPENROUTER_API_KEY"),
        "base_url": os.getenv("OPENROUTER_END_POINT"),
        "api_type": "openai",
        "temperature": 0.5,
        "price": [0.001, 0.001],
    }]
}

llm_config_mini = {
    "config_list": [{
        "model": os.getenv("OPENROUTER_MODEL_FOR_REPORT"),
        "api_key": os.getenv("OPENROUTER_API_KEY"),
        "base_url": os.getenv("OPENROUTER_END_POINT"),
        "api_type": "openai",
        "temperature": 0.5,
        "price": [0.001, 0.001],
    }]
}

logger = logging.getLogger(__name__)

def setup_logger():
    level = os.getenv("LOG_LEVEL", logging.INFO)
    logger.setLevel(level)
    logger.propagate = False

    formatter = logging.Formatter(
        fmt="%(asctime)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )

    log_file = os.path.join("log", f"md_analysis_{datetime.datetime.now().strftime("%Y%m%d%H%M%S")}.log")
    os.makedirs(os.path.dirname(log_file), exist_ok=True)
    
    file_handler = logging.FileHandler(log_file, mode='a', encoding='utf-8')
    file_handler.setLevel(level)
    file_handler.setFormatter(formatter)

    # 创建控制台处理器
    console_handler = logging.StreamHandler()
    console_handler.setLevel(level)
    console_handler.setFormatter(formatter)

    # 添加处理器到日志器
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)

def load_markdown_file(markdown_file_path: str) -> str:
    """
    Load the content of a markdown file.

    Args:
        markdown_file_path (str): The path to the markdown file.

    Returns:
        str: The content of the markdown file.
    """
    try:
        with open(markdown_file_path, "r", encoding="utf-8") as f:
            md_content = f.read()
    except FileNotFoundError:
        md_content = "Markdown文件不存在，请检查文件路径是否正确。"
    except Exception as e:
        md_content = f"读取Markdown文件时发生错误：{e}"

    return md_content

def save_report_to_file(report_content: str, report_file_path: str) -> str:
    """
    Save the content of a report to a file.

    Args:
        report_content (str): The content of the report.
        report_file_path (str): The path to the report markdown file.
    """
    # 如果文件夹不存在则创建文件夹
    os.makedirs(os.path.dirname(report_file_path), exist_ok=True)

    with open(report_file_path, "w", encoding="utf-8") as f:
        f.write(report_content)
    
    return "保存成功"

def init_agents():
    markdown_analyzer_agent = ConversableAgent(
        name="Markdown_Analyzer_Agent",
        llm_config=llm_config,
        human_input_mode="NEVER",
        description="日本大学留学生招生信息分析Agent",
        system_message="""
                你是一位严谨的Markdown分析助手,你根据User_Proxy_Agent提供的内容继续以下工作流：
                1. 仔细分析该文档内容,并对task中给出的问题逐一用中文给出准确的回答。如果信息不确定,请明确指出。
                    - 回答问题时请务必按照问题的顺序逐一回答（每个回答后附上对原文的引用）
                    - 输出的结果中不需要包含任何额外的信息，只需要回答问题即可
                    - 输出的结果中不要包含任何文档路径相关的信息
                    - 请忽略最终要将结果保存到文件的步骤，只需要回答问题即可。保存工作会由其他Agent接手
                    - 请严格按照文档来回答问题，不要进行任何额外的推测或猜测！
        """,
        is_termination_msg=lambda x: "NOTCONTINUE" in (x.get("content", "") or "").upper(),
    )

    review_agent = ConversableAgent(
        name="Review_Agent",
        llm_config=llm_config_mini,
        human_input_mode="NEVER",
        description="分析结果检查Agent",
        system_message="""
                你是一位严谨的校对人员,你根据Markdown_Analyzer_Agent的分析结果与最先提供的Markdown原文进行校对。
                你的工作流程如下：
                1. 逐一核对,针对其中不相符的情况直接对分析结果进行修正。
                    - 不论你是否发现错误，请将修正后的完整分析结果告诉大家，每个问题所关联的原文的引用需要保留；
                    - 请严格按照文档来校对和修正，不要进行任何额外的推测或猜测！
                    - 请忽略最终要将结果保存到文件的步骤，只需要回答问题即可。保存工作会由其他Agent接手
                2. 确认是否有语法错误，针对其中的中文部分和日语部分的语法错误分别进行修正。
        """,
        is_termination_msg=lambda x: "NOTCONTINUE" in (x.get("content", "") or "").upper(),
    )

    report_agent = ConversableAgent(
        name="Report_Agent",
        llm_config=llm_config_mini,
        human_input_mode="NEVER",
        description="报告生成Agent",
        system_message="""
                你的工作是将将Review_Agent提供的分析结果整理成Markdown格式的最终报告。
                你的工作流程如下：
                1. 基于Review_Agent提供的分析结果，整理成Markdown格式的最终报告，不需要再对Markdown文档的原文进行分析，也不要进行任何推测；
                    - 报告标题：
                        - 报告H1标题为：「大学名称」私费外国人留学生招生信息分析报告
                        - 接下来每个问题都是一个H2标题，问题的回答紧跟在H2标题下
                    - 每一个问题本身（文字）进行适当缩减，特别是“该文档…”之类的文字都要进行缩减，但保持顺序不变；
                    - 最终的报告中不需要包含任何文档路径、分析时间、特别提示等额外信息；
                    - 如果问题的回答有关联原文的引用的，保留引用内容，如果没有的也不需要额外添加说明；
                    - 你整理的最终报告用于给人类用户阅读，请尽可能使用表格、加粗、斜体等Markdown格式来使报告更易读；
                    - 请忽略最终要将结果保存到文件的步骤，只需要回答问题即可。保存工作会由其他Agent接手
                    - 不要在你输出的内容前后再额外使用“```markdown”之类的定界符！
        """,
        is_termination_msg=lambda x: "NOTCONTINUE" in (x.get("content", "") or "").upper(),
    )

    save_report_agent = ConversableAgent(
        name="Save_Report_Agent",
        llm_config=llm_config_mini,
        human_input_mode="NEVER",
        description="报告保存Agent",
        system_message="""
                你的工作是将最终的报告使用save_report_to_file工具保存成指定的文件(report_file_path)。
                你必须执行以下步骤：
                1. 确认Report_Agent提供的最终报告内容是否正常，如果不正常请说明原因并结束任务
                    - 这里的正常是指：Report_Agent是否提供了一份报告，而不是空白或其他异常情况
                    - 并不是要你再次校对报告的内容，除了格式和必要的语言调整之外，请不要修改报告的内容
                2. 调用save_report_to_file工具，参数为:
                    - report_content: Report_Agent提供的最终报告内容
                    - report_file_path: 原始的task中提供的report_file_path值
                3. 确认文件保存是否成功
                    
                请记住：
                    - 你必须显式调用save_report_to_file工具来保存文件。
                    - 最后的保存的文件中不必再包含report_file_path相关的信息。
                    - 不要在Markdown文档的开头或结尾再附加其他的说明性文字.
                    - 不要在你输出的内容前后再额外使用“```markdown”之类的定界符！
                    
                请务必按照上述步骤执行，以确保报告能够正确保存。
        """,
        is_termination_msg=lambda x: "NOTCONTINUE" in (x.get("content", "") or "").upper(),
    )
    
    register_function(
        save_report_to_file,
        caller=save_report_agent,
        executor=save_report_agent,
        description="Save the content of a report to a file.",
    )

    return (
        markdown_analyzer_agent,
        review_agent,
        report_agent,
        save_report_agent,
    )

def main(base_folder: str) -> None:
    (
        markdown_analyzer_agent,
        review_agent,
        report_agent,
        save_report_agent,
    ) = init_agents()

    user_proxy = UserProxyAgent(
        name="User_Proxy_Agent",
        human_input_mode="NEVER",
        llm_config=False,
        code_execution_config=False,
    )
    
    team = GroupChat(
        agents=[
            user_proxy,
            markdown_analyzer_agent,
            review_agent,
            report_agent,
            save_report_agent,
        ],
        max_round=6,
        speaker_selection_method="round_robin",
        messages=[]
    )
    
    manager = GroupChatManager(groupchat=team, llm_config=llm_config_mini)

    # 从md_analysis_questions.txt文件中读取问题
    with open("md_analysis_questions.txt", "r", encoding="utf-8") as f:
        questions = f.read()

    # 遍历其下的所有子文件夹，找到其中所有*.md文件(忽略文件名中包含"_中文"或"_report"的文件)
    # 遍历这些符合要求的文件，将其路径作为markdown_file_path参数传入到team.run_stream()中
    base_dirs = glob.glob(base_folder)

    md_files = []

    for base_dir in base_dirs:
        for root, dirs, files in os.walk(base_dir):
            for file in files:
                if file.endswith(".md"):
                    if "_中文" not in file and "_report" not in file:
                        full_path = os.path.join(root, file)
                        md_files.append(full_path)

    logger.info(f"共有{len(md_files)}个Markdown文件需要处理...")
    
    for markdown_file_path in md_files:
        logger.info(f"开始处理：{markdown_file_path}")
        
        team.reset()
        manager.reset()
        
        output_file_path = markdown_file_path.replace(".md", "_report.md")
        # 如果文件已存在，将原文件以.年月日时分秒.bak后缀备份
        if os.path.exists(output_file_path):
            bak_file_path = (
                output_file_path
                + "."
                + datetime.datetime.now().strftime("%Y%m%d%H%M%S")
                + ".bak"
            )
            os.rename(output_file_path, bak_file_path)
        
        md_content = load_markdown_file(markdown_file_path)

        task = f"""
            请帮我分析以下Markdown文档中的内容,并回答问题：
            
{md_content}
            
            ---
            以上是Markdown文档的内容，虽然文档内容是日语，但以下的问题和问题的答案都使用简体中文：
            
{questions}
            
            ---
            以上是我的问题，请务必严格按照Markdown文档中的内容回答问题。
            
            并将最终的报告保存到以下路径：
            
            report_file_path = {output_file_path}
        """
        std_output_file = f"output_{os.path.basename(markdown_file_path)}_{datetime.datetime.now().strftime("%Y%m%d%H%M%S")}.txt"
        sys.stdout = open(std_output_file, "w")
        try:
            user_proxy.initiate_chat(
                recipient=manager,
                message=task
            )
            
            sys.stdout.close()
            sys.stdout = sys.__stdout__
        except Exception as e:
            sys.stdout.close()
            sys.stdout = sys.__stdout__
            
            logger.error(f"未能完成: {markdown_file_path} 的分析，发生错误: {e}")
        finally:
            logger.info(f"完成处理：{markdown_file_path}")
            
        # 检查是否有报告生成
        if os.path.exists(output_file_path):
            logger.info(f"确认已生成报告：{output_file_path}")
            if os.getenv("LOG_LEVEL") == "INFO":
                # 删除std_output_file
                os.remove(std_output_file)
                logger.info(f"删除：{std_output_file}")
        else:
            logger.error(f"未生成报告：{output_file_path}")
            
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='招生信息Markdown文档分析')
    parser.add_argument('base_folder', help='保存每个学校的资料文件夹的根目录。')
    args = parser.parse_args()

    base_folder = args.base_folder

    if not os.path.exists(base_folder):
        print(f'指定的文件夹： {base_folder} 不存在。')
        print('Usage: python md_analysis.py <base_folder>')
        sys.exit(1)
    
    setup_logger()
    
    logger.info(f"开始处理：{base_folder}")
    main(base_folder)
