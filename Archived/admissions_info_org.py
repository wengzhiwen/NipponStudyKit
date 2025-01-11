import datetime
import io
import os
import sys
from openai import AzureOpenAI
from dotenv import load_dotenv
from typing import Dict, List
import google.generativeai as genai

# 检查和设置 Google Cloud API Key json 文件
def set_google_cloud_api_key_json():
    # 检查os.environ['GOOGLE_APPLICATION_CREDENTIALS']是否已经设置
    if 'GOOGLE_APPLICATION_CREDENTIALS' in os.environ:
        # 检查设置的文件是否存在
        if os.path.exists(os.environ['GOOGLE_APPLICATION_CREDENTIALS']):
            return
    
    print('The specified GOOGLE_APPLICATION_CREDENTIALS file does not exist.')
    print('Load from local .env settings...')
    
    load_dotenv()
    GOOGLE_ACCOUNT_KEY_JSON = os.getenv('GOOGLE_ACCOUNT_KEY_JSON')
    
    # 检查GOOGLE_ACCOUNT_KEY_JSON设置的文件是否存在
    if GOOGLE_ACCOUNT_KEY_JSON is not None and os.path.exists(GOOGLE_ACCOUNT_KEY_JSON):
        os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = GOOGLE_ACCOUNT_KEY_JSON
        print('Set GOOGLE_APPLICATION_CREDENTIALS to {}'.format(GOOGLE_ACCOUNT_KEY_JSON))
        return
    
    print('The GOOGLE_ACCOUNT_KEY_JSON file: {} does not exist.'.format(GOOGLE_ACCOUNT_KEY_JSON))
    print('Cannot load GOOGLE_APPLICATION_CREDENTIALS file.')
    sys.exit(1)

def org_md(ref_md_path):
    genai.configure()
    GEMINI_ORG_MODEL = os.getenv('GEMINI_MODEL_FOR_ORG_INFO', 'gemini-1.5-pro')

    try:
        model = genai.GenerativeModel(GEMINI_ORG_MODEL)
    except Exception as e:
        print(f"Error occurred while loading the Gemini model: {e}")
        return None

    try:
        with open(ref_md_path, 'r', encoding='utf-8') as f:
            md_content = f.read()
    except Exception as e:
        print(f"Error occurred while reading MD file: {e}")
        return None

    prompt = '''请用**中文**回答我的问题：
        提示词最后添付的文本是根据从大学官网下载的原始PDF文件OCR成的markdown版本，虽然markdown是日文的，但输出的结果请全部使用中文。
        首先确认，这是不是包含该大学的本科（学部）私费留学生的招生信息（募集要项）。
        如果不是的话（比如这只是一个报名表，或募集要项的预告并非正式版本，或是只有大学院的招生信息，或是只有一般募集的招生信息），请按以下输出一行CSV，每一列要合适的使用双引号定界符：
            第一列：从文档中获得的大学名称（日语），如果无法获得就写【不明】；
            第二列：这是一个什么文档（既然不包含本科留学生的募集要项，那他是什么？）。
            其他列留空，也同时忽略下面的问题。
        如果是的话，请按照该学校招收本科私费留学生的专业，每个专业一行CSV，每一列要合适的使用双引号定界符：
            第一列：从文档中获得的大学名称（日语），如果无法获得就写【不明】；
            第二列：学校的简介（1～3句话，如果有QS排名也要带上QS排名，如果没有QS排名就不要提QS排名的事儿了）；
            第三列：学部名；
            第四列：专业名；
            第五列：该专业计划招收私费外国人留学生的人数；
            第六列：该专业的私费留学生是否需要提供英语托福/托业/雅思等第三方考试成绩，如果需要的话有没有明确的成绩标准或参考标准，用1～3句话说明；
            第七列：该专业的私费留学生是否有明确的日本留学试验（EJU）考试科目要求、报名成绩标准或参考成绩标准；
            第八列：该专业的私费留学生是否需要面试，如果需要的话，首先确认面试的类型是会问知识问题的“口头试问”还是主要看学生语言表达能力的“一般面谈”，而后再用1～3句话总结面试要求；
            第九列：该专业的私费留学生本次募集的报名的截止日期（年/月/日），如果文档中没有直接给出年份，请根据文档上下文推测一个合适的年份，补足年/月/日；
            第十列：该大学的地址，如果文档中出现了多个校园的地址，选择其中看上去最像本校（总校）的地址。地址中应包含邮编（使用〒符号开头以半角数字000-0000的格式准确描述），不需要电话号码；
        以上问题，请严格按照我提出的格式回答，以便于我整合多次回答的结果，进行数据整理。
        以下是添付的markdown内容：\n\n'''
    
    prompt = prompt + md_content + '''
        \n\n以上是所有的markdown内容，请用中文回答我提出的问题。
        注意，不要输出类似“```csv ```”这样的语法提示，不要省略内容，保持逗号分隔的CSV格式不要随便换行，也不要额外的说明！
        如果发生输出文字限制的状况，输出到最后一个完整的行即可，后续直接省略不用额外说明。
        '''

    try:
        response = model.generate_content(
            [prompt],
            stream=False,
        )

        prompt = '''以下是其他人给我的CSV数据，请为我检查其格式是否符合CSV的要求，如果不符合的话，请尽可能帮我修正。
            注意，我只要检查和修正格式，千万不要改动其中的任何数据！！不要根据你的经验通过推测对任何内容文本进行调整。
            每一列要合适的使用双引号定界符，不要输出类似“```csv ```”这样的语法提示，也不要额外的说明。
            '''
        prompt = prompt + response.text + '''
            \n以上是所有的CSV内容，请按照我的要求进行格式检查。
            输出符合CSV格式的数据给我，不要增加任何额外的说明，以便于我整合这些内容。
            如果输入内容就已经完全符合需求了，就原样输出给我，不要改动。
            '''

        response = model.generate_content(
            [prompt],
            stream=False,
        )

        return response
    except Exception as e:
        print(f"Error on Gemini: {e}")
        return None

