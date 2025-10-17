#!/bin/bash

# 1. 安装依赖
echo "开始安装Python依赖..."
pip install -r requirements.txt

# 检查依赖是否安装成功
if [ $? -ne 0 ]; then
    echo "依赖安装失败，退出！"
    exit 1
fi

# 2. 运行主程序
echo "依赖安装完成，开始运行程序..."
python app.py
