# PDF to Markdown Converter with Index Generation

This tool automates the process of converting PDF admission handbooks to markdown files with Chinese translations and organizing them based on university information.

## Features

- Converts PDF files to PNG images
- Performs OCR on images using Google Cloud Vision API
- Creates markdown files with proper formatting using Gemini AI
- Translates content to Chinese using Gemini AI
- Analyzes admission information to identify valid handbooks
- Organizes files by university name and application deadline
- Generates detailed processing reports

## Prerequisites

1. Python 3.8 or higher
2. Google Cloud Vision API credentials
3. Google Gemini AI API access
4. `poppler-utils` for PDF processing:
   - Ubuntu/Debian: `sudo apt-get install poppler-utils`
   - macOS: `brew install poppler`
   - Windows: Download from [poppler releases](http://blog.alivate.com.au/poppler-windows/)

## Setup

1. Install dependencies:
```bash
pip install -r requirements.txt
```

2. Create a `.env` file with the following settings:
```
GOOGLE_ACCOUNT_KEY_JSON=/path/to/your/google-cloud-key.json
GEMINI_MODEL_FOR_FORMAT_MD=gemini-1.5-flash
GEMINI_MODEL_FOR_ORG_INFO=gemini-1.5-pro
```

## Directory Structure

```
.
├── pdf/                    # Input directory for PDF files
├── pdf_with_md_[datetime]/ # Output directory with processed files
│   ├── [university_deadline]/  # One folder per valid handbook
│   │   ├── [university_deadline].pdf
│   │   ├── [university_deadline].md
│   │   └── [university_deadline]_中文.md
│   └── ...
```

## Usage

1. Place PDF files in the `./pdf` directory
2. Run the script:
```bash
python pdf2img2md_make_index.py
```

The script will:
1. Create a timestamped output directory
2. Process each PDF file:
   - Convert to PNG images
   - Perform OCR and create markdown
   - Translate to Chinese
   - Analyze if it's a valid admission handbook
3. Organize valid handbooks by university name and deadline
4. Generate a processing report with statistics

## Processing Report

The script generates a report showing:
- Total number of PDF files processed
- Total pages converted to images
- Number of valid admission handbooks
- Output directory location

## Error Handling

- Invalid or non-admission handbooks are automatically removed
- Detailed error messages for failed operations
- Progress bars for long-running operations
- Graceful handling of API failures

## Notes

- The script uses multi-threading for PDF to PNG conversion
- OCR and AI operations are rate-limited by API quotas
- Large PDF files may take longer to process
- Ensure sufficient disk space for image files
