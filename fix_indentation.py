import sys

with open("app/scorer.py", "r") as f:
    lines = f.readlines()

new_lines = []
in_try_block = False

for i, line in enumerate(lines):
    # Detect start of try block
    if "try:" in line and "for attempt in range(3):" in lines[i-1]:
        in_try_block = True
        new_lines.append(line)
        continue
        
    # Detect end of try block
    if "scored_count += 1" in line and in_try_block:
        in_try_block = False
        new_lines.append("                scored_count += 1\n")
        continue

    if in_try_block:
        if line.strip() == "":
            new_lines.append("\n")
        else:
            # We are currently at 12 spaces, need 16 spaces
            if line.startswith("            "):
                new_lines.append("    " + line)
            elif line.startswith("        "):
                new_lines.append("        " + line)
            else:
                new_lines.append("                " + line.lstrip())
    else:
        new_lines.append(line)

with open("app/scorer.py", "w") as f:
    f.writelines(new_lines)
