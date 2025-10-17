# Pterodactyl面板Python环境

## 运行方式1
### 上传requirements.txt和app.py两个文件
#### Startup Command 1
pip install -r requirements.txt
#### Startup Command 2 (Optional)
python app.py

Command 1  | Command 2|
--------- | --------|
```pip install -r requirements.txt  | ```python app.py |

## 运行方式2
### 上传requirements.txt、app.py和start.sh全部三个文件
#### Startup Command 1
bash start.sh

## 注意
1. 节点只支持 CDN 模式，请确保域名(youerdomain) 已在 Cloudflare 解析并开启代理。
2. 你需要通过 Cloudflare 的 **Origin Rules** 将流量路由到代理监听端口: (面板分配端口)
3. Cloudflare 的 SSL/TLS 加密模式必须为 **灵活 (Flexible)**。
