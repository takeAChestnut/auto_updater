#!/usr/bin/env python3
"""
IPTV列表自动化处理脚本
功能：
1. 自动从IPTV网站获取M3U链接
2. 处理M3U内容（清理、去重、排序）
3. 保存为CN.m3u
"""

import re
import sys
import requests
import time
from typing import List, Dict, Tuple
from datetime import datetime
from urllib.parse import urlparse, unquote
import os

# ==================== 自动化获取M3U链接部分 ====================
from playwright.sync_api import sync_playwright

def get_m3u_url() -> str:
    """自动化获取M3U下载链接"""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        page = browser.new_page()
        page.set_default_timeout(60000)
        
        try:
            print("1. 正在访问初始页面...")
            page.goto("https://iptv.cqshushu.com/?t=multicast&province=all&limit=6&hotel_page=1&multicast_page=1")
            page.wait_for_selector("table")
            time.sleep(2)
            
            print("2. 点击第一行第一列...")
            page.evaluate('''() => {
                const table = document.querySelector('table');
                const firstCell = table.querySelector('tbody tr td');
                if (firstCell.querySelector('a')) {
                    firstCell.querySelector('a').click();
                } else {
                    firstCell.click();
                }
            }''')
            
            try:
                page.wait_for_event('framenavigated', timeout=10000)
                print("✅ 第一次页面跳转成功")
            except:
                print("⚠️ 未检测到跳转，但继续执行...")
            
            time.sleep(3)
            
            print("3. 寻找并点击'查看频道列表'按钮...")
            
            # 查找按钮
            button_selectors = [
                "a:has-text('查看频道列表')", 
                "button:has-text('查看频道列表')",
                "text='查看频道列表'",
            ]
            
            button_found = False
            for selector in button_selectors:
                try:
                    element = page.locator(selector).first
                    if element.is_visible(timeout=3000):
                        print(f"✅ 找到按钮: 使用选择器 '{selector}'")
                        element.click()
                        button_found = True
                        break
                except:
                    continue
            
            if not button_found:
                # 备用方案
                page.locator("a:has-text('查看频道列表')").first.click()
                button_found = True
            
            if button_found:
                print("4. 按钮点击成功，等待页面跳转...")
                
                try:
                    page.wait_for_event('framenavigated', timeout=10000)
                    print("✅ 第二次页面跳转成功")
                except:
                    print("⚠️ 未检测到跳转，继续等待...")
                
                time.sleep(3)
                
                print(f"当前页面URL: {page.url}")
                
                print("5. 定位'M3U下载'链接...")
                m3u_link_element = page.locator('a:has-text("M3U下载")').first
                if m3u_link_element.is_visible():
                    m3u_url = m3u_link_element.get_attribute('href')
                    print(f"获取到的参数：{m3u_url}")
                    
                    # 构造完整的M3U下载链接
                    base_url = "https://iptv.cqshushu.com/?"
                    full_m3u_url = base_url + m3u_url.lstrip("?") if m3u_url.startswith("?") else base_url + "?" + m3u_url
                    
                    print(f"✅ 完整的M3U下载链接：{full_m3u_url}")
                    return full_m3u_url
                else:
                    print("❌ 未找到可见的M3U下载链接")
                    sys.exit(1)
            else:
                print("❌ 无法找到'查看频道列表'按钮")
                sys.exit(1)
                
        except Exception as e:
            print(f"❌ 自动化过程出错: {str(e)}")
            sys.exit(1)
        finally:
            browser.close()

