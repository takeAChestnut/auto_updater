#!/usr/bin/env python3
"""
IPTV列表自动化处理脚本 - 集成IP检查功能（优化版）

功能：
1. 访问网页获取所有IP列表
2. 检查每个IP的可用性，跳过节目数为0或状态为"暂时失效"的IP
3. 模拟点击获取完整的IP:端口信息（从URL中提取）
4. 保存所有可用IP的M3U下载链接到文件（每行一个URL）
5. 解析M3U内容，提取CCTV5地址进行测试
6. 如果CCTV5地址测试失败，尝试下一个可用IP
7. 选择CCTV5测试通过的IP重新获取M3U并处理
8. 保存为CN.m3u
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
from urllib.parse import urlparse, unquote
from playwright.sync_api import sync_playwright

# ==================== 配置参数 ====================
# 目标网站URL
TARGET_URL = "https://iptv.cqshushu.com/index.php"

# Chrome User-Agent
CHROME_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

# 保存可用IP链接的文件名
AVAILABLE_IPS_FILE = "available_m3u_urls.txt"  # 纯文本文件，每行一个URL

# M3U下载链接模板
M3U_URL_TEMPLATE = "https://iptv.cqshushu.com/?s={ip_port}&t=multicast&channels=1&download=m3u"

# ==================== M3U链接保存函数 ====================
def save_m3u_urls_to_file(available_ips: List[Dict]):
    """保存所有可用IP的M3U链接到文本文件，每行一个URL"""
    try:
        # 收集所有有效的M3U链接
        m3u_urls = []
        
        for ip_info in available_ips:
            m3u_url = ip_info.get("m3u_url", "")
            if m3u_url:  # 只保存有M3U链接的IP
                m3u_urls.append(m3u_url)
        
        if not m3u_urls:
            print("⚠️ 没有有效的M3U链接需要保存")
            return
        
        # 保存到文件，每行一个URL
        with open(AVAILABLE_IPS_FILE, "w", encoding="utf-8") as f:
            for url in m3u_urls:
                f.write(f"{url}\n")
        
        print(f"✅ 已保存 {len(m3u_urls)} 个M3U链接到 {AVAILABLE_IPS_FILE}")
        
        # 显示前几个URL作为预览
        print(f"📋 前5个M3U链接预览:")
        for i, url in enumerate(m3u_urls[:5], 1):
            print(f"  {i}. {url}")
        
    except Exception as e:
        print(f"❌ 保存M3U链接失败: {str(e)}")

# ==================== IP检查功能 ====================
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

def get_all_m3u_urls(available_ips: List[Dict]) -> List[Dict]:
    """获取所有可用IP的M3U链接（需要点击获取完整IP:端口）"""
    print("\n📋 获取所有可用IP的完整IP:端口并生成M3U链接")
    print("-"*60)
    
    ips_with_m3u = []
    
    for ip_info in available_ips:
        ip_without_port = ip_info['ip']  # 初始只有IP，没有端口
        print(f"\n处理IP: {ip_without_port}")
        
        try:
            # 模拟点击获取完整的IP:端口信息
            print(f"  模拟点击获取完整IP:端口...")
            full_ip_port = get_full_ip_port_from_url(ip_info)
            
            if full_ip_port and ':' in full_ip_port:
                # 使用完整的IP:端口生成M3U链接
                m3u_url = M3U_URL_TEMPLATE.format(ip_port=full_ip_port)
                print(f"  ✓ 生成M3U链接: {m3u_url}")
                
                # 保存完整的IP:端口和M3U链接到IP信息中
                ip_info['full_ip_port'] = full_ip_port
                ip_info['m3u_url'] = m3u_url
                ips_with_m3u.append(ip_info)
            else:
                print(f"  ✗ 获取完整IP:端口失败")
                
        except Exception as e:
            print(f"  ✗ 处理IP {ip_without_port} 时出错: {str(e)}")
            continue
    
    return ips_with_m3u

def get_full_ip_port_from_url(ip_info: Dict) -> str:
    """模拟点击并从URL中提取完整的IP:端口信息"""
    ip_without_port = ip_info['ip']
    row_index = ip_info['rowIndex']
    
    print(f"\n🔄 为IP {ip_without_port} 获取完整IP:端口...")
    
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
                user_agent=CHROME_UA,
                ignore_https_errors=True
            )
            
            page = context.new_page()
            page.set_default_timeout(60000)
            page.set_default_navigation_timeout(60000)
            
            # ====== 第一步：访问首页 ======
            print(f"  1. 访问首页...")
            
            # 设置Referer头部
            page.set_extra_http_headers({
                'Referer': 'https://iptv.cqshushu.com/'
            })
            
            page.goto(
                TARGET_URL,
                wait_until="domcontentloaded",
                timeout=30000
            )
            print(f"    ✓ 首页加载完成")
            
            # 等待组播源列表加载
            try:
                page.wait_for_selector('section.group-section[aria-label*="组播源列表"]', timeout=10000)
                print(f"    ✓ 组播源列表已加载")
            except:
                print(f"    ⚠️  组播源列表加载较慢，继续执行")
            
            # ====== 第二步：点击组播源列表中的IP地址 ======
            print(f"  2. 点击组播源列表中的IP地址...")
            
            click_result = page.evaluate("""(rowIndex) => {
                try {
                    // 先找到组播源列表
                    const groupSections = document.querySelectorAll('section.group-section');
                    let multicastSection = null;
                    
                    for (const section of groupSections) {
                        const ariaLabel = section.getAttribute('aria-label');
                        if (ariaLabel && ariaLabel.includes('组播源列表')) {
                            multicastSection = section;
                            break;
                        }
                    }
                    
                    if (!multicastSection) {
                        console.log('未找到组播源列表section');
                        return {success: false, error: '未找到组播源列表'};
                    }
                    
                    // 在section内查找表格
                    const table = multicastSection.querySelector('table');
                    if (!table) {
                        console.log('未找到表格');
                        return {success: false, error: '未找到表格'};
                    }
                    
                    const tbody = table.querySelector('tbody');
                    if (!tbody) {
                        console.log('未找到tbody');
                        return {success: false, error: '未找到tbody'};
                    }
                    
                    const rows = tbody.querySelectorAll('tr');
                    if (!rows || rows.length === 0) {
                        console.log('未找到行');
                        return {success: false, error: '未找到表格行'};
                    }
                    
                    if (rowIndex >= 0 && rowIndex < rows.length) {
                        const selectedRow = rows[rowIndex];
                        const firstCell = selectedRow.querySelector('td');
                        
                        if (firstCell) {
                            console.log('找到单元格，准备点击');
                            const link = firstCell.querySelector('a');
                            if (link) {
                                link.click();
                                return {success: true};
                            } else {
                                firstCell.click();
                                return {success: true};
                            }
                        }
                    }
                    return {success: false, error: '无法点击指定行的IP'};
                } catch (error) {
                    return {success: false, error: error.toString()};
                }
            }""", row_index)
            
            if not click_result['success']:
                raise Exception(f"点击组播源IP地址失败: {click_result.get('error', '未知错误')}")
            
            print(f"    ✓ 组播源IP地址点击成功")
            
            # 等待页面跳转并获取URL
            print(f"  3. 等待页面跳转...")
            time.sleep(4)
            
            current_url = page.url
            print(f"    ✓ 当前URL: {current_url}")
            
            # ====== 第三步：从URL中提取IP:端口信息 ======
            print(f"  4. 从URL中提取IP:端口信息...")
            
            # 解析URL，查找s参数（包含IP:端口）
            parsed_url = urlparse(current_url)
            
            # 解析查询参数
            query_params = {}
            if parsed_url.query:
                for param in parsed_url.query.split('&'):
                    if '=' in param:
                        key, value = param.split('=', 1)
                        query_params[key] = value
            
            # 检查s参数
            if 's' in query_params:
                ip_port_encoded = query_params['s']
                # 解码URL编码（%3A -> :）
                full_ip_port = unquote(ip_port_encoded)
                print(f"    ✓ 从URL参数中找到IP:端口: {full_ip_port}")
                
                # 验证IP:端口格式
                if re.match(r'^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}:\d+$', full_ip_port):
                    print(f"    ✓ IP:端口格式验证通过")
                    
                    browser.close()
                    print(f"\n✅ 获取到完整IP:端口: {full_ip_port}")
                    return full_ip_port
                else:
                    print(f"    ⚠️  IP:端口格式不正确: {full_ip_port}")
            
            # 如果没有s参数，尝试从URL的其他部分查找
            print(f"    ⚠️  未找到s参数，尝试其他方法...")
            
            # 方法1：在URL中直接查找IP:端口模式
            url_text = current_url
            ip_port_pattern = r'\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}(?:%3A|:)\d+'
            matches = re.findall(ip_port_pattern, url_text)
            
            if matches:
                full_ip_port = matches[0]
                # 替换URL编码的冒号
                full_ip_port = full_ip_port.replace('%3A', ':')
                print(f"    ✓ 从URL中找到IP:端口: {full_ip_port}")
                
                browser.close()
                print(f"\n✅ 获取到完整IP:端口: {full_ip_port}")
                return full_ip_port
            
            # 方法2：如果还没有找到，继续点击"查看频道列表"按钮
            print(f"    ℹ️  继续查找'查看频道列表'按钮...")
            
            # 查找并点击按钮
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
                        print(f"    ✓ 找到按钮: 使用选择器 '{selector}'")
                        
                        element.scroll_into_view_if_needed()
                        time.sleep(1)
                        
                        element.click()
                        button_found = True
                        print(f"    ✓ 按钮点击成功")
                        break
                        
                except Exception as e:
                    continue
            
            if button_found:
                # 等待跳转
                print(f"  5. 等待跳转到频道列表页...")
                time.sleep(4)
                
                final_url = page.url
                print(f"    ✓ 最终URL: {final_url}")
                
                # 从最终URL中提取IP:端口
                parsed_final_url = urlparse(final_url)
                final_query_params = {}
                if parsed_final_url.query:
                    for param in parsed_final_url.query.split('&'):
                        if '=' in param:
                            key, value = param.split('=', 1)
                            final_query_params[key] = value
                
                if 's' in final_query_params:
                    ip_port_encoded = final_query_params['s']
                    full_ip_port = unquote(ip_port_encoded)
                    print(f"    ✓ 从最终URL参数中找到IP:端口: {full_ip_port}")
                    
                    browser.close()
                    print(f"\n✅ 获取到完整IP:端口: {full_ip_port}")
                    return full_ip_port
                
                # 从URL文本中查找
                url_matches = re.findall(ip_port_pattern, final_url)
                if url_matches:
                    full_ip_port = url_matches[0].replace('%3A', ':')
                    print(f"    ✓ 从最终URL中找到IP:端口: {full_ip_port}")
                    
                    browser.close()
                    print(f"\n✅ 获取到完整IP:端口: {full_ip_port}")
                    return full_ip_port
            
            # 如果所有方法都失败
            raise Exception("无法从URL中提取IP:端口信息")
            
        except Exception as e:
            print(f"\n❌ 获取完整IP:端口失败: {str(e)}")
            
            # 确保浏览器关闭
            try:
                browser.close()
            except:
                pass
            
            raise

def test_all_ips_speed(available_ips: List[Dict]) -> List[Dict]:
    """测试所有IP的下载速度并排序"""
    print("\n📊 测试所有IP的下载速度")
    print("-"*60)
    
    tested_ips = []
    
    for ip_info in available_ips:
        ip_with_port = ip_info.get('full_ip_port', ip_info['ip'])
        m3u_url = ip_info.get('m3u_url')
        
        if not m3u_url:
            print(f"\n⚠️  IP {ip_with_port} 没有M3U链接，跳过测试")
            continue
            
        print(f"\n测试IP: {ip_with_port}")
        
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
                # 3. 测试下载速度
                print(f"  3. 测试下载速度(3秒)...")
                success, speed_kb = test_ip_download_speed(test_url, test_duration=3)
                
                if success:
                    # 保存测试结果
                    ip_result = ip_info.copy()
                    ip_result['test_url'] = test_url
                    ip_result['speed_kb'] = speed_kb
                    ip_result['success'] = True
                    tested_ips.append(ip_result)
                else:
                    print(f"    ✗ 下载测试失败")
            else:
                print(f"    ✗ 未找到测试地址")
                
        except Exception as e:
            print(f"    ✗ 处理IP {ip_with_port} 时出错: {str(e)}")
            continue
    
    # 按下载速度排序（从高到低）
    tested_ips.sort(key=lambda x: x.get('speed_kb', 0), reverse=True)
    
    print(f"\n📊 速度测试结果:")
    print("-"*50)
    if tested_ips:
        for i, ip_result in enumerate(tested_ips[:10]):  # 只显示前10个
            speed_mb = ip_result['speed_kb'] / 1024
            print(f"{i+1:2d}. {ip_result.get('full_ip_port', ip_result['ip']):25s} 速度: {ip_result['speed_kb']:7.1f} KB/s ({speed_mb:.2f} MB/s)")
        
        if len(tested_ips) > 10:
            print(f"... 还有 {len(tested_ips) - 10} 个IP未显示")
    else:
        print("❌ 没有可用的IP")
    
    return tested_ips

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
        request += f"User-Agent: {CHROME_UA}\r\n"  # 使用Chrome UA
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
        
        # 构建curl命令 - 使用Chrome User-Agent
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
            process.kill()
        
        # 记录结束时间
        elapsed = time.time() - start_time
        
        # 检查下载的文件
        if os.path.exists(temp_file):
            file_size = os.path.getsize(temp_file)
            
            if file_size > 0:
                # 计算下载速度
                speed_kb = file_size / elapsed / 1024
                speed_mb = speed_kb / 1024
                
                # 分析文件内容
                try:
                    with open(temp_file, 'rb') as f:
                        first_packet = f.read(188)
                        
                    if first_packet and first_packet[0] == 0x47:
                        print(f"  下载成功: {file_size:,} 字节，检测到TS流")
                        print(f"  平均速度: {speed_kb:.1f} KB/s ({speed_mb:.2f} MB/s)")
                        
                        # 清理临时文件
                        os.remove(temp_file)
                        return True
                except:
                    pass
                
                print(f"  下载完成: {file_size:,} 字节")
                print(f"  平均速度: {speed_kb:.1f} KB/s ({speed_mb:.2f} MB/s)")
                
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
    print(f"📡 访问网站: {TARGET_URL}")
    
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
                user_agent=CHROME_UA,  # 使用Chrome UA
                ignore_https_errors=True
            )
            
            page = context.new_page()
            page.set_default_timeout(60000)
            page.set_default_navigation_timeout(60000)
            
            # 访问首页 - 添加Referer头部
            print("  访问首页...")
            
            # 设置Referer头部
            page.set_extra_http_headers({
                'Referer': 'https://iptv.cqshushu.com/'
            })
            
            page.goto(
                TARGET_URL,  # 使用配置的URL
                wait_until="domcontentloaded",
                timeout=60000
            )
            
            time.sleep(2)
            
            # 查找组播源列表中的IP地址
            print("  查找组播源列表中的IP地址...")
            find_result = page.evaluate("""() => {
                try {
                    // 查找组播源列表section
                    const groupSections = document.querySelectorAll('section.group-section');
                    let multicastSection = null;
                    
                    for (const section of groupSections) {
                        const ariaLabel = section.getAttribute('aria-label');
                        if (ariaLabel && ariaLabel.includes('组播源列表')) {
                            multicastSection = section;
                            break;
                        }
                    }
                    
                    if (!multicastSection) {
                        return {success: false, error: '未找到组播源列表section'};
                    }
                    
                    // 在section内查找表格
                    const table = multicastSection.querySelector('table');
                    if (!table) {
                        return {success: false, error: '组播源列表中未找到表格'};
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
                                        rowIndex: i,
                                        sectionType: 'multicast'  // 标记为组播源
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
            print(f"✅ 从组播源列表中找到 {len(available_ips)} 个可用IP地址")
            
            browser.close()
            return available_ips
            
        except Exception as e:
            print(f"❌ 获取IP列表失败: {str(e)}")
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
    print(f"📡 下载链接: {url}")
    
    try:
        headers = {
            'User-Agent': CHROME_UA,  # 使用Chrome UA
            'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
            'Referer': 'https://iptv.cqshushu.com/',
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
    print("🎬 IPTV列表自动化处理脚本 - 带IP检查功能（优化版）")
    print("="*70)
    print(f"📡 目标网站: {TARGET_URL}")
    print(f"🕒 开始时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("="*70)
    
    try:
        # 第一步：获取所有可用IP
        print("\n📋 第一步：获取可用IP列表")
        print("-"*60)
        available_ips = get_available_ips()
        
        if not available_ips:
            print("❌ 未找到可用IP地址")
            sys.exit(1)
        
        print(f"找到 {len(available_ips)} 个组播源可用IP:")
        for i, ip_info in enumerate(available_ips, 1):
            print(f"  {i}. IP: {ip_info['ip']}, 节目数: {ip_info['programCount']}, 状态: {ip_info['status']}")
        
        # 第二步：模拟点击获取完整IP:端口并生成M3U链接
        print("\n📋 第二步：模拟点击获取完整IP:端口并生成M3U链接")
        print("-"*60)
        
        ips_with_m3u = get_all_m3u_urls(available_ips)
        
        if ips_with_m3u:
            # 保存所有M3U链接到文件
            save_m3u_urls_to_file(ips_with_m3u)
        else:
            print("⚠️ 未能获取到任何M3U链接")
            sys.exit(0)
        
        # 第三步：测试所有IP的下载速度并选择最快的
        print("\n📋 第三步：测试所有IP的下载速度")
        print("-"*60)
        
        tested_ips = test_all_ips_speed(ips_with_m3u)
        
        if not tested_ips:
            print("❌ 所有IP测试都失败，但仍已保存M3U链接到文件")
            print("📄 生成的M3U链接文件: available_m3u_urls.txt")
            sys.exit(0)  # 退出码改为0，表示部分成功
        
        # 第四步：选择速度最快的IP
        selected_ip = tested_ips[0]
        selected_m3u_url = selected_ip['m3u_url']
        
        print(f"\n🏆 选择速度最快的IP: {selected_ip.get('full_ip_port', selected_ip['ip'])}")
        print(f"   下载速度: {selected_ip['speed_kb']:.1f} KB/s (≈{selected_ip['speed_kb']/1024:.2f} MB/s)")
        
        # 第五步：处理选中的IP的M3U内容
        print("\n📋 第四步：处理M3U内容")
        print("-"*60)
        print(f"使用IP: {selected_ip.get('full_ip_port', selected_ip['ip'])}")
        
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
        print(f"📄 M3U链接文件: {AVAILABLE_IPS_FILE}")
        print(f"🚀 使用IP: {selected_ip.get('full_ip_port', selected_ip['ip'])} (速度: {selected_ip['speed_kb']:.1f} KB/s)")
        
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
