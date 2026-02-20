# 📦 AstrBot Web Archive Pro (MySQL存档 + 独立WebUI)

基于 MySQL 8 的全功能聊天记录存档插件。不仅是冷冰冰的聊天日志，更是一个 WebUI 的消息画廊。一切撤回，统统绳之以法！

## [WebUI展示]<img width="1913" height="933" alt="d945f2a7c0ccf6a18b3521c27141e9e6" src="https://github.com/user-attachments/assets/ec4a776d-963c-41dd-b311-faed1fb879c7" />
<img width="554" height="364" alt="image" src="https://github.com/user-attachments/assets/1dfa49d3-3eea-466f-aaa2-dfb28d26a6cf" />




## ✨ 核心特性

- 🗄️ **全媒体存底**：自动抓取并本地化保存文本、图片、*视频(new)*，SHA256 去重，变相完美防撤回。
- 🎨 **WebUI(new)**：内置轻量级 Web 服务，支持全屏透明壁纸。
- ⏱️ **水滴时间轴(new)**：右下角极简进度条，按时间节点瞬间滑动跳转，海量消息顺滑触底无闪烁。
- 💖 **Emoji 支持(new)**：原生采用 `utf8mb4` 字符集建表，彻底告别特殊表情导致的入库报错。
- 🧹 **空间管理(new)**：内置过期媒体自动清理机制（默认 60 天），支持指令永久锁定特定月份。
- 🔐 **鉴权隔离(new)**：管理员可纵览全域，普通用户经配置后仅可查看自己所在的群组记录。

---

## 🚀 快速上手

### 1. 安装依赖
请确保环境中已安装以下异步库：
```bash
pip install aiomysql aiohttp aiofiles
```

### 2. 部署插件
将本插件放入 AstrBot 的 `plugins/` 目录下，重启机器人。
媒体文件默认存入 `Astrbot/data/plugin_data/astrbot_plugin_web_archive`

*插件初次运行会自动在数据库中创建所需的数据表（支持 MySQL 8）。*

### 3. 可视化配置
进入 AstrBot 控制面板的**插件配置**页面，直接填写以下信息：
- **MySQL 数据库连接**（Host、端口、账号、密码、库名）
- **WebUI 端口**
- **管理员 QQ 与 登录密码**

### 4. 访问查阅
配置完成并有新消息入库后，打开浏览器访问：
👉 `http://你的服务器IP:port`

*(注：你可以将 `static/bg2.jpg` 替换为自己喜欢的壁纸，获得极致的透明悬浮体验！)  `template/index.html` 也需对应修改*

---

## 💻 交互指令

| 指令 | 说明 | 权限 |
| :--- | :--- | :--- |
| `/chat_stats` | 查看当前数据库消息总数、媒体文件数量及硬盘空间占用情况。 | 全局 |
| `/save_month YYYY-MM` | 将指定月份（如 `2026-02`）标记为永久保存，豁免自动清理逻辑。 | 全局 |

---
*Powered by Gemini3 | Fork from https://github.com/LWWD/astrbot_plugin_sql_history.*
