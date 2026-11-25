# 公网部署指南（安全加固版）

目标：应用只监听 `127.0.0.1`，由 Nginx 终止 TLS 并做第一层限流/拦截，FastAPI 内置安全层做第二层防护。**不要**把 8100 端口直接暴露到公网。

> 内置限流是单进程内存实现，只能配合单 worker 运行（本仓库的 systemd 单元即为单 worker）。如需多进程/多实例，必须在 Nginx 或网关层完成限流，不能依赖应用内计数。

## 1. 主机与账号

```bash
sudo useradd --system --home /opt/helper --shell /usr/sbin/nologin helper
sudo mkdir -p /opt/helper /etc/helper
sudo chown -R helper:helper /opt/helper

# 代码放到 /opt/helper，创建虚拟环境
cd /opt/helper
sudo -u helper python3 -m venv .venv
sudo -u helper .venv/bin/pip install fastapi uvicorn pydantic requests numpy scipy

# 数据库与缓存目录（systemd 的 ReadWritePaths 依赖此目录存在）
sudo -u helper mkdir -p /opt/helper/data
sudo chmod 700 /opt/helper/data
```

只开放 80/443（以及 SSH），不要开放 8000/8100：

```bash
sudo ufw allow 80,443/tcp
```

## 2. 环境变量

写入 `/etc/helper/helper.env`，权限 `600`、属主 `root:helper`：

```ini
# 必填：你的公网域名（不匹配的 Host 会被直接拒绝）
HELPER_ALLOWED_HOSTS=example.com

# 必填：强制 HTTPS（反向代理已传 X-Forwarded-Proto=https）
HELPER_REQUIRE_HTTPS=1
HELPER_TRUSTED_PROXIES=127.0.0.1,::1
HELPER_SESSION_COOKIE_SECURE=auto

# 注册策略：invite 需邀请码；closed 完全关闭；open 完全开放（不建议公网使用）
HELPER_REGISTRATION_MODE=invite
HELPER_INVITE_CODE=请替换为足够长的随机邀请码

# 会话与限流（按需调整）
HELPER_SESSION_TTL_DAYS=7
HELPER_LOGIN_FAIL_MAX=5
HELPER_LOGIN_FAIL_WINDOW_SECONDS=300
HELPER_RATE_GLOBAL_PER_MINUTE=600
HELPER_RATE_AUTH_PER_MINUTE=30
HELPER_RATE_EXPENSIVE_PER_MINUTE=60
HELPER_MAX_BODY_BYTES=262144

# 可选：大乐透实验室刷新接口管理令牌（实验室不建议公网暴露）
LAB_ADMIN_TOKEN=请替换为足够长的随机令牌
```

生成随机值：`python3 -c "import secrets; print(secrets.token_urlsafe(32))"`。

## 3. 启动服务

```bash
sudo cp deploy/helper.service /etc/systemd/system/helper.service
sudo systemctl daemon-reload
sudo systemctl enable --now helper
sudo systemctl status helper
```

确认只监听回环：`ss -lntp | grep 8100` 应显示 `127.0.0.1:8100`。

## 4. Nginx 与证书

```bash
sudo mkdir -p /etc/nginx/snippets /var/www/certbot
sudo cp deploy/nginx-proxy-snippet.conf /etc/nginx/snippets/helper-proxy.conf
sudo cp deploy/nginx-helper.conf /etc/nginx/conf.d/helper.conf
# 编辑 server_name、证书路径
sudo nginx -t && sudo systemctl reload nginx
```

首次签发证书（示例）：

```bash
sudo certbot certonly --webroot -w /var/www/certbot -d example.com
sudo systemctl reload nginx
```

## 5. 上线后验证

```bash
# 1) HTTP 应 301 到 HTTPS
curl -I http://example.com

# 2) 安全响应头
curl -sI https://example.com/login | grep -Ei 'strict-transport|content-security|x-frame|x-content-type'

# 3) 扫描路径应 404
curl -s -o /dev/null -w '%{http_code}\n' https://example.com/.git/config

# 4) 登录接口应有独立限流（连续请求出现 429）
for i in $(seq 1 20); do
  curl -s -o /dev/null -w '%{http_code} ' -X POST https://example.com/api/helper/auth/login \
    -H 'Content-Type: application/json' -d '{"username":"nobody","password":"badpass"}'
done; echo
```

## 6. 部署检查清单

- [ ] 8100/8000 未对公网开放，仅监听 `127.0.0.1`
- [ ] `HELPER_ALLOWED_HOSTS` 为真实域名，`HELPER_REQUIRE_HTTPS=1`
- [ ] 注册模式为 `invite` 或 `closed`
- [ ] 数据库文件权限 `600`，数据目录 `700`（目录由部署步骤设置，文件启动时自动收紧）
- [ ] `/docs`、`/redoc`、`/openapi.json` 返回 404
- [ ] HSTS、CSP、X-Frame-Options 等响应头存在
- [ ] 登录连续失败会触发 429，日志中可见 `auth_event=login_failed`
- [ ] `data/` 已加入备份计划，且备份文件不公开
- [ ] 操作系统与依赖定期更新
