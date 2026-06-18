# TODO

## Icon 提取 bar 读取 bug（代码分析完成，待 bar 文件验证）

### 匹配链路（已确认正确）

```
protoy.xml icon 字段 → 候选路径扩展(4种) → bar_index 精确匹配 → match_map
→ Pass1: extract_file_data(bar_path, entry) → lz4解压 → DDT解码 → save PNG
```

`cannon` 和 `xppropheavycannon` 走完全相同的链路，proto_icon 相同、候选相同、
`bar_index` 返回相同 `(bar_path, entry)`、`entry['offset']` 相同。
理论上应该产出完全相同的 PNG，但实际上不同。

### 已确认的代码问题

**A. 64-bit offset 截断（`aoe3_bar_extractor.py` 第 67-68 行）**

```python
offset = struct.unpack('<I', f.read(4))[0]   # 只读低 32 位
f.read(4)  # unknown                          # 高 32 位被丢弃
```

头部 `dir_offset` 用了 uint64（第 59 行 `unpack('<Q', ...)`），说明 BAR 格式
支持 8 字节偏移。但 per-file entry 只读了 4 字节 offset + 跳过 4 字节"unknown"。
这 4 字节大概率是 offset 的高 32 位。若条目偏移 >= 4GB，只用低 32 位会 seek 到
错误位置，读到其他 DDT 纹理的数据——解释了 "像游戏截图但不对" 的症状。

**但这种情况下同一 entry 两次读取应得到相同错误数据，无法解释**
cannon 和 xppropheavycannon 的不一致。

### 无法仅从代码确认的点（需要 bar 文件才能验证）

1. **同名条目是否跨 bar 文件存在多份？** `cannon_icon_64.png` 可能同时存在于
   ArtUnitsTextures1.bar 和 ArtUnitsTextures3.bar，各有不同的 offset/size。
   `bar_index` 按名字索引，最后扫描的 bar 文件覆盖前面的，两个单位拿到的
   是同一个 entry——但从代码看，无法解释不一致。

2. **at `4c17635` commit 时 extractor 到底是怎么跑的？** 是否分多次运行？
   中间是否有人工修改？Co-authored-by Cursor 是否做了额外处理？

3. **DDT 解码器对特定纹理是否不稳定？** `decode_ddt_to_png` 对有歧义的
   DXT1/DXT5 数据可能在不同 Pillow 版本下给出不同结果，但同一 run 内应一致。

4. **实际 offset 是否超过 4GB？** 如果 ArtUnitsTextures*.bar 中某些纹理的
   offset 高位非零，修复 64-bit offset 问题后重新提取可能解决。

### 待做（需有 bar 文件的机器）

- [ ] 修复 per-file offset 为 uint64（合并当前 offset 和 unknown 字段）
- [ ] 在 bar 文件机器上重新运行 extractor
- [ ] 运行 `scripts/fix_aoe3_icons.py` 检查是否还有不一致
- [ ] 检查 469 独苗 + 98 variant_copy
