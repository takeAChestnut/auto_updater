#!/usr/bin/env python3
"""
IPTV列表处理脚本
功能：
1. 从URL获取M3U内容（使用requests库处理403）
2. 去除tvg-id和频道名称中的"高清"字样
3. 根据tvg-id去重（保留最后一个）
4. 按规则排序：CCTV按数字排序 → 卫视 → 其他
5. 保存为CN.m3u
"""

import re
import sys
import requests
from typing import List, Dict, Tuple
from datetime import datetime

def fetch_m3u_content(url: str) -> str:
    """从指定URL获取M3U内容（使用requests库）"""
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
            'Referer': 'http://iptv.cqshushu.com/',  # 添加来源页
        }
        
        # 添加超时设置（10秒连接，30秒读取）
        response = requests.get(url, headers=headers, timeout=(10, 30))
        
        # 检查状态码
        response.raise_for_status()  # 如果状态码不是200，将抛出HTTPError
        
        content = response.text
        print(f"成功获取内容，长度：{len(content)} 字符")
        return content
    except requests.exceptions.HTTPError as e:
        print(f"HTTP错误: {e}")
        if response.status_code == 403:
            print("服务器明确拒绝访问（403 Forbidden）。可能是IP被限制或需要特定Cookie。")
        sys.exit(1)
    except requests.exceptions.Timeout:
        print("请求超时，服务器响应过慢。")
        sys.exit(1)
    except Exception as e:
        print(f"获取内容失败: {e}")
        sys.exit(1)

def parse_m3u(content: str) -> List[Tuple[str, Dict, str, str]]:
    """
    解析M3U内容，返回格式：(tvg_id, attributes, channel_line, first_line)
    新增返回 first_line: 原始的第一行（可能是#EXTM3U头部）
    """
    lines = content.strip().split('\n')
    entries = []
    channel_count = 0
    first_line = ""
    
    # 保存原始的第一行（如果是#EXTM3U头部）
    if lines and lines[0].startswith('#EXTM3U'):
        first_line = lines[0]
        print(f"识别到文件头: {first_line}")
        # 移除第一行，以便后续解析频道条目
        lines = lines[1:]
    
    i = 0
    while i < len(lines):
        if lines[i].startswith('#EXTINF:'):
            extinf_line = lines[i]
            i += 1
            
            # 确保有对应的URL行
            if i < len(lines) and not lines[i].startswith('#'):
                stream_url = lines[i].strip()
                
                # 提取tvg-id
                tvg_id_match = re.search(r'tvg-id="([^"]*)"', extinf_line)
                tvg_id = tvg_id_match.group(1) if tvg_id_match else ""
                
                # 提取tvg-logo
                logo_match = re.search(r'tvg-logo="([^"]*)"', extinf_line)
                tvg_logo = logo_match.group(1) if logo_match else ""
                
                # 提取group-title
                group_match = re.search(r'group-title="([^"]*)"', extinf_line)
                group_title = group_match.group(1) if group_match else ""
                
                # 提取频道名称（EXTINF末尾部分）
                channel_name = ""
                if ',' in extinf_line:
                    channel_name = extinf_line.split(',')[-1].strip()
                
                # 构建标准化的频道行
                channel_line = f'#EXTINF:-1 tvg-id="{tvg_id}"'
                if tvg_logo:
                    channel_line += f' tvg-logo="{tvg_logo}"'
                if group_title:
                    channel_line += f' group-title="{group_title}"'
                channel_line += f',{channel_name}\n{stream_url}'
                
                entries.append((tvg_id, {
                    'tvg-logo': tvg_logo,
                    'group-title': group_title,
                    'channel_name': channel_name,
                    'stream_url': stream_url
                }, channel_line))
                
                channel_count += 1
        i += 1
    
    print(f"📊 解析出 {channel_count} 个频道条目")
    return entries, first_line  # 现在返回两个值：条目和第一行

def clean_tvg_id(tvg_id: str) -> str:
    """清理tvg-id：去除'高清'字样并标准化"""
    # 去除"高清"字样
    cleaned = tvg_id.replace("高清", "")
    
    # 可选：标准化CCTV格式（如"CCTV1" -> "CCTV-1"）
    cctv_match = re.match(r'^CCTV[-\s]?(\d+)', cleaned)
    if cctv_match:
        num = cctv_match.group(1)
        cleaned = f"CCTV-{num}"
    
    return cleaned.strip()

def extract_cctv_number(tvg_id: str) -> int:
    """从CCTV频道ID中提取数字用于排序"""
    if not tvg_id.startswith('CCTV'):
        return 9999  # 非CCTV频道返回大数，排后面
    
    # 匹配CCTV后的数字
    match = re.search(r'CCTV[-\s]?(\d+)', tvg_id)
    if match:
        try:
            return int(match.group(1))
        except ValueError:
            pass
    
    # 如果没有数字（如CCTV-新闻），返回一个大数使其排在数字频道后面
    return 9998

