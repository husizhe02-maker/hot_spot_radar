# 中文社媒热点雷达（AI 增强版）

这是一个用于影视娱乐账号运营的社媒热点雷达看板。它会低频采集公开热榜，进行热点去重、聚类、评分、风险识别，并生成短视频选题角度、标题模板和标签建议。

## 功能

- 公开热榜采集：微博、百度、B站、抖音、小红书实验入口
- 热点清洗、去重与聚类
- 本地规则评分：排名、热度、跨平台共振、影视娱乐相关性、风险词
- 可选 OpenAI API 增强：AI 判断、选题角度、标题模板、标签建议
- 静态网页看板：`dashboard.html`
- GitHub Actions 定时刷新并部署到 GitHub Pages

## 本地运行

```powershell
python hotspot_radar.py
python -m http.server 8000 --bind 127.0.0.1
```

打开：

```text
http://127.0.0.1:8000/dashboard.html
```

## AI 增强

```powershell
$env:OPENAI_API_KEY="你的 OpenAI API key"
python hotspot_radar.py --ai --ai-limit 10
```

默认模型是 `gpt-5-nano`，也可以指定：

```powershell
python hotspot_radar.py --ai --ai-model gpt-5-mini --ai-limit 20
```

## GitHub Pages 部署

仓库包含 `.github/workflows/deploy-pages.yml`。进入 GitHub：

1. `Settings -> Pages`
2. Source 选择 `GitHub Actions`
3. `Actions -> Deploy hotspot radar`
4. 点击 `Run workflow`

如果要开启 AI 增强，在 `Settings -> Secrets and variables -> Actions` 添加：

- Secret: `OPENAI_API_KEY`
- Variable: `OPENAI_MODEL`，可选，默认 `gpt-5-nano`
- Variable: `AI_LIMIT`，可选，默认 `10`

工作流默认每 6 小时自动刷新一次。

## 合规边界

本项目只做公开热榜轻量采集，不做登录态抓取、不绕验证码、不抓评论、不下载视频、不模拟 App 抓包。若某个平台公开入口限制访问，工具会记录采集提示并继续处理其他平台。
