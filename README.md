# KA-PVE 监控面板 (KA-PVE Monitor)

这是一个轻量级的 Proxmox VE 和 Docker 监控与控制面板。
专为 HomeLab 设计，提供现代化的 Web 界面，支持虚拟机开关机和容器管理。

## ✨ 功能特点
- 📊 **状态监控**：实时查看 PVE 虚拟机和 Docker 容器运行状态。
- 🚀 **快捷控制**：一键开机、关机、重启容器。
- 📱 **响应式设计**：完美适配手机和桌面端。
- 🔒 **数据安全**：配置保存在本地，无云端依赖。

## 🛠️ 快速部署

### Docker Compose (推荐)

```yaml
version: '3'
services:
  ka-pve-monitor:
    image: konnoamon/ka-pve-monitor:latest
    container_name: ka-pve-monitor
    ports:
      - "8080:8000"
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock
      - ./data:/app/data
    restart: unless-stopped

    访问 http://ip:8080 即可进入设置页面。

⚙️ 初始化配置
访问 http://你的IP:8080。

自动跳转到设置页，填入 PVE 信息：

Host: PVE 的 IP 地址 (如 192.168.1.2)

User: root@pam

Token ID: monitor (注意不带 root@pam!)

Secret: 你的 UUID 密钥

⚠️ 注意事项
请确保挂载了 /app/data 目录，否则重启容器后配置会丢失。