# AI 内部提效工具集

基于 DeepSeek API 的企业内部 AI 提效工具集。

## 功能

| 模块 | 说明 |
|------|------|
| 会议决策追踪器 | 上传录音自动转写 → AI 提取结构化纪要 → 选两次会议追踪决策 |
| 说明书瘦身器 | 上传 PDF 说明书 → AI 压缩为速查卡 |
| 智能客服回复 | 中英文消息自动分类（10 类意图）并生成回复草稿 |

## 技术栈

- **后端**：Flask
- **前端**：Vue.js 3（CDN）
- **AI**：DeepSeek API
- **语音转写**：OpenAI Whisper（tiny 模型，本地运行）

## 快速开始

### 1. 安装依赖

```bash
pip install flask openai python-dotenv openai-whisper librosa PyPDF2
```

### 2. 配置 API Key

编辑 `.env` 文件，填入 DeepSeek API Key：

```
DEEPSEEK_API_KEY=sk-你的key
```

### 3. 启动

```bash
python app.py local
```

浏览器打开 `http://127.0.0.1:5001`

## 项目结构

```
ai-tools/
├── app.py                   # Flask 后端入口（全部路由）
├── combined_app.py          # Flask 后端（旧版入口）
├── templates/
│   └── index.html           # Vue 前端页面（3 个 Tab）
├── .env                     # API Key 配置（不提交到 Git）
├── .gitignore
├── meetings.json            # 会议记录存储
├── requirements.txt
└── README.md
```

## API 端点

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/status` | GET | API 配置状态 |
| `/api/meetings` | GET | 会议列表 |
| `/api/meeting/upload-audio` | POST | 上传音频转写+提取纪要 |
| `/api/track` | POST | 决策追踪（支持会议ID或直接粘贴） |
| `/api/slim` | POST | PDF/文本说明书瘦身 |
| `/api/email` | POST | 智能客服回复 |
| `/api/demo/<type>` | GET | 示例数据 |
