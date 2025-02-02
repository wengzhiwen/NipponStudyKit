from autogen_agentchat.agents import AssistantAgent
from autogen_agentchat.teams import RoundRobinGroupChat
from autogen_agentchat.ui import Console
from autogen_ext.models.openai import OpenAIChatCompletionClient
import datetime
import os
from dotenv import load_dotenv

load_dotenv()

def load_markdown_file(markdown_file_path: str) -> str:
    '''
    Load the content of a markdown file.
    
    Args:
        markdown_file_path (str): The path to the markdown file.
    
    Returns:
        str: The content of the markdown file.
    '''
    try:
        with open(markdown_file_path, "r", encoding="utf-8") as f:
            md_content = f.read()
    except FileNotFoundError:
        md_content = "Markdown文件不存在，请检查文件路径是否正确。"
    except Exception as e:
        md_content = f"读取Markdown文件时发生错误：{e}"

    return md_content

def save_report_to_file(report_content: str, report_file_path: str) -> None:
    '''
    Save the content of a report to a file.
    
    Args:
        report_content (str): The content of the report.
        report_file_path (str): The path to the report markdown file.
    '''
    
    print(f"#########save_report_to_file called") # 添加调试信息
    print(f"#########content: {report_content[:100]}...") # 打印内容前100个字符
    print(f"#########file_path: {report_file_path}")
    
    # 如果文件夹不存在则创建文件夹
    os.makedirs(os.path.dirname(report_file_path), exist_ok=True)
    
    # 如果文件已存在，将原文件以.年月日时分秒.bak后缀备份
    if os.path.exists(report_file_path):
        bak_file_path = report_file_path + "." + datetime.datetime.now().strftime("%Y%m%d%H%M%S") + ".bak"
        os.rename(report_file_path, bak_file_path)
        
    with open(report_file_path, "w", encoding="utf-8") as f:
        f.write(report_content)

def init_agents():
    markdown_analyzer_agent = AssistantAgent(
        name="Markdown_Analyzer_Agent",
        model_client=OpenAIChatCompletionClient(
            model=os.getenv("GEMINI_MODEL_FOR_ANALYSIS"),
            api_key=os.getenv("GOOGLE_AI_STUDIO_API_KEY"),
            base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
            model_info={
                "vision": True,
                "function_calling": True,
                "json_output": True,
                "family": "unknown",
            },
        ),
        tools=[load_markdown_file],
        description="日本大学留学生招生信息分析Agent",
        system_message='''你是一位严谨的助手,能够准确地阅读Markdown文档并回答问题。
            你首先需要通过load_markdown_file工具加载Markdown文档内容。
            然后仔细分析文档内容,并给出准确的回答。如果信息不确定,请明确指出。
            
            如果你在收到Markdown文档和指定的问题之外，还收到了指出你错误的信息，请核对错误并修正后再次回答问题。
            
            回答问题时请务必按照问题的顺序逐一回答（每个回答后附上对原文的引用），并在回答结束后附上Markdown文档的全文，以及最终报告需要保存的路径（report_file_path）传递给下一个Agent。
        ''',
    )

    review_agent = AssistantAgent(
        name="Review_Agent",
        model_client=OpenAIChatCompletionClient(
            model=os.getenv("GEMINI_MODEL_FOR_ANALYSIS"),
            api_key=os.getenv("GOOGLE_AI_STUDIO_API_KEY"),
            base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
            model_info={
                "vision": True,
                "function_calling": True,
                "json_output": True,
                "family": "unknown",
            },
        ),
        description="分析结果检查Agent",
        system_message='''你是一位严谨的校对人员,根据收到的上一个Agent的分析结果和最后附上的Markdown文档原文进行校对。
            你需要逐一核对仔文档内容和上一个Agent的分析结果,针对其中不相符的情况直接对分析结果进行修正。
            
            不论你是否发现错误，请将修正后的分析结果传递给下一个Agent，每个问题所关联的原文的引用需要保留，但最后不要再附上Markdown文档的全文了。
            最后请务必附上最终报告需要保存的路径（report_file_path）一起传递给下一个Agent。
        ''',
    )

    report_agent = AssistantAgent(
        name="Report_Agent",
        model_client=OpenAIChatCompletionClient(
            model=os.getenv("GEMINI_MODEL_FOR_ANALYSIS"),
            api_key=os.getenv("GOOGLE_AI_STUDIO_API_KEY"),
            base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
            model_info={
                "vision": True,
                "function_calling": True,
                "json_output": True,
                "family": "unknown",
            },
            llm_config={
                "temperature": 0.2,
                "verbose": True
            },
        ),
        description="报告生成Agent",
        system_message='''你的工作是将将上一个Agent提供的分析结果整理成Markdown格式的最终报告。
            你只需要整理上一个Agent提供的分析结果，不需要再对Markdown文档的原文进行分析。
            把每一个问题中涉及的对原文的引用统一放到报告的最后，尽可能保留足够多的原文关联内容，使得报告更加易读的同时也更加容易进行对照参考。
            你整理的最终报告用于给人类用户阅读，请尽可能使用表格、加粗、斜体等Markdown格式来使报告更易读。
            不要在你输出的内容前后再额外使用“```markdown”之类的定界符！
            
            最后请务必附上最终报告需要保存的路径（report_file_path）一起传递给下一个Agent。
        ''',
    )
    
    save_report_agent = AssistantAgent(
        name="Save_Report_Agent",
        model_client=OpenAIChatCompletionClient(
            model=os.getenv("GEMINI_MODEL_FOR_ANALYSIS"),
            api_key=os.getenv("GOOGLE_AI_STUDIO_API_KEY"),
            base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
            model_info={
                "vision": True,
                "function_calling": True,
                "json_output": True,
                "family": "unknown",
            },
            llm_config={
                "temperature": 0.2,
                "verbose": True
            },
        ),
        tools=[save_report_to_file],
        description="报告保存Agent",
        system_message='''你的工作是将最终的报告使用save_report_to_file工具保存成指定的文件(report_file_path)。
            你必须执行以下步骤：
                1. 调用save_report_to_file工具，参数为:
                    - report_content: 上一个Agent提供的分析结果整理成Markdown格式的最终报告
                    - report_file_path: 上一位Agent提供的report_file_path值
                2. 确认文件保存是否成功
                
            请记住：
                - 你必须显式调用save_report_to_file工具来保存文件。
                - 最后的保存的文件中不必再包含report_file_path相关的信息。
                - 不要在Markdown文档的开头或结尾再附加其他的说明性文字.
                - 不要在你输出的内容前后再额外使用“```markdown”之类的定界符！
                
            请务必按照上述步骤执行，以确保报告能够正确保存。
            
            任务完成后请提供如下通知：
                - 报告已经保存到指定路径：report_file_path
        ''',
    )
    
    return markdown_analyzer_agent, review_agent, report_agent, save_report_agent

