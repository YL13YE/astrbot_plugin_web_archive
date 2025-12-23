# MySQL存储
(支持 MySQL8 )
记录历史聊天信息, 会自动创建message表, 一切撤回都绳之以法！

功能：将所有聊天记录存入数据库。方便后续统计分析, 例如日活,月活,以及变相防撤回.

配置：
![img.png](img.png)

```sql
create table messages
(
    message_id    varchar(255) not null
        primary key,
    platform_type varchar(50)  not null,
    self_id       varchar(255) not null,
    session_id    varchar(255) not null,
    group_id      varchar(255) null,
    sender        json         not null,
    message_str   text         not null,
    raw_message   longtext null,
    timestamp     int          not null
) engine = InnoDB;

```
# 1.1.0 
支持存储图片和时间戳

## 迁移方案
### A 
删除以前message表，更新代码后重启，回自动建表

### B
1. 创建新表 image_assets
```sql
CREATE TABLE IF NOT EXISTS image_assets (
    image_hash    VARCHAR(64) PRIMARY KEY,
    file_path     TEXT NOT NULL,
    file_size     INT,
    created_time  DATETIME NOT NULL
);
```
2. 修改 messages 表
```sql
# 添加两个新字段 
ALTER TABLE messages ADD COLUMN image_ids JSON;
ALTER TABLE messages ADD COLUMN created_time DATETIME;
```
