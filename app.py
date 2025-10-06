#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
VLESS 代理服务脚本 - Xray内核 CDN专用版
专为 64MB Pterodactyl 容器优化
"""

import os
import sys
import json
import uuid
import time
import signal
import shutil
import gc
import subprocess
from pathlib import Path
from urllib.parse import quote
import urllib.request
import platform
import zipfile
import requests

# ======================================================================
# 核心配置区
# ======================================================================
DOMAIN = "cloudflare.182682.xyz"  # 你的域名（Cloudflare 代理开启橙色云朵）
UUID = ""  # UUID变量，留空自动生成或写入固定值
PORT = ""  # 建议留空将自动使用分配的端口
NODE_NAME = "Panel"  # 节点名称，将显示在客户端
# ======================================================================


class PterodactylDetector:
    @staticmethod
    def detect_environment():
        indicators = {
            "SERVER_MEMORY": "Pterodactyl 内存限制",
            "SERVER_IP": "Pterodactyl 服务器IP",
            "SERVER_PORT": "Pterodactyl 主端口",
        }
        detected = {k: os.environ.get(k) for k in indicators if os.environ.get(k)}
        if detected:
            for k, desc in indicators.items():
                if k in detected:
                    print(f"✓ 检测到 {desc}: {detected[k]}")
        return len(detected) > 0, detected

    @staticmethod
    def get_server_ip():
        server_ip = os.environ.get("SERVER_IP")
        if server_ip and server_ip != "0.0.0.0":
            return server_ip
        try:
            req = urllib.request.Request("https://api.ipify.org")
            with urllib.request.urlopen(req, timeout=5) as response:
                return response.read().decode().strip()
        except:
            return "127.0.0.1"


class MinimalXray:
    @staticmethod
    def download_xray():
        arch_map = {"x86_64": "amd64", "x64": "amd64", "aarch64": "arm64", "arm64": "arm64"}
        arch = arch_map.get(platform.machine().lower(), "amd64")
        filename = (
            "Xray-linux-64.zip" if arch == "amd64" else "Xray-linux-arm64-v8a.zip"
        )
        url = f"https://github.com/XTLS/Xray-core/releases/latest/download/{filename}"

        print(f"下载 Xray ({arch})...")
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=30) as response:
                with open("xray.zip", "wb") as f:
                    shutil.copyfileobj(response, f)
            print("下载完成")
            return True
        except Exception as e:
            print(f"下载失败: {e}")
            return False

    @staticmethod
    def extract_xray():
        try:
            zip_path = Path("xray.zip")
            if not zip_path.exists():
                print("✗ xray.zip 不存在，跳过解压。")
                return False

            os.makedirs("xray_temp", exist_ok=True)
            found = False
            with zipfile.ZipFile(zip_path, "r") as zip_ref:
                for file_name in zip_ref.namelist():
                    if file_name.endswith("/xray") or file_name == "xray":
                        zip_ref.extract(file_name, path="xray_temp")
                        extracted_path = Path("xray_temp") / file_name
                        final_path = Path("./xray")
                        os.makedirs(final_path, exist_ok=True)
                        shutil.move(extracted_path, final_path / "xray")
                        found = True
                        break

            shutil.rmtree("xray_temp", ignore_errors=True)
            zip_path.unlink()

            final_path = Path("./xray/xray")
            if not found or not final_path.exists():
                print("❌ 错误：未找到 Xray 可执行文件。")
                return False

            os.chmod(final_path, 0o755)
            gc.collect()
            print("✓ 文件清理完成，已节省空间")
            return True
        except Exception as e:
            print(f"解压失败: {e}")
            return False

    @staticmethod
    def create_vless_config(uuid, path, domain, port):
        config = {
            "log": {"loglevel": "error"},
            "inbounds": [
                {
                    "port": port,
                    "listen": "0.0.0.0",
                    "protocol": "vless",
                    "settings": {
                        "clients": [{"id": uuid, "level": 0}],
                        "decryption": "none",
                    },
                    "streamSettings": {
                        "network": "ws",
                        "security": "none",
                        "wsSettings": {"path": path, "headers": {"Host": domain}},
                    },
                }
            ],
            "outbounds": [{"protocol": "freedom", "settings": {}}],
            "policy": {
                "levels": {"0": {"bufferSize": 256, "connIdle": 120}},
                "system": {
                    "statsOutboundUplink": False,
                    "statsOutboundDownlink": False,
                },
            },
        }
        return config


class VLESSXrayProxy:
    def __init__(self, domain, user_uuid, user_port, node_name):
        self.uuid = user_uuid if user_uuid else str(uuid.uuid4())
        self.path = "/" + str(uuid.uuid4()).split("-")[0]
        self.domain = domain
        self.user_port = user_port
        self.node_name = node_name
        self.process = None
        self.setup_signals()

    def setup_signals(self):
        def handler(signum, frame):
            print("\n停止服务...")
            self.cleanup()
            sys.exit(0)

        signal.signal(signal.SIGINT, handler)
        if hasattr(signal, "SIGTERM"):
            signal.signal(signal.SIGTERM, handler)

    def cleanup(self):
        if self.process:
            try:
                self.process.terminate()
                self.process.wait(timeout=3)
            except:
                self.process.kill()
        for f in ["xray.zip", "config.json", "vless_xray_links.txt"]:
            if os.path.exists(f):
                os.remove(f)
        if os.path.exists("xray"):
            shutil.rmtree("xray", ignore_errors=True)
        gc.collect()

    def get_isp_info(self):
        try:
            print("正在获取ISP信息...")
            response = requests.get("https://speed.cloudflare.com/meta", timeout=5)
            response.raise_for_status()
            data = response.json()
            isp = f"{data['country']}-{data['asOrganization']}".replace(" ", "_")
            print(f"✓ 获取ISP成功: {isp}")
            return isp
        except requests.exceptions.RequestException as e:
            print(f"❌ 获取ISP失败: {e}")
            return "Unknown"

    def start(self):
        print(
            """
