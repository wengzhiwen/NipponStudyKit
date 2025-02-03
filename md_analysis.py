import sys
from autogen import ConversableAgent, GroupChat, GroupChatManager, register_function
import datetime
import os
import glob
from dotenv import load_dotenv

load_dotenv()

llm_config = {
    "model": os.getenv("GEMINI_MODEL_FOR_TOOLS"),
    "api_key": os.getenv("GOOGLE_AI_STUDIO_API_KEY"),
    "api_type": "google",
}

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

    # 如果文件已存在，将原文件以.年月日时分秒.bak后缀备份
    if os.path.exists(report_file_path):
        bak_file_path = (
            report_file_path
            + "."
            + datetime.datetime.now().strftime("%Y%m%d%H%M%S")
            + ".bak"
        )
        os.rename(report_file_path, bak_file_path)

    with open(report_file_path, "w", encoding="utf-8") as f:
        f.write(report_content)
    
    return "保存成功"

def init_agents():
    markdown_loader_agent = ConversableAgent(
        name="Markdown_Loader_Agent",
        llm_config=llm_config,
        description="Markdown文件加载Agent",
        system_message="""你是负责为整个Team读取需要被分析的Markdown文档。
            通过load_markdown_file工具加载Markdown文档内容。
        """,
    )

    register_function(
        load_markdown_file,
        caller=markdown_loader_agent,
        executor=markdown_loader_agent,
        description="Load the content of a markdown file.",
    )

    markdown_analyzer_agent = ConversableAgent(
        name="Markdown_Analyzer_Agent",
        llm_config=llm_config,
        description="日本大学留学生招生信息分析Agent",
        system_message="""
                你是一位严谨的Markdown分析助手,你根据Markdown_Loader_Agent的工作结果继续以下工作流：
                1. 确认该文档是否含有针对'外国人留学生'的本科(学部)招生信息，如果不包含请输出“NOTCONTINUE”来结束任务，就此停止不要继续
                2. 确认该文档中的报名日期的年份是否为2024年1月1日及以后的日期，如果不是请输出“NOTCONTINUE”来结束任务，就此停止不要继续
                3. 仔细分析该文档内容,并对task中给出的问题逐一用中文给出准确的回答。如果信息不确定,请明确指出。
                    - 回答问题时请务必按照问题的顺序逐一回答（每个回答后附上对原文的引用）
        """,
        is_termination_msg=lambda x: "NOTCONTINUE"
        in (x.get("content", "") or "").upper(),
    )

    review_agent = ConversableAgent(
        name="Review_Agent",
        llm_config=llm_config,
        description="分析结果检查Agent",
        system_message="""你是一位严谨的校对人员,你根据Markdown_Analyzer_Agent的分析结果与Markdown_Loader_Agent获得的Markdown原文校对。
            你需要逐一核对,针对其中不相符的情况直接对分析结果进行修正。
            
            不论你是否发现错误，请将修正后的完整分析结果告诉大家，每个问题所关联的原文的引用需要保留。
        """,
    )

    report_agent = ConversableAgent(
        name="Report_Agent",
        llm_config=llm_config,
        description="报告生成Agent",
        system_message="""你的工作是将将Review_Agent提供的分析结果整理成Markdown格式的最终报告。
            你只需要整理Review_Agent提供的分析结果，不需要再对Markdown文档的原文进行分析。
            把每一个问题中涉及的对原文的引用统一放到报告的最后，尽可能保留足够多的原文关联内容，使得报告更加易读的同时也更加容易进行对照参考。
            你整理的最终报告用于给人类用户阅读，请尽可能使用表格、加粗、斜体等Markdown格式来使报告更易读。
            不要在你输出的内容前后再额外使用“```markdown”之类的定界符！
        """,
    )

    save_report_agent = ConversableAgent(
        name="Save_Report_Agent",
        llm_config=llm_config,
        description="报告保存Agent",
        system_message="""你的工作是将最终的报告使用save_report_to_file工具保存成指定的文件(report_file_path)。
            你必须执行以下步骤：
                1. 调用save_report_to_file工具，参数为:
                    - report_content: Report_Agent提供的最终报告内容
                    - report_file_path: 原始的task中提供的report_file_path值
                2. 确认文件保存是否成功
                
            请记住：
                - 你必须显式调用save_report_to_file工具来保存文件。
                - 最后的保存的文件中不必再包含report_file_path相关的信息。
                - 不要在Markdown文档的开头或结尾再附加其他的说明性文字.
                - 不要在你输出的内容前后再额外使用“```markdown”之类的定界符！
                
            请务必按照上述步骤执行，以确保报告能够正确保存。
        """,
    )
    
    register_function(
        save_report_to_file,
        caller=save_report_agent,
        executor=save_report_agent,
        description="Save the content of a report to a file.",
    )

    return (
        markdown_loader_agent,
        markdown_analyzer_agent,
        review_agent,
        report_agent,
        save_report_agent,
    )


def main() -> None:
    (
        markdown_loader_agent,
        markdown_analyzer_agent,
        review_agent,
        report_agent,
        save_report_agent,
    ) = init_agents()

    team = GroupChat(
        agents=[
            markdown_loader_agent,
            markdown_analyzer_agent,
            review_agent,
            report_agent,
            save_report_agent,
        ],
        max_round=6,
        speaker_selection_method="round_robin",
        messages=[]
    )
    
    manager = GroupChatManager(groupchat=team, llm_config=llm_config)

    # 从md_analysis_questions.txt文件中读取问题
    with open("md_analysis_questions.txt", "r", encoding="utf-8") as f:
        questions = f.read()

    # 所有以"pdf_with_md"开头的文件夹中遍历其下的所有子文件夹，找到其中所有*.md文件(忽略文件名中包含"_中文"或"_report"的文件)
    # 遍历这些符合要求的文件，将其路径作为markdown_file_path参数传入到team.run_stream()中
    base_dirs = glob.glob("pdf_with_md*")

    md_files = []

    for base_dir in base_dirs:
        for root, dirs, files in os.walk(base_dir):
            for file in files:
                if file.endswith(".md"):
                    if "_中文" not in file and "_report" not in file:
                        full_path = os.path.join(root, file)
                        md_files.append(full_path)

    for markdown_file_path in md_files:
        print(f"开始处理：{markdown_file_path}")

        output_file_path = markdown_file_path.replace(".md", "_report.md")
        team.reset()
        manager.reset()

        task = f"""
            请帮我分析以下路径所指定的Markdown文档中的内容,并回答问题：
            
            markdown_file_path = {markdown_file_path}
            
            ---
            虽然文档内容是日语，但以下的问题和问题的答案都是用简体中文：
            
            {questions}
            
            ---
            以上是我的问题，请务必严格按照Markdown文档中的内容回答问题。
            
            并将最终的报告保存到以下路径：
            
            report_file_path = {output_file_path}
        """

        sys.stdout = open(f"output_{os.path.basename(markdown_file_path)}_{datetime.datetime.now().strftime("%Y%m%d%H%M%S")}.txt", "w")
        try:
            markdown_loader_agent.initiate_chat(
                recipient=manager,
                message=task
            )
        except Exception as e:
            print(f"An error occurred during chat initiation: {e}")
        finally:
            # 重置sys.stdout为控制台输出
            sys.stdout.close()
            sys.stdout = sys.__stdout__

if __name__ == "__main__":
    main()
