# 基于 LangChain + 知识图谱双引擎的服装多源文档智能客服系统

毕业设计演示项目。系统面向服装客服场景，把 **多源文档（TXT / Word / Excel / PPT / PDF / 扫描 PDF / SQL 脚本 / 客服聊天记录 / MySQL 商品数据）** 自动加工成两套知识：

- **向量知识库（Qdrant）**：LangChain 切片 + LLM 打元标签 + 稠密/稀疏混合检索 + RRF 融合 + 标签过滤
- **知识图谱（Neo4j）**：LLM 抽取三元组，约束实体与关系，问答时提供事实依据

用户提问后，两个引擎**并行检索**，结果合并进强约束 Prompt，由大模型**流式（SSE）**输出答案，找不到资料时固定回复「暂无相关信息」，避免编造。

---

## 一、技术栈

| 层次 | 技术 |
| --- | --- |
| 前端 | Vue 3 + Vite（两套独立 H5：管理端 / 客户端） |
| 后端 | Python FastAPI + Uvicorn |
| RAG 框架 | LangChain（文本切片、ChatPromptTemplate、ChatOpenAI） |
| 向量库 | Qdrant（dense + sparse 命名向量、payload 元数据过滤、手动 RRF） |
| 知识图谱 | Neo4j 5（中文实体/关系、唯一约束） |
| 业务库 | MySQL 8（管理员、文件、Agent 配置、对话历史、商品） |
| 文件解析 | pdfplumber、PyMuPDF、PaddleOCR、python-docx、python-pptx、pandas |

---

## 二、三个 Agent

| Agent | 运行时机 | 职责 |
| --- | --- | --- |
| **Agent1 文档预处理** | 离线（上传文件后自动触发，不阻塞问答） | 解析 → 清洗 → LangChain 切片 → LLM 打元标签（来源类型 / 商品款号 / 内容分类）→ Embedding → 写入 Qdrant |
| **Agent2 知识抽取** | 离线（与预处理同一条流水线） | 读取清洗文本 → LLM 抽取三元组（7 类实体 / 5 种关系）→ 写入 Neo4j |
| **Agent3 问答推理** | 在线（用户提问触发） | 并行查询 Neo4j + Qdrant → RRF 融合 → 组装强约束 Prompt → SSE 流式回答 → 写缓存与历史 |

三个 Agent 的提示词全部集中在 `backend/app/prompts.py`，与需求原文一致，可直接在答辩时展示。

---

## 三、目录结构

