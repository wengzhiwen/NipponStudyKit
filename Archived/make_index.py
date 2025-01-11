import os
import csv
from pathlib import Path
from typing import Dict, Optional

def get_university_info(org_csv_path: str) -> Dict[str, tuple]:
    """Get first occurrence of each university's info from org CSV."""
    university_info = {}
    with open(org_csv_path, 'r', encoding='utf-8') as f:
        reader = csv.reader(f)
        for row in reader:
            if len(row) < 11:  # Skip invalid rows
                continue
            # Extract university name from the path in first column
            path_parts = row[0].split('/')
            if len(path_parts) < 2:
                continue
            dir_name = path_parts[-2]
            uni_name = extract_university_name(dir_name)
            
            if uni_name and uni_name not in university_info:
                print(f"Found university in org CSV: {uni_name}")
                university_info[uni_name] = (
                    row[9].strip(),  # deadline
                    row[10].strip(),  # address
                    row[2].strip()   # description
                )
    return university_info

def find_files_in_dir(dir_path: Path) -> Optional[tuple]:
    """Find PDF, MD and Chinese MD files in directory."""
    pdf_files = list(dir_path.glob("*.pdf"))
    md_files = [f for f in dir_path.glob("*.md") if not f.name.endswith('中文.md')]
    zh_md_files = list(dir_path.glob("*中文.md"))
    
    if not (pdf_files and md_files):  # Must have both PDF and MD
        return None
        
    return (
        pdf_files[0].name,  # Just store the filename, not full path
        md_files[0].name,
        zh_md_files[0].name if zh_md_files else ""
    )

def extract_university_name(dir_name: str) -> str:
    """Extract university name from directory name."""
    # Split by underscore and take first part
    name = dir_name.split('_')[0]
    # Split by any non-Japanese characters and take first part
    name = ''.join(c for c in name if '\u4e00' <= c <= '\u9fff' or '\u3040' <= c <= '\u309f' or '\u30a0' <= c <= '\u30ff')
    return name

def escape_field(field: str) -> str:
    """Properly escape field content for CSV."""
    if '"' in field:
        # Replace single quotes with escaped quotes
        field = field.replace('"', '""')
    return field

def main():
    pdf_with_md_dir = Path("pdf_with_md")
    org_csv_path = pdf_with_md_dir / "org_20250106093355.csv"
    
    print(f"Reading org CSV from: {org_csv_path}")
    
    # Get university information
    university_info = get_university_info(org_csv_path)
    print(f"Found {len(university_info)} universities in org CSV")
    
    # Prepare data for index.csv
    index_data = []
    
    # Get all first-level subdirectories
    subdirs = [d for d in pdf_with_md_dir.iterdir() if d.is_dir()]
    print(f"Found {len(subdirs)} subdirectories in pdf_with_md/")
    
    # Process each subdirectory
    for subdir in subdirs:
        print(f"\nProcessing directory: {subdir.name}")
        files = find_files_in_dir(subdir)
        if not files:
            print("  No PDF/MD pair found")
            continue
            
        uni_name = extract_university_name(subdir.name)
        print(f"  Extracted university name: {uni_name}")
        
        if uni_name not in university_info:
            print("  University not found in org CSV")
            continue
            
        deadline, address, description = university_info[uni_name]
        print("  Found matching university info")
        
        pdf_path, md_path, zh_md_path = files
        # Escape all fields
        row_data = [
            escape_field(f"{subdir.name}/{pdf_path}"),
            escape_field(f"{subdir.name}/{md_path}"),
            escape_field(f"{subdir.name}/{zh_md_path}" if zh_md_path else ""),
            escape_field(uni_name),
            escape_field(deadline),
            escape_field(address),
            escape_field(description)
        ]
        index_data.append(row_data)
    
    print(f"\nWriting {len(index_data)} entries to index.csv")
    
    # Write to index.csv with proper quoting
    index_path = pdf_with_md_dir / "index.csv"
    with open(index_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f, quoting=csv.QUOTE_ALL)
        writer.writerow([
            'pdf_path',
            'md_path',
            'zh_md_path',
            'university_name',
            'deadline',
            'address',
            'description'
        ])
        writer.writerows(sorted(index_data, key=lambda x: x[3]))  # Sort by university name

if __name__ == "__main__":
    main()
