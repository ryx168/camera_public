import json

top_vids = ["v2829063347", "v2829063851", "v2829062861", "v2829130373", "v2829081362", "v2829076853", "v2829074511", "v2829079666", "v2829080041", "v2829073416"]

with open('videos.json', encoding='utf-16') as f:
    data = [json.loads(line) for line in f]
    
for v in top_vids:
    for d in data:
        if d['id'] == v:
            print(f"{v}: {d.get('createdAt') or d.get('created_at') or d.get('published_at') or d.get('upload_date')}, Title: {d['title']}")
            break