```text
智能客服/
├── start.bat                      # Windows 一键启动（推荐）
├── start.sh                       # macOS / Linux 一键启动
├── stop.bat                       # 一键停止（后端 + 容器）
├── docker-compose.yml             # MySQL / Qdrant / Neo4j 编排
├── .env.example                   # 环境变量示例（可复制为 .env）
├── README.md                      # 本文档
│
├── backend/
│   ├── run.py                     # 后端启动入口（0.0.0.0:8000）
│   ├── requirements.txt           # 后端核心依赖
│   ├── requirements-ocr.txt       # OCR 可选依赖（体积较大，按需安装）
│   ├── sql/init.sql               # MySQL 建库建表 + 默认管理员 + Agent 配置 + 演示商品
│   ├── neo4j/constraints.cypher   # Neo4j 唯一约束与索引脚本
│   ├── uploads/                   # 上传文件保存目录（自动创建）
│   └── app/
│       ├── main.py                # FastAPI 入口、异常处理、静态页面托管
│       ├── config.py              # 全部配置（支持 .env）
│       ├── db.py                  # MySQL 连接、自动建库、建表、默认数据
│       ├── models.py              # 5 张业务表模型
│       ├── schemas.py             # 请求/响应模型
│       ├── security.py            # JWT、密码哈希、登录限流
│       ├── prompts.py             # 三个 Agent 的提示词（逐字保留需求原文）
│       ├── api_utils.py           # 统一返回 {code,msg,data}
│       ├── routers/
│       │   ├── auth.py            # 管理员登录 / 普通用户登录 / 身份校验
│       │   ├── kb.py              # 文件上传、源文件查看/下载、片段查看/编辑、召回测试、向量看板/检索、图谱数据与关联增删
│       │   ├── admin.py           # 管理端数据看板：用户提问、会话详情、检索日志、操作日志
│       │   ├── agents.py          # Agent 配置查询 / 更新 / 重置（热更新）
│       │   ├── chat.py            # SSE 流式问答 + 会话列表/历史/删除
│       │   └── health.py          # 健康检查（MySQL/Qdrant/Neo4j/密钥状态）
│       └── services/
│           ├── parsers.py         # 8 类文件解析 + OCR（含 SQL 建表/INSERT 解析）
│           ├── text_utils.py      # 自动清洗（带统计）、款号/分类识别、关键词、稀疏向量
│           ├── chunking.py        # 三种切片策略：语义 / 段落 / 章节
│           ├── recall_eval.py     # 自动生成测试问题、召回评估、不达标切换策略重试
│           ├── pipeline.py        # 离线流水线（Agent1 + Agent2 + 召回自愈）
│           ├── jobs.py            # 后台线程池 + 重启续跑
│           ├── audit.py           # 检索日志 / 操作日志 / 召回准确度评分
│           ├── llm_client.py      # OpenAI 兼容 LLM 客户端（热更新、流式）
│           ├── embedding_client.py# Embedding 客户端（批量、重试、归一化）
│           ├── qdrant_store.py    # 集合、payload 索引、混合检索、RRF、片段读取/改写/删除
│           ├── neo4j_store.py     # 约束、三元组写入、图查询、可视化图数据
│           ├── retrieval.py       # 双引擎并行检索 + 标签过滤 + 降级
│           └── cache.py           # 高频问题 TTL + LRU 缓存
│
└── frontend/
    ├── index.html                 # 客户端入口（/）
    ├── admin.html                 # 管理端入口（/admin）
    ├── vite.config.js             # 多页面构建 + /api 代理
    ├── src/
    │   ├── styles.css             # 全局样式（极简移动端）
    │   ├── client/                # 客户端 H5（演示账号一键登录 + 独立会话）
    │   ├── admin/                 # 管理端 H5（登录 + 7 个 Tab）
    │   ├── components/            # ChatPanel 共用聊天组件、Toast
    │   └── shared/                # api / sse / format 工具
    └── dist/                      # 构建产物（后端直接托管，手机可访问）
```

---

## 四、快速开始

### 方式 A：Windows 一键启动（推荐）

1. 双击根目录 `start.bat`
2. 脚本会自动完成：创建虚拟环境 → 安装依赖 → 启动 Docker 基础设施 → 检查/构建前端 → 启动后端
3. 浏览器自动打开管理端：<http://127.0.0.1:8000/admin>
4. 手机与电脑连同一 Wi-Fi，访问脚本提示的 `http://电脑IP:8000/`

停止：双击 `stop.bat`，或直接关闭后端窗口。

### 方式 B：手动启动

```bash
# 1. 基础设施（本机已有 MySQL 时，只启动 Qdrant 与 Neo4j）
docker compose up -d

# 本机没有 MySQL 时（Docker 提供 MySQL，映射到 3307，需要 .env 中 MYSQL_PORT=3307）
docker compose --profile with-mysql up -d

# 2. 后端
python -m venv .venv
.venv\Scripts\activate            # Windows
# source .venv/bin/activate       # macOS / Linux
pip install -r backend/requirements.txt
python backend/run.py

# 3. 前端（dist 已构建可跳过；修改前端后重新构建）
cd frontend
npm install
npm run build
```

### 默认账号

| 项目 | 值 |
| --- | --- |
| 管理端地址 | <http://127.0.0.1:8000/admin> |
| 管理员账号 | `admin`（登录页已预填） |
| 管理员密码 | `123456`（登录页已预填，直接点「登录」） |
| 客户端地址 | <http://127.0.0.1:8000/> |
| 演示用户账号 | `demo`（登录页已预填，直接点「进入演示」） |
| 演示用户密码 | `123456` |

