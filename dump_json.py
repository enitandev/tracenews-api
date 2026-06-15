import json
import os

with open('temp.json', 'r') as f:
    data = json.load(f)

markdown_content = f'''# Cluster Deep Dive JSON Response

```json
{json.dumps(data, indent=2)}
```
'''

artifact_path = '/Users/emekaabraham/.gemini/antigravity-ide/brain/71123c42-1d07-4292-9283-9464e9ce1a21/cluster_api_response.md'
with open(artifact_path, 'w') as f:
    f.write(markdown_content)
print("Done")