# ==================== M3U处理部分 ====================
def fetch_m3u_content(url: str) -> str:
    """从指定URL获取M3U内容（使用requests库）"""
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
            'Referer': 'http://iptv.cqshushu.com/',
        }
        
        response = requests.get(url, headers=headers, timeout=(10, 30))
        response.raise_for_status()
        
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
    """
    lines = content.strip().split('\n')
    entries = []
    channel_count = 0
    first_line = ""
    
    if lines and lines[0].startswith('#EXTM3U'):
        first_line = lines[0]
        print(f"识别到文件头: {first_line}")
        lines = lines[1:]
    
    i = 0
    while i < len(lines):
        if lines[i].startswith('#EXTINF:'):
            extinf_line = lines[i]
            i += 1
            
            if i < len(lines) and not lines[i].startswith('#'):
                stream_url = lines[i].strip()
                
                tvg_id_match = re.search(r'tvg-id="([^"]*)"', extinf_line)
                tvg_id = tvg_id_match.group(1) if tvg_id_match else ""
                
                logo_match = re.search(r'tvg-logo="([^"]*)"', extinf_line)
                tvg_logo = logo_match.group(1) if logo_match else ""
                
                group_match = re.search(r'group-title="([^"]*)"', extinf_line)
                group_title = group_match.group(1) if group_match else ""
                
                channel_name = ""
                if ',' in extinf_line:
                    channel_name = extinf_line.split(',')[-1].strip()
                
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
    return entries, first_line

def clean_cctv_name(name: str, name_type: str = "tvg_id") -> str:
    """统一清理CCTV相关名称"""
    if not name:
        return name

    original_name = name
    cleaned = name.replace("高清", "")

    if 'CCTV' in cleaned.upper():
        cctv_match = re.match(r'^(CCTV)[-\s]?(\d+)(.*)$', cleaned, re.IGNORECASE)
        if cctv_match:
            prefix, num, suffix = cctv_match.groups()
            suffix = suffix.strip()

            preserve_suffixes = ['新闻', '体育', '综艺', '电影', '少儿', '音乐', '戏曲', '农业', '科教']

            if suffix.endswith('+') or suffix.endswith('＋'):
                cleaned = f"CCTV{num}+"
            else:
                preserved_suffix = ""
                for ps in preserve_suffixes:
                    if suffix.endswith(ps) or f"-{ps}" in suffix:
                        preserved_suffix = ps
                        break

                if preserved_suffix:
                    cleaned = f"CCTV{num}-{preserved_suffix}"
                else:
                    remove_suffixes = ['-综合', '综合', 'HD', 'UHD', 'FHD', '超清', '标清', ' ']
                    temp_suffix = suffix
                    for rs in remove_suffixes:
                        temp_suffix = temp_suffix.replace(rs, "")
                    cleaned = f"CCTV{num}"

    if name_type == "logo" and cleaned != original_name:
        cleaned = re.sub(r'[<>:"/\\|?*]', '', cleaned)

    if original_name != cleaned:
        print(f"    {name_type}清理: {original_name} → {cleaned}")

    return cleaned

def clean_tvg_id(tvg_id: str) -> str:
    """清理tvg-id"""
    original_id = tvg_id
    corrected_id = tvg_id
    
    if 'CCVT' in corrected_id.upper():
        corrected_id = corrected_id.upper().replace('CCVT', 'CCTV')
        if original_id != corrected_id:
            print(f"    tvg-id拼写纠正: {original_id} → {corrected_id}")
    
    return clean_cctv_name(corrected_id, "tvg_id")

def clean_logo_url(logo_url: str, tvg_id: str = "") -> str:
    """清理logo URL"""
    if not logo_url:
        return logo_url
    
    original_logo = logo_url
    
    try:
        parsed_url = urlparse(logo_url)
        path = parsed_url.path
        decoded_path = unquote(path)
        dirname, filename = os.path.split(decoded_path)
        basename, ext = os.path.splitext(filename)
        
        clean_basename = clean_cctv_name(basename, "logo")
        
        if tvg_id and 'CCTV' in tvg_id.upper():
            clean_from_tvg = clean_cctv_name(tvg_id, "logo")
            if clean_from_tvg and clean_from_tvg != clean_basename:
                print(f"    根据tvg-id({tvg_id})更新logo名: {clean_basename} → {clean_from_tvg}")
                clean_basename = clean_from_tvg
        
        new_filename = clean_basename + ext
        new_path = os.path.join(dirname, new_filename)
        encoded_path = new_path.replace('\\', '/')
        cleaned_logo = parsed_url._replace(path=encoded_path).geturl()
        
        return cleaned_logo
    
    except Exception as e:
        print(f"    logo清理错误({logo_url}): {e}")
        return logo_url

def extract_cctv_number(tvg_id: str) -> int:
    """从CCTV频道ID中提取数字用于排序"""
    if not tvg_id.startswith('CCTV'):
        return 9999
    
    match = re.search(r'CCTV[-\s]?(\d+)', tvg_id)
    if match:
        try:
            return int(match.group(1))
        except ValueError:
            pass
    
    return 0

def process_entries(entries: List[Tuple[str, Dict, str]], first_line: str = "") -> List[str]:
    """处理条目：清理、去重、排序"""
    print("🔄 开始处理频道列表...")
    
    processed = []
    for tvg_id, attrs, channel_line in entries:
        clean_id = clean_tvg_id(tvg_id)
        
        if attrs['channel_name']:
            channel_name = attrs['channel_name']
            if 'CCVT' in channel_name.upper():
                corrected_name = channel_name.upper().replace('CCVT', 'CCTV')
                if channel_name != corrected_name:
                    print(f"    频道名拼写纠正: {channel_name} → {corrected_name}")
                clean_name = clean_cctv_name(corrected_name, "channel_name")
            else:
                clean_name = clean_cctv_name(attrs['channel_name'], "channel_name")
        else:
            clean_name = ""
        
        clean_logo = clean_logo_url(attrs['tvg-logo'], clean_id)
        
        clean_group = attrs['group-title']
        if clean_group:
            clean_group = clean_group.replace("高清", "")
        
        new_line = f'#EXTINF:-1 tvg-id="{clean_id}"'
        if clean_logo:
            new_line += f' tvg-logo="{clean_logo}"'
        if clean_group:
            new_line += f' group-title="{clean_group}"'
        new_line += f',{clean_name}\n{attrs["stream_url"]}'
        
        processed.append((clean_id, new_line))
    
    unique_dict = {}
    duplicate_count = 0
    for tvg_id, channel_line in processed:
        if tvg_id in unique_dict:
            duplicate_count += 1
        unique_dict[tvg_id] = channel_line
    
    if duplicate_count > 0:
        print(f"🔄 去重操作：移除了 {duplicate_count} 个重复频道")
    print(f"📊 去重后剩余 {len(unique_dict)} 个唯一频道")
    
    def sort_key(item):
        tvg_id, _ = item
        
        if tvg_id.startswith('CCTV'):
            category_weight = 0
        elif tvg_id.endswith('卫视') or tvg_id.endswith('卫視'):
            category_weight = 1
        else:
            category_weight = 2
        
        if tvg_id.startswith('CCTV'):
            num = extract_cctv_number(tvg_id)
            return (category_weight, num, tvg_id)
        else:
            return (category_weight, tvg_id)
    
    sorted_items = sorted(unique_dict.items(), key=sort_key)
    
    cctv_count = sum(1 for tvg_id, _ in sorted_items if tvg_id.startswith('CCTV'))
    weishi_count = sum(1 for tvg_id, _ in sorted_items if tvg_id.endswith('卫視') or tvg_id.endswith('卫视'))
    other_count = len(sorted_items) - cctv_count - weishi_count
    
    print(f"📈 排序结果：CCTV频道 {cctv_count} 个，卫视频道 {weishi_count} 个，其他频道 {other_count} 个")
    
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
    
    return filename

def preview_results(result_lines: List[str], count: int = 15):
    """预览处理结果"""
    print("\n" + "="*50)
    print("📺 排序后的前15个频道：")
    print("="*50)
    
    cctv_shown = 0
    weishi_shown = 0
    other_shown = 0
    
    for i, line in enumerate(result_lines[1:], 1):
        if i > count:
            break
            
        if line.startswith('#EXTINF:'):
            parts = line.split(',')
            if len(parts) > 1:
                channel_name = parts[-1].strip().split('\n')[0]
            else:
                channel_name = line
                
            tvg_id_match = re.search(r'tvg-id="([^"]*)"', line)
            tvg_id = tvg_id_match.group(1) if tvg_id_match else ""
            
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

# ==================== 主函数 ====================
def main():
    """主函数"""
    print("="*60)
    print("🎬 IPTV列表自动化处理脚本")
    print(f"🕒 开始时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("="*60)
    
    # 1. 自动获取M3U链接
    print("🚀 第一阶段：自动获取M3U下载链接")
    m3u_url = get_m3u_url()
    print(f"🌐 获取到M3U链接: {m3u_url}")
    
    print("\n" + "="*60)
    print("🚀 第二阶段：下载并处理M3U内容")
    print("="*60)
    
    # 2. 获取M3U内容
    content = fetch_m3u_content(m3u_url)
    
    # 3. 解析内容
    entries, first_line = parse_m3u(content)
    
    if not entries:
        print("❌ 错误：未解析到任何频道条目")
        sys.exit(1)
    
    # 4. 处理条目
    result_lines = process_entries(entries, first_line)
    
    # 5. 保存输出
    output_file = save_output(result_lines)
    
    # 6. 预览结果
    preview_results(result_lines)
    
    print("="*60)
    print("✅ 脚本执行完成！")
    print("="*60)

if __name__ == "__main__":
    main()