if __name__ == '__main__':
    set_google_cloud_api_key_json()

    base_folder = "./pdf_with_md"
    current_time = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
    output_csv = os.path.join(base_folder, f"org_{current_time}.csv")
    output_csv_error = os.path.join(base_folder, f"org_error_{current_time}.csv")
    processed_md_count = 0
    error_md_count = 0

    # 遍历一级子目录
    for subdir in os.listdir(base_folder):
        subdir_path = os.path.join(base_folder, subdir)
        if not os.path.isdir(subdir_path):
            continue

        # 查找非"*中文.md"的md文件
        md_file = None
        for file in os.listdir(subdir_path):
            if file.endswith('.md') and not file.endswith('中文.md'):
                md_file = os.path.join(subdir_path, file)
                break
        
        if md_file is None:
            print(f"Warning: No suitable MD file found in {subdir_path}")
            continue
        
        print(f"开始处理：{md_file}")
        
        try:
            response = org_md(md_file)
            if response is not None:
                if len(response.text.split(",")) < 3:
                    # 非预期的MD内容
                    with open(output_csv_error, 'a', encoding='utf-8') as f:
                        f.write("\"" + md_file + "\", " + response.text)
                    error_md_count += 1
                    print(f"该文件不是预期的文件内容：{response.text}")
                else:
                    with open(output_csv, 'a', encoding='utf-8') as f:
                        for line in response.text.splitlines():
                            processed_line = "\"" + md_file + "\", " + line + "\n"
                            print(processed_line)
                            f.write(processed_line)
                    processed_md_count += 1
                    print(f"处理完成：{md_file}")
            else:
                print(f"Warning: Cannot get response for {md_file}")
        except Exception as e:
            print(f"处理{md_file}发生莫名奇妙的错误：{e}")

    print(f"所有MD文件处理完成：{processed_md_count}，非预期的内容：{error_md_count}")

