from datetime import datetime
import os
from vision_parse import VisionParser
from dotenv import load_dotenv

load_dotenv()
GOOGLE_AI_STUDIO_API_KEY = os.getenv('GOOGLE_AI_STUDIO_API_KEY')
OPENROUTER_API_KEY = os.getenv('OPENROUTER_API_KEY')
OPENROUTER_END_POINT = os.getenv('OPENROUTER_END_POINT')

'''
# Initialize parser with Google Gemini model
parser = VisionParser(
    model_name="gemini-1.5-flash",
    api_key=GOOGLE_AI_STUDIO_API_KEY,
    temperature=0.7,
    top_p=0.4,
    image_mode="base64",
    detailed_extraction=True, # Set to True for more detailed extraction
    enable_concurrency=True,
)'''

parser = VisionParser(
    model_name="gpt-4o",
    api_key=OPENROUTER_API_KEY,
    openai_config={"OPENAI_BASE_URL": OPENROUTER_END_POINT},  # Fixed dictionary syntax
    temperature=0.7,
    top_p=0.4,
    image_mode="base64",
    detailed_extraction=True,
    enable_concurrency=True,
)

pdf_path = "./pdf_with_md/お茶の水女子大学_20241208/お茶の水女子大学_20241208.pdf"
markdown_pages = parser.convert_pdf(pdf_path)
markdown_path = f"markdown_{datetime.now().strftime('%Y%m%d%H%M%S')}.md"

with open(markdown_path, 'w', encoding='utf-8') as f:
    for i, page_content in enumerate(markdown_pages):
        f.write(page_content)