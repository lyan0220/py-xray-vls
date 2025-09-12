#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
VLESS 代理服务脚本 - Xray内核 极致精简版
专为 64MB Pterodactyl 容器优化
自动检测容器环境并生成直连与CDN双模式链接
"""

import os
import sys
import json
import uuid
import time
import signal
import shutil
import gc
import socket
import subprocess
from pathlib import Path
from urllib.parse import quote
import urllib.request
import platform
import zipfile

# ======================================================================
# 核心配置区 - 据你的需求修改以下参数
# ======================================================================
# 你的域名，用于Cloudflare CDN代理
DOMAIN = "cloudflare.182682.xyz"

# 如果你想使用一个固定的UUID，可以在这里设置
# 如果想每次随机生成，请保留默认值
UUID_STR = str(uuid.uuid4())

# WebSocket 路径
PATH = "/" + str(uuid.uuid4()).split('-')[0]
# ======================================================================

class PterodactylDetector:
    """Pterodactyl 环境检测"""
    @staticmethod
    def detect_environment():
        indicators = {
            'SERVER_MEMORY': 'Pterodactyl 内存限制',
            'SERVER_IP': 'Pterodactyl 服务器IP',
            'SERVER_PORT': 'Pterodactyl 主端口',
        }
        detected = {key: os.environ.get(key) for key in indicators if os.environ.get(key)}
        if detected:
            for key, desc in indicators.items():
                if key in detected:
                    print(f"✓ 检测到 {desc}: {detected[key]}")
        return len(detected) > 0, detected
    
    @staticmethod
    def get_server_ip():
        server_ip = os.environ.get('SERVER_IP')
        if server_ip and server_ip != '0.0.0.0':
            return server_ip
        
        try:
            req = urllib.request.Request('https://api.ipify.org')
            with urllib.request.urlopen(req, timeout=5) as response:
                return response.read().decode().strip()
        except:
            return "127.0.0.1"

class MinimalXray:
    """最小化 Xray 服务，包含下载和精简"""
    @staticmethod
    def download_xray():
        """下载 Xray"""
        arch_map = {'x86_64': 'amd64', 'x64': 'amd64', 'aarch64': 'arm64', 'arm64': 'arm64'}
        arch = arch_map.get(platform.machine().lower(), 'amd64')
        filename = f"Xray-linux-64.zip" if arch == 'amd64' else f"Xray-linux-arm64-v8a.zip"
        url = f"https://github.com/XTLS/Xray-core/releases/latest/download/{filename}"
        
        print(f"下载 Xray ({arch})...")
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=30) as response:
                with open('xray.zip', 'wb') as f:
                    shutil.copyfileobj(response, f)
            print("下载完成")
            return True
        except Exception as e:
            print(f"下载失败: {e}")
            return False
    
    @staticmethod
    def extract_xray():
        """解压 Xray 并删除不必要的文件"""
        try:
            zip_path = Path('xray.zip')
            if not zip_path.exists():
                print("✗ xray.zip 不存在，跳过解压。")
                return False
            
            os.makedirs('xray_temp', exist_ok=True)
            
            found = False
            with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                for file_name in zip_ref.namelist():
                    if file_name.endswith('/xray') or file_name == 'xray':
                        zip_ref.extract(file_name, path='xray_temp')
                        
                        extracted_path = Path('xray_temp') / file_name
                        final_path = Path('./xray')
                        
                        os.makedirs(final_path, exist_ok=True)
                        shutil.move(extracted_path, final_path / 'xray')
                        found = True
                        break
            
            shutil.rmtree('xray_temp', ignore_errors=True)
            zip_path.unlink()
            
            final_path = Path('./xray/xray')
            if not found or not final_path.exists():
                print("❌ 错误：在压缩包中未找到 Xray 可执行文件。")
                return False

            os.chmod(final_path, 0o755)
            
            gc.collect()
            print("✓ 文件清理完成，已节省约 30MB 空间")
            return True
        except Exception as e:
            print(f"解压或清理失败: {e}")
            return False

    @staticmethod
    def create_vless_config(uuid_str, path, domain, direct_port, cdn_port):
        config = {
            "log": {"loglevel": "error"},
            "inbounds": [
                # 直连节点配置
                {
                    "port": direct_port,
                    "listen": "0.0.0.0",
                    "protocol": "vless",
                    "settings": {
                        "clients": [{"id": uuid_str, "level": 0}],
                        "decryption": "none"
                    },
                    "streamSettings": {
                        "network": "ws",
                        "security": "none",
                        "wsSettings": {
                            "path": path,
                            "headers": {"Host": domain}
                        }
                    }
                },
                # CDN节点配置
                {
                    "port": cdn_port,
                    "listen": "0.0.0.0",
                    "protocol": "vless",
                    "settings": {
                        "clients": [{"id": uuid_str, "level": 0}],
                        "decryption": "none"
                    },
                    "streamSettings": {
                        "network": "ws",
                        "security": "tls",
                        "tlsSettings": {
                            "serverName": domain,
                            "allowInsecure": False
                        },
                        "wsSettings": {
                            "path": path,
                            "headers": {"Host": domain}
                        }
                    }
                }
            ],
            "outbounds": [{"protocol": "freedom", "settings": {}}],
            "policy": {"levels": {"0": {"bufferSize": 256, "connIdle": 120}}}
        }
        return config

class VLESSXrayProxy:
    """VLESS Xray 双模式代理服务"""
    
    def __init__(self, domain, uuid_str, path):
        self.process = None
        self.domain = domain
        self.uuid_str = uuid_str
        self.path = path
        self.setup_signals()
    
    def setup_signals(self):
        def handler(signum, frame):
            print("\n停止服务...")
            self.cleanup()
            sys.exit(0)
        
        signal.signal(signal.SIGINT, handler)
        if hasattr(signal, 'SIGTERM'):
            signal.signal(signal.SIGTERM, handler)
    
    def cleanup(self):
        if self.process:
            try:
                self.process.terminate()
                self.process.wait(timeout=3)
            except:
                self.process.kill()
        
        if os.path.exists('xray.zip'):
            os.remove('xray.zip')
        if os.path.exists('config.json'):
            os.remove('config.json')
        if os.path.exists('vless_xray_links.txt'):
            os.remove('vless_xray_links.txt')
        
        if os.path.exists('xray'):
            shutil.rmtree('xray', ignore_errors=True)
        
        gc.collect()
    
    def start(self):
        print("""
