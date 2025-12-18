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
from urllib.parse import urlparse, unquote
import os

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

def clean_cctv_name(name: str, name_type: str = "tvg_id") -> str:
    """
    统一清理CCTV相关名称（tvg-id, logo文件名, 频道名称）
    处理规则：
    1. 移除"高清"字样
    2. 标准化命名，明确区分三种情况：
       - 情况A: 明确包含"+"的频道 -> 格式：CCTV5+
       - 情况B: 含有特定后缀（如"体育"）的频道 -> 格式：CCTV5-体育
       - 情况C: 普通数字频道 -> 格式：CCTV5
    3. 保留特定后缀：新闻、体育、综艺、电影、少儿、音乐、戏曲、农业、科教
    4. 移除不需要的后缀：综合、HD、UHD、标清等
    """
    if not name:
        return name

    original_name = name

    # 1. 移除"高清"字样
    cleaned = name.replace("高清", "")

    # 2. 处理CCTV频道
    if 'CCTV' in cleaned.upper():
        # 支持格式：CCTV-5, CCTV5, CCTV-5+, CCTV5+, CCTV-5体育, CCTV5-体育
        cctv_match = re.match(r'^(CCTV)[-\s]?(\d+)(.*)$', cleaned, re.IGNORECASE)
        if cctv_match:
            prefix, num, suffix = cctv_match.groups()
            suffix = suffix.strip()

            # 需要保留的特定后缀列表
            preserve_suffixes = ['新闻', '体育', '综艺', '电影', '少儿', '音乐', '戏曲', '农业', '科教']

            # 情况A: 判断是否为“+”频道 (明确包含+或＋)
            if suffix.endswith('+') or suffix.endswith('＋'):
                # 这是明确的CCTV5+频道
                cleaned = f"CCTV{num}+"
            else:
                # 情况B & C: 检查是否有需要保留的特定后缀
                preserved_suffix = ""
                for ps in preserve_suffixes:
                    # 检查后缀是否以特定词结尾，或包含“-特定词”的模式
                    if suffix.endswith(ps) or f"-{ps}" in suffix:
                        preserved_suffix = ps
                        break

                if preserved_suffix:
                    # 情况B: 有特定后缀，格式为 CCTV5-体育
                    cleaned = f"CCTV{num}-{preserved_suffix}"
                else:
                    # 情况C: 普通CCTV数字频道，无特定后缀
                    # 需要移除可能残留的通用后缀（如“综合”、“HD”等）
                    remove_suffixes = ['-综合', '综合', 'HD', 'UHD', 'FHD', '超清', '标清', ' ']
                    temp_suffix = suffix
                    for rs in remove_suffixes:
                        temp_suffix = temp_suffix.replace(rs, "")
                    
                    # 如果清理后suffix还不为空，说明有未处理的杂项，暂时忽略（或可根据需要处理）
                    # 此处主要确保基础格式正确
                    cleaned = f"CCTV{num}"

    # 对于logo处理，确保是有效的文件名
    if name_type == "logo" and cleaned != original_name:
        cleaned = re.sub(r'[<>:"/\\|?*]', '', cleaned)

    # 打印变化日志
    if original_name != cleaned:
        print(f"    {name_type}清理: {original_name} → {cleaned}")

    return cleaned

def clean_tvg_id(tvg_id: str) -> str:
    """清理tvg-id：先纠正拼写错误，再使用统一的CCTV清理方法"""
    # 1. 首先纠正常见的拼写错误
    original_id = tvg_id
    corrected_id = tvg_id
    
    # 纠正 CCVT -> CCTV (V和T颠倒)
    if 'CCVT' in corrected_id.upper():
        corrected_id = corrected_id.upper().replace('CCVT', 'CCTV')
        if original_id != corrected_id:
            print(f"    tvg-id拼写纠正: {original_id} → {corrected_id}")
    
    # 2. 使用统一的CCTV清理方法处理纠正后的ID
    return clean_cctv_name(corrected_id, "tvg_id")

def clean_logo_url(logo_url: str, tvg_id: str = "") -> str:
    """清理logo URL，使用统一的CCTV命名方法"""
    if not logo_url:
        return logo_url
    
    original_logo = logo_url
    
    try:
        # 解析URL
        parsed_url = urlparse(logo_url)
        
        # 获取路径部分
        path = parsed_url.path
        
        # 解码URL编码的路径
        decoded_path = unquote(path)
        
        # 获取文件名和扩展名
        dirname, filename = os.path.split(decoded_path)
        basename, ext = os.path.splitext(filename)
        
        # 使用统一的CCTV清理方法处理文件名
        clean_basename = clean_cctv_name(basename, "logo")
        
        # 如果提供了tvg_id，优先使用tvg_id的命名
        if tvg_id and 'CCTV' in tvg_id.upper():
            # 从tvg_id提取干净的频道名（去除tvg-id=）
            clean_from_tvg = clean_cctv_name(tvg_id, "logo")
            if clean_from_tvg and clean_from_tvg != clean_basename:
                print(f"    根据tvg-id({tvg_id})更新logo名: {clean_basename} → {clean_from_tvg}")
                clean_basename = clean_from_tvg
        
        # 重建路径
        new_filename = clean_basename + ext
        new_path = os.path.join(dirname, new_filename)
        
        # 重新编码路径
        encoded_path = new_path.replace('\\', '/')
        
        # 重建完整URL
        cleaned_logo = parsed_url._replace(path=encoded_path).geturl()
        
        return cleaned_logo
    
    except Exception as e:
        print(f"    logo清理错误({logo_url}): {e}")
        return logo_url