def process_entries(entries: List[Tuple[str, Dict, str]], first_line: str = "") -> List[str]:
    """处理条目：去重、清理、排序"""
    print("🔄 开始处理频道列表...")
    
    def clean_channel_name(channel_name: str) -> str:
        """
        清理频道名称，规则：
        1. 特别处理CCTV频道：将“CCTV1”格式规范化为“CCTV-1”，但保留后续节目名/特性
        2. 去除结尾的通用质量后缀
        3. 保留特性标识如“4K”、“8K”等
        """
        if not channel_name:
            return channel_name

        original_name = channel_name

        # === 规则1：规范CCTV数字格式（保留后续节目名/特性）===
        # 匹配 “CCTV” + 数字 + 任意后续内容
        cctv_match = re.match(r'^(CCTV)[-\s]?(\d+)(.*)$', channel_name, re.IGNORECASE)
        if cctv_match:
            prefix, number, suffix = cctv_match.groups()
            
            # 保留的特定特性后缀列表
            preserved_suffixes = ['4K', '8K', 'K', '新闻', '体育', '电影', '少儿', '音乐', '戏曲', '农业', '科教']
            
            # 检查后缀是否为需要保留的特性
            should_preserve_suffix = False
            preserved_part = ""
            
            for preserve_suffix in preserved_suffixes:
                if suffix.strip().startswith(preserve_suffix):
                    should_preserve_suffix = True
                    preserved_part = suffix.strip()
                    break
            
            # 构建规范化名称
            if should_preserve_suffix:
                channel_name = f"CCTV-{number}{preserved_part}"
            else:
                # 普通CCTV频道，只保留数字部分
                channel_name = f"CCTV-{number}"

        # === 规则2：去除结尾的通用质量后缀（但不删除特性标识）===
        # 只去除纯粹的质量后缀，不删除作为频道标识一部分的
        generic_suffixes = ['高清', '超清', 'HD', 'FHD', 'UHD', '标清', '综合']
        
        # 特殊处理：如果已经是CCTV-4K格式，不要删除K
        if not re.match(r'^CCTV-\d+[48]?K$', channel_name):
            for suffix in generic_suffixes:
                # 检查是否是独立后缀（前面有空格或连字符）
                if channel_name.endswith(suffix):
                    # 确保不是特性标识的一部分
                    if not (suffix == 'HD' and 'CCTV' in channel_name and '新闻' in channel_name):
                        channel_name = channel_name[:-len(suffix)].strip()
                elif channel_name.endswith(f'-{suffix}'):
                    channel_name = channel_name[:-len(suffix)-1].strip()
                elif channel_name.endswith(f' {suffix}'):
                    channel_name = channel_name[:-len(suffix)-1].strip()

        # === 规则3：清理多余的连字符和空格 ===
        channel_name = re.sub(r'\s+', ' ', channel_name).strip()
        channel_name = re.sub(r'-+', '-', channel_name)
        
        # 打印变化日志
        if original_name != channel_name:
            print(f"    频道名称标准化: {original_name} → {channel_name}")
        
        return channel_name
    
    # 1. 清理tvg-id并构建新条目（同时清理频道名称）
    processed = []
    for tvg_id, attrs, channel_line in entries:
        clean_id = clean_tvg_id(tvg_id)
        
        # 使用新的函数清理频道名称
        if attrs['channel_name']:
            clean_name = clean_channel_name(attrs['channel_name'])
        else:
            clean_name = ""
        
        # 更新频道行中的tvg-id和频道名称
        new_line = channel_line.replace(
            f'tvg-id="{tvg_id}"', 
            f'tvg-id="{clean_id}"'
        )
        
        # 如果频道名称有变化，需要替换
        if clean_name and clean_name != attrs['channel_name']:
            # 找到原始的频道名称部分并替换
            name_start = new_line.rfind(',') + 1
            url_start = new_line.rfind('\n')
            if name_start > 0 and url_start > name_start:
                new_line = new_line[:name_start] + clean_name + new_line[url_start:]
        
        processed.append((clean_id, new_line))
    
    # 2. 根据tvg-id去重（保留最后一个）
    unique_dict = {}
    duplicate_count = 0
    for tvg_id, channel_line in processed:
        if tvg_id in unique_dict:
            duplicate_count += 1
        unique_dict[tvg_id] = channel_line
    
    if duplicate_count > 0:
        print(f"🔄 去重操作：移除了 {duplicate_count} 个重复频道")
    print(f"📊 去重后剩余 {len(unique_dict)} 个唯一频道")
    
    # 3. 排序（修复CCTV数字排序问题）
    def sort_key(item):
        tvg_id, _ = item
        
        # 第一优先级：CCTV开头
        if tvg_id.startswith('CCTV'):
            num = extract_cctv_number(tvg_id)
            return (0, num, tvg_id)
        # 第二优先级：以"卫视"结尾
        elif tvg_id.endswith('卫视'):
            return (1, tvg_id)
        # 第三优先级：其他
        else:
            return (2, tvg_id)
    
    sorted_items = sorted(unique_dict.items(), key=sort_key)
    
    # 统计各类频道数量
    cctv_count = sum(1 for tvg_id, _ in sorted_items if tvg_id.startswith('CCTV'))
    weishi_count = sum(1 for tvg_id, _ in sorted_items if tvg_id.endswith('卫视'))
    other_count = len(sorted_items) - cctv_count - weishi_count
    
    print(f"📈 排序结果：CCTV频道 {cctv_count} 个，卫视频道 {weishi_count} 个，其他频道 {other_count} 个")
    
    # 添加M3U文件头 - 使用原始的第一行，如果为空则使用默认
    if first_line:
        result_lines = [first_line]
    else:
        result_lines = ["#EXTM3U"]
    result_lines.extend(line for _, line in sorted_items)
    
    return result_lines

