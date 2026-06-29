#!/usr/bin/env python3
"""
更新hosts文件的脚本
从指定的GitHub链接获取hosts内容，生成hosts文件和AdGuard DNS重写规则文件
不更新系统hosts，只生成文件到当前目录
"""

import urllib.request
import urllib.error
import os
import sys
import time
import re
from pathlib import Path

# 要保留的文件头部分（注释 + 本地回环记录，仅用于hosts文件）
HEADER = """# Any manual change will be lost if the host name is changed or system upgrades.
127.0.0.1       localhost
::1             localhost
127.0.0.1       NAS
::1             NAS
"""

# 固定的域名解析记录（同时用于hosts和adguard-hosts.txt）
FIXED_RECORDS = """172.19.0.2  crackemby.mb6.top
172.19.0.2  mb3admin.com
104.20.16.23 linux.do
172.66.166.61 linux.do
"""

# 要获取的hosts文件URL列表
HOSTS_URLS = [
    "https://raw.githubusercontent.com/cnwikee/CheckTMDB/refs/heads/main/Tmdb_host_ipv4",
    "https://raw.githubusercontent.com/maxiaof/github-hosts/master/hosts"
]

def fetch_hosts_content(url):
    """从URL获取hosts内容"""
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        req = urllib.request.Request(url, headers=headers)
        
        with urllib.request.urlopen(req, timeout=30) as response:
            content = response.read().decode('utf-8')
            print(f"成功从 {url} 获取内容 ({len(content)} 字节)")
            return content
    except urllib.error.URLError as e:
        print(f"从 {url} 获取内容失败: {e}")
        return None
    except Exception as e:
        print(f"处理 {url} 时出错: {e}")
        return None

def parse_hosts_line(line):
    """解析hosts行，返回IP和域名"""
    line = line.strip()
    if not line or line.startswith('#'):
        return None, None
    
    # 按空白字符分割
    parts = line.split()
    if len(parts) < 2:
        return None, None
    
    ip = parts[0]
    domain = parts[1]
    
    # 验证IP格式（简单验证）
    ip_pattern = re.compile(r'^(\d{1,3}\.){3}\d{1,3}$|^::[\da-f]*$|^[\da-f]*::[\da-f]*$', re.IGNORECASE)
    if not ip_pattern.match(ip):
        return None, None
    
    return ip, domain

def get_all_records(contents_list):
    """
    获取所有记录（保留重复项）
    返回: [(ip, domain), ...] 列表，保持顺序
    """
    all_records = []
    
    # 首先添加固定的记录
    fixed_lines = FIXED_RECORDS.strip().split('\n')
    for line in fixed_lines:
        ip, domain = parse_hosts_line(line)
        if ip and domain:
            all_records.append((ip, domain))
    
    # 然后添加远程获取的记录
    for content in contents_list:
        if content:
            lines = content.strip().split('\n')
            for line in lines:
                ip, domain = parse_hosts_line(line)
                if ip and domain:
                    all_records.append((ip, domain))
    
    return all_records

def convert_to_adguard_format(records):
    """
    将hosts记录转换为AdGuard DNS重写规则格式
    格式: ||domain^$dnsrewrite=IP
    保留所有记录（包括重复的）
    """
    rules = []
    for ip, domain in records:
        # 移除可能的通配符前缀
        clean_domain = domain.lstrip('*.')
        rule = f"||{clean_domain}^$dnsrewrite={ip}"
        rules.append(rule)
    return rules

def save_hosts_file(all_records, filepath="hosts"):
    """保存hosts文件（包含文件头，保留所有记录）"""
    try:
        # 生成hosts内容（保留所有记录）
        lines = []
        for ip, domain in all_records:
            lines.append(f"{ip}\t{domain}")
        
        content = HEADER + "\n" + '\n'.join(lines)
        
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(content)
        
        print(f"✅ hosts文件已保存到: {os.path.abspath(filepath)}")
        print(f"文件大小: {len(content)} 字节")
        
        # 显示统计信息
        total_lines = len(content.split('\n'))
        header_lines = len(HEADER.strip().split('\n'))
        record_count = len(all_records)
        
        print(f"总行数: {total_lines}")
        print(f"文件头行数: {header_lines}")
        print(f"域名记录数: {record_count}")
        
        return True
    except Exception as e:
        print(f"❌ 保存hosts文件失败: {e}")
        return False

