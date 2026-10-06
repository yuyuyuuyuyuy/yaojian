# 海淘管家 · ECS部署记录

> 目的：全程记录部署操作，防止数据丢失、出问题可回溯。
> 原则：先勘察（只读）→ 备份 → 再改动；每条命令及输出都记录在此。

## 决策记录

| 时间 | 决策 | 原因 |
|---|---|---|
| 2026-10-03 | 部署目标 = 唯一的 Ubuntu 22.04 ECS | 用户委托选择；ECS列表仅此一台 |
| 2026-10-03 | 部署前必须先勘察服务器现状（只读命令） | 服务器上可能跑着Dify（QC知识库），不能误伤 |
| 2026-10-03 | 药鉴为Windows桌面程序，判断其不运行在这台Ubuntu上 | 待勘察确认 |

## 勘察结果（2026-10-03，只读命令）

| 项目 | 结果 | 结论 |
|---|---|---|
| 监听端口 | 仅 22 (SSH) | 无其他服务，部署零冲突 |
| Docker | 已安装，0个容器 | 不动它 |
| 磁盘 | 40G，用15G，剩23G (41%) | 充足 |
| 内存 | 1.6G总/1.0G可用，无swap | 部署时加1G swapfile |
| Python | 3.10.12 (系统自带) | 满足要求 |
| 主机名 | iZbp1istoxb4o9dcn6pdmnZ | Ubuntu 22.04 |

结论：服务器实际是空置的（此前判断的Dify/药鉴均不在此机上），可直接部署。

## 部署方案（已定）

- 位置：/opt/haigou（代码+venv+data）
- 服务：systemd 单元 haigou，端口8501，开机自启+崩溃自动重启
- 内存：加 1G swapfile
- 依赖安装用清华pip镜像（国内加速）
- 防火墙：阿里云安全组放行 8501（控制台操作，用户完成）
- 管理端强口令（写入服务器.env）；HTTPS需域名，暂无域名则HTTP+强口令（待用户确认是否加域名）
- 数据保护：改动前实例快照（用户控制台操作）＋每日cron备份SQLite与uploads（保留7天）
- 数据迁移：本地 data/（含现有订单数据）随部署包上传服务器

## 部署包内容（本地生成 haigou-deploy.zip）

- 项目代码（不含.git/__pycache__/tests/docs）
- data/ 现有数据
- server.env（17TRACK密钥+生成的强管理口令，不入git）
- deploy/install.sh（一键安装）、backup.sh（每日备份）、haigou.service（systemd）

## 操作日志

| 时间 | 操作 | 输出摘要 |
|---|---|---|
| 2026-10-03 | 只读勘察（ss/docker ps/df/free/python3） | 仅SSH监听、无容器、23G可用、1.6G内存、Python3.10 |
| 2026-10-03 | 部署包经Workbench上传→解压→install.sh | ✅安装完成，systemd服务haigou active(running)，内存43M |
| 2026-10-03 | 安全组放行8501 | 管理端/个人查询均可访问 |
| 2026-10-03 | 两次代码更新（昵称登录、台账修复+状态管理） | unzip -o -x data/* 方式更新，服务器数据零丢失 |

## ✅ 部署完成状态（2026-10-03）

- 服务：systemd haigou（开机自启、崩溃自动重启），端口8501
- 数据：/opt/haigou/data/daigou.db（已含用户真实导入数据）；每日凌晨3点备份到 /opt/haigou/backups（保留7天）
- 管理口令：写入 /opt/haigou/.env 的 ADMIN_PASSWORD（不记录在此文件，群主自行保存）
- 个人查询：群友用昵称登录（如"本人"），数据隔离

## 日常维护手册

```bash
# 查看服务状态
systemctl status haigou
# 重启服务
systemctl restart haigou
# 查看运行日志
journalctl -u haigou -n 50
# 手动备份一次
bash /opt/haigou/deploy/backup.sh
# 修改管理口令：编辑 /opt/haigou/.env 的 ADMIN_PASSWORD 后
systemctl restart haigou
# 系统代码更新：本地打包→Workbench上传→
#   cd /opt/haigou && unzip -o /root/haigou-deploy.zip -x "data/*" "deploy/README.txt" && systemctl restart haigou
```

安全提醒：安全组只保留 22 和 8501 端口；重要数据变动后在控制台给实例做快照；SSH密码保持高强度。
