#!/usr/bin/env python3
"""
更新系统hosts文件的脚本
从指定的GitHub链接获取hosts内容，生成hosts文件和AdGuard DNS重写规则文件
"""

import urllib.request
import urllib.error
import subprocess
import tempfile
import os
import sys
import time
import re
from pathlib import Path

# 要保留的文件头部分（保持原样）
HEADER = """# Any manual change will be lost if the host name is changed or system upgrades.
127.0.0.1       localhost
::1             localhost
127.0.0.1       NAS
::1             NAS
192.168.31.123 mb3admin.com
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

def merge_and_clean_hosts(contents_list):
    """合并多个hosts内容并去重"""
    records = {}  # domain -> ip
    
    for content in contents_list:
        if content:
            lines = content.strip().split('\n')
            for line in lines:
                ip, domain = parse_hosts_line(line)
                if ip and domain:
                    # 如果域名已存在，保留第一个出现的记录
                    if domain not in records:
                        records[domain] = ip
    
    return records

def convert_to_adguard_format(records):
    """
    将hosts记录转换为AdGuard DNS重写规则格式
    格式: ||domain^$dnsrewrite=IP
    """
    rules = []
    for domain, ip in sorted(records.items()):
        # 移除可能的通配符前缀
        clean_domain = domain.lstrip('*.')
        rule = f"||{clean_domain}^$dnsrewrite={ip}"
        rules.append(rule)
    return rules

def save_hosts_file(records, filepath="hosts"):
    """保存hosts文件（包含文件头）"""
    try:
        # 生成hosts内容
        lines = []
        for domain, ip in sorted(records.items()):
            lines.append(f"{ip}\t{domain}")
        
        content = HEADER + "\n" + '\n'.join(lines)
        
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(content)
        
        print(f"✅ hosts文件已保存到: {os.path.abspath(filepath)}")
        print(f"文件大小: {len(content)} 字节")
        
        # 显示统计信息
        total_lines = len(content.split('\n'))
        header_lines = len(HEADER.strip().split('\n'))
        domain_count = len(records)
        
        print(f"总行数: {total_lines}")
        print(f"文件头行数: {header_lines}")
        print(f"域名记录数: {domain_count}")
        
        return True
    except Exception as e:
        print(f"❌ 保存hosts文件失败: {e}")
        return False

def save_adguard_hosts_file(records, filepath="adguard-hosts.txt"):
    """保存AdGuard DNS重写规则文件"""
    try:
        rules = convert_to_adguard_format(records)
        content = '\n'.join(rules)
        
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(content)
        
        print(f"✅ AdGuard hosts文件已保存到: {os.path.abspath(filepath)}")
        print(f"规则数量: {len(rules)}")
        
        # 显示前几条规则作为示例
        print("\n规则示例（前5条）：")
        for rule in rules[:5]:
            print(f"  {rule}")
        
        return True
    except Exception as e:
        print(f"❌ 保存AdGuard hosts文件失败: {e}")
        return False

def backup_current_hosts():
    """备份当前的hosts文件（如果存在）"""
    if not os.path.exists("/etc/hosts"):
        print("⚠️  /etc/hosts文件不存在，无需备份")
        return True
    
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    backup_path = f"/etc/hosts.backup.{timestamp}"
    
    try:
        with open("/etc/hosts", "r", encoding="utf-8") as f:
            current_content = f.read()
        
        with open(backup_path, "w", encoding="utf-8") as f:
            f.write(current_content)
        print(f"✅ 已备份当前hosts文件到: {backup_path}")
        return True
    except PermissionError:
        print("❌ 权限不足，需要sudo权限来备份hosts文件")
        return False
    except Exception as e:
        print(f"❌ 备份hosts文件失败: {e}")
        return False

def update_system_hosts(records):
    """更新系统的/etc/hosts文件"""
    # 生成hosts内容（包含文件头）
    lines = []
    for domain, ip in sorted(records.items()):
        lines.append(f"{ip}\t{domain}")
    content = HEADER + "\n" + '\n'.join(lines)
    
    try:
        # 使用临时文件
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', delete=False) as tmp_file:
            tmp_file.write(content)
            tmp_path = tmp_file.name
        
        # 移动临时文件到/etc/hosts（需要root权限）
        subprocess.run(['sudo', 'cp', tmp_path, '/etc/hosts'], check=True)
        subprocess.run(['sudo', 'chmod', '644', '/etc/hosts'], check=True)
        
        # 清理临时文件
        os.unlink(tmp_path)
        
        print("✅ 系统hosts文件更新成功！")
        print(f"更新后的文件大小: {len(content)} 字节")
        print(f"域名记录数: {len(records)}")
        
        return True
        
    except PermissionError:
        print("❌ 权限不足，请使用sudo运行此脚本")
        return False
    except subprocess.CalledProcessError as e:
        print(f"❌ 更新hosts文件失败: {e}")
        return False
    except Exception as e:
        print(f"❌ 更新过程中出错: {e}")
        return False

def main():
    print("=" * 60)
    print("开始获取和生成hosts文件")
    print("=" * 60)
    
    # 检查/etc/hosts是否存在
    hosts_exists = os.path.exists("/etc/hosts")
    
    if hosts_exists:
        print("📁 检测到系统/etc/hosts文件存在")
        print("将尝试更新系统hosts文件（需要管理员权限）")
        
        # 检查是否以root权限运行
        if os.geteuid() != 0:
            print("\n⚠️  注意：更新系统hosts文件需要root权限")
            print("请使用: sudo python3 update_hosts.py")
            print("或者输入密码进行授权")
            print("\n如果您没有root权限，文件将保存到当前目录")
            proceed = input("是否继续并保存到当前目录？(y/n): ").lower()
            if proceed != 'y':
                print("操作已取消")
                sys.exit(0)
            # 标记为不更新系统文件
            update_system = False
        else:
            update_system = True
            
        # 备份当前hosts文件
        if update_system and not backup_current_hosts():
            print("继续操作可能会导致数据丢失，是否继续？(y/n)")
            choice = input().lower()
            if choice != 'y':
                print("操作已取消")
                sys.exit(1)
    else:
        print("📁 未检测到系统/etc/hosts文件")
        print("文件将保存到当前目录")
        update_system = False
    
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
    
    # 合并和清理内容
    print("\n" + "-" * 60)
    print("正在合并和清理hosts内容...")
    print("-" * 60)
    
    records = merge_and_clean_hosts(all_contents)
    
    if not records:
        print("❌ 未能解析到有效的hosts记录")
        sys.exit(1)
    
    print(f"解析到 {len(records)} 条有效域名记录")
    
    # 保存hosts文件（包含文件头）
    print("\n" + "-" * 60)
    print("正在保存hosts文件...")
    print("-" * 60)
    
    hosts_success = save_hosts_file(records, "hosts")
    
    # 保存AdGuard hosts文件（使用正确的格式）
    print("\n" + "-" * 60)
    print("正在保存AdGuard hosts文件...")
    print("-" * 60)
    
    adguard_success = save_adguard_hosts_file(records, "adguard-hosts.txt")
    
    # 根据情况选择是否更新系统hosts
    if update_system and hosts_exists:
        print("\n" + "-" * 60)
        print("正在更新系统hosts文件...")
        print("-" * 60)
        
        if update_system_hosts(records):
            print("✅ 系统hosts文件更新成功！")
        else:
            print("❌ 系统hosts文件更新失败")
    
    if hosts_success and adguard_success:
        print("\n" + "=" * 60)
        print("✅ 所有操作完成！")
        print("=" * 60)
        print("\n生成的文件：")
        print("  - hosts: 标准hosts格式文件（包含文件头）")
        print("  - adguard-hosts.txt: AdGuard DNS重写规则文件（格式：||domain^$dnsrewrite=IP）")
        
        # 显示DNS刷新提示
        if update_system:
            print("\n📋 可能需要刷新DNS缓存：")
            print("Linux: sudo systemctl restart systemd-resolved 或 sudo /etc/init.d/nscd restart")
            print("macOS: sudo killall -HUP mDNSResponder")
            print("Windows: ipconfig /flushdns")
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