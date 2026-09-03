import re

with open('app/main.py', 'r') as f:
    code = f.read()

# Replace the corrupted xml string
code = re.sub(r'xml = \(\n\s*\'<\?xml version="1.0" encoding="UTF-8"\?>\n\'\n\s*\'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"/>\'\n\s*\)', 
              'xml = (\\n            \\'<?xml version="1.0" encoding="UTF-8"?>\\\\n\\'\\n            \\'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"/>\\'\\n        )',
              code)

# Try replacing again using AST parsing or simple lines if regex fails
lines = code.split('\n')
for i in range(len(lines)):
    if '<?xml version="1.0" encoding="UTF-8"?>' in lines[i] and not lines[i].endswith(r'\n"') and not lines[i].endswith(r"\n'"):
        lines[i] = lines[i] + r"\n'"
        lines[i] = lines[i].replace("?>'", "?>")

with open('app/main.py', 'w') as f:
    f.write('\n'.join(lines))
