# 中文社媒热点雷达

这是一个用于影视娱乐/社媒运营场景的热点雷达看板。它可以采集公开热榜和 TikHub 热榜数据，做基础去重、聚类、评分、风险识别，并在需要时调用 AI 生成智能总结和选题建议。

## 当前能力

- 基础看板默认不调用 AI，只展示热点、评分、推荐等级、风险等级、来源链接。
- 点击「刷新数据」会由后端重新采集最新热点。
- 每张卡片可单独点击「智能总结」，使用 OpenAI 联网搜索后总结该热点。
- 每张卡片可单独点击「智能选题」，使用 OpenAI 生成选题角度、标题模板和标签。
- 支持 TikHub：抖音热榜、微博文娱、小红书热榜。
- 百度和 B 站保留为补充来源，但评分权重更低。

## 本地运行

```powershell
python server.py 8031
```

打开：

```text
http://127.0.0.1:8031/dashboard.html
```

刷新数据：直接点看板右上角「刷新数据」。

## 环境变量

本地可以创建 `.env`，线上 Render 在后台 Environment 里配置：

```text
OPENAI_API_KEY=sk-your-openai-api-key
OPENAI_MODEL=gpt-5-mini
OPENAI_WEB_MODEL=gpt-5.5
TIKHUB_API_KEY=your-tikhub-bearer-token
```

说明：

- `OPENAI_API_KEY`：只在点击「智能总结」或「智能选题」时使用。
- `OPENAI_MODEL`：智能选题模型，当前建议 `gpt-5-mini`。
- `OPENAI_WEB_MODEL`：联网总结模型，当前建议 `gpt-5.5`。
- `TIKHUB_API_KEY`：用于获取抖音、微博文娱、小红书等更稳定的热点来源。

## Render 部署

仓库包含 `render.yaml`，可以直接用 Render Blueprint 部署。

1. 打开 Render Dashboard。
2. 点击 `New`，选择 `Blueprint`。
3. 连接 GitHub 仓库 `husizhe02-maker/hot_spot_radar`。
4. Render 会读取 `render.yaml` 创建 Web Service。
5. 在 Environment 中填入：
   - `OPENAI_API_KEY`
   - `TIKHUB_API_KEY`
6. 部署完成后访问：

```text
https://你的服务名.onrender.com/dashboard.html
```

部署后，别人打开这个 Render 链接也可以使用看板。免费版 Render 可能会休眠，第一次打开或第一次刷新会慢一些。

## 合规边界

本项目只做公开热榜和授权 API 的轻量采集，不做登录态抓取、不绕验证码、不抓评论、不下载视频、不模拟 App 抓包。若某个平台限制公开入口，工具会记录采集提示并继续处理其他平台。