---

## 五、首次使用步骤（答辩演示流程）

1. **进入管理端**，账号密码已预填为 admin / 123456，直接点「登录」。
2. 打开 **Agent 模型配置**（第 6 个页签），给三个 Agent 填入 **硅基流动（SiliconFlow）** 的 **ApiKey**（注册地址 <https://cloud.siliconflow.cn>，控制台「API 密钥」里创建，有免费额度）：
   - 默认 LLM：`https://api.siliconflow.cn/v1/chat/completions`，模型 `Qwen/Qwen2.5-7B-Instruct`
   - 默认 Embedding：`https://api.siliconflow.cn/v1/embeddings`，模型 `BAAI/bge-m3`（1024 维，与 `EMBEDDING_DIM` 一致）
   - 两个接口填**同一个**硅基流动 ApiKey 即可
   - 如果控制台里模型名称有调整，直接把「LLM 模型名 / Embedding 模型名」改成当前可用的模型名
   - 三个 Agent 可分别配置，保存后**立即生效，无需重启**
   - 密钥只保存在后端 MySQL，前端只显示「已配置 / 未配置」
3. 打开 **Tab1 知识库管理**：
   - 可点击「导入 MySQL 商品数据」，把内置 3 条演示商品转成自然语言后走完整离线流水线
   - 也可多选上传 TXT / Word / Excel / PPT / PDF / CSV / JSON / **SQL** 文件
   - 上传前选择切片策略（语义切分 / 段落切分 / 章节切分），原始脏数据无需人工清洗，由程序自动识别并统计
   - 上传后自动触发离线 Agent，页面展示状态、进度、切片数、三元组数、自动清洗统计
   - 处理完成后自动做召回自测；不达标会**自动换切片策略重试**（最多 3 轮），保留召回最好的一轮
   - 每个文件可点「查看源文件」：弹窗内三个页签对照查看「原始内容 / 自动清洗后 / 清洗明细」（清洗前后字符数、URL、邮箱、页码、分隔线、重复行等剔除项及示例），并可直接「下载原文件」保留原始格式
   - 每个文件可点「查看片段」：逐条查看向量片段原文，**可直接点击修改并保存**（保存时同步重建稠密/稀疏向量，改完立即影响检索），也可删除单条片段；弹窗标题会显示当前切片策略及规则说明
   - 点「召回明细」查看每一轮的测试问题、是否命中、最高相似度；「召回测试」可随时重新自测
4. 打开 **Tab2 向量库**：图形化看板展示向量条数、维度、距离度量、集合状态，按文件 / 分类的片段分布与 payload 索引字段；「向量检索实验台」输入一句话（或点下方的示例问题）即可查看 Top-N 命中片段、综合匹配度与稠密相似度
5. 打开 **Tab3 知识图谱**：可视化实体关系图，默认只展示关联最多的核心实体（避免拥挤），可一键「显示全部」；按实体类型分色，点击图例可隐藏某类实体；顶部支持实体搜索与关系类型筛选；节点可拖动，单击节点在右侧查看类型与出入边详情；**单击连线可选中并删除**，右侧「手动建立关联」可直接选择起点实体 + 关系类型 + 终点实体建立关联（无需改代码或数据库）
6. 打开 **Tab4 用户提问**：查看客户端用户列表 → 点击用户 → 会话列表 → 会话详情，可看到该用户每条提问的检索命中状态、召回准确度、命中片段数、耗时与完整对话
7. 打开 **Tab5 日志中心**：检索日志（按命中等级 / 关键词筛选）与操作日志（管理员、用户操作全量留存）分页查看
8. 打开 **Tab7 AI 对话测试**，问例如：
   - `FY2026-001 的面料成分是什么？`
   - `这条牛仔裤怎么保养？`
   - `支持七天无理由退换吗？`
9. 手机 / 浏览器打开客户端 `http://电脑IP:8000/`：使用预填的演示账号一键登录；客户端与管理端的 AI 对话记录**各自独立保存**，均可点「历史」切换会话、点「新对话」开启新会话

