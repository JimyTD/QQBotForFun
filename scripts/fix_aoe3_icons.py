"""修复 aoe3 icon 不一致：用组内多数派覆盖少数派。"""
import json
import os
import hashlib
import shutil
from collections import Counter

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MANIFEST_PATH = os.path.join(PROJECT_ROOT, 'data', 'aoe3', 'icon_manifest.json')
ICONS_DIR = os.path.join(PROJECT_ROOT, 'resources', 'aoe3', 'icons')

manifest = json.load(open(MANIFEST_PATH, encoding='utf-8'))
entries = manifest['entries']

# 1. 按 bar_entry 分组
by_bar = {}
for uid, info in entries.items():
    be = info.get('bar_entry', '')
    src = info.get('source', '')
    if not be or src not in ('bar', 'bar_alt'):
        continue
    by_bar.setdefault(be, []).append(uid)

# 2. 找组内 MD5 不一致的
fixed, skipped = [], []

for be, uids in sorted(by_bar.items()):
    if len(uids) < 2:
        continue
    md5s = {}
    for uid in uids:
        p = os.path.join(ICONS_DIR, f'{uid}.png')
        if os.path.exists(p):
            md5s[uid] = (hashlib.md5(open(p, 'rb').read()).hexdigest(), os.path.getsize(p))
    unique = set(v[0] for v in md5s.values())
    if len(unique) <= 1:
        continue

    # 多数派 = 正确；1:1 平票时用较大的文件
    md5_votes = Counter(v[0] for v in md5s.values())
    if len(set(md5_votes.values())) == 1 and len(md5_votes) > 1:
        # 平票：按每组中最大文件尺寸排序
        md5_to_max_size = {}
        for uid, (m, sz) in md5s.items():
            md5_to_max_size[m] = max(md5_to_max_size.get(m, 0), sz)
        correct_md5 = max(md5_votes, key=lambda m: md5_to_max_size[m])
    else:
        correct_md5 = md5_votes.most_common(1)[0][0]
    correct_uid = next(uid for uid, (md5, _) in md5s.items() if md5 == correct_md5)
    correct_path = os.path.join(ICONS_DIR, f'{correct_uid}.png')
    correct_size = md5s[correct_uid][1]

    wrong_uids = [uid for uid, (md5, _) in md5s.items() if md5 != correct_md5]
    same_uids = [uid for uid, (md5, _) in md5s.items() if md5 == correct_md5]

    short_be = be.replace('resources\\art\\', '...\\')
    print(f'[{be}]')
    print(f'  correct ({len(same_uids)}): {same_uids}')

    for uid in wrong_uids:
        wrong_path = os.path.join(ICONS_DIR, f'{uid}.png')
        _, wrong_size = md5s[uid]
        print(f'  fix: {uid} ({wrong_size}B -> {correct_size}B, from {correct_uid})')
        shutil.copy2(correct_path, wrong_path)
        fixed.append(uid)

    print()

if fixed:
    print(f'=== fixed {len(fixed)} icons ===')
else:
    print('=== all icons consistent, nothing to fix ===')
