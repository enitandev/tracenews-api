import re

with open("shadow_output.txt") as f:
    text = f.read()

# Find the block for SOURCING
start = text.find("BLOCKED BY SOURCING — review each")
end = text.find("CLEAR:", start)
block = text[start:end]

clusters = []
current = []
for line in block.split("\n")[2:]: # skip the header lines
    if line.strip() == "":
        if current:
            clusters.append("\n".join(current))
            current = []
    else:
        current.append(line.strip())
if current:
    clusters.append("\n".join(current))

# Group by category to ensure a good spread
by_cat = {}
for c in clusters:
    match = re.search(r"Category: (.+)", c)
    if match:
        cat = match.group(1).strip()
        if cat not in by_cat:
            by_cat[cat] = []
        by_cat[cat].append(c)

selected = []
while len(selected) < 15 and by_cat:
    for cat in list(by_cat.keys()):
        if by_cat[cat]:
            selected.append(by_cat[cat].pop(0))
            if len(selected) == 15:
                break
        else:
            del by_cat[cat]

print(f"Total parsed: {len(clusters)}")
for s in selected:
    print(s)
    print("")