> 没有 ApiKey 时系统不会崩溃：上传会明确提示「请检查 LLM 配置」，问答会提示「尚未配置 Agent3 的 LLM ApiKey」。

---

## 六、后端接口清单（权限隔离）

| 方法 | 路径 | 权限 | 说明 |
| --- | --- | --- | --- |
| POST | `/api/admin/login` | 公开 | 管理员登录，返回 JWT |
| GET | `/api/admin/me` | 管理员 | 校验登录态 |
| POST | `/api/user/login` | 公开 | 演示用户登录（demo / 123456），返回用户 JWT |
| GET | `/api/user/me` | 普通用户 | 校验普通用户登录态 |
| POST | `/api/kb/upload` | 管理员 | 多文件上传（可带 `strategy`）并触发离线处理 |
| GET | `/api/kb/files` | 管理员 | 知识库文件列表（含切片策略 / 清洗统计 / 召回结果） |
| POST | `/api/kb/files/{id}/reprocess?strategy=` | 管理员 | 重新处理，可切换切片策略 |
| DELETE | `/api/kb/files/{id}` | 管理员 | 删除文件及其向量/图谱数据 |
| GET | `/api/kb/files/{id}/chunks` | 管理员 | 查看该文件全部向量片段（含原文与元数据） |
| GET | `/api/kb/files/{id}/raw` | 管理员 | 源文件对照：原始内容、自动清洗后文本、清洗明细与被剔除示例 |
| GET | `/api/kb/files/{id}/download` | 管理员 | 下载原格式文件（支持 `?token=` 直接打开） |
| PUT | `/api/kb/files/{id}/chunks/{point_id}` | 管理员 | 人工修改片段文本，服务端同步重建稠密 + 稀疏向量 |
| DELETE | `/api/kb/files/{id}/chunks/{point_id}` | 管理员 | 删除单条向量片段 |
| POST | `/api/kb/files/{id}/recall-test` | 管理员 | 触发一次自动召回测试 |
| GET | `/api/kb/files/{id}/recall` | 管理员 | 查询召回测试状态与逐轮明细 |
| GET | `/api/kb/graph?limit=` | 管理员 | 知识图谱可视化数据（节点 / 关系 / 可选关系类型） |
| POST | `/api/kb/graph/relationships` | 管理员 | 手动建立实体关联（起点 ID + 关系类型 + 终点 ID） |
| DELETE | `/api/kb/graph/relationships/{id}` | 管理员 | 删除一条实体关联（仅删关系，不删实体） |
| GET | `/api/kb/vector-overview` | 管理员 | 向量库看板数据（条数 / 维度 / 距离 / 文件与分类分布 / 索引字段） |
| POST | `/api/kb/search` | 管理员 | 向量检索实验台：输入一句话查看 Top-N 命中片段与匹配度 |
| POST | `/api/kb/import-goods` | 管理员 | 导入 MySQL 商品数据 |
| GET | `/api/kb/stats` | 管理员 | 文件数、向量数、图谱节点/关系数 |
| GET | `/api/admin/overview` | 管理员 | 管理端概览（用户数 / 提问数 / 命中率等） |
| GET | `/api/admin/users` | 管理员 | 客户端用户列表（提问数 / 会话数 / 平均准确度） |
| GET | `/api/admin/users/{id}/sessions` | 管理员 | 某用户的会话列表 |
| GET | `/api/admin/sessions/{sid}/messages` | 管理员 | 某会话的完整对话 + 检索记录 |
| GET | `/api/admin/retrieval-logs` | 管理员 | 检索日志（按用户 / 命中等级 / 关键词筛选） |
| GET | `/api/admin/operation-logs` | 管理员 | 操作日志（按角色 / 关键词筛选） |
| GET | `/api/agents` | 管理员 | 查询 3 个 Agent 配置（密钥脱敏） |
| PUT | `/api/agents/{agent_key}` | 管理员 | 更新配置（热更新 + 清缓存） |
| POST | `/api/agents/{agent_key}/reset` | 管理员 | 重置默认配置 |
| POST | `/api/chat/stream` | 普通用户/管理员 | SSE 流式问答（`?token=` 标识身份） |
| GET | `/api/chat/sessions?token=` | 普通用户/管理员 | 当前身份自己的历史会话列表 |
| DELETE | `/api/chat/sessions/{sid}?token=` | 普通用户/管理员 | 删除当前身份自己的会话 |
| POST | `/api/chat/history` | 普通用户/管理员 | 保存对话消息（记录 user_id / username） |
| GET | `/api/chat/history?session_id=&token=` | 普通用户/管理员 | 查询会话历史（按身份隔离） |
| GET | `/api/health` | 公开 | MySQL/Qdrant/Neo4j/密钥状态 |

统一返回格式：`{ "code": 0, "msg": "", "data": ... }`；`code != 0` 表示失败。
SSE 事件：`meta` → `status` → `delta`（多次）→ `done`，异常时 `error`。

---

## 七、数据库初始化

### MySQL

- 首次启动后端会自动建库、建表并写入默认数据（幂等）。
- 也可手动执行：`backend/sql/init.sql`
- 9 张表：

| 表 | 用途 |
| --- | --- |
| `admins` | 管理员账号（SHA256 密码） |
| `user_accounts` | 普通用户账号（演示账号 demo / 123456） |
| `kb_files` | 知识库文件、切片策略、自动清洗统计、召回自测结果 |
| `agent_configs` | 三个 Agent 的模型配置 |
| `chat_history` | 对话历史（`user_type` + `user_id` 区分管理员 / 各客户端用户） |
| `retrieval_logs` | 每次提问的命中文档数、三元组数、最高相似度、准确度评分、耗时 |
| `operation_logs` | 管理员与用户关键操作全量留存 |
| `recall_tests` | 自动召回测试逐轮明细（策略 / 测试问题 / 是否命中 / 相似度） |
| `goods` | 商品结构化数据（可一键导入知识库） |

### Neo4j

- 服务启动时自动执行约束，也可手动执行 `backend/neo4j/constraints.cypher`
- 实体类型：商品、面料、颜色、尺码、检测报告、售后政策、保养方式
- 关系仅允许：`面料是`、`支持售后`、`保养方式为`、`对应检测报告`、`适用尺码`（写入前有白名单校验）

### Qdrant

- 启动时自动创建集合 `fashion_kb`：`dense`（Cosine，1024 维）+ `sparse`
- 自动创建 payload 索引：`file_id`、`source_type`、`goods_no`、`category`
- 仪表盘：<http://127.0.0.1:6333/dashboard>

---

## 八、加速与防幻觉机制

1. 解析 / OCR / 切片 / 打标签 / 图谱入库全部在后台线程池执行，上传接口立即返回
2. Neo4j 查询与 Qdrant 检索并行（`asyncio` 先发起图谱查询，同时做向量检索，最后汇总）
3. 稠密召回 Top20 + 稀疏召回 Top20，RRF 融合后只保留 Top3~6 片段
4. 高频问题缓存（TTL 10 分钟 + LRU 200 条），相同问题直接打字机输出
5. 文本清洗（HTML、URL、页码、重复行）、payload 标签过滤（分类 / 款号）、图谱关系白名单
6. Prompt 强约束：只允许依据检索片段与图谱三元组回答，无资料固定回复「暂无相关信息」
7. 检索层降级：Qdrant / Neo4j 任一不可用时，另一路仍可工作，并在 `done` 事件标记 `degraded`

### 知识库增强能力（切片自愈与人工干预）

1. **自动清洗**：上传的原始文件不做人工预处理，URL、邮箱、控制字符、页码行、重复行、空行由程序自动识别，清洗前后的字符数与各项剔除量写入 `kb_files.clean_stats`，管理端可直接查看。
2. **三种切片策略**：语义切分（LangChain RecursiveCharacterTextSplitter）、段落切分（按空行聚合并带 overlap）、章节切分（识别 `# 标题` / `第X章` / `一、` / `1.1` / `【标题】`）。
3. **召回自测与自愈**：切片入库后自动抽样生成测试问题（LLM 生成，失败回退关键词），限定 `file_id` 检索并按字符二元组重合度（≥0.35 记命中）评分；命中率低于 60% 时清空该文件向量、自动切换下一种策略重新切片入库，最多 3 轮，最终保留准确度最高的一轮结果。
4. **片段可看可改**：管理端逐条展示向量片段原文与元数据；修改保存时服务端重新计算稠密向量与稀疏向量并 `set_payload`，人工修正后立即参与检索，无需重新上传文件；单个片段也可删除。
5. **图谱可视化**：`GET /api/kb/graph` 返回 Neo4j 实体与关系，前端用原生 SVG 绘制力导向布局（按实体类型分色、核心节点优先展示），节点可拖动、可重新布局；管理员可在界面上手动新增或删除关联。

---

## 九、OCR（扫描 PDF）说明

核心依赖不包含 PaddleOCR，避免首次安装过慢。需要识别扫描版 PDF 时：

```bash
.venv\Scripts\pip install -r backend\requirements-ocr.txt
```

- 程序会先尝试 pdfplumber 提取文本层；某页文字过少时自动用 PyMuPDF 渲染图片并调用 PaddleOCR
- 未安装 OCR 依赖时，上传扫描 PDF 会给出明确提示，不会静默失败
- 单次 OCR 最多处理 30 页，避免演示时卡住

---

## 十、常见问题

### 1. Docker 报 `500 Internal Server Error` 或 `HCS_E_HYPERV_NOT_INSTALLED`

说明 Windows 的虚拟化组件未启用（Docker Desktop 无法启动 Linux 引擎）。以**管理员身份**打开 PowerShell 执行：

```powershell
dism.exe /online /enable-feature /featurename:VirtualMachinePlatform /all /norestart
dism.exe /online /enable-feature /featurename:Microsoft-Windows-Subsystem-Linux /all /norestart
wsl --update
wsl --set-default-version 2
```

然后**重启电脑**，再次双击 `start.bat`。可在任务管理器 → 性能 → CPU 中确认「虚拟化：已启用」。

### 2. 端口被占用

| 端口 | 用途 | 处理 |
| --- | --- | --- |
| 8000 | 后端 + 前端页面 | 关闭占用进程，或修改 `backend/run.py` 端口 |
| 3306 | 本机 MySQL | 脚本会自动优先使用本机 MySQL |
| 3307 | Docker MySQL | 仅 `--profile with-mysql` 时使用 |
| 6333 / 6334 | Qdrant | 关闭冲突容器 |
| 7474 / 7687 | Neo4j | 关闭冲突容器 |

### 3. 上传成功但状态是 failed

看文件卡片上的 `error_msg`：

- 「请检查管理端 LLM URL 与 ApiKey 配置」→ 去「Agent 模型配置」页签配置密钥
- 「Embedding 服务调用失败」→ 检查 Embedding URL / 模型名 / 维度（默认 1024）
- 「Qdrant 连接失败」→ 确认 `docker compose up -d` 已启动

### 4. 问答一直回复「暂无相关信息」

表示两路检索都没有召回内容：先确认知识库里有 `done` 状态的文件，再检查提问中的款号/分类是否与文档一致。

### 5. 手机打不开页面

- 确认手机与电脑在同一 Wi-Fi
- Windows 防火墙放行 8000 端口（首次运行时会弹窗，请选择「允许」）
- 关闭电脑上的代理软件后再试

### 6. 修改了前端代码但页面没变化

```bash
cd frontend
npm run build
```

后端直接托管 `frontend/dist`，构建后刷新浏览器即可（必要时 Ctrl+F5）。

---

## 十一、服务器 Docker 部署（已上线）

本项目已在服务器上以**独立编排**运行，与服务器上其他项目（乡策通、OUC 食堂）互不影响。

