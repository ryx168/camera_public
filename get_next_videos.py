import json
with open('videos.json', encoding='utf-16') as f:
    data = [json.loads(line) for line in f]
    
idx = next(i for i, d in enumerate(data) if d['id'] == 'v2829086396')
print(f"Target video index: {idx}")
print("\nVideos immediately AFTER (chronologically):")
for i in range(idx - 1, idx - 11, -1):
    vid = data[i]['id'][1:]
    print(f"https://www.twitch.tv/videos/{vid}")
