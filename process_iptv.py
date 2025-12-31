#!/usr/bin/env python3
"""
IPTV列表自动化处理脚本 - 集成IP检查功能（优化版）
功能：
1. 访问网页获取所有IP列表
2. 检查每个IP的可用性，跳过节目数为0或状态为"暂时失效"的IP
3. 使用第一个可用IP获取M3U链接
4. 解析M3U内容，提取CCTV5地址进行测试
5. 如果CCTV5地址测试失败，尝试下一个可用IP
6. 选择CCTV5测试通过的IP重新获取M3U并处理
7. 保存为CN.m3u
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
from playwright.sync_api import sync_playwright

# ==================== IP检查功能 ====================
def test_cctv5_url(cctv5_url: str) -> bool:
    """测试CCTV5地址的可用性"""
    print(f"\n🎯 测试CCTV5地址: {cctv5_url}")
    print("-" * 60)
    
    # 方法1：直接连接测试
    method1_result = simple_test(cctv5_url)
    
    # 方法2：下载测试
    method2_result = download_test(cctv5_url, test_duration=2)
    
    # 汇总结果
    print(f"\n测试结果:")
    print(f"  直接连接测试: {'✓ 成功' if method1_result else '✗ 失败'}")
    print(f"  下载测试: {'✓ 成功' if method2_result else '✗ 失败'}")
    
    success_count = sum([method1_result, method2_result])
    
    if success_count == 2:
        print(f"\n✅ CCTV5地址可用！")
        return True
    elif success_count == 1:
        print(f"\n⚠️  CCTV5地址可能可用")
        return True  # 部分成功也认为是可用
    else:
        print(f"\n❌ CCTV5地址不可用")
        return False

def simple_test(url):
    """最简单的测试：直接尝试连接并接收数据"""
    try:
        parsed = urlparse(url)
        host = parsed.hostname
        port = parsed.port or 80
        
        # 创建socket连接
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(5)
        
        sock.connect((host, port))
        
        # 发送HTTP GET请求
        path = parsed.path or '/'
        request = f"GET {path} HTTP/1.1\r\n"
        request += f"Host: {host}:{port}\r\n"
        request += "User-Agent: SimpleStreamTest/1.0\r\n"
        request += "Accept: */*\r\n"
        request += "Connection: close\r\n"
        request += "\r\n"
        
        sock.sendall(request.encode())
        
        # 接收响应头
        response_header = b""
        header_start = time.time()
        
        while True:
            chunk = sock.recv(1024)
            if not chunk:
                break
            
            response_header += chunk
            
            if b"\r\n\r\n" in response_header:
                break
                
            if time.time() - header_start > 3:
                break
        
        if response_header:
            # 接收一些数据体
            data_received = len(response_header)
            max_data = 65536
            data_start = time.time()
            ts_packets = 0
            
            while data_received < max_data:
                try:
                    sock.settimeout(2)
                    chunk = sock.recv(8192)
                    if not chunk:
                        break
                    data_received += len(chunk)
                    
                    # 检查是否为TS流数据
                    if chunk and chunk[0] == 0x47:
                        ts_packets += 1
                        
                except socket.timeout:
                    break
            
            sock.close()
            
            if data_received > 0 and ts_packets > 0:
                print(f"  接收数据: {data_received:,} 字节，TS包: {ts_packets} 个")
                return True
            
        sock.close()
        return False
        
    except Exception as e:
        print(f"  连接错误: {str(e)}")
        return False

def download_test(url, test_duration=2):
    """使用curl下载测试流媒体数据接收"""
    try:
        # 检查curl是否可用
        try:
            subprocess.run(['curl', '--version'], 
                          capture_output=True, 
                          check=True,
                          timeout=2)
        except:
            print("  未找到curl，跳过下载测试")
            return False
        
        # 临时文件名
        temp_file = "test_cctv5.tmp"
        
        # 构建curl命令
        command = [
            'curl',
            '--silent',
            '--show-error',
            '--max-time', str(test_duration + 5),
            '--connect-timeout', '5',
            '--retry', '0',
            '--user-agent', 'VLC/3.0.18 LibVLC/3.0.18',
            '--header', 'Accept: */*',
            '--header', 'Connection: close',
            '--output', temp_file,
            url
        ]
        
        # 启动curl进程
        process = subprocess.Popen(command)
        
        # 等待指定时间后终止
        try:
            time.sleep(test_duration)
            process.terminate()
            process.wait(timeout=2)
        except:
            process.kill()
        
        # 检查下载的文件
        if os.path.exists(temp_file):
            file_size = os.path.getsize(temp_file)
            
            if file_size > 0:
                # 分析文件内容
                try:
                    with open(temp_file, 'rb') as f:
                        first_packet = f.read(188)
                        
                    if first_packet and first_packet[0] == 0x47:
                        print(f"  下载成功: {file_size:,} 字节，检测到TS流")
                        
                        # 清理临时文件
                        os.remove(temp_file)
                        return True
                except:
                    pass
                
                # 清理临时文件
                os.remove(temp_file)
            
        return False
        
    except Exception:
        # 清理临时文件
        if os.path.exists(temp_file):
            os.remove(temp_file)
        return False

# ==================== 自动化获取M3U链接部分 ====================
def get_available_ips() -> List[Dict]:
    """获取所有可用的IP地址列表"""
    print("🔍 获取可用IP地址列表...")
    
    with sync_playwright() as p:
        try:
            browser = p.chromium.launch(
                headless=True,
                args=[
                    '--no-sandbox',
                    '--disable-dev-shm-usage',
                    '--disable-gpu',
                    '--disable-setuid-sandbox',
                ]
            )
            
            context = browser.new_context(
                viewport={'width': 1280, 'height': 720},
                user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                ignore_https_errors=True
            )
            
            page = context.new_page()
            page.set_default_timeout(30000)
            page.set_default_navigation_timeout(30000)
            
            # 访问首页
            print("访问首页...")
            page.goto(
                "https://iptv.cqshushu.com/?t=multicast&province=all&limit=6&hotel_page=1&multicast_page=1",
                wait_until="domcontentloaded",
                timeout=30000
            )
            
            time.sleep(2)
            
            # 查找所有可用的IP地址
            print("查找所有可用IP地址...")
            find_result = page.evaluate("""() => {
                try {
                    const table = document.querySelector('table');
                    if (!table) {
                        return {success: false, error: '未找到表格'};
                    }
                    
                    const tbody = table.querySelector('tbody');
                    if (!tbody) {
                        return {success: false, error: '未找到tbody'};
                    }
                    
                    const rows = tbody.querySelectorAll('tr');
                    if (!rows || rows.length === 0) {
                        return {success: false, error: '未找到表格行'};
                    }
                    
                    const availableIPs = [];
                    
                    for (let i = 0; i < rows.length; i++) {
                        const row = rows[i];
                        const cells = row.querySelectorAll('td');
                        
                        if (cells.length >= 6) {
                            const ipCell = cells[0];
                            const programCountCell = cells[1];
                            const statusCell = cells[5];
                            
                            if (ipCell && programCountCell && statusCell) {
                                const ipText = ipCell.textContent.trim();
                                const programCountText = programCountCell.textContent.trim();
                                const statusText = statusCell.textContent.trim();
                                
                                // 检查节目数是否为0
                                const programCount = parseInt(programCountText);
                                const isProgramCountValid = !isNaN(programCount) && programCount > 0;
                                
                                // 检查状态是否为"暂时失效"
                                const isStatusValid = !statusText.includes('暂时失效') && 
                                                    !statusText.includes('失效') &&
                                                    !statusText.includes('下线');
                                
                                if (isProgramCountValid && isStatusValid) {
                                    availableIPs.push({
                                        ip: ipText,
                                        programCount: programCountText,
                                        status: statusText,
                                        rowIndex: i
                                    });
                                }
                            }
                        }
                    }
                    
                    return {
                        success: true,
                        ips: availableIPs
                    };
                } catch (error) {
                    return {success: false, error: error.toString()};
                }
            }""")
            
            if not find_result['success']:
                raise Exception(f"获取IP列表失败: {find_result.get('error', '未知错误')}")
            
            available_ips = find_result.get('ips', [])
            print(f"找到 {len(available_ips)} 个可用IP地址")
            
            browser.close()
            return available_ips
            
        except Exception as e:
            print(f"❌ 获取IP列表失败: {str(e)}")
            try:
                browser.close()
            except:
                pass
            raise

def get_m3u_url_for_ip(ip_info: Dict) -> str:
    """为指定IP获取M3U下载链接"""
    ip_with_port = ip_info['ip']
    row_index = ip_info['rowIndex']
    
    print(f"\n🔄 为IP {ip_with_port} 获取M3U链接...")
    
    with sync_playwright() as p:
        try:
            browser = p.chromium.launch(
                headless=True,
                args=[
                    '--no-sandbox',
                    '--disable-dev-shm-usage',
                    '--disable-gpu',
                    '--disable-setuid-sandbox',
                ]
            )
            
            context = browser.new_context(
                viewport={'width': 1280, 'height': 720},
                user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                ignore_https_errors=True
            )
            
            page = context.new_page()
            page.set_default_timeout(30000)
            page.set_default_navigation_timeout(30000)
            
            # 访问首页
            page.goto(
                "https://iptv.cqshushu.com/?t=multicast&province=all&limit=6&hotel_page=1&multicast_page=1",
                wait_until="domcontentloaded",
                timeout=30000
            )
            
            time.sleep(2)
            
            # 点击指定的IP地址
            click_result = page.evaluate("""(rowIndex) => {
                try {
                    const table = document.querySelector('table');
                    const tbody = table.querySelector('tbody');
                    const rows = tbody.querySelectorAll('tr');
                    
                    if (rowIndex >= 0 && rowIndex < rows.length) {
                        const selectedRow = rows[rowIndex];
                        const firstCell = selectedRow.querySelector('td');
                        
                        if (firstCell) {
                            if (firstCell.querySelector('a')) {
                                firstCell.querySelector('a').click();
                            } else {
                                firstCell.click();
                            }
                            return {success: true};
                        }
                    }
                    return {success: false, error: '无法点击指定行的IP'};
                } catch (error) {
                    return {success: false, error: error.toString()};
                }
            }""", row_index)
            
            if not click_result['success']:
                raise Exception(f"点击IP地址失败: {click_result.get('error', '未知错误')}")
            
            # 等待跳转到第二个页面
            time.sleep(3)
            
            # 点击"查看频道列表"按钮
            button_found = False
            button_selectors = [
                'a:has-text("查看频道列表")',
                'button:has-text("查看频道列表")',
                ':text("查看频道列表")',
                'a:has-text("频道列表")',
                'button:has-text("频道列表")',
            ]
            
            for selector in button_selectors:
                try:
                    element = page.locator(selector).first
                    if element.is_visible(timeout=5000):
                        element.click()
                        button_found = True
                        break
                except:
                    continue
            
            if not button_found:
                button_clicked = page.evaluate("""() => {
                    const elements = document.querySelectorAll('a, button, span, div');
                    for (let elem of elements) {
                        const text = elem.textContent || elem.innerText || '';
                        if (text.includes('查看频道列表') || text.includes('频道列表')) {
                            if (elem.click) {
                                elem.click();
                                return true;
                            }
                        }
                    }
                    return false;
                }""")
                
                if button_clicked:
                    button_found = True
            
            if not button_found:
                raise Exception("未找到'查看频道列表'按钮")
            
            # 等待跳转到第三个页面
            time.sleep(3)
            
            # 获取"M3U下载"链接
            m3u_element = page.locator('a:has-text("M3U下载")').first
            
            if not m3u_element.is_visible(timeout=10000):
                m3u_href = page.evaluate("""() => {
                    const allLinks = document.querySelectorAll('a');
                    for (let link of allLinks) {
                        const text = link.textContent || link.innerText || '';
                        if (text.includes('M3U下载')) {
                            return link.getAttribute('href');
                        }
                    }
                    return null;
                }""")
                
                if not m3u_href:
                    raise Exception("未找到'M3U下载'链接")
            else:
                m3u_href = m3u_element.get_attribute('href')
            
            if not m3u_href:
                raise Exception("M3U链接href属性为空")
            
            # 构造完整的M3U下载链接
            if m3u_href.startswith('?'):
                full_m3u_url = f"https://iptv.cqshushu.com/{m3u_href}"
            elif m3u_href.startswith('/?'):
                full_m3u_url = f"https://iptv.cqshushu.com{m3u_href}"
            elif m3u_href.startswith('http'):
                full_m3u_url = m3u_href
            else:
                full_m3u_url = f"https://iptv.cqshushu.com/?{m3u_href}"
            
            browser.close()
            
            print(f"✅ 获取到M3U链接: {full_m3u_url}")
            return full_m3u_url
            
        except Exception as e:
            print(f"❌ 获取M3U链接失败: {str(e)}")
            try:
                browser.close()
            except:
                pass
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

# ==================== M3U处理部分 ====================
def fetch_m3u_content(url: str) -> str:
    """从指定URL获取M3U内容"""
    print("📥 正在下载M3U文件内容...")
    
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
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
    print("="*60)
    print("🎬 IPTV列表自动化处理脚本 - 带IP检查功能")
    print(f"🕒 开始时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("="*60)
    
    try:
        # 第一步：获取所有可用IP
        print("\n📋 第一步：获取可用IP列表")
        print("-"*60)
        available_ips = get_available_ips()
        
        if not available_ips:
            print("❌ 未找到可用IP地址")
            sys.exit(1)
        
        print(f"找到 {len(available_ips)} 个可用IP:")
        for i, ip_info in enumerate(available_ips, 1):
            print(f"  {i}. IP: {ip_info['ip']}, 节目数: {ip_info['programCount']}, 状态: {ip_info['status']}")
        
        # 第二步：逐个测试IP，直到找到CCTV5可用的IP
        print("\n📋 第二步：测试IP的CCTV5地址可用性")
        print("-"*60)
        
        selected_ip = None
        selected_m3u_url = None
        
        for ip_info in available_ips:
            ip_with_port = ip_info['ip']
            print(f"\n测试IP: {ip_with_port}")
            
            try:
                # 获取该IP的M3U链接
                m3u_url = get_m3u_url_for_ip(ip_info)
                
                # 下载M3U内容
                m3u_content = fetch_m3u_content(m3u_url)
                
                # 提取CCTV5地址
                cctv5_url = extract_cctv5_url(m3u_content)
                
                if cctv5_url:
                    # 测试CCTV5地址
                    if test_cctv5_url(cctv5_url):
                        selected_ip = ip_info
                        selected_m3u_url = m3u_url
                        print(f"\n✅ 找到可用IP: {ip_with_port}")
                        break
                    else:
                        print(f"❌ IP {ip_with_port} 的CCTV5地址不可用，尝试下一个IP")
                else:
                    print(f"⚠️  IP {ip_with_port} 的M3U中没有CCTV5地址，尝试下一个IP")
                    
            except Exception as e:
                print(f"❌ 处理IP {ip_with_port} 时出错: {str(e)}，尝试下一个IP")
                continue
        
        if not selected_ip:
            print("\n❌ 所有IP的CCTV5地址都不可用")
            sys.exit(1)
        
        # 第三步：处理选中的IP的M3U内容
        print("\n📋 第三步：处理M3U内容")
        print("-"*60)
        print(f"使用IP: {selected_ip['ip']}")
        
        # 重新获取M3U内容（确保是最新的）
        final_m3u_content = fetch_m3u_content(selected_m3u_url)
        
        # 处理M3U内容
        processed_content = process_m3u_content(final_m3u_content)
        
        # 保存到文件
        output_file = "CN.m3u"
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write(processed_content)
        
        # 统计频道数量
        channel_count = processed_content.count('#EXTINF:')
        print(f"\n✅ 处理完成！")
        print(f"📁 输出文件: {output_file}")
        print(f"📺 频道数量: {channel_count} 个")
        
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
        
        print("\n" + "="*60)
        print("✅ 脚本执行完成！")
        print("="*60)
        
    except Exception as e:
        print(f"\n❌ 脚本执行失败: {str(e)}")
        sys.exit(1)

if __name__ == "__main__":
    main()