def save_output(result_lines: List[str], filename: str = "CN.m3u"):
    """保存处理结果到文件"""
    output_content = '\n'.join(result_lines)
    
    with open(filename, 'w', encoding='utf-8') as f:
        f.write(output_content)
    
    print(f"💾 处理完成！共 {len(result_lines)-1} 个频道已保存到 {filename}")
    
    # 验证文件
    with open(filename, 'r', encoding='utf-8') as f:
        saved_lines = f.readlines()
    
    print(f"📁 文件验证：实际保存了 {len(saved_lines)} 行")
    
    # 显示文件头
    if saved_lines:
        print(f"📋 文件头: {saved_lines[0].strip()}")
    
    return filename

def preview_results(result_lines: List[str], count: int = 15):
    """预览处理结果"""
    print("\n" + "="*50)
    print("📺 排序后的前15个频道：")
    print("="*50)
    
    cctv_shown = 0
    weishi_shown = 0
    other_shown = 0
    
    # 跳过第一行（文件头）
    for i, line in enumerate(result_lines[1:], 1):
        if i > count:
            break
            
        if line.startswith('#EXTINF:'):
            # 提取频道名称
            parts = line.split(',')
            if len(parts) > 1:
                channel_name = parts[-1].strip()
            else:
                channel_name = line
                
            # 提取tvg-id用于分类显示
            tvg_id_match = re.search(r'tvg-id="([^"]*)"', line)
            tvg_id = tvg_id_match.group(1) if tvg_id_match else ""
            
            # 分类标识
            category = ""
            if tvg_id.startswith('CCTV'):
                category = "[CCTV]"
                cctv_shown += 1
            elif tvg_id.endswith('卫视'):
                category = "[卫视]"
                weishi_shown += 1
            else:
                category = "[其他]"
                other_shown += 1
            
            print(f"  {i:2d}. {category} {channel_name}")
    
    print("="*50)
    print(f"预览统计: CCTV {cctv_shown} 个, 卫视 {weishi_shown} 个, 其他 {other_shown} 个")

def main():
    """主函数"""
    print("="*60)
    print("🎬 IPTV列表处理脚本")
    print(f"🕒 开始时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("="*60)
    
    # 目标URL
    url = "http://iptv.cqshushu.com/?s=218.15.183.23%3A9901&t=hotel&channels=1&format=m3u"
    print(f"🌐 目标URL: {url}")
    
    # 1. 获取内容
    content = fetch_m3u_content(url)
    
    # 2. 解析内容（现在返回两个值：entries和first_line）
    entries, first_line = parse_m3u(content)
    
    if not entries:
        print("❌ 错误：未解析到任何频道条目")
        sys.exit(1)
    
    # 3. 处理条目（传入first_line参数）
    result_lines = process_entries(entries, first_line)
    
    # 4. 保存输出
    output_file = save_output(result_lines)
    
    # 5. 预览结果
    preview_results(result_lines)
    
    # 6. 显示一些示例
    print("\n🔍 CCTV频道排序示例:")
    cctv_examples = []
    for line in result_lines[1:]:  # 跳过文件头
        if len(cctv_examples) >= 10:
            break
        if 'tvg-id="CCTV' in line:
            tvg_id_match = re.search(r'tvg-id="([^"]*)"', line)
            if tvg_id_match:
                # 获取频道名称
                channel_name = ""
                if ',' in line:
                    channel_name = line.split(',')[-1].strip().split('\n')[0]
                cctv_examples.append(f"{tvg_id_match.group(1)} ({channel_name})")
    
    if cctv_examples:
        print("   " + " → ".join(cctv_examples[:5]))
    
    # 7. 显示清理"高清"的效果
    print("\n🧹 清理'高清'字样效果示例:")
    hd_examples = []
    for line in result_lines[1:15]:  # 检查前15个频道
        if '高清' in line:
            # 提取清理前后的对比
            tvg_id_match = re.search(r'tvg-id="([^"]*)"', line)
            if tvg_id_match and '高清' in tvg_id_match.group(1):
                clean_id = clean_tvg_id(tvg_id_match.group(1))
                hd_examples.append(f"{tvg_id_match.group(1)} → {clean_id}")
    
    if hd_examples:
        for example in hd_examples[:3]:
            print(f"   {example}")
    else:
        print("   未发现需要清理'高清'字样的频道")
    
    print("\n" + "="*60)
    print("✅ 脚本执行完成！")
    print("="*60)

if __name__ == "__main__":
    main()