async def main() -> None:
    markdown_analyzer_agent, review_agent, report_agent, save_report_agent = init_agents()
    
    team = RoundRobinGroupChat(
        [markdown_analyzer_agent, review_agent, report_agent, save_report_agent],
        max_turns=4
    )
    
    markdown_file_path = "./pdf_with_md_20250112103823/東京理科大学_2023-11-30/東京理科大学_2023-11-30.md"
    
    questions = '''
        1. 该文档是否含有针对'外国人留学生'的本科(学部)招生信息?
        2. 该文档中涉及的针对'外国人留学生'的招生信息中,具体涉及哪些本科(学部)的专业?
        3. 该文档中涉及的针对'外国人留学生'的'报名截止日期(年月日)'是什么时间?
        4. 该文档中涉及的针对'外国人留学生'的报名要求中是否包含托福或托业的成绩单、具体分数的说明?如果不同的专业有不同的要求请分别列举。
        5. 该文档中涉及的针对'外国人留学生'的报名要求中针对在日本有超过12个月或是超过24个月的学习经历的学生是否有特殊限制?
        6. 该文档中涉及的针对'外国人留学生'的报名要求中是否包含EJU(日本统一留学生考试)的成绩单、具体分数的说明?如果不同的专业有不同的要求请分别列举。
        7. 该文档中涉及的针对'外国人留学生'的报名要求中是否包含JLPT或其他日语水平考试的要求?如果有的话,是否有具体分数的说明?如果不同的专业有不同的要求请分别列举。
    '''
    
    output_file_path = "./pdf_with_md_20250112103823/東京理科大学_2023-11-30/東京理科大学_2023-11-30_report.md"
    
    task = f'''
        请帮我分析以下路径所指定的Markdown文档中的内容,并回答问题：
        
        markdown_file_path = {markdown_file_path}
        
        ---
        虽然文档内容是日语，但以下的问题和问题的答案都是用简体中文：
        
        {questions}
        
        ---
        以上是我的问题，请务必严格按照Markdown文档中的内容回答问题。
        
        并将最终的报告保存到以下路径：
        
        report_file_path = {output_file_path}
    '''
    
    await Console(team.run_stream(task=task))
    
    #print(task)
    

if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
