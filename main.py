from astrbot import logger
from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, register
from astrbot.api import AstrBotConfig
from astrbot.api.message_components import Image, Video, File
import aiomysql
from aiomysql import DictCursor  
import json
import os
import aiohttp
from aiohttp import web  
import aiofiles
import hashlib
import datetime
import re  
from pathlib import Path
from typing import Optional
import asyncio

@register("web_archive", "yueye109", "MySQL存档+ 独立WebUI", "1.0.0")
class MySQLPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.config = config
        self.pool: Optional[aiomysql.Pool] = None

        # 基础目录初始化
        root_dir = Path(os.getcwd()).absolute()

        img_path_str = str(self.config.get("image_save_path", "")).strip()
        vid_path_str = str(self.config.get("video_save_path", "")).strip()

        self.is_save_image = self.config.get("is_save_image", True)
        self.image_save_path = Path(img_path_str) if img_path_str else (root_dir / "data" / "plugin_data" / "astrbot_plugin_web_archive" / "chat_images")
        self.image_save_path = self.image_save_path.absolute()

        self.is_save_video = self.config.get("is_save_video", True)
        self.video_save_path = Path(vid_path_str) if vid_path_str else (root_dir / "data" / "chat_videos")
        self.video_save_path = self.video_save_path.absolute()

        self.auto_cleanup = self.config.get("auto_cleanup", True)
        self.keep_days = self.config.get("keep_days", 60)
        
        # WebUI 配置与前端模板目录初始化
        self.web_port = self.config.get("web_port", 8055)
        self.template_dir = Path(__file__).parent / "templates"
        self.template_dir.mkdir(parents=True, exist_ok=True)

        self.whitelist_file = Path(__file__).parent / "whitelist.json"
        self.whitelist_file.parent.mkdir(parents=True, exist_ok=True)
        self.qq_group_map = self._load_whitelist()

        asyncio.create_task(self._init_db_and_tasks())

    def _load_whitelist(self):
        if self.whitelist_file.exists():
            try:
                with open(self.whitelist_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"读取白名单失败: {e}")
        return {}

    def _save_whitelist(self):
        try:
            with open(self.whitelist_file, 'w', encoding='utf-8') as f:
                json.dump(self.qq_group_map, f, ensure_ascii=False, indent=4)
        except Exception as e:
            logger.error(f"保存白名单失败: {e}")


    async def _init_db_and_tasks(self):
        try:
            logger.info("正在初始化 MySQL 连接...")
            self.pool = await aiomysql.create_pool(
                host=self.config.get("host", "127.0.0.1"),
                port=self.config.get("port", 3306),
                user=self.config.get("username", "root"),
                password=self.config.get("password", ""),
                db=self.config.get("database", "astrbot"),
                charset='utf8mb4',  # 支持 Emoji
                autocommit=True,
                minsize=1,
                maxsize=5
            )
            logger.info(">>> MySQL 连接成功")
            
            async with self.pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    # 读取外部 SQL 文件
                    sql_file_path = Path(__file__).parent / "init.sql" # 确保路径正确
                    if sql_file_path.exists():
                        async with aiofiles.open(sql_file_path, mode='r', encoding='utf-8') as f:
                            content = await f.read()
                            # 按分号分割多条语句
                            sql_statements = [s.strip() for s in content.split(';') if s.strip()]
                            for statement in sql_statements:
                                await cursor.execute(statement)
                        logger.info(">>> 数据库表结构初始化完成")
                    
                    # 索引
                    try:
                        await cursor.execute("CREATE INDEX idx_group_session ON messages (group_id(50), session_id(50));")
                        await cursor.execute("CREATE INDEX idx_month_created ON messages (month, created_time);")
                        logger.info(">>> 数据库索引检查/建立完成")
                    except Exception:
                        pass

            if self.auto_cleanup:
                asyncio.create_task(self._cleanup_loop())
            
            # 启动内置 WebUI
            asyncio.create_task(self._start_webui())
                
        except Exception as e:
            import traceback
            logger.error(f"插件初始化失败: {e}\n{traceback.format_exc()}")

    # ------------------ 内置 WebUI 逻辑 ------------------
    async def _start_webui(self):
        app = web.Application()
        
        static_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
        app.router.add_static('/static/', path=static_dir, name='static')
        
        app.router.add_get('/', self.web_index)
        app.router.add_post('/api/groups', self.web_api_groups)     
        app.router.add_post('/api/messages', self.web_api_messages) 
        app.router.add_get('/media/image/{hash}', self.web_media_image)
        app.router.add_get('/media/video/{hash}', self.web_media_video)
        app.router.add_get('/{group_id:\d+}', self.web_index)

        self.web_runner = web.AppRunner(app)
        await self.web_runner.setup()
        self.site = web.TCPSite(self.web_runner, '0.0.0.0', self.web_port)
        try:
            await site.start()
            logger.info(f">>> 内置 WebUI 已启动！请在浏览器访问: http://127.0.0.1:{self.web_port}")
        except Exception as e:
            logger.error(f"WebUI 端口 {self.web_port} 被占用或启动失败: {e}")

    async def web_index(self, request: web.Request):
        index_path = self.template_dir / "index.html"
        if not index_path.exists():
            return web.Response(
                status=404, 
                text="<h1>找不到前端页面！</h1><p>请确保你在插件目录下创建了 <code>templates/index.html</code> 文件。</p>", 
                content_type='text/html'
            )
        return web.FileResponse(str(index_path))

    # ---  接口 1：安全获取有权限的群组列表 ---
    async def web_api_groups(self, request: web.Request):
        try:
            data = await request.json()
        except:
            data = {}
            
        req_qq = data.get('qq', '')
        req_pwd = data.get('pwd', '')

        admin_qq = str(self.config.get("admin_qq", ""))
        admin_pwd = self.config.get("admin_pwd", "")

        is_admin = False
        allowed_groups = []

        # 身份验证
        if req_qq == admin_qq:
            if req_pwd == admin_pwd:
                is_admin = True
            else:
                return web.json_response({"status": "error", "message": "管理员密码错误", "data": []})
        elif req_qq in self.qq_group_map:
            allowed_groups = self.qq_group_map[req_qq]
        else:
            return web.json_response({"status": "error", "message": "QQ号未授权或密码错误", "data": []})

        groups_with_names = []
        async with self.pool.acquire() as conn:
            async with conn.cursor(DictCursor) as cursor:
                # 从数据库直接提取群号和群名的映射关系
                
                await cursor.execute("""
                    SELECT group_id, MAX(group_name) as group_name 
                    FROM messages 
                    WHERE group_id IS NOT NULL AND group_id != ''
                    GROUP BY group_id
                """)
                group_info = await cursor.fetchall()
                
                db_name_map = {str(r['group_id']): r['group_name'] for r in group_info if r.get('group_id')}

                # 提取私聊 session_id (私聊通常没有 group_name)
                await cursor.execute("""
                    SELECT DISTINCT session_id 
                    FROM messages 
                    WHERE session_id IS NOT NULL AND session_id != ''
                """)
                for r in await cursor.fetchall():
                    sid = str(r['session_id'])
                    if sid not in db_name_map:
                        db_name_map[sid] = sid 

                # 判断权限
                if is_admin:
                    final_groups = list(db_name_map.keys())
                else:
                    final_groups = allowed_groups

                # 去重并组装最终发给前端的数据
                final_groups = list(set([str(g) for g in final_groups if g]))
                for gid in final_groups:
                    await cursor.execute("""
                        SELECT group_name FROM messages 
                        WHERE (group_id = %s OR session_id = %s) AND group_name IS NOT NULL AND group_name != ''
                        ORDER BY created_time DESC LIMIT 1
                    """, (gid, gid))
                    
                    row = await cursor.fetchone()
                    
                    # 如果查到了最新的名字，就用新名字，否则退化为群号
                    name = row['group_name'] if row else None
                    display_name = name if name else gid
                    
                    groups_with_names.append({
                        "id": gid,
                        "name": display_name
                    })

        return web.json_response({"status": "success", "data": groups_with_names})

    # ---  接口 2：按需获取指定群组的消息 ---
    async def web_api_messages(self, request: web.Request):
        try:
            data = await request.json()
        except:
            data = {}
            
        limit = int(data.get('limit', 1000))
        req_qq = data.get('qq', '')
        req_pwd = data.get('pwd', '')
        target_id = data.get('target_id', '') 
        target_date = data.get('date', '')    

        if not target_id:
            return web.json_response({"status": "success", "data": []})

        admin_qq = str(self.config.get("admin_qq", ""))
        admin_pwd = self.config.get("admin_pwd", "")

        is_admin = (req_qq == admin_qq and req_pwd == admin_pwd)
        allowed_groups = self.qq_group_map.get(req_qq, [])

        # 越权拦截
        if not is_admin and target_id not in allowed_groups:
            return web.json_response({"status": "error", "message": "无权限查看该群", "data": []})

        async with self.pool.acquire() as conn:
            async with conn.cursor(DictCursor) as cursor:
                base_query = """
                    SELECT message_id, platform_type, session_id, group_id, sender, message_str, image_ids, video_ids, created_time 
                    FROM messages 
                    WHERE (group_id = %s OR session_id = %s)
                """
                params = [target_id, target_id]

                # 精准过滤日期
                if target_date:
                    base_query += " AND created_time LIKE %s"
                    params.append(f"{target_date}%")

                base_query += " ORDER BY created_time DESC LIMIT %s"
                params.append(limit)

                await cursor.execute(base_query, tuple(params))
                rows = await cursor.fetchall()

                for row in rows:
                    row['sender'] = json.loads(row['sender'])
                    row['image_ids'] = json.loads(row['image_ids'] or "[]")
                    row['video_ids'] = json.loads(row['video_ids'] or "[]")
                    row['created_time'] = row['created_time'].strftime("%Y-%m-%d %H:%M:%S")

                return web.json_response({"status": "success", "data": rows})

    async def web_media_image(self, request: web.Request):
        h = request.match_info.get('hash')
        async with self.pool.acquire() as conn:
            async with conn.cursor(DictCursor) as cursor:
                await cursor.execute("SELECT file_path FROM image_assets WHERE image_hash = %s", (h,))
                res = await cursor.fetchone()
                if res and os.path.exists(res['file_path']):
                    return web.FileResponse(res['file_path'])
        return web.Response(status=404, text="Image Not Found")

    async def web_media_video(self, request: web.Request):
        h = request.match_info.get('hash')
        async with self.pool.acquire() as conn:
            async with conn.cursor(DictCursor) as cursor:
                await cursor.execute("SELECT file_path FROM video_assets WHERE video_hash = %s", (h,))
                res = await cursor.fetchone()
                if res and os.path.exists(res['file_path']):
                    return web.FileResponse(res['file_path'])
        return web.Response(status=404, text="Video Not Found")

    # ------------------ 资源下载逻辑 ------------------
    async def _download_and_store(self, url: str, base_save_path: Path, asset_table: str, sub_folder: str) -> Optional[str]:
        if not url: return None
        try:
            sha256_obj = hashlib.sha256()
            temp_file_name = f"temp_{datetime.datetime.now().timestamp()}.tmp"
            
            target_dir = base_save_path / sub_folder
            target_dir.mkdir(parents=True, exist_ok=True)
            temp_file_path = target_dir / temp_file_name

            file_size = 0
            header_bytes = b"" 
            
            async with aiohttp.ClientSession() as session:
                async with session.get(url) as resp:
                    if resp.status != 200: return None
                    
                    async with aiofiles.open(temp_file_path, mode='wb') as f:
                        async for chunk in resp.content.iter_chunked(65536):
                            if file_size == 0:
                                header_bytes = chunk[:12]
                            await f.write(chunk)
                            sha256_obj.update(chunk)
                            file_size += len(chunk)

            sha256_hash = sha256_obj.hexdigest()

            async with self.pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute(f"SELECT file_path FROM {asset_table} WHERE {asset_table[:-7]}_hash=%s", (sha256_hash,))
                    if await cursor.fetchone():
                        if temp_file_path.exists():
                            temp_file_path.unlink()
                        return sha256_hash

                    file_ext = ".dat"
                    if asset_table == "image_assets":
                        if header_bytes[:4].startswith(b'\x89PNG'): file_ext = ".png"
                        elif header_bytes[:3].startswith(b'GIF'): file_ext = ".gif"
                        elif header_bytes[:4].startswith(b'RIFF') and header_bytes[8:12] == b'WEBP': file_ext = ".webp"
                        else: file_ext = ".jpg"
                    elif asset_table == "video_assets":
                        file_ext = ".mp4"

                    file_name = f"{sha256_hash}{file_ext}"
                    abs_path = str(target_dir / file_name)
                    
                    temp_file_path.rename(abs_path)

                    await cursor.execute(f"""
                        INSERT INTO {asset_table} ({asset_table[:-7]}_hash, file_path, file_size, created_time)
                        VALUES (%s, %s, %s, %s)
                    """, (sha256_hash, abs_path, file_size, datetime.datetime.now()))
                    
                    return sha256_hash

        except Exception as e:
            logger.error(f"下载/存储失败 {url}: {e}")
            if 'temp_file_path' in locals() and temp_file_path.exists():
                temp_file_path.unlink()
            return None

    async def _process_image(self, url: str, sub_folder: str) -> Optional[str]:
        if self.is_save_image:
            return await self._download_and_store(url, self.image_save_path, "image_assets", sub_folder)
        return None

    async def _process_video(self, url: str, sub_folder: str) -> Optional[str]:
        if self.is_save_video:
            return await self._download_and_store(url, self.video_save_path, "video_assets", sub_folder)
        return None

    # ------------------ 消息入库逻辑 ------------------
    @filter.event_message_type(filter.EventMessageType.ALL)
    async def on_all_message(self, event: AstrMessageEvent):
        if not self.pool: 
            return 
            
        try:
            msg = event.message_obj
            meta = event.platform_meta

            dt_object = datetime.datetime.fromtimestamp(msg.timestamp)
            msg_month = dt_object.strftime("%Y-%m-%d")

            sender_id = str(msg.sender.user_id)
            target_id = str(msg.group_id) if msg.group_id else str(event.session_id)
            
            group_name = getattr(msg, 'group_name', None)
            
            if not group_name and msg.group_id:
                if not hasattr(self, 'group_name_cache'):
                    self.group_name_cache = {}
                
                if target_id in self.group_name_cache:
                    group_name = self.group_name_cache[target_id]
                else:
                    try:
                        # 确保当前平台是支持 OneBot 协议的平台 (如 aiocqhttp)
                        if hasattr(event, 'bot') and hasattr(event.bot, 'api'):
                            
                            payloads = {
                                "group_id": int(msg.group_id),
                                "no_cache": False
                            }
                            api_ret = await event.bot.api.call_action('get_group_info', **payloads)
                            
                            if api_ret and isinstance(api_ret, dict):
                                # 提取数据 (兼容 {"status": "ok", "data": {"group_name": "..."}} 格式)
                                data_dict = api_ret.get("data", api_ret) 
                                fetched_name = data_dict.get("group_name")
                                
                                if fetched_name:
                                    group_name = fetched_name
                                    self.group_name_cache[target_id] = fetched_name
                                else:
                                    group_name = target_id
                                    self.group_name_cache[target_id] = target_id
                            else:
                                group_name = target_id
                                self.group_name_cache[target_id] = target_id
                        else:
                            group_name = target_id
                            self.group_name_cache[target_id] = target_id
                            
                    except Exception as e:
                        logger.error(f"获取群名失败 (群号: {target_id}): {e}")
                        group_name = target_id
                        self.group_name_cache[target_id] = target_id
            

            if sender_id and target_id:
                if sender_id not in self.qq_group_map:
                    self.qq_group_map[sender_id] = []
                # 只要发现这个人在新群里说话了，立刻拉入白名单并保存到本地 JSON
                if target_id not in self.qq_group_map[sender_id]:
                    self.qq_group_map[sender_id].append(target_id)
                    self._save_whitelist()

            image_hashes, video_hashes = [], []
            comp_types = []
            
            # --- 原始数据预处理 ---
            raw_data = msg.raw_message
            if isinstance(raw_data, str):
                try:
                    raw_data = json.loads(raw_data)
                except:
                    pass
            
            # --- 【拦截器】：优雅处理系统通知 (Notice) ---
            is_notice = False
            final_message_str = event.message_str.strip()
            
            if isinstance(raw_data, dict) and raw_data.get("post_type") == "notice":
                is_notice = True
                notice_type = raw_data.get("notice_type", "")
                
                if notice_type == "group_upload":
                    file_info = raw_data.get("file", {})
                    file_name = file_info.get("name", "未知文件")
                    size_mb = file_info.get("size", 0) / (1024 * 1024)
                    final_message_str = f"[上传了群文件: {file_name} ({size_mb:.2f}MB)]"
                elif notice_type == "group_increase":
                    final_message_str = "[有人加入了群聊]"
                elif notice_type == "group_decrease":
                    final_message_str = "[有人退出了群聊]"
                elif notice_type == "notify" and raw_data.get("sub_type") == "poke":
                    final_message_str = "[拍了拍/戳一戳]"
                
                # --- 撤回防丢失 & 数据库反查昵称功能 ---
                elif notice_type in ["group_recall", "friend_recall"]:
                    operator_id = raw_data.get("operator_id")
                    user_id = raw_data.get("user_id")
                    recalled_msg_id = raw_data.get("message_id")
                    
                    # 默认先用框架自带的昵称，如果没有就用 QQ 号保底
                    recalled_nickname = getattr(msg.sender, 'nickname', None) or str(user_id)
                    
                    # 去我们自己的数据库里，捞出被撤回那条消息对应的真实历史昵称
                    if recalled_msg_id:
                        try:
                            async with self.pool.acquire() as conn:
                                async with conn.cursor() as cursor:
                                    await cursor.execute("SELECT sender FROM messages WHERE message_id = %s", (str(recalled_msg_id),))
                                    row = await cursor.fetchone()
                                    if row and row[0]:
                                        old_sender_data = json.loads(row[0])
                                        if old_sender_data.get("nickname"):
                                            recalled_nickname = old_sender_data.get("nickname")
                        except Exception:
                            pass 

                    if notice_type == "group_recall":
                        if str(operator_id) == str(user_id):
                            final_message_str = f"[{recalled_nickname} 撤回了一条消息]"
                        else:
                            final_message_str = f"[管理员撤回了 {recalled_nickname} 的一条消息]"
                    else:
                        final_message_str = f"[{recalled_nickname} 撤回了一条消息]"
                
                else:
                    final_message_str = f"[群系统通知: {notice_type}]"

            # --- 如果是常规聊天消息，再去解析并下载媒体文件 ---
            if not is_notice:
                if isinstance(raw_data, dict) and "message" in raw_data:
                    raw_data = raw_data["message"]

                if isinstance(raw_data, list):
                    for segment in raw_data:
                        if not isinstance(segment, dict): continue
                        
                        seg_type = segment.get("type", "")
                        data = segment.get("data", {})
                        comp_types.append(seg_type) 
                        
                        if seg_type == "video":
                            url = data.get("url") or data.get("file") or data.get("file_id")
                            if url and isinstance(url, str) and url.startswith("http"):
                                h = await self._process_video(url, msg_month)
                                if h: video_hashes.append(h)
                                
                        elif seg_type == "image":
                            url = data.get("url") or (data.get("file") if str(data.get("file", "")).startswith("http") else None)
                            if url:
                                h = await self._process_image(url, msg_month)
                                if h: image_hashes.append(h)
                                
                        elif seg_type == "file":
                            url = data.get("url")
                            file_name = str(data.get("name", data.get("file", ""))).lower()
                            if url and url.startswith("http") and file_name.endswith(('.mp4', '.mov', '.avi', '.mkv')):
                                h = await self._process_video(url, msg_month)
                                if h: video_hashes.append(h)

                # 框架组件兜底抓取
                if not image_hashes and not video_hashes:
                    for component in msg.message:
                        comp_types.append(type(component).__name__.lower())
                        if type(component).__name__.lower() == "video":
                            url = getattr(component, 'url', getattr(component, 'file', getattr(component, 'path', getattr(component, 'file_id', None))))
                            if url and isinstance(url, str) and url.startswith("http"):
                                h = await self._process_video(url, msg_month)
                                if h: video_hashes.append(h)

                # 文本清洗与空白兜底逻辑
                if image_hashes or video_hashes:
                    final_message_str = re.sub(r'\[(File|Video|Image|文件|视频|图片|不支持的格式.*?)\]', '', final_message_str, flags=re.IGNORECASE).strip()

                if not final_message_str and not image_hashes and not video_hashes:
                    types_str = " ".join(comp_types).lower()
                    if "video" in types_str:
                        final_message_str = "[视频 (链接获取失败/未开放外链)]" 
                    elif "nudge" in types_str or "poke" in types_str:
                        final_message_str = "[拍了拍/戳一戳]"
                    elif "face" in types_str or "mface" in types_str:
                        final_message_str = "[互动表情]"
                    elif "record" in types_str:
                        final_message_str = "[语音消息]"
                    elif "json" in types_str or "xml" in types_str:
                        final_message_str = "[卡片/小程序消息]"
                    else:
                        final_message_str = f"[特殊互动格式: {','.join(set(comp_types))}]"

            # 统一收集发件人信息
            sender_data = {
                'user_id': msg.sender.user_id,
                'nickname': msg.sender.nickname,
                'platform_id': getattr(meta, 'id', 'unknown')
            }

            # 执行入库
            async with self.pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    #  修改点：增加了 group_name 字段及其占位符 %s
                    await cursor.execute("""
                        INSERT INTO messages (message_id, platform_type, self_id, session_id, group_id, group_name,
                                              sender, message_str, raw_message, image_ids, video_ids,
                                              timestamp, created_time, month)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """, (
                        msg.message_id,
                        meta.name,
                        event.get_self_id() if hasattr(event, 'get_self_id') else msg.self_id,
                        event.session_id,
                        msg.group_id or None,
                        group_name,                                  #  传入提取到的群名
                        json.dumps(sender_data, ensure_ascii=False),
                        final_message_str,
                        json.dumps(msg.raw_message, ensure_ascii=False),
                        json.dumps(image_hashes),
                        json.dumps(video_hashes),
                        msg.timestamp,
                        dt_object,
                        msg_month
                    ))
        except Exception as e:
            logger.error(f"日志记录异常: {e}")

    # ------------------ 自动清理逻辑 ------------------
    async def _cleanup_loop(self):
        while True:
            try:
                await self._cleanup_old_months()
            except Exception as e:
                logger.error(f"自动清理异常: {e}")
            await asyncio.sleep(24*3600)

    async def _cleanup_old_months(self):
        now = datetime.datetime.now()
        cutoff_month = (now - datetime.timedelta(days=self.keep_days)).strftime("%Y-%m")

        async with self.pool.acquire() as conn:
            async with conn.cursor() as cursor:
                await cursor.execute("SELECT DISTINCT month FROM messages WHERE month < %s AND month_saved=0", (cutoff_month,))
                months_to_delete = [row[0] for row in await cursor.fetchall()]

                for month in months_to_delete:
                    await cursor.execute("SELECT image_ids, video_ids FROM messages WHERE month=%s", (month,))
                    rows = await cursor.fetchall()
                    for image_ids_json, video_ids_json in rows:
                        image_ids = json.loads(image_ids_json or "[]")
                        video_ids = json.loads(video_ids_json or "[]")
                        for img_hash in image_ids:
                            await self._delete_asset_if_unused("image_assets", "image_hash", img_hash)
                        for vid_hash in video_ids:
                            await self._delete_asset_if_unused("video_assets", "video_hash", vid_hash)

                    await cursor.execute("DELETE FROM messages WHERE month=%s", (month,))
                    logger.info(f"自动删除未保存月份消息: {month}")

    async def _delete_asset_if_unused(self, table: str, hash_column: str, asset_hash: str):
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cursor:
                await cursor.execute(f"SELECT COUNT(*) FROM messages WHERE JSON_CONTAINS({hash_column.replace('_assets','_ids')}, %s)", (json.dumps(asset_hash),))
                count = (await cursor.fetchone())[0]
                if count == 0:
                    await cursor.execute(f"SELECT file_path FROM {table} WHERE {hash_column}=%s", (asset_hash,))
                    row = await cursor.fetchone()
                    if row:
                        file_path = row[0]
                        if os.path.exists(file_path):
                            os.remove(file_path)
                            try:
                                folder_path = os.path.dirname(file_path)
                                os.rmdir(folder_path)
                            except OSError:
                                pass
                    await cursor.execute(f"DELETE FROM {table} WHERE {hash_column}=%s", (asset_hash,))

    # ------------------ 指令：保存整个月 ------------------
    @filter.command("save_month")
    async def save_month_cmd(self, event: AstrMessageEvent, month: str):
        """保存整个月消息不受自动清理影响 (格式：YYYY-MM)"""
        if not self.pool:
            yield event.plain_result("插件未初始化或数据库不可用")
            return

        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute("UPDATE messages SET month_saved=1 WHERE month=%s", (month,))
            yield event.plain_result(f"{month} 的消息已标记永久保存，不会被自动清理。")
        except Exception as e:
            logger.error(f"标记保存失败: {e}")
            yield event.plain_result("指令执行失败，请检查控制台报错。")

    async def terminate(self):
        if getattr(self, "web_runner", None):
            await self.web_runner.cleanup()
            logger.info("内置 WebUI 已安全关闭")
            
        if getattr(self, "pool", None):
            self.pool.close()
            await self.pool.wait_closed()
            
    @filter.command("chat_stats")
    async def chat_stats_cmd(self, event: AstrMessageEvent):
        """查看聊天记录及媒体存储统计"""
        if not self.pool:
            yield event.plain_result("插件未初始化或数据库不可用")
            return

        try:
            db_name = self.config.get("database", "astrbot")

            async with self.pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute("SELECT COUNT(*) FROM messages")
                    msg_count = (await cursor.fetchone())[0] or 0

                    await cursor.execute("SELECT COUNT(*), SUM(file_size) FROM image_assets")
                    img_res = await cursor.fetchone()
                    img_count = img_res[0] or 0
                    img_size_bytes = int(img_res[1] or 0)

                    await cursor.execute("SELECT COUNT(*), SUM(file_size) FROM video_assets")
                    vid_res = await cursor.fetchone()
                    vid_count = vid_res[0] or 0
                    vid_size_bytes = int(vid_res[1] or 0)

                    await cursor.execute("""
                        SELECT SUM(data_length + index_length) 
                        FROM information_schema.TABLES 
                        WHERE table_schema = %s
                    """, (db_name,))
                    db_size_res = await cursor.fetchone()
                    db_size_bytes = int(db_size_res[0] or 0)

            def format_size(size_bytes):
                if size_bytes < 1024:
                    return f"{size_bytes} B"
                elif size_bytes < 1024 * 1024:
                    return f"{size_bytes / 1024:.2f} KB"
                elif size_bytes < 1024 * 1024 * 1024:
                    return f"{size_bytes / (1024 * 1024):.2f} MB"
                else:
                    return f"{size_bytes / (1024 * 1024 * 1024):.2f} GB"

            img_size_str = format_size(img_size_bytes)
            vid_size_str = format_size(vid_size_bytes)
            db_size_str = format_size(db_size_bytes)
            
            total_media_bytes = img_size_bytes + vid_size_bytes
            total_all_bytes = total_media_bytes + db_size_bytes

            reply_text = (
                f"📊 聊天存档统计信息\n"
                f"----------------------\n"
                f"💬 消息总数：{msg_count} 条\n"
                f"🗄️ 数据库大小：{db_size_str}\n"
                f"🖼️ 图片总数：{img_count} 张 ({img_size_str})\n"
                f"🎬 视频总数：{vid_count} 个 ({vid_size_str})\n"
                f"----------------------\n"
                f"💾 媒体占用：{format_size(total_media_bytes)}\n"
                f"📦 整体总占用：{format_size(total_all_bytes)}"
            )
            yield event.plain_result(reply_text)

        except Exception as e:
            logger.error(f"获取统计信息失败: {e}")
            yield event.plain_result("获取统计信息失败，请检查控制台报错。")