#!/usr/bin/env python3
"""
IPTV列表自动化处理脚本 - 完整版（三步骤流程）
功能：
1. 访问第一个网页 → 检查第一行IP，如果节目数为0或状态为"暂时失效"则选择下一行，直到找到正常的IP
2. 跳转到第二个网页 → 点击"查看频道列表"按钮  
3. 跳转到第三个网页 → 获取"M3U下载"链接
4. 下载并处理M3U内容（清理、去重、排序）
5. 保存为CN.m3u（修复logo扩展名问题）
"""

import re
import sys
import requests
import time
from typing import List, Dict, Tuple
from datetime import datetime
from urllib.parse import urlparse, unquote, quote
import os

# ==================== 自动化获取M3U链接部分 ====================
from playwright.sync_api import sync_playwright

def get_m3u_url() -> str:
    """
    自动化获取M3U下载链接（完整三步骤）
    流程：首页检查IP → 详情页点击"查看频道列表" → 频道列表页获取M3U链接
    """
    
    print("🚀 第一阶段：自动获取M3U下载链接（三步骤流程）")
    
    with sync_playwright() as p:
        try:
            # 启动浏览器（GitHub Actions使用无头模式）
            browser = p.chromium.launch(
                headless=True, 
                args=[
                    '--no-sandbox', 
                    '--disable-dev-shm-usage',
                    '--disable-gpu',
                    '--disable-setuid-sandbox',
                ]
            )
            
            # 创建浏览器上下文
            context = browser.new_context(
                viewport={'width': 1280, 'height': 720},
                user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                ignore_https_errors=True
            )
            
            page = context.new_page()
            page.set_default_timeout(30000)
            page.set_default_navigation_timeout(30000)
            
            # ========== 第一步：访问第一个网页，查找可用的IP ==========
            print("="*50)
            print("第一步：访问首页并查找可用IP地址")
            print("="*50)
            
            print("1. 正在访问初始页面...")
            page.goto(
                "https://iptv.cqshushu.com/?t=multicast&province=gd&limit=6&hotel_page=1&multicast_page=1",
                wait_until="domcontentloaded",
                timeout=30000
            )
            
            # 等待页面加载
            time.sleep(2)
            
            # 查找可用的IP地址
            print("2. 查找可用的IP地址（检查节目数和状态）...")
            
            # 使用JavaScript查找表格并检查每一行
            find_result = page.evaluate("""() => {
                try {
                    // 查找表格
                    const table = document.querySelector('table');
                    if (!table) {
                        console.error('未找到表格');
                        return {success: false, error: '未找到表格'};
                    }
                    
                    // 获取所有行
                    const tbody = table.querySelector('tbody');
                    if (!tbody) {
                        console.error('未找到tbody');
                        return {success: false, error: '未找到tbody'};
                    }
                    
                    const rows = tbody.querySelectorAll('tr');
                    if (!rows || rows.length === 0) {
                        console.error('未找到表格行');
                        return {success: false, error: '未找到表格行'};
                    }
                    
                    console.log('找到', rows.length, '行数据');
                    
                    // 遍历每一行
                    for (let i = 0; i < rows.length; i++) {
                        const row = rows[i];
                        const cells = row.querySelectorAll('td');
                        
                        if (cells.length >= 6) { // 确保有足够的列
                            const ipCell = cells[0];
                            const programCountCell = cells[1];
                            const statusCell = cells[5];
                            
                            if (ipCell && programCountCell && statusCell) {
                                const ipText = ipCell.textContent.trim();
                                const programCountText = programCountCell.textContent.trim();
                                const statusText = statusCell.textContent.trim();
                                
                                console.log(`第${i+1}行: IP=${ipText}, 节目数=${programCountText}, 状态=${statusText}`);
                                
                                // 检查节目数是否为0
                                const programCount = parseInt(programCountText);
                                const isProgramCountValid = !isNaN(programCount) && programCount > 0;
                                
                                // 检查状态是否为"暂时失效"
                                const isStatusValid = !statusText.includes('暂时失效') && 
                                                    !statusText.includes('失效') &&
                                                    !statusText.includes('下线');
                                
                                if (isProgramCountValid && isStatusValid) {
                                    console.log(`✅ 找到可用IP: ${ipText}，节目数: ${programCountText}，状态: ${statusText}`);
                                    return {
                                        success: true,
                                        rowIndex: i,
                                        ip: ipText,
                                        programCount: programCountText,
                                        status: statusText,
                                        method: 'valid_ip_found'
                                    };
                                } else {
                                    console.log(`❌ 跳过IP ${ipText}: 节目数=${programCountText}, 状态=${statusText}`);
                                }
                            }
                        }
                    }
                    
                    return {
                        success: false, 
                        error: '未找到符合条件的IP地址（所有IP节目数为0或状态为暂时失效）'
                    };
                } catch (error) {
                    return {success: false, error: error.toString()};
                }
            }""")
            
            if not find_result['success']:
                raise Exception(f"未找到可用IP地址: {find_result.get('error', '未知错误')}")
            
            ip_with_port = find_result.get('ip', '')
            program_count = find_result.get('programCount', '')
            status = find_result.get('status', '')
            row_index = find_result.get('rowIndex', 0)
            
            print(f"✅ 找到可用IP地址: {ip_with_port}")
            print(f"   节目数: {program_count}")
            print(f"   状态: {status}")
            print(f"   行号: {row_index + 1}")
            
            # 点击选中的IP地址
            print("3. 点击选中的IP地址...")
            click_result = page.evaluate("""(rowIndex) => {
                try {
                    const table = document.querySelector('table');
                    const tbody = table.querySelector('tbody');
                    const rows = tbody.querySelectorAll('tr');
                    
                    if (rowIndex >= 0 && rowIndex < rows.length) {
                        const selectedRow = rows[rowIndex];
                        const firstCell = selectedRow.querySelector('td');
                        
                        if (firstCell) {
                            // 点击该单元格
                            if (firstCell.querySelector('a')) {
                                firstCell.querySelector('a').click();
                            } else {
                                firstCell.click();
                            }
                            return {success: true, clickedIp: firstCell.textContent.trim()};
                        }
                    }
                    return {success: false, error: '无法点击指定行的IP'};
                } catch (error) {
                    return {success: false, error: error.toString()};
                }
            }""", row_index)
            
            if not click_result['success']:
                raise Exception(f"点击IP地址失败: {click_result.get('error', '未知错误')}")
            
            print(f"✅ 点击IP地址成功: {ip_with_port}")
            
            # 等待跳转到第二个页面
            print("4. 等待跳转到第二个页面（IP详情页）...")
            time.sleep(3)
            
            # 检查当前URL
            current_url = page.url
            print(f"当前URL（第二个页面）: {current_url}")
            
            # ========== 第二步：在第二个网页点击"查看频道列表" ==========
            print("\n" + "="*50)
            print("第二步：点击'查看频道列表'按钮")
            print("="*50)
            
            print("5. 查找并点击'查看频道列表'按钮...")
            
            # 多种方式查找按钮
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
                        print(f"✅ 找到按钮: 使用选择器 '{selector}'")
                        element.click()
                        button_found = True
                        break
                except:
                    continue
            
            # 如果选择器方式失败，使用JavaScript查找
            if not button_found:
                print("使用JavaScript查找按钮...")
                button_clicked = page.evaluate("""() => {
                    const elements = document.querySelectorAll('a, button, span, div');
                    for (let elem of elements) {
                        const text = elem.textContent || elem.innerText || '';
                        if (text.includes('查看频道列表') || text.includes('频道列表')) {
                            console.log('找到按钮文本:', text);
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
                    print("✅ JavaScript找到并点击按钮")
            
            if not button_found:
                raise Exception("未找到'查看频道列表'按钮")
            
            # 等待跳转到第三个页面
            print("6. 等待跳转到第三个页面（频道列表页）...")
            time.sleep(3)
            
            # 检查当前URL
            current_url = page.url
            print(f"当前URL（第三个页面）: {current_url}")
            
            # ========== 第三步：在第三个网页获取"M3U下载"链接 ==========
            print("\n" + "="*50)
            print("第三步：获取'M3U下载'链接")
            print("="*50)
            
            print("7. 查找'M3U下载'链接...")
            
            # 使用Playwright定位包含"M3U下载"文本的链接
            m3u_element = page.locator('a:has-text("M3U下载")').first
            
            if not m3u_element.is_visible(timeout=10000):
                # 备用方法：使用JavaScript查找
                print("Playwright方式未找到，使用JavaScript查找...")
                m3u_href = page.evaluate("""() => {
                    // 查找所有链接
                    const allLinks = document.querySelectorAll('a');
                    for (let link of allLinks) {
                        const text = link.textContent || link.innerText || '';
                        if (text.includes('M3U下载')) {
                            console.log('找到M3U下载链接文本:', text);
                            return link.getAttribute('href');
                        }
                    }
                    return null;
                }""")
                
                if not m3u_href:
                    raise Exception("未找到'M3U下载'链接")
            else:
                # 获取链接的href属性
                m3u_href = m3u_element.get_attribute('href')
            
            if not m3u_href:
                raise Exception("M3U链接href属性为空")
            
            print(f"获取到的链接参数: {m3u_href}")
            
            # 构造完整的M3U下载链接
            # 根据HTML格式，直接拼接基础URL
            if m3u_href.startswith('?'):
                full_m3u_url = f"https://iptv.cqshushu.com/{m3u_href}"
            elif m3u_href.startswith('/?'):
                full_m3u_url = f"https://iptv.cqshushu.com{m3u_href}"
            elif m3u_href.startswith('http'):
                full_m3u_url = m3u_href
            else:
                # 默认情况
                full_m3u_url = f"https://iptv.cqshushu.com/?{m3u_href}"
            
            print(f"✅ 完整的M3U下载链接: {full_m3u_url}")
            
            # 验证链接格式
            if ip_with_port and ':' in ip_with_port:
                port = ip_with_port.split(':')[1]
                if f'%3A{port}' not in full_m3u_url:
                    print(f"⚠️ 注意：链接中可能缺少端口号 {port}")
            
            # 关闭浏览器
            browser.close()
            
            return full_m3u_url
            
        except Exception as e:
            print(f"❌ 获取M3U链接失败: {str(e)}")
            
            # 尝试截图以便调试
            try:
                page.screenshot(path="automation_error.png")
                print("📸 已保存错误截图: automation_error.png")
            except:
                pass
            
            # 确保浏览器关闭
            try:
                browser.close()
            except:
                pass
            
            raise

# ==================== M3U处理部分 ====================
def fetch_m3u_content(url: str) -> str:
    """从指定URL获取M3U内容（使用requests库）"""
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
        
        # 检查是否为有效的M3U文件
        if '#EXTM3U' not in content:
            print("⚠️ 警告：下载的内容可能不是标准M3U格式")
        
        return content
        
    except requests.exceptions.HTTPError as e:
        print(f"HTTP错误: {e}")
        if response.status_code == 403:
            print("服务器拒绝访问（403 Forbidden），可能需要检查网络或Cookie设置")
        sys.exit(1)
    except requests.exceptions.Timeout:
        print("请求超时，服务器响应过慢")
        sys.exit(1)
    except Exception as e:
        print(f"获取内容失败: {e}")
        sys.exit(1)

def parse_m3u(content: str) -> Tuple[List[Tuple[str, Dict, str]], str]:
    """
    解析M3U内容
    返回: (entries, first_line)
    entries格式: (tvg_id, attributes, channel_line)
    """
    lines = content.strip().split('\n')
    entries = []
    channel_count = 0
    first_line = ""
    
    # 提取文件头
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
                
                # 提取tvg-id
                tvg_id_match = re.search(r'tvg-id="([^"]*)"', extinf_line)
                tvg_id = tvg_id_match.group(1) if tvg_id_match else ""
                
                # 提取tvg-logo
                logo_match = re.search(r'tvg-logo="([^"]*)"', extinf_line)
                tvg_logo = logo_match.group(1) if logo_match else ""
                
                # 提取group-title
                group_match = re.search(r'group-title="([^"]*)"', extinf_line)
                group_title = group_match.group(1) if group_match else ""
                
                # 提取频道名称
                channel_name = ""
                if ',' in extinf_line:
                    channel_name = extinf_line.split(',')[-1].strip()
                
                # 构建频道行
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

            # 需要保留的特定后缀
            preserve_suffixes = ['新闻', '体育', '综艺', '电影', '少儿', '音乐', '戏曲', '农业', '科教']

            # 处理CCTV5+等格式
            if suffix.endswith('+') or suffix.endswith('＋'):
                cleaned = f"CCTV{num}+"
            else:
                # 检查是否有需要保留的特定后缀
                preserved_suffix = ""
                for ps in preserve_suffixes:
                    if suffix.endswith(ps) or f"-{ps}" in suffix:
                        preserved_suffix = ps
                        break

                if preserved_suffix:
                    cleaned = f"CCTV{num}-{preserved_suffix}"
                else:
                    # 移除通用后缀
                    remove_suffixes = ['-综合', '综合', 'HD', 'UHD', 'FHD', '超清', '标清', ' ']
                    temp_suffix = suffix
                    for rs in remove_suffixes:
                        temp_suffix = temp_suffix.replace(rs, "")
                    cleaned = f"CCTV{num}"

    # 对logo文件名进行安全处理
    if name_type == "logo" and cleaned != original_name:
        cleaned = re.sub(r'[<>:"/\\|?*]', '', cleaned)

    if original_name != cleaned:
        print(f"    {name_type}清理: {original_name} → {cleaned}")

    return cleaned

def clean_tvg_id(tvg_id: str) -> str:
    """清理tvg-id"""
    original_id = tvg_id
    corrected_id = tvg_id
    
    # 纠正拼写错误 CCVT -> CCTV
    if 'CCVT' in corrected_id.upper():
        corrected_id = corrected_id.upper().replace('CCVT', 'CCTV')
        if original_id != corrected_id:
            print(f"    tvg-id拼写纠正: {original_id} → {corrected_id}")
    
    return clean_cctv_name(corrected_id, "tvg_id")

def clean_logo_url(logo_url: str, tvg_id: str = "") -> str:
    """重构tvg-logo URL，使用固定模板格式"""
    if not tvg_id:
        # 如果没有tvg-id，保持原样
        return logo_url
    
    # 清理tvg-id（去除特殊字符，确保是有效的文件名）
    clean_id = clean_tvg_id(tvg_id)
    
    # 构建新的logo URL
    base_url = "https://gcore.jsdelivr.net/gh/taksssss/tv/icon/"
    new_logo_url = f"{base_url}{clean_id}.png"
    
    # 记录变化
    if logo_url != new_logo_url:
        print(f"    logo重构: {logo_url or '无'} → {new_logo_url}")
    
    return new_logo_url

def extract_cctv_number(tvg_id: str) -> int:
    """从CCTV频道ID中提取数字用于排序"""
    if not tvg_id.startswith('CCTV'):
        return 9999  # 非CCTV频道排后面
    
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
    
    # 1. 清理所有字段
    processed = []
    for tvg_id, attrs, channel_line in entries:
        clean_id = clean_tvg_id(tvg_id)
        
        # 清理频道名称
        if attrs['channel_name']:
            channel_name = attrs['channel_name']
            # 纠正拼写错误
            if 'CCVT' in channel_name.upper():
                corrected_name = channel_name.upper().replace('CCVT', 'CCTV')
                if channel_name != corrected_name:
                    print(f"    频道名拼写纠正: {channel_name} → {corrected_name}")
                clean_name = clean_cctv_name(corrected_name, "channel_name")
            else:
                clean_name = clean_cctv_name(attrs['channel_name'], "channel_name")
        else:
            clean_name = ""
        
        # 清理logo（确保有扩展名）
        clean_logo = clean_logo_url(attrs['tvg-logo'], clean_id)
        
        # 清理group-title
        clean_group = attrs['group-title']
        if clean_group:
            clean_group = clean_group.replace("高清", "")
        
        # 构建新的频道行
        new_line = f'#EXTINF:-1 tvg-id="{clean_id}"'
        if clean_logo:
            new_line += f' tvg-logo="{clean_logo}"'
        if clean_group:
            new_line += f' group-title="{clean_group}"'
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
    
    # 3. 排序：CCTV按数字 → 卫视 → 其他
    def sort_key(item):
        tvg_id, _ = item
        
        # 分类权重
        if tvg_id.startswith('CCTV'):
            category_weight = 0  # CCTV权重最高
        elif tvg_id.endswith('卫视') or tvg_id.endswith('卫視'):
            category_weight = 1  # 卫视其次
        else:
            category_weight = 2  # 其他最后
        
        # CCTV频道按数字排序
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
    
    # 4. 构建结果行
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
            # 提取频道名称
            parts = line.split(',')
            if len(parts) > 1:
                channel_name = parts[-1].strip().split('\n')[0]
            else:
                channel_name = line
                
            # 提取tvg-id用于分类
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

# ==================== 主函数 ====================
def main():
    """主函数"""
    print("="*60)
    print("🎬 IPTV列表自动化处理脚本 - 完整三步骤流程")
    print(f"🕒 开始时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("="*60)
    
    try:
        # 第一阶段：自动获取M3U链接（三步骤）
        m3u_url = get_m3u_url()
        print(f"🌐 获取到M3U链接: {m3u_url}")
        
        print("\n" + "="*60)
        print("🚀 第二阶段：下载并处理M3U内容")
        print("="*60)
        
        # 第二阶段：获取M3U内容
        content = fetch_m3u_content(m3u_url)
        
        # 第三阶段：解析内容
        entries, first_line = parse_m3u(content)
        
        if not entries:
            print("❌ 错误：未解析到任何频道条目")
            sys.exit(1)
        
        # 第四阶段：处理条目
        result_lines = process_entries(entries, first_line)
        
        # 第五阶段：保存输出
        output_file = save_output(result_lines, "CN.m3u")
        
        # 第六阶段：预览结果
        preview_results(result_lines)
        
        print("\n" + "="*60)
        print("✅ 脚本执行完成！")
        print(f"📁 输出文件: {output_file}")
        print("="*60)
        
    except Exception as e:
        print(f"❌ 脚本执行失败: {str(e)}")
        sys.exit(1)

if __name__ == "__main__":
    main()
