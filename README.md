# 海军科技 · 赛鸽成绩实时查询

数据来源：赛鸽资讯网（saige.com）林甸县乐天赛鸽运动协会公开发布成绩表。  
自动发现新比赛文章，实时查询，完全免费，无需登录。

## 本地运行

```bash
python3 server.py
```

浏览器打开 http://127.0.0.1:8080

## 云服务器部署（推荐）

### 方式一：Railway（免费额度，推荐）

1. 打开 https://railway.app 注册/登录
2. New Project → Deploy from GitHub（先把本目录推到 GitHub）
   或 直接用 Railway CLI：
   ```bash
   npm i -g @railway/cli
   railway login
   railway init
   railway up
   ```
3. 部署完成后会得到一个公网网址，手机直接访问即可

### 方式二：Render

1. 打开 https://render.com 注册
2. New → Web Service
3. 连接 GitHub 仓库，或手动上传
4. Runtime: Python
5. Build Command: 留空
6. Start Command: `python3 server.py`
7. 部署后获得公网地址

### 方式三：自己的 VPS（Ubuntu）

```bash
# 上传本目录到服务器后
cd 海军科技_实时查询
nohup python3 server.py > app.log 2>&1 &

# 或用 systemd 保活，端口默认 8080
# 可用 nginx 反代到 80/443
```

### 方式四：Docker

```bash
docker build -t haijun-saige .
docker run -d -p 8080:8080 --name saige haijun-saige
```

## 接口

- `GET /` 手机查询页面
- `GET /api/query?ring=2026-08-0493701` 查询成绩
- `GET /api/races` 当前已发现的成绩列表
- `GET /api/refresh` 强制刷新成绩列表

## 说明

成绩列表会自动从协会首页发现新文章，缓存 1 小时。  
源站更新新比赛后，最多 1 小时内会自动纳入查询（或访问 /api/refresh 立即刷新）。