=====================================
VLESS Xray 代理服务（CDN模式）
专为 64MB Pterodactyl 容器优化
=====================================
"""
        )
        is_pterodactyl, env_info = PterodactylDetector.detect_environment()
        if not is_pterodactyl:
            print("❌ 未检测到 Pterodactyl 环境，脚本终止。")
            return False

        if self.user_port:
            port = int(self.user_port)
            print("✓ 正在使用手动设置的 PORT。")
        else:
            port = int(os.environ.get("SERVER_PORT", 0))
            if port == 0:
                print("❌ 未检测到可用的监听端口，终止。")
                return False
            print("✓ 正在使用 Pterodactyl 分配的 SERVER_PORT。")

        print(f"✓ 内存限制: {env_info.get('SERVER_MEMORY', 'Unknown')}")
        print(f"✓ 代理监听端口: {port}")

        if not MinimalXray.download_xray() or not MinimalXray.extract_xray():
            return False

        xray_path = Path("./xray/xray")
        if not xray_path.exists():
            print("❌ 错误：Xray 可执行文件不存在。")
            return False

        config = MinimalXray.create_vless_config(self.uuid, self.path, self.domain, port)
        with open("config.json", "w") as f:
            json.dump(config, f, indent=2)

        isp_info = self.get_isp_info()
        self.display_info(port, isp_info)

        print("\n启动 Xray...")
        env = os.environ.copy()
        env["GOMEMLIMIT"] = "15MiB"
        env["GOGC"] = "15"

        self.process = subprocess.Popen(
            [str(xray_path), "run", "-config", "config.json"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=env,
        )

        time.sleep(2)
        if self.process.poll() is not None:
            print("✗ Xray 启动失败")
            return False

        print("✓ Xray 运行中")
        return True

    def display_info(self, port, isp_info):
        final_node_name = f"{self.node_name}-{isp_info}"

        print("\n" + "=" * 60)
        print("VLESS Xray CDN 节点已启动")
        print("=" * 60)

        cdn_link = (
            f"vless://{self.uuid}@{self.domain}:443?"
            f"encryption=none&security=tls&type=ws"
            f"&host={quote(self.domain)}&path={quote(self.path)}"
            f"&sni={quote(self.domain)}"
            f"#{quote(final_node_name)}"
        )

        print(f"\n🔗 **CDN 节点链接**:")
        print(cdn_link)

        with open("vless_xray_links.txt", "w", encoding="utf-8") as f:
            f.write("CDN 节点：\n")
            f.write(cdn_link + "\n")

        print(f"\n链接已保存到: vless_xray_links.txt")
        print(f"\n⚠ **提示**:")
        print(f"1. 节点只支持 CDN 模式，请确保域名({self.domain}) 已在 Cloudflare 解析并开启代理。")
        print(f"2. 你需要通过 Cloudflare 的 **Origin Rules** 将流量路由到代理监听端口: {port}")
        print(f"3. Cloudflare 的 SSL/TLS 加密模式必须为 **灵活 (Flexible)**。")
        print("\n✅ 服务运行中 (Ctrl+C 停止)")

def main():
    gc.enable()
    gc.set_threshold(200, 4, 4)
    proxy = VLESSXrayProxy(DOMAIN, UUID, PORT, NODE_NAME)
    if proxy.start():
        try:
            restart_limit = 5
            restart_count = 0
            while True:
                time.sleep(30)
                gc.collect(2)
                if proxy.process and proxy.process.poll() is not None:
                    print("\n⚠ Xray 进程异常退出，尝试重启")
                    restart_count += 1
                    if restart_count > restart_limit:
                        print("❌ 达到最大重启次数，停止重启")
                        break
                    proxy.cleanup()
                    if not proxy.start():
                        print("❌ 重启失败，退出")
                        break
        except KeyboardInterrupt:
            print("\n检测到 Ctrl+C，正常退出")
    else:
        print("\n❌ 启动失败")
    proxy.cleanup()
    print("服务已停止")


if __name__ == "__main__":
    main()
