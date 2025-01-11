import os
import csv
import shutil
from pathlib import Path

def get_first_occurrence(csv_path):
    """Get first occurrence of each university with its application date."""
    universities = {}
    print(f"Reading CSV file: {csv_path}")
    with open(csv_path, 'r', encoding='utf-8') as f:
        reader = csv.reader(f)
        for row in reader:
            if len(row) >= 10:  # Ensure row has enough columns
                univ_name = row[1].strip().strip('"')  # University name is in second column
                app_date = row[9].strip().strip('"')   # Application date is in 10th column
                if univ_name and app_date and univ_name not in universities and not app_date.startswith('面试'):
                    universities[univ_name] = app_date.replace('/', '')
                    print(f"Found university: {univ_name} with date: {app_date}")
    print(f"Found {len(universities)} unique universities")
    return universities

def should_process_directory(dir_name, new_name):
    """Check if directory should be processed based on its name."""
    # Skip if directory is already in the correct format
    if dir_name == new_name:
        return False
    # Skip if directory is a temporary directory
    if dir_name.endswith('_temp'):
        return False
    return True

def rename_directory_and_files(base_dir, old_dir_name, new_dir_name):
    """Rename directory and its contents according to the new naming pattern."""
    # Skip if directory is already correctly named
    if not should_process_directory(old_dir_name, new_dir_name):
        print(f"Skipping already processed directory: {old_dir_name}")
        return

    old_path = os.path.join(base_dir, old_dir_name)
    new_path = os.path.join(base_dir, new_dir_name)
    
    print(f"\nProcessing directory: {old_path}")
    print(f"New directory name will be: {new_path}")
    
    # Skip if old directory doesn't exist
    if not os.path.exists(old_path):
        print(f"Directory not found: {old_path}")
        return
    
    # Create new directory
    temp_path = new_path
    os.makedirs(temp_path, exist_ok=True)
    
    # First pass: Move PDF and MD files
    files_moved = False
    for file in os.listdir(old_path):
        old_file_path = os.path.join(old_path, file)
        print(f"Processing file: {file}")
        
        # Only process PDF and MD files
        if not (file.endswith('.pdf') or file.endswith('.md')):
            continue
            
        # Determine new file name based on extension
        if file.endswith('.pdf'):
            new_file_name = f"{new_dir_name}.pdf"
        elif file.endswith('_中文.md'):
            new_file_name = f"{new_dir_name}_中文.md"
        elif file.endswith('.md'):
            new_file_name = f"{new_dir_name}.md"
        else:
            continue
        
        new_file_path = os.path.join(temp_path, new_file_name)
        print(f"Moving {old_file_path} to {new_file_path}")
        
        # Move and rename file
        try:
            shutil.copy2(old_file_path, new_file_path)
            os.remove(old_file_path)
            files_moved = True
            print(f"Successfully moved and renamed file to: {new_file_name}")
        except Exception as e:
            print(f"Error moving file {old_file_path}: {e}")
    
    # Second pass: Remove all remaining files and the directory
    try:
        if files_moved:
            print("\nCleaning up old directory...")
            shutil.rmtree(old_path)
            print(f"Removed old directory and its contents: {old_path}")
        else:
            print("No PDF or MD files were found to move")
            # If no files were moved but directory only contains PNGs, remove it
            has_important_files = False
            for file in os.listdir(old_path):
                if file.endswith(('.pdf', '.md')):
                    has_important_files = True
                    break
            if not has_important_files:
                print("Directory only contains non-essential files, removing it...")
                shutil.rmtree(old_path)
                print(f"Removed directory: {old_path}")
            else:
                print("Directory contains unprocessed PDF/MD files, keeping it")
    except Exception as e:
        print(f"Error in cleanup: {e}")

def cleanup_temp_directories(base_dir):
    """Remove any remaining temporary directories."""
    print("\nCleaning up temporary directories...")
    for dir_name in os.listdir(base_dir):
        dir_path = os.path.join(base_dir, dir_name)
        if os.path.isdir(dir_path) and dir_name.endswith('_temp'):
            try:
                shutil.rmtree(dir_path)
                print(f"Removed temporary directory: {dir_path}")
            except Exception as e:
                print(f"Error removing temporary directory {dir_path}: {e}")

def main():
    base_dir = 'pdf_with_md'
    csv_path = os.path.join(base_dir, 'org_20250106093355.csv')
    
    print("Starting directory reorganization...")
    print(f"Base directory: {base_dir}")
    
    # Get first occurrence of each university
    universities = get_first_occurrence(csv_path)
    
    # Process each directory in pdf_with_md
    for dir_name in os.listdir(base_dir):
        dir_path = os.path.join(base_dir, dir_name)
        if not os.path.isdir(dir_path):
            print(f"Skipping non-directory: {dir_name}")
            continue
        if dir_name == '__pycache__':
            print("Skipping __pycache__ directory")
            continue
            
        print(f"\nChecking directory: {dir_name}")
        # Find matching university
        matched = False
        for univ_name, app_date in universities.items():
            if univ_name in dir_name.replace('_', ' '):
                print(f"Matched university: {univ_name}")
                new_dir_name = f"{univ_name}_{app_date}"
                rename_directory_and_files(base_dir, dir_name, new_dir_name)
                matched = True
                break
        
        if not matched:
            print(f"No matching university found for directory: {dir_name}")
    
    # Clean up any remaining temporary directories
    cleanup_temp_directories(base_dir)
    
    print("\nDirectory reorganization completed")

if __name__ == '__main__':
    main()