def save_adguard_hosts_file(all_records, filepath="adguard-hosts.txt"):
    """保存AdGuard DNS重写规则文件（保留所有记录）"""
    try:
        rules = convert_to_adguard_format(all_records)
        content = '\n'.join(rules)
        
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(content)
        
        print(f"✅ AdGuard hosts文件已保存到: {os.path.abspath(filepath)}")
        print(f"规则数量: {len(rules)}")
        
        # 显示前几条规则作为示例
        print("\n规则示例（前5条）：")
        for rule in rules[:5]:
            print(f"  {rule}")
        
        # 显示固定记录是否包含
        fixed_lines = FIXED_RECORDS.strip().split('\n')
        print(f"\n✅ FIXED_RECORDS中的 {len(fixed_lines)} 条记录已包含在adguard-hosts.txt中")
        
        return True
    except Exception as e:
        print(f"❌ 保存AdGuard hosts文件失败: {e}")
        return False

def main():
    print("=" * 60)
    print("开始获取和生成hosts文件")
    print("=" * 60)
    
    print("📁 文件将保存到当前目录（不更新系统hosts）")
    
    # 获取所有hosts内容
    all_contents = []
    print("\n" + "-" * 60)
    print("开始获取远程hosts内容...")
    print("-" * 60)
    
    for i, url in enumerate(HOSTS_URLS, 1):
        print(f"\n[{i}/{len(HOSTS_URLS)}] 正在获取: {url}")
        content = fetch_hosts_content(url)
        if content:
            all_contents.append(content)
        time.sleep(1)  # 避免请求过快
    
    if not all_contents:
        print("❌ 未能获取到任何hosts内容")
        sys.exit(1)
    
    # 获取所有记录（保留重复）
    print("\n" + "-" * 60)
    print("正在合并hosts内容（保留所有记录）...")
    print("-" * 60)
    
    all_records = get_all_records(all_contents)
    
    if not all_records:
        print("❌ 未能解析到有效的hosts记录")
        sys.exit(1)
    
    print(f"总共获取到 {len(all_records)} 条记录")
    
    # 统计重复情况
    domains = {}
    for ip, domain in all_records:
        if domain in domains:
            domains[domain].append(ip)
        else:
            domains[domain] = [ip]
    
    duplicates = {d: ips for d, ips in domains.items() if len(ips) > 1}
    if duplicates:
        print(f"\n发现 {len(duplicates)} 个域名有多个IP记录：")
        for domain, ips in duplicates.items():
            print(f"  {domain}: {', '.join(ips)}")
    
    # 保存hosts文件（包含文件头，保留所有记录）
    print("\n" + "-" * 60)
    print("正在保存hosts文件...")
    print("-" * 60)
    
    hosts_success = save_hosts_file(all_records, "hosts")
    
    # 保存AdGuard hosts文件（保留所有记录）
    print("\n" + "-" * 60)
    print("正在保存AdGuard hosts文件...")
    print("-" * 60)
    
    adguard_success = save_adguard_hosts_file(all_records, "adguard-hosts.txt")
    
    if hosts_success and adguard_success:
        print("\n" + "=" * 60)
        print("✅ 所有操作完成！")
        print("=" * 60)
        print("\n生成的文件：")
        print("  - hosts: 标准hosts格式文件（包含HEADER和所有记录）")
        print("  - adguard-hosts.txt: AdGuard DNS重写规则文件（保留所有记录）")
        print("\n说明：")
        print("  - 所有记录都保留，不做去重")
        print("  - FIXED_RECORDS中的记录会优先出现在文件顶部")
        print("  - 同一个域名如果有多个IP，在hosts中会全部保留")
        print("  - AdGuard规则中同一个域名如果有多个IP，可能会被覆盖")
    else:
        print("❌ 部分操作失败")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n操作被用户中断")
        sys.exit(0)
    except Exception as e:
        print(f"\n❌ 程序执行出错: {e}")
        sys.exit(1)
