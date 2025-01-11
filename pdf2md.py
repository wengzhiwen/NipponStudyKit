from datetime import datetime
import os
from vision_parse import VisionParser
from dotenv import load_dotenv

load_dotenv()
GOOGLE_AI_STUDIO_API_KEY = os.getenv('GOOGLE_AI_STUDIO_API_KEY')

# Initialize parser with Google Gemini model
parser = VisionParser(
    model_name="gemini-1.5-flash",
    api_key=GOOGLE_AI_STUDIO_API_KEY,
    temperature=0.7,
    top_p=0.4,
    image_mode="base64",
    detailed_extraction=True, # Set to True for more detailed extraction
    enable_concurrency=True,
)

pdf_path = "/Users/wengzhiwen/Documents/NipponStudyKit/download_20250105_011016/愛媛学園大学2025_sihiryu_youkou-1.pdf"
markdown_pages = parser.convert_pdf(pdf_path)
markdown_path = f"markdown_{datetime.now().strftime('%Y%m%d%H%M%S')}.md"

with open(markdown_path, 'w', encoding='utf-8') as f:
    for i, page_content in enumerate(markdown_pages):
        f.write(page_content)