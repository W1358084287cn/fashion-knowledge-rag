-- ============================================================
-- 服装多源文档智能客服系统 - MySQL 初始化脚本
-- 适用版本：MySQL 8.0+
-- 说明：docker compose 首次启动会自动执行本脚本；
--       若使用已有 MySQL，也可手动执行：mysql -uroot -p < init.sql
-- 默认管理员：admin / 123456（密码以 SHA256 摘要存储）
-- ============================================================

CREATE DATABASE IF NOT EXISTS `fashion_cs`
  DEFAULT CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;

USE `fashion_cs`;

-- ------------------------------------------------------------
-- 1. 管理员表
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS `admins` (
  `id` BIGINT NOT NULL AUTO_INCREMENT,
  `username` VARCHAR(50) NOT NULL COMMENT '管理员账号',
  `password_hash` VARCHAR(128) NOT NULL COMMENT 'SHA256 密码摘要',
  `created_at` DATETIME DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_admin_username` (`username`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='管理员账号表';

-- 默认密码 123456 的 SHA256 摘要
INSERT IGNORE INTO `admins` (`username`, `password_hash`)
VALUES ('admin', '8d969eef6ecad3c29a3a629280e686cf0c3f5d5a86aff3ca12020c923adc6c92');

-- ------------------------------------------------------------
-- 1.1 普通用户账号表（演示环境固定账号 demo / 123456，登录页预填一键登录）
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS `user_accounts` (
  `id` BIGINT NOT NULL AUTO_INCREMENT,
  `username` VARCHAR(50) NOT NULL COMMENT '登录账号',
  `password_hash` VARCHAR(128) NOT NULL COMMENT 'SHA256 密码摘要',
  `display_name` VARCHAR(50) DEFAULT '' COMMENT '展示昵称',
  `created_at` DATETIME DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  `last_login_at` DATETIME DEFAULT NULL COMMENT '最近登录时间',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_user_username` (`username`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='普通用户账号表';

INSERT IGNORE INTO `user_accounts` (`username`, `password_hash`, `display_name`)
VALUES ('demo', '8d969eef6ecad3c29a3a629280e686cf0c3f5d5a86aff3ca12020c923adc6c92', '演示用户');

-- ------------------------------------------------------------
-- 2. 知识库文件表
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS `kb_files` (
  `id` BIGINT NOT NULL AUTO_INCREMENT,
  `file_name` VARCHAR(255) NOT NULL COMMENT '原始文件名',
  `stored_name` VARCHAR(255) NOT NULL COMMENT '磁盘存储文件名',
  `file_path` VARCHAR(500) NOT NULL COMMENT '文件绝对路径',
  `file_type` VARCHAR(20) NOT NULL COMMENT '扩展名',
  `source_type` VARCHAR(20) DEFAULT '文档' COMMENT '文档/聊天记录/表格数据',
  `file_size` BIGINT DEFAULT 0 COMMENT '文件大小（字节）',
  `status` VARCHAR(20) DEFAULT 'pending' COMMENT '处理状态',
  `progress` INT DEFAULT 0 COMMENT '处理进度 0~100',
  `chunk_count` INT DEFAULT 0 COMMENT '切片数量',
  `triple_count` INT DEFAULT 0 COMMENT '三元组数量',
  `error_msg` TEXT COMMENT '失败原因',
  -- 新增：切片策略、自动清洗统计、召回自测结果
  `chunk_strategy` VARCHAR(20) DEFAULT 'semantic' COMMENT 'semantic/paragraph/chapter',
  `clean_stats` TEXT COMMENT '自动清洗统计（JSON）',
  `recall_status` VARCHAR(20) DEFAULT 'pending' COMMENT 'pending/running/passed/failed',
  `recall_score` INT DEFAULT 0 COMMENT '召回准确度 0~100',
  `recall_detail` TEXT COMMENT '召回测试明细（JSON）',
  `created_at` DATETIME DEFAULT CURRENT_TIMESTAMP COMMENT '上传时间',
  `updated_at` DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  PRIMARY KEY (`id`),
  KEY `idx_kb_status` (`status`),
  KEY `idx_kb_created` (`created_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='知识库文件表';

-- ------------------------------------------------------------
-- 3. Agent 配置表（密钥仅存后端，前端不回显）
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS `agent_configs` (
  `id` BIGINT NOT NULL AUTO_INCREMENT,
  `agent_key` VARCHAR(30) NOT NULL COMMENT 'agent1/agent2/agent3',
  `agent_name` VARCHAR(100) NOT NULL COMMENT 'Agent 名称',
  `description` TEXT NOT NULL COMMENT '功能说明',
  `llm_url` VARCHAR(500) DEFAULT '' COMMENT 'LLM 接口地址',
  `llm_api_key` VARCHAR(500) DEFAULT '' COMMENT 'LLM 密钥',
  `llm_model` VARCHAR(100) DEFAULT 'Qwen/Qwen2.5-7B-Instruct' COMMENT 'LLM 模型名',
  `embedding_url` VARCHAR(500) DEFAULT '' COMMENT 'Embedding 接口地址',
  `embedding_api_key` VARCHAR(500) DEFAULT '' COMMENT 'Embedding 密钥',
  `embedding_model` VARCHAR(100) DEFAULT 'BAAI/bge-m3' COMMENT 'Embedding 模型名',
  `updated_at` DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_agent_key` (`agent_key`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='Agent 模型配置表';

INSERT IGNORE INTO `agent_configs`
  (`agent_key`, `agent_name`, `description`, `llm_url`, `llm_api_key`, `llm_model`,
   `embedding_url`, `embedding_api_key`, `embedding_model`)
VALUES
  ('agent1', '文档预处理 Agent',
   '离线执行。上传文件后自动触发，负责多源文件解析、文本清洗、LangChain 切片、调用 LLM 打元标签（来源类型 / 商品款号 / 内容分类），并写入 Qdrant 向量库。',
   'https://api.siliconflow.cn/v1/chat/completions', '', 'Qwen/Qwen2.5-7B-Instruct',
   'https://api.siliconflow.cn/v1/embeddings', '', 'BAAI/bge-m3'),
  ('agent2', '知识抽取 Agent',
   '离线执行，与文档预处理同步运行。读取清洗后的文本，抽取服装领域实体与关系三元组，写入 Neo4j 知识图谱，供问答时做事实约束。',
   'https://api.siliconflow.cn/v1/chat/completions', '', 'Qwen/Qwen2.5-7B-Instruct',
   'https://api.siliconflow.cn/v1/embeddings', '', 'BAAI/bge-m3'),
  ('agent3', '问答推理 Agent',
   '在线执行。用户提问后并行查询 Neo4j 图谱与 Qdrant 混合检索（稠密 + 稀疏 RRF 融合 + 标签过滤），组装强约束 Prompt，通过 SSE 流式返回答案。',
   'https://api.siliconflow.cn/v1/chat/completions', '', 'Qwen/Qwen2.5-7B-Instruct',
   'https://api.siliconflow.cn/v1/embeddings', '', 'BAAI/bge-m3');

-- ------------------------------------------------------------
-- 4. 对话历史表（区分管理员 / 普通用户）
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS `chat_history` (
  `id` BIGINT NOT NULL AUTO_INCREMENT,
  `session_id` VARCHAR(64) NOT NULL COMMENT '会话ID',
  `user_type` VARCHAR(10) DEFAULT 'user' COMMENT 'admin/user',
  `role` VARCHAR(10) NOT NULL COMMENT 'user/assistant',
  `content` TEXT NOT NULL COMMENT '消息内容',
  `user_id` BIGINT DEFAULT NULL COMMENT '用户ID（普通用户登录后写入）',
  `username` VARCHAR(50) DEFAULT NULL COMMENT '用户账号（冗余，便于展示）',
  `created_at` DATETIME DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  PRIMARY KEY (`id`),
  KEY `idx_chat_session` (`session_id`),
  KEY `idx_chat_created` (`created_at`),
  KEY `idx_chat_user` (`user_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='对话历史表';

-- ------------------------------------------------------------
-- 5. 商品结构化数据表（演示 MySQL 数据接入）
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS `goods` (
  `id` BIGINT NOT NULL AUTO_INCREMENT,
  `goods_no` VARCHAR(50) NOT NULL COMMENT '商品款号',
  `name` VARCHAR(200) NOT NULL COMMENT '商品名称',
  `fabric` VARCHAR(500) DEFAULT '' COMMENT '面料成分',
  `sizes` VARCHAR(200) DEFAULT '' COMMENT '可选尺码',
  `colors` VARCHAR(200) DEFAULT '' COMMENT '可选颜色',
  `care` VARCHAR(500) DEFAULT '' COMMENT '保养方式',
  `after_sale` VARCHAR(500) DEFAULT '' COMMENT '售后政策',
  `activity` VARCHAR(500) DEFAULT '' COMMENT '活动信息',
  `report_no` VARCHAR(100) DEFAULT '' COMMENT '检测报告编号',
  `created_at` DATETIME DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_goods_no` (`goods_no`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='商品结构化数据表';

INSERT IGNORE INTO `goods`
  (`goods_no`, `name`, `fabric`, `sizes`, `colors`, `care`, `after_sale`, `activity`, `report_no`)
VALUES
  ('FY2026-001', '轻暖羊毛混纺大衣',
   '面料成分为 70% 羊毛、25% 聚酯纤维、5% 羊绒，里布为 100% 聚酯纤维。',
   'S、M、L、XL', '燕麦色、深灰色、黑色',
   '建议干洗，不可漂白，低温熨烫，悬挂存放避免重压。',
   '支持 7 天无理由退换，非质量问题运费由买家承担；出现开线、掉扣等质量问题支持 30 天内免费维修。',
   '新品上市期间，购买任意大衣赠送同色系防尘袋一个。', 'JC2026-WL-0188'),
  ('FY2026-002', '凉感冰丝短袖衬衫',
   '面料成分为 88% 锦纶、12% 氨纶，具有凉感与四面弹性能。',
   'S、M、L、XL、XXL', '雾蓝色、米白色、浅灰色',
   '可机洗，建议使用洗衣袋，水温不超过 30 摄氏度，禁止烘干与高温熨烫。',
   '支持 7 天无理由退换；洗涤后出现严重缩水可凭订单申请质检。',
   '第二件半价，活动截止到本月底。', 'JC2026-LG-0203'),
  ('FY2026-003', '高腰直筒牛仔裤',
   '面料成分为 98% 棉、2% 氨纶，采用环保水洗工艺。',
   '25、26、27、28、29、30', '浅蓝、深蓝、复古黑',
   '建议翻面冷水手洗，避免暴晒，首次洗涤可能有轻微浮色属正常现象。',
   '支持 7 天无理由退换；裤长可提供一次免费修改服务。',
   '会员下单立减 20 元。', 'JC2026-NZ-0311');

-- ------------------------------------------------------------
-- 6. 检索日志表（每次提问的命中情况与召回准确度，管理端可查）
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS `retrieval_logs` (
  `id` BIGINT NOT NULL AUTO_INCREMENT,
  `session_id` VARCHAR(64) DEFAULT '' COMMENT '会话ID',
  `user_id` BIGINT DEFAULT NULL COMMENT '用户ID',
  `username` VARCHAR(50) DEFAULT '' COMMENT '用户账号',
  `user_type` VARCHAR(10) DEFAULT 'user' COMMENT 'admin/user',
  `question` VARCHAR(500) NOT NULL COMMENT '用户提问',
  `doc_count` INT DEFAULT 0 COMMENT '命中文档片段数',
  `triple_count` INT DEFAULT 0 COMMENT '命中三元组数',
  `top_score` FLOAT DEFAULT 0 COMMENT '最高向量相似度',
  `hit` TINYINT(1) DEFAULT 0 COMMENT '是否命中知识库',
  `accuracy` INT DEFAULT 0 COMMENT '召回准确度 0~100',
  `accuracy_level` VARCHAR(10) DEFAULT 'miss' COMMENT 'high/medium/low/miss',
  `latency_ms` INT DEFAULT 0 COMMENT '检索耗时（毫秒）',
  `filters` VARCHAR(200) DEFAULT '' COMMENT '标签过滤条件',
  `degraded` VARCHAR(200) DEFAULT '' COMMENT '降级原因',
  `sources` TEXT COMMENT '召回结果快照（JSON）',
  `created_at` DATETIME DEFAULT CURRENT_TIMESTAMP COMMENT '提问时间',
  PRIMARY KEY (`id`),
  KEY `idx_retrieval_user` (`user_id`),
  KEY `idx_retrieval_created` (`created_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='检索日志表';

-- ------------------------------------------------------------
-- 7. 操作日志表（管理员与用户关键操作全量留存）
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS `operation_logs` (
  `id` BIGINT NOT NULL AUTO_INCREMENT,
  `actor_type` VARCHAR(10) DEFAULT 'admin' COMMENT 'admin/user/system',
  `actor` VARCHAR(50) DEFAULT '' COMMENT '操作人',
  `action` VARCHAR(50) NOT NULL COMMENT '操作类型',
  `target` VARCHAR(200) DEFAULT '' COMMENT '操作对象',
  `detail` TEXT COMMENT '操作详情',
  `ip` VARCHAR(64) DEFAULT '' COMMENT '来源 IP',
  `created_at` DATETIME DEFAULT CURRENT_TIMESTAMP COMMENT '操作时间',
  PRIMARY KEY (`id`),
  KEY `idx_op_created` (`created_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='操作日志表';

-- ------------------------------------------------------------
-- 8. 召回测试记录表（保存自动召回测试每一轮结果）
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS `recall_tests` (
  `id` BIGINT NOT NULL AUTO_INCREMENT,
  `file_id` BIGINT NOT NULL COMMENT '知识库文件ID',
  `strategy` VARCHAR(20) DEFAULT 'semantic' COMMENT '本轮切片策略',
  `iteration` INT DEFAULT 1 COMMENT '第几轮测试',
  `question` VARCHAR(500) DEFAULT '' COMMENT '自动生成的测试问题',
  `hit` TINYINT(1) DEFAULT 0 COMMENT '是否召回命中',
  `score` FLOAT DEFAULT 0 COMMENT '最高相似度',
  `doc_count` INT DEFAULT 0 COMMENT '召回片段数',
  `detail` TEXT COMMENT '召回明细（JSON）',
  `created_at` DATETIME DEFAULT CURRENT_TIMESTAMP COMMENT '测试时间',
  PRIMARY KEY (`id`),
  KEY `idx_recall_file` (`file_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='召回测试记录表';