| 项目 | 说明 |
| --- | --- |
| 客户端访问 | http://49.232.131.254:3002/ （演示账号 `demo / 123456`，登录页已预填） |
| 管理端访问 | http://49.232.131.254:3002/admin （`admin / 123456`） |
| 接口文档 | http://49.232.131.254:3002/api/docs |
| 部署目录 | `/opt/fashion-cs` |
| 容器 | `fashion-cs-app`（512M）、`fashion-cs-qdrant`（256M）、`fashion-cs-neo4j`（512M） |
| MySQL | 复用宿主 `stack-mysql`，独立库 `fashion_cs` + 独立账号 `fashion_app` |
| 网络 | 自建 `fashion-net`，同时接入 `stack-net` 以便访问 MySQL |
| 数据卷 | `fashion-cs_fashion_uploads`、`fashion-cs_fashion_qdrant`、`fashion-cs_fashion_neo4j` |

管理端 7 个 Tab：知识库管理（含源文件查看/下载、片段查看/编辑、召回自测）、向量库（看板 + 检索实验台）、知识图谱（可拖动、可手动增删关联）、用户提问、日志中心、Agent 配置、AI 对话测试。
客户端与管理端的 AI 对话记录按身份隔离保存，均支持「历史会话」切换与「新对话」。

### 1. 首次部署

```bash
# 服务器上已存在：
#   /opt/fashion-cs/backend            后端代码
#   /opt/fashion-cs/frontend/dist      前端构建产物（本地 npm run build 后上传）
#   /opt/fashion-cs/Dockerfile
#   /opt/fashion-cs/docker-compose.server.yml
#   /opt/fashion-cs/.env               数据库密码、Neo4j 密码、JWT 密钥

cd /opt/fashion-cs
docker compose -f docker-compose.server.yml build app     # 使用清华 PyPI 镜像
docker compose -f docker-compose.server.yml up -d
docker compose -f docker-compose.server.yml ps
```

首次启动会自动建表、写入管理员 `admin / 123456`、演示用户 `demo / 123456`、三个 Agent 默认配置与演示商品数据。

### 2. 配置模型密钥

登录管理端 → **Agent 模型配置** → 三个 Agent 分别填写硅基流动 ApiKey → 保存。
密钥只保存在 MySQL，接口仅返回「是否已配置」，不会回显明文。

默认接口与模型（已预置，无需修改）：

- LLM：`https://api.siliconflow.cn/v1/chat/completions`，`Qwen/Qwen2.5-7B-Instruct`
- Embedding：`https://api.siliconflow.cn/v1/embeddings`，`BAAI/bge-m3`（1024 维）

### 3. 导入演示知识库

管理端 → **知识库管理** → 「导入商品数据」。
该操作会把 MySQL `goods` 表的数据拼成文本，完整走一遍 Agent1（切片 + 打标签 + 向量入库）与 Agent2（三元组写入 Neo4j）。

### 4. 更新代码

```bash
# 本地上传新代码后，服务器执行：
cd /opt/fashion-cs
docker compose -f docker-compose.server.yml build app
docker compose -f docker-compose.server.yml up -d
```

### 5. 备份与排查

```bash
# 数据库备份
docker exec stack-mysql sh -c 'mysqldump -uroot -p"$MYSQL_ROOT_PASSWORD" fashion_cs' > /opt/backup/fashion_cs.sql

# 日志
docker logs --tail 100 fashion-cs-app

# 内存占用（2C2G 机器重点观察）
docker stats --no-stream
```

`.env` 中的数据库密码、Neo4j 密码、JWT 密钥属于敏感信息，不要提交到代码仓库。

---

## 十二、停止与清理

```bash
# 停止容器（保留数据）
docker compose --profile with-mysql down

# 清空所有数据（MySQL / Qdrant / Neo4j 全部重置，谨慎）
docker compose --profile with-mysql down -v
```

上传的原始文件保存在 `backend/uploads/`，删除文件记录时不会删除磁盘原文件，便于答辩时追溯。