=====================================
VLESS Xray 代理服务（双模式）
专为 64MB Pterodactyl 容器优化
=====================================
""")
        
        is_pterodactyl, env_info = PterodactylDetector.detect_environment()
        
        if not is_pterodactyl:
            print("❌ 未检测到 Pterodactyl 环境，脚本终止。")
            return False
            
        direct_port = int(os.environ.get('SERVER_PORT', 0))
        if direct_port == 0:
            print("❌ 未检测到 Pterodactyl 分配的端口，脚本终止。")
            return False
        
        print(f"✓ 检测到 Pterodactyl 环境")
        print(f"内存限制: {env_info.get('SERVER_MEMORY', 'Unknown')}")
        server_ip = PterodactylDetector.get_server_ip()
        print(f"服务器IP: {server_ip}")
        print(f"直连端口: {direct_port}")

        if not MinimalXray.download_xray() or not MinimalXray.extract_xray():
            return False
        
        xray_path = Path('./xray/xray')
        if not xray_path.exists():
            print("❌ 错误：Xray 可执行文件未成功解压或不存在。")
            return False
        
        cdn_port = 443
        
        config = MinimalXray.create_vless_config(self.uuid_str, self.path, self.domain, direct_port, cdn_port)
        
        with open('config.json', 'w') as f:
            json.dump(config, f, indent=2)
        
        self.display_info(server_ip, direct_port, cdn_port)
        
        print("\n启动 Xray...")
        env = os.environ.copy()
        env['GOMEMLIMIT'] = '30MiB'
        env['GOGC'] = '30'
        
        self.process = subprocess.Popen(
            [str(xray_path), 'run', '-config', 'config.json'],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=env
        )
        
        time.sleep(2)
        if self.process.poll() is not None:
            print("✗ Xray 启动失败")
            return False
        
        print("✓ Xray 运行中")
        
        return True
    
    def display_info(self, ip, direct_port, cdn_port):
        print("\n" + "=" * 60)
        print("VLESS Xray 双模式服务已启动")
        print("=" * 60)
        
        # 直连链接
        direct_link = (f"vless://{self.uuid_str}@{ip}:{direct_port}?"
                       f"encryption=none&security=none&type=ws"
                       f"&host={quote(self.domain)}&path={quote(self.path)}"
                       f"#VLESS-Xray-Direct")
        
        print(f"\n🔗 **直连链接**:")
        print(direct_link)
        
        # CDN优化链接
        cdn_link = (f"vless://{self.uuid_str}@{self.domain}:{cdn_port}?"
                    f"encryption=none&security=tls&type=ws"
                    f"&host={quote(self.domain)}&path={quote(self.path)}"
                    f"&sni={quote(self.domain)}"
                    f"#VLESS-Xray-CDN")
        
        print(f"\n🔗 **CDN优化链接**:")
        print(cdn_link)
        
        # 保存到文件
        with open('vless_xray_links.txt', 'w', encoding='utf-8') as f:
            f.write("直连节点：\n")
            f.write(direct_link + "\n\n")
            f.write("CDN 节点：\n")
            f.write(cdn_link + "\n")
        
        print(f"\n链接已保存到: vless_xray_links.txt")
        print(f"\n⚠ **重要提示**:")
        print(f"1. 直连链接直接连接到你的服务器IP，端口为{direct_port}。")
        print(f"2. CDN链接需要你的域名({self.domain})已在Cloudflare中正确解析并开启代理（橙色云朵）。")
        
        print("\n✅ 服务运行中 (Ctrl+C 停止)")
        
def main():
    gc.enable()
    gc.set_threshold(200, 4, 4)
    proxy = VLESSXrayProxy(DOMAIN, UUID_STR, PATH)
    if proxy.start():
        try:
            while True:
                time.sleep(30)
                gc.collect(2)
                if proxy.process and proxy.process.poll() is not None:
                    print("\n⚠ Xray 进程异常退出")
                    break
        except KeyboardInterrupt:
            pass
    else:
        print("\n❌ 启动失败")
    proxy.cleanup()
    print("服务已停止")

if __name__ == "__main__":
    main()