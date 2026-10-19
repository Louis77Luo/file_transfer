# 传输空间

一个仅供本人使用的文件和文本传输助手，部署在 **https://file.louis77.top**。手机、平板、电脑均可使用。

## 使用

- 使用已有的私人账号登录，不提供注册。
- 点击「上传内容」选择文件（支持多选、拖放和上传进度）或粘贴文本（支持可选标题）。
- 每份内容独立显示为卡片，可搜索名称/文本摘要、查看或复制完整文本、下载原文件或 `.txt`、删除释放空间。
- 登录后可按文件/文本筛选。页面每 30 秒同步列表，切回页面时也自动刷新。
- 文件和文本合计配额为 **20 GiB（21,474,836,480 字节）**。单条文本最多 1 MiB。搜索匹配名称与前 280 字符摘要。
- 上传按文件逐个完成。失败或中止时已完成的文件保留，未完成的文件不出现在列表中；可重新上传。文件不自动过期。

## 技术与目录

Python 3.12、Flask、Gunicorn、SQLite，前端为原生 HTML/CSS/JavaScript，无第三方 CDN。生产镜像使用一个进程、8 个线程，上传以 1 MiB 分块写入磁盘；请保持单进程、单实例以保证并发配额锁有效。

```text
/root/file_transfer/
├── app.py                 # API、鉴权、存储、配额
├── static/                # 响应式界面
├── compose.yaml           # 127.0.0.1:8003 → 容器 8080
├── deploy/                # 初始配置脚本与 Nginx 配置
├── tests/                 # 鉴权、配额、文件完整性等回归测试
├── .env                   # 私有配置（忽略）
└── data/                  # SQLite 与文件（忽略、持久化）
```

## 首次部署

以下在服务器以 root 执行，需已安装 Docker Compose、Nginx 和 Certbot：

```bash
git clone https://github.com/Louis77Luo/file_transfer.git /root/file_transfer
cd /root/file_transfer
python3 deploy/configure.py
# 按提示输入密码：仅保存随机盐 PBKDF2 哈希；不把密码写进命令历史。
docker compose up -d --build
curl --fail http://127.0.0.1:8003/healthz
```

申请证书前，先在 Nginx 配置 `file.louis77.top` 的 80 端口虚拟主机，将 `/.well-known/acme-challenge/` 指向 `/var/www/letsencrypt`，并确认 DNS 已指向本机：

```bash
mkdir -p /var/www/letsencrypt
certbot certonly --webroot -w /var/www/letsencrypt -d file.louis77.top
cp deploy/nginx.conf /etc/nginx/sites-available/file-transfer
ln -s /etc/nginx/sites-available/file-transfer /etc/nginx/sites-enabled/file-transfer
nginx -t && systemctl reload nginx
```

HTTPS 上传关闭 Nginx 请求缓冲，避免大文件占用双份磁盘。Nginx 的 `client_max_body_size` 与应用配额均为 20 GiB。这里使用应用配额，**没有提前占满 20 GiB 磁盘**；上传还为宿主机和其他服务保留至少 1 GiB 可用空间。若磁盘被其他服务写满，可能提前拒绝上传。

Certbot 使用系统自带续期定时器；部署时已设置 Nginx 续期后 reload 的 deploy hook。

## 日常运维

```bash
cd /root/file_transfer
docker compose ps
docker compose logs --tail=100
git pull --ff-only
docker compose up -d --build
```

容器非 root 运行，根文件系统只读，数据通过宿主机 `data/` 目录持久化；停止/重建容器不会删除内容。容量统计仅计算已保存文本和文件的字节，数据库及索引不计入用户配额。会话有效期 14 天，退出即失效。登录连续错误 10 次后同一 IP 限制 10 分钟。

修改 `.env` 后用 `docker compose up -d --force-recreate` 生效。更改密码时可先安全备份 `.env`，删除原 `.env` 后重新运行配置脚本，重建容器；如需立即撤销旧登录，可在停止容器后删除 SQLite `sessions` 表中的记录。不要删除数据库或 `data/files/`。

备份时先停止服务，完整备份 `data/` 与 `.env`，再启动服务。恢复时先停止服务，将文件放回同一目录，执行 `chown -R 10001:10001 data` 并启动。备份含私人内容及密码哈希，应放在仓库之外并限制权限。

```bash
docker compose stop
tar -czf /root/file-transfer-backup-$(date +%Y%m%d-%H%M%S).tar.gz data .env
docker compose start
```

## 验证

测试在隔离临时目录使用测试账号，不读取生产数据：

```bash
docker compose run --rm --no-deps -v "$PWD/tests:/app/tests:ro" app python -m unittest discover -s tests -v
```

`.gitignore` 与 `.dockerignore` 排除真实 `.env`、上传文件、数据库、备份、私钥及缓存。仓库不包含服务器密码或登录密码。
