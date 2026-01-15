#!/usr/bin/env python3
"""
IPTV M3U链接速度测试脚本
从GitHub文件获取M3U链接，测试速度并选择最优的生成CN.m3u

功能：
1. 从GitHub下载available_m3u_urls.txt文件
2. 提取所有M3U链接
3. 对每个M3U链接进行CCTV5速度测试
4. 选择速度最快的链接
5. 下载并处理M3U内容
6. 保存为CN-fast.m3u
"""

import re
import sys
import socket
import time
import os
import requests
import subprocess
from typing import List, Dict, Tuple, Optional
from datetime import datetime
from urllib.parse import urlparse

# ==================== 配置参数 ====================
# GitHub上M3U链接文件的URL
GITHUB_M3U_URLS_FILE = "https://raw.githubusercontent.com/takeAChestnut/auto_updater/refs/heads/main/available_m3u_urls.txt"

# 本地保存M3U链接的文件名
LOCAL_M3U_URLS_FILE = "available_m3u_urls.txt"

# Chrome User-Agent
CHROME_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

# ==================== 文件下载和处理函数 ====================
def download_m3u_urls_from_github() -> List[str]:
    """从GitHub下载M3U链接文件并提取所有URL"""
    print("🔍 从GitHub下载M3U链接文件...")
    print(f"📡 文件URL: {GITHUB_M3U_URLS_FILE}")
    
    try:
        # 下载文件
        headers = {
            'User-Agent': CHROME_UA,
        }
        
        response = requests.get(GITHUB_M3U_URLS_FILE, headers=headers, timeout=30)
        response.raise_for_status()
        
        # 保存到本地文件
        with open(LOCAL_M3U_URLS_FILE, 'w', encoding='utf-8') as f:
            f.write(response.text)
        
        print(f"✅ 已下载文件到 {LOCAL_M3U_URLS_FILE}")
        
        # 提取URL
        urls = []
        lines = response.text.strip().split('\n')
        
        for line in lines:
            line = line.strip()
            if line and line.startswith('http'):  # 只提取以http开头的行
                urls.append(line)
        
        print(f"📋 提取到 {len(urls)} 个M3U链接")
        
        # 显示前几个URL
        if urls:
            print("📋 前5个M3U链接:")
            for i, url in enumerate(urls[:5], 1):
                print(f"  {i}. {url}")
        
        return urls
        
    except Exception as e:
        print(f"❌ 下载M3U链接文件失败: {str(e)}")
        
        # 尝试从本地文件读取（如果存在）
        if os.path.exists(LOCAL_M3U_URLS_FILE):
            print("⚠️  尝试从本地文件读取...")
            try:
                with open(LOCAL_M3U_URLS_FILE, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                urls = []
                lines = content.strip().split('\n')
                
                for line in lines:
                    line = line.strip()
                    if line and line.startswith('http'):
                        urls.append(line)
                
                if urls:
                    print(f"✅ 从本地文件读取到 {len(urls)} 个M3U链接")
                    return urls
            except Exception as e2:
                print(f"❌ 读取本地文件失败: {str(e2)}")
        
        return []

# ==================== 速度测试函数 ====================
def test_ip_download_speed(url: str, test_duration: int = 3) -> Tuple[bool, float]:
    """测试IP下载速度，返回(是否成功, 速度KB/s)"""
    print(f"  测试下载速度: {url}")
    
    temp_file = "test_speed.tmp"
    speed_kb = 0.0
    
    try:
        # 检查curl是否可用
        try:
            subprocess.run(['curl', '--version'], 
                          capture_output=True, 
                          check=True,
                          timeout=2)
        except:
            print("    ⚠️ 未找到curl，跳过下载测试")
            return False, 0.0
        
        # 构建curl命令
        command = [
            'curl',
            '--silent',
            '--show-error',
            '--max-time', str(test_duration + 5),
            '--connect-timeout', '5',
            '--retry', '0',
            '--user-agent', CHROME_UA,
            '--header', 'Accept: */*',
            '--header', 'Connection: close',
            '--output', temp_file,
            url
        ]
        
        # 启动curl进程并记录开始时间
        start_time = time.time()
        process = subprocess.Popen(command)
        
        # 等待指定时间后终止
        try:
            time.sleep(test_duration)
            process.terminate()
            process.wait(timeout=2)
        except:
            try:
                process.kill()
            except:
                pass
        
        # 记录结束时间
        elapsed = time.time() - start_time
        
        # 检查下载的文件
        if os.path.exists(temp_file):
            file_size = os.path.getsize(temp_file)
            
            if file_size > 0:
                # 计算下载速度
                speed_kb = file_size / elapsed / 1024
                
                # 检查是否为有效的流媒体数据
                is_valid_stream = False
                try:
                    with open(temp_file, 'rb') as f:
                        # 读取前几个包检查TS流
                        data = f.read(1024)
                        if len(data) >= 188 and data[0] == 0x47:  # TS包头
                            is_valid_stream = True
                except:
                    pass
                
                if is_valid_stream:
                    print(f"    ✓ 下载成功: {file_size:,} 字节，速度: {speed_kb:.1f} KB/s")
                else:
                    print(f"    ⚠️ 下载完成但非流媒体数据: {file_size:,} 字节，速度: {speed_kb:.1f} KB/s")
                    speed_kb = speed_kb * 0.5  # 非流媒体数据，速度减半
                
                # 清理临时文件
                try:
                    os.remove(temp_file)
                except:
                    pass
                
                return True, speed_kb
            else:
                print(f"    ✗ 下载文件为空")
        else:
            print(f"    ✗ 未下载到文件")
            
        return False, 0.0
        
    except Exception as e:
        print(f"    ✗ 下载测试异常: {str(e)}")
        # 清理临时文件
        try:
            if os.path.exists(temp_file):
                os.remove(temp_file)
        except:
            pass
        return False, 0.0

def test_m3u_url_speed(m3u_url: str) -> Dict:
    """测试单个M3U链接的速度"""
    print(f"\n🔄 测试M3U链接: {m3u_url}")
    
    result = {
        'url': m3u_url,
        'success': False,
        'speed_kb': 0,
        'test_url': '',
        'error': ''
    }
    
    try:
        # 1. 下载M3U内容
        print(f"  1. 下载M3U内容...")
        m3u_content = fetch_m3u_content(m3u_url)
        
        # 2. 提取CCTV5地址作为测试目标
        print(f"  2. 提取测试地址...")
        test_url = extract_cctv5_url(m3u_content)
        
        if not test_url:
            # 如果没有CCTV5，尝试提取第一个可用地址
            lines = m3u_content.strip().split('\n')
            for i, line in enumerate(lines):
                if line.startswith('#EXTINF:') and i + 1 < len(lines):
                    if not lines[i + 1].startswith('#'):
                        test_url = lines[i + 1].strip()
                        print(f"    ⚠️ 未找到CCTV5，使用第一个频道测试: {test_url[:60]}...")
                        break
        
        if test_url:
            result['test_url'] = test_url
            
            # 3. 测试下载速度
            print(f"  3. 测试下载速度(3秒)...")
            success, speed_kb = test_ip_download_speed(test_url, test_duration=3)
            
            if success:
                result['success'] = True
                result['speed_kb'] = speed_kb
                print(f"    ✓ 测试成功，速度: {speed_kb:.1f} KB/s")
            else:
                result['error'] = "下载测试失败"
                print(f"    ✗ 下载测试失败")
        else:
            result['error'] = "未找到测试地址"
            print(f"    ✗ 未找到测试地址")
            
    except Exception as e:
        error_msg = str(e)
        result['error'] = error_msg
        print(f"    ✗ 测试过程中出错: {error_msg}")
    
    return result

def test_all_m3u_urls_speed(m3u_urls: List[str]) -> List[Dict]:
    """测试所有M3U链接的速度"""
    print("\n📊 开始测试所有M3U链接速度")
    print("-"*60)
    
    tested_results = []
    
    for i, m3u_url in enumerate(m3u_urls, 1):
        print(f"\n📡 测试第 {i}/{len(m3u_urls)} 个链接")
        print("-"*40)
        
        result = test_m3u_url_speed(m3u_url)
        tested_results.append(result)
        
        # 如果测试成功，显示当前速度排名
        if result['success']:
            temp_sorted = sorted([r for r in tested_results if r['success']], 
                                key=lambda x: x['speed_kb'], reverse=True)
            rank = temp_sorted.index(result) + 1
            print(f"    📈 当前排名: 第{rank}位 (速度: {result['speed_kb']:.1f} KB/s)")
    
    # 过滤出成功的测试结果并按速度排序
    successful_results = [r for r in tested_results if r['success']]
    successful_results.sort(key=lambda x: x['speed_kb'], reverse=True)
    
    print(f"\n📊 速度测试结果:")
    print("-"*50)
    
    if successful_results:
        print(f"✅ 成功测试 {len(successful_results)}/{len(m3u_urls)} 个链接")
        print("\n🏆 速度排名:")
        
        for i, result in enumerate(successful_results[:10], 1):  # 只显示前10个
            speed_mb = result['speed_kb'] / 1024
            url_display = result['url'][:60] + "..." if len(result['url']) > 60 else result['url']
            print(f"{i:2d}. 速度: {result['speed_kb']:7.1f} KB/s ({speed_mb:.2f} MB/s)")
            print(f"    URL: {url_display}")
        
        if len(successful_results) > 10:
            print(f"... 还有 {len(successful_results) - 10} 个链接未显示")
    else:
        print("❌ 没有成功的测试结果")
    
    return successful_results

# ==================== M3U处理函数 ====================
def fetch_m3u_content(url: str) -> str:
    """从指定URL获取M3U内容"""
    print("📥 正在下载M3U文件内容...")
    print(f"📡 下载链接: {url}")
    
    try:
        headers = {
            'User-Agent': CHROME_UA,
            'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
            'Referer': 'http://iptv.cqshushu.com/',
        }
        
        response = requests.get(url, headers=headers, timeout=(10, 30))
        response.raise_for_status()
        
        content = response.text
        print(f"✅ 成功获取内容，长度: {len(content)} 字符")
        
        if '#EXTM3U' not in content:
            print("⚠️ 警告：下载的内容可能不是标准M3U格式")
        
        return content
        
    except Exception as e:
        print(f"❌ 获取M3U内容失败: {e}")
        raise

def extract_cctv5_url(m3u_content: str) -> Optional[str]:
    """从M3U内容中提取CCTV5的地址"""
    lines = m3u_content.strip().split('\n')
    
    for i, line in enumerate(lines):
        if line.startswith('#EXTINF:'):
            # 检查是否是CCTV5
            if 'CCTV5' in line.upper() or 'CCTV-5' in line:
                # 下一行应该是URL
                if i + 1 < len(lines) and not lines[i + 1].startswith('#'):
                    cctv5_url = lines[i + 1].strip()
                    print(f"找到CCTV5地址: {cctv5_url}")
                    return cctv5_url
    
    print("未找到CCTV5地址")
    return None

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
    """重构tvg-logo URL"""
    if not tvg_id:
        return logo_url
    
    clean_id = clean_tvg_id(tvg_id)
    base_url = "https://gcore.jsdelivr.net/gh/taksssss/tv/icon/"
    new_logo_url = f"{base_url}{clean_id}.png"
    
    return new_logo_url

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

def process_m3u_content(content: str) -> str:
    """处理M3U内容：清理、去重、排序"""
    lines = content.strip().split('\n')
    entries = []
    first_line = ""
    
    # 提取文件头
    if lines and lines[0].startswith('#EXTM3U'):
        first_line = lines[0]
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
                
                # 清理字段
                clean_id = clean_tvg_id(tvg_id)
                
                if channel_name:
                    if 'CCVT' in channel_name.upper():
                        corrected_name = channel_name.upper().replace('CCVT', 'CCTV')
                        clean_name = clean_cctv_name(corrected_name, "channel_name")
                    else:
                        clean_name = clean_cctv_name(channel_name, "channel_name")
                else:
                    clean_name = ""
                
                clean_logo = clean_logo_url(tvg_logo, clean_id)
                
                if group_title:
                    clean_group = group_title.replace("高清", "")
                else:
                    clean_group = ""
                
                # 构建新的频道行
                new_line = f'#EXTINF:-1 tvg-id="{clean_id}"'
                if clean_logo:
                    new_line += f' tvg-logo="{clean_logo}"'
                if clean_group:
                    new_line += f' group-title="{clean_group}"'
                new_line += f',{clean_name}\n{stream_url}'
                
                entries.append((clean_id, new_line))
        i += 1
    
    # 去重
    unique_dict = {}
    duplicate_count = 0
    for tvg_id, channel_line in entries:
        if tvg_id in unique_dict:
            duplicate_count += 1
        unique_dict[tvg_id] = channel_line
    
    if duplicate_count > 0:
        print(f"🔄 去重操作：移除了 {duplicate_count} 个重复频道")
    
    # 排序
    def sort_key(item):
        tvg_id, _ = item
        
        # 分类权重
        # 0: CCTV数字频道 (CCTV1, CCTV2, CCTV13等)
        # 1: 卫视频道 (湖南卫视、浙江卫视等)
        # 2: 纯CCTV (没有数字)
        # 3: 其他频道
        
        if tvg_id == "CCTV":
            # 纯CCTV频道，放在卫视后面
            category_weight = 2
            return (category_weight, tvg_id)
        elif tvg_id.startswith('CCTV'):
            # CCTV数字频道
            category_weight = 0
            num = extract_cctv_number(tvg_id)
            return (category_weight, num, tvg_id)
        elif tvg_id.endswith('卫视') or tvg_id.endswith('卫視'):
            # 卫视频道
            category_weight = 1
            return (category_weight, tvg_id)
        else:
            # 其他频道
            category_weight = 3
            return (category_weight, tvg_id)
    
    sorted_items = sorted(unique_dict.items(), key=sort_key)
    
    # 统计各类频道数量
    cctv_digital_count = sum(1 for tvg_id, _ in sorted_items if tvg_id.startswith('CCTV') and tvg_id != "CCTV")
    cctv_only_count = sum(1 for tvg_id, _ in sorted_items if tvg_id == "CCTV")
    weishi_count = sum(1 for tvg_id, _ in sorted_items if tvg_id.endswith('卫視') or tvg_id.endswith('卫视'))
    other_count = len(sorted_items) - cctv_digital_count - cctv_only_count - weishi_count
    
    print(f"📈 排序结果：CCTV数字频道 {cctv_digital_count} 个，纯CCTV {cctv_only_count} 个，卫视频道 {weishi_count} 个，其他频道 {other_count} 个")
    
    # 显示排序后的前几个频道
    print(f"📺 排序后的前5个频道:")
    for i, (tvg_id, _) in enumerate(sorted_items[:5]):
        print(f"  {i+1}. {tvg_id}")
    
    # 构建结果
    if first_line:
        result_lines = [first_line]
    else:
        result_lines = ["#EXTM3U"]
    result_lines.extend(line for _, line in sorted_items)
    
    return '\n'.join(result_lines)

# ==================== 主函数 ====================
def main():
    """主函数"""
    print("="*70)
    print("🎬 IPTV M3U链接速度测试脚本")
    print("="*70)
    print(f"📡 来源: {GITHUB_M3U_URLS_FILE}")
    print(f"🕒 开始时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("="*70)
    
    try:
        # 第一步：从GitHub下载M3U链接文件
        print("\n📋 第一步：下载M3U链接文件")
        print("-"*60)
        m3u_urls = download_m3u_urls_from_github()
        
        if not m3u_urls:
            print("❌ 未获取到M3U链接")
            sys.exit(1)
        
        # 第二步：测试所有M3U链接的速度
        print("\n📋 第二步：测试M3U链接速度")
        print("-"*60)
        
        successful_results = test_all_m3u_urls_speed(m3u_urls)
        
        if not successful_results:
            print("❌ 所有M3U链接测试都失败")
            sys.exit(1)
        
        # 第三步：选择速度最快的M3U链接
        fastest_result = successful_results[0]
        fastest_url = fastest_result['url']
        
        print(f"\n🏆 选择速度最快的M3U链接:")
        print(f"   速度: {fastest_result['speed_kb']:.1f} KB/s (≈{fastest_result['speed_kb']/1024:.2f} MB/s)")
        print(f"   URL: {fastest_url}")
        
        # 第四步：处理选中的M3U内容
        print("\n📋 第三步：处理M3U内容")
        print("-"*60)
        
        # 下载M3U内容
        final_m3u_content = fetch_m3u_content(fastest_url)
        
        # 处理M3U内容
        processed_content = process_m3u_content(final_m3u_content)
        
        # 保存到文件
        output_file = "CN-fast.m3u"
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write(processed_content)
        
        # 统计频道数量
        channel_count = processed_content.count('#EXTINF:')
        print(f"\n✅ 处理完成！")
        print(f"📁 输出文件: {output_file}")
        print(f"📺 频道数量: {channel_count} 个")
        print(f"🚀 使用URL: {fastest_url[:80]}...")
        print(f"⚡ 测试速度: {fastest_result['speed_kb']:.1f} KB/s (≈{fastest_result['speed_kb']/1024:.2f} MB/s)")
        
        # 预览前10个频道
        print("\n📺 前10个频道预览:")
        print("-"*40)
        lines = processed_content.split('\n')
        count = 0
        for i, line in enumerate(lines):
            if line.startswith('#EXTINF:'):
                if count < 10:
                    # 提取频道名称
                    if ',' in line:
                        channel_name = line.split(',')[-1].strip()
                        print(f"  {count+1}. {channel_name}")
                        count += 1
        
        print("\n" + "="*70)
        print("✅ 脚本执行完成！")
        print("="*70)
        
    except Exception as e:
        print(f"\n❌ 脚本执行失败: {str(e)}")
        sys.exit(1)

if __name__ == "__main__":

    main()
