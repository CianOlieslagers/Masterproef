import os
import shutil
import argparse

def main():
    parser = argparse.ArgumentParser(description="Filter useful ECO iterations based on file presence.")
    parser.add_argument(
        "input_folder", 
        help="Path to the folder containing the iter_ folders (e.g., iterations or non_useful_iterations)"
    )
    args = parser.parse_args()

    # Resolve paths dynamically
    source_dir = os.path.abspath(args.input_folder)
    base_dir = os.path.dirname(source_dir) # Goes up one level (to 2026-04-23_13-37-57)
    
    useful_dir = os.path.join(base_dir, "useful_iterations")
    non_useful_dir = os.path.join(base_dir, "non_useful_iterations")
    summary_file = os.path.join(base_dir, "iterations_summary.txt")

    os.makedirs(useful_dir, exist_ok=True)
    os.makedirs(non_useful_dir, exist_ok=True)

    summary_data = []
    useful_count = 0
    non_useful_count = 0

    print(f"Scanning iterations in: {source_dir}...\n")

    for iter_folder in sorted(os.listdir(source_dir)):
        iter_path = os.path.join(source_dir, iter_folder)

        if not os.path.isdir(iter_path) or not iter_folder.startswith("iter_"):
            continue

        files_in_folder = os.listdir(iter_path)
        
        # --- THE NEW LOGIC ---
        # A successful iteration makes it far enough to generate a 'compare.log'
        is_useful = "compare.log" in files_in_folder

        if is_useful:
            target_path = os.path.join(useful_dir, iter_folder)
            status = "USEFUL     "
            useful_count += 1
        else:
            target_path = os.path.join(non_useful_dir, iter_folder)
            status = "NOT USEFUL "
            non_useful_count += 1

        # Move the folder ONLY if it's not already in the correct destination
        if iter_path != target_path:
            shutil.move(iter_path, target_path)

        # Record for the summary
        file_list_str = ", ".join(sorted(files_in_folder))
        summary_data.append(f"[{status}] {iter_folder} --> Files: {file_list_str}")

    # Write summary
    with open(summary_file, 'w') as f:
        f.write("=========================================\n")
        f.write("       ECO ITERATIONS SUMMARY REPORT     \n")
        f.write("=========================================\n\n")
        f.write(f"Total Useful:     {useful_count}\n")
        f.write(f"Total Not Useful: {non_useful_count}\n")
        f.write("-" * 41 + "\n\n")
        
        for line in summary_data:
            f.write(line + "\n")

    print(f"Done! Found {useful_count} useful and {non_useful_count} non-useful iterations.")
    print(f"Summary saved to: {summary_file}")

if __name__ == "__main__":
    main()
