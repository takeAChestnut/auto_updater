#!/bin/bash
# 脚本路径：~/work/auto_updater/auto_update.sh

# 进入工作目录
cd ~/work/auto_updater || exit 1

# 激活Python环境（如果需要，例如使用virtualenv）
# source /path/to/venv/bin/activate

# 执行Python脚本
python iptv-test.py

# 检查执行是否成功
if [ $? -eq 0 ]; then
    echo "Python脚本执行成功，开始Git操作..."
    
    # 添加所有更改
    git add .
    
    # 提交更改（使用自动生成的提交信息）
    commit_msg="自动更新: $(date '+%Y-%m-%d %H:%M:%S')"
    git commit -m "$commit_msg"
    
    # 推送到GitHub
    git push origin main
    
    # 检查推送结果
    if [ $? -eq 0 ]; then
        echo "✅ 自动更新完成并已推送到GitHub"
    else
        echo "❌ Git推送失败，请检查网络或权限"
        exit 1
    fi
else
    echo "❌ Python脚本执行失败，跳过Git操作"
    exit 1
fi
