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
        "default_headers": {"HTTP-Referer": "https://james.wengs.net/", "X-Title": "NipponStudyKit"},
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
        "default_headers": {"HTTP-Referer": "https://james.wengs.net/", "X-Title": "NipponStudyKit"},
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
    print(f"save_report_to_file - report_file_path: {report_file_path}")
    
    # 如果文件夹不存在则创建文件夹
    os.makedirs(os.path.dirname(report_file_path), exist_ok=True)
    
    # 如果文件不存在则创建文件并插入首行
    if not os.path.exists(report_file_path):
        logging.debug(f"文件不存在，创建文件并插入首行")
        with open(report_file_path, "w", encoding="utf-8") as f:
            f.write("URL,标题,托福或托业,EJU,JLPT,校内考试,校内-数学,校内-英语,超过12个月在日,超过24个月在日\n")
        logging.debug(f"文件创建成功")

    with open(report_file_path, "a", encoding="utf-8") as f:
        f.write(report_content + "\n")
    
    return "保存成功"

def init_agents():
    report_analyzer_agent = ConversableAgent(
        name="Report_Analyzer_Agent",
        llm_config=llm_config,
        human_input_mode="NEVER",
        description="日本大学留学生招生信息分析Agent",
        system_message="""
        你是一位严谨的文档分析助手,你根据User_Proxy_Agent提供的文档内容继续以下工作流：
        - 仔细分析该文档内容,并对以下问题逐一用中文给出准确的回答
        - 请将答案组织成CSV样式的一行，每个问题的答案是这个CSV的一个单元格，每一个单元格都需要用双引号包裹。
        - 只需要输出答案行，不需要输出问题，也不要输出任何额外的说明
        - 仅根据文档中提供的内容进行回答，文档中没有涉及的就回答“未知”，不要推测
        - User_Proxy_Agent提到的保存结果的任务，请不要理会，会由其他Agent完成
        
        以下是所有的问题：
    
        1、文档路径
        2、文档标题
        3、是否要求提供托福或托业成绩（要求提供 / 要求提供且有最低报名分数线【分数】 / 未要求）
                - 若多个专业有不同的分数线，只列出最高的那个
        4、是否要求提供EJU考试成绩（要求提供 / 要求提供且有最低报名分数线【分数】 / 未要求）
                - 若多个专业有不同的分数线，只列出最高的那个
        5、是否要求提供JLPT考试成绩（要求提供 / 要求提供且有最低报名级别要求【级别】 / 未要求）
                - 若多个专业有不同的级别要求，只列出最高的那个（N1最高、N5最低）
        6、是否要求参加校内考试（要求 / 未要求 / 部分专业要求）
        7、校内考试是否会单独测试数学（是 / 否 / 部分专业）
        8、校内考试是否会单独测试英语（是 / 否 / 部分专业）
        9、该校对在日本有超过12个月的学习经历的学生是否有特殊限制（有限制【具体限制内容】 / 无限制 / 部分专业有限制【专业列表，具体限制内容】）
        10、该校对在日本有超过24个月的学习经历的学生是否有特殊限制（有限制【具体限制内容】 / 无限制 / 部分专业有限制【专业列表，具体限制内容】）
        """,
        is_termination_msg=lambda x: "NOTCONTINUE" in (x.get("content", "") or "").upper(),
    )

    save_report_agent = ConversableAgent(
        name="Save_Report_Agent",
        llm_config=llm_config_mini,
        human_input_mode="NEVER",
        description="报告保存Agent",
        system_message="""
                你的工作是将上一位Agent输出的结果使用save_report_to_file工具保存到指定的文件(report_file_path)。
                你必须执行以下步骤：
                1. 确认上一位Agent提供的内容是否正常，如果不正常请说明原因并结束任务
                    - 这里的正常是指：上一位Agent是否提供了一行CSV格式的内容，而不是空白或其他异常情况
                    - 并不是要你再次执行校对，请不要修改上一位Agent提供的内容
                2. 调用save_report_to_file工具，参数为:
                    - report_content: 上一位Agent提供的内容
                    - report_file_path: 原始的task中提供的report_file_path值
                    
                请记住：
                    - 你必须显式调用save_report_to_file工具来保存文件
                    - 不要在保存内容的的开头或结尾再附加其他的说明性文字
                    
                请务必按照上述步骤执行，以确保能够正确保存。
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
        report_analyzer_agent,
        save_report_agent,
    )

def main(base_folder: str, output_file_path: str) -> None:
    (
        report_analyzer_agent,
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
            report_analyzer_agent,
            save_report_agent,
        ],
        max_round=4,
        speaker_selection_method="round_robin",
        messages=[]
    )
    
    manager = GroupChatManager(groupchat=team, llm_config=llm_config_mini)

    # 遍历其下的所有子文件夹，找到其中所有*_report.md文件
    # 遍历这些符合要求的文件，将其路径作为markdown_file_path参数传入到team.run_stream()中
    base_dirs = glob.glob(base_folder)

    md_files = []

    for base_dir in base_dirs:
        for root, dirs, files in os.walk(base_dir):
            for file in files:
                if file.endswith("_report.md"):
                    full_path = os.path.join(root, file)
                    md_files.append(full_path)

    logger.info(f"共有{len(md_files)}个Report Markdown文件需要处理...")
    
    for markdown_file_path in md_files:
        logger.info(f"开始处理：{markdown_file_path}")
        
        team.reset()
        manager.reset()
        
        md_content = load_markdown_file(markdown_file_path)

        task = f"""
        文档路径：{os.path.basename(os.path.dirname(markdown_file_path))}
        以下是待处理的文档的内容：
            
{md_content}
            
        ---
        以上是Markdown文档的内容，请各自完成工作后，将最终结果保存到以下路径：
        
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
            
            logger.info(f"完成：{markdown_file_path}")
            if os.getenv("LOG_LEVEL") == "INFO":
                # 删除std_output_file
                os.remove(std_output_file)
                logger.info(f"删除：{std_output_file}")
                
        except Exception as e:
            sys.stdout.close()
            sys.stdout = sys.__stdout__
            
            logger.error(f"未能完成: {markdown_file_path} 的分析，发生错误: {e}")
            
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
    
    output_file_path = os.path.join(os.path.curdir, os.path.dirname(base_folder) + ".csv")
    
    # 如果文件已经存在，将显存文件以 原文件名_年月日时分秒.bak改名
    if os.path.exists(output_file_path):
        os.rename(output_file_path, output_file_path.replace(".csv", f"_{datetime.datetime.now().strftime("%Y%m%d%H%M%S")}.bak"))
        logger.info(f"输入路径已存在文件，备份到：{output_file_path.replace(".csv", f"_{datetime.datetime.now().strftime("%Y%m%d%H%M%S")}.bak")}")
 
    logger.info(f"开始处理：{base_folder}")
    logger.info(f"输出文件路径：{output_file_path}")
    main(base_folder, output_file_path)