def extract_cctv_number(tvg_id: str) -> int:
    """从CCTV频道ID中提取数字用于排序，处理CCTV5+等特殊情况"""
    if not tvg_id.startswith('CCTV'):
        return 9999  # 非CCTV频道返回大数，排后面
    
    # 匹配CCTV后的数字（支持CCTV5、CCTV5+、CCTV5-体育等格式）
    match = re.search(r'CCTV[-\s]?(\d+)', tvg_id)
    if match:
        try:
            return int(match.group(1))
        except ValueError:
            pass
    
    # 如果没有数字（如CCTV-新闻），返回0使其排在数字频道前面
    return 0

def process_entries(entries: List[Tuple[str, Dict, str]], first_line: str = "") -> List[str]:
    """处理条目：清理、去重、排序"""
    print("🔄 开始处理频道列表...")
    
    # 1. 清理tvg-id并构建新条目（同时清理频道名称）
    processed = []
    for tvg_id, attrs, channel_line in entries:
        # 清理tvg-id
        clean_id = clean_tvg_id(tvg_id)
        
        # 清理频道名称（使用统一的CCTV清理方法）
        if attrs['channel_name']:
            # 先对频道名进行拼写纠正，再清理
            channel_name = attrs['channel_name']
            # 纠正 CCVT -> CCTV (V和T颠倒) - 应用与tvg-id相同的规则
            if 'CCVT' in channel_name.upper():
                corrected_name = channel_name.upper().replace('CCVT', 'CCTV')
                if channel_name != corrected_name:
                    print(f"    频道名拼写纠正: {channel_name} → {corrected_name}")
                clean_name = clean_cctv_name(corrected_name, "channel_name")
            else:
                clean_name = clean_cctv_name(attrs['channel_name'], "channel_name")
        else:
            clean_name = ""
        
        # 清理tvg-logo：使用统一的CCTV命名方法
        clean_logo = clean_logo_url(attrs['tvg-logo'], clean_id)
        
        # 清理group-title：移除"高清"字样
        clean_group = attrs['group-title']
        if clean_group:
            # group-title不需要特殊处理，只移除高清字样
            clean_group = clean_group.replace("高清", "")
        
        # 构建新的频道行
        # 首先构建基础行
        new_line = f'#EXTINF:-1 tvg-id="{clean_id}"'
        
        # 添加清理后的logo
        if clean_logo:
            new_line += f' tvg-logo="{clean_logo}"'
        
        # 添加清理后的group-title
        if clean_group:
            new_line += f' group-title="{clean_group}"'
        
        # 添加频道名称和URL
        new_line += f',{clean_name}\n{attrs["stream_url"]}'
        
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
    
    # 3. 排序（修复排序问题，确保所有CCTV排在卫视前面）
    def sort_key(item):
        tvg_id, _ = item
        
        # 第一优先级：分类权重
        if tvg_id.startswith('CCTV'):
            category_weight = 0  # CCTV权重最高
        elif tvg_id.endswith('卫视') or tvg_id.endswith('卫視'):
            category_weight = 1  # 卫视其次
        else:
            category_weight = 2  # 其他最后
        
        # 第二优先级：CCTV频道按数字排序
        if tvg_id.startswith('CCTV'):
            num = extract_cctv_number(tvg_id)
            return (category_weight, num, tvg_id)
        else:
            return (category_weight, tvg_id)
    
    sorted_items = sorted(unique_dict.items(), key=sort_key)
    
    # 统计各类频道数量
    cctv_count = sum(1 for tvg_id, _ in sorted_items if tvg_id.startswith('CCTV'))
    weishi_count = sum(1 for tvg_id, _ in sorted_items if tvg_id.endswith('卫視') or tvg_id.endswith('卫视'))
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
                channel_name = parts[-1].strip().split('\n')[0]
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
            elif tvg_id.endswith('卫视') or tvg_id.endswith('卫視'):
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
    url = "http://iptv.cqshushu.com/?s=27.46.125.183%3A808&t=hotel&channels=1&format=m3u"
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
    
    # 6. 显示特殊频道处理示例
    print("\n🔍 特殊CCTV频道处理示例:")
    special_examples = []
    
    # 查找有特定后缀的CCTV频道
    special_suffixes = ['综艺', '新闻', '体育', '电影', '少儿', '音乐', '戏曲', '农业', '科教', '+']
    
    for line in result_lines[1:30]:  # 检查前30个频道
        if 'tvg-id="CCTV' in line:
            tvg_id_match = re.search(r'tvg-id="([^"]*)"', line)
            if tvg_id_match:
                tvg_id = tvg_id_match.group(1)
                
                # 检查是否有特殊后缀
                has_special = any(suffix in tvg_id for suffix in special_suffixes)
                
                if has_special:
                    # 获取频道名称
                    channel_name = ""
                    if ',' in line:
                        channel_name = line.split(',')[-1].strip().split('\n')[0]
                    
                    # 获取logo
                    logo_match = re.search(r'tvg-logo="([^"]*)"', line)
                    logo = logo_match.group(1) if logo_match else ""
                    
                    special_examples.append({
                        'tvg_id': tvg_id,
                        'channel_name': channel_name,
                        'logo': logo
                    })
                    
                    if len(special_examples) >= 5:
                        break
    
    if special_examples:
        print("   统一命名处理效果:")
        for i, example in enumerate(special_examples):
            logo_name = example['logo'].split('/')[-1] if example['logo'] else "无logo"
            print(f"     {i+1}. tvg-id: {example['tvg_id']}")
            print(f"         频道名: {example['channel_name']}")
            print(f"         logo: {logo_name}")
            print()
    
    print("="*60)
    print("✅ 脚本执行完成！")
    print("="*60)

if __name__ == "__main__":
    main()
