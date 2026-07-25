# content-curator/app/database.py
"""SQLite database initialization and connection."""
import sqlite3
import json
from pathlib import Path
from datetime import datetime

DB_PATH = Path(__file__).parent.parent / "data" / "content_curator.db"


def get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = get_db()
    c = conn.cursor()

    c.executescript("""
    CREATE TABLE IF NOT EXISTS creators (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        platform TEXT NOT NULL,
        uid TEXT NOT NULL,
        name TEXT,
        avatar TEXT,
        update_strategy TEXT DEFAULT 'select',
        priority TEXT DEFAULT 'normal',
        content_types TEXT DEFAULT '[]',
        custom_tags TEXT DEFAULT '[]',
        enabled INTEGER DEFAULT 1,
        last_checked TIMESTAMP,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(platform, uid)
    );

    CREATE TABLE IF NOT EXISTS contents (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        creator_id INTEGER REFERENCES creators(id) ON DELETE CASCADE,
        platform TEXT NOT NULL,
        bvid TEXT,
        url TEXT,
        title TEXT,
        duration INTEGER DEFAULT 0,
        word_count INTEGER DEFAULT 0,
        pub_date TIMESTAMP,
        cover TEXT,
        is_collection INTEGER DEFAULT 0,
        collection_id TEXT,
        status TEXT DEFAULT 'pending',
        error_msg TEXT,
        retry_count INTEGER DEFAULT 0,
        processed_at TIMESTAMP,
        note_path TEXT,
        category TEXT,
        sub_category TEXT,
        used_frames INTEGER DEFAULT 0,
        frame_decision TEXT,
        content_hash TEXT,
        ai_summary TEXT,
        structured_info TEXT,
        cleaned_text TEXT,
        original_subtitle TEXT,
        content_tags TEXT DEFAULT '[]',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(platform, bvid)
    );

    CREATE TABLE IF NOT EXISTS task_queue (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        content_id INTEGER REFERENCES contents(id) ON DELETE CASCADE,
        task_type TEXT NOT NULL,
        status TEXT DEFAULT 'pending',
        priority INTEGER DEFAULT 0,
        scheduled_at TIMESTAMP,
        started_at TIMESTAMP,
        finished_at TIMESTAMP,
        result TEXT,
        error TEXT
    );

    CREATE TABLE IF NOT EXISTS settings (
        key TEXT PRIMARY KEY,
        value TEXT,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS review_state (
        content_id INTEGER PRIMARY KEY REFERENCES contents(id) ON DELETE CASCADE,
        last_hash TEXT,
        last_reviewed TIMESTAMP,
        review_status TEXT DEFAULT 'pending'
    );

    CREATE TABLE IF NOT EXISTS pending_claims (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        content_id INTEGER REFERENCES contents(id) ON DELETE CASCADE,
        claim TEXT,
        claim_type TEXT,
        status TEXT DEFAULT 'pending',
        correction TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );

    CREATE INDEX IF NOT EXISTS idx_contents_status ON contents(status);
    CREATE INDEX IF NOT EXISTS idx_contents_creator ON contents(creator_id);
    CREATE INDEX IF NOT EXISTS idx_tasks_status ON task_queue(status);
    """)

    # Insert default settings
    defaults = {
        "vault_path": "/app/vault",
        "ai_config": json.dumps({
            "api_base": "https://api.siliconflow.cn/v1",
            "text_model": "deepseek-ai/DeepSeek-V3",
            "vision_model": "Qwen/Qwen3-VL-8B-Instruct",
            "temperature": 0.3,
            "max_tokens": 2500
        }),
        "whisper_config": json.dumps({
            "mode": "cloud",
            "model_size": "base",
            "language": "zh"
        }),
        "sessdata": "",
        "wechat_method": "manual",
        "schedule_config": json.dumps({
            "check_time": "09:00",
            "process_collections": False
        }),
        "ad_filter_prompt": "识别并删除赞助广告、推广、带货、优惠码、关注点赞求三连等无关信息。只保留有价值的知识性内容。",
        "domain_taxonomy": json.dumps({
            "AI与智能体": ["ai", "人工智能", "大模型", "llm", "gpt", "claude", "deepseek", "gemma", "智能体", "agent", "prompt", "提示词", "rag", "微调", "finetune", "embedding", "向量", "transformer", "mcp", "工具调用"],
            "自动化工作流": ["n8n", "自动化", "工作流", "workflow", "zapier", "make", "dify", "coze", "flowise", "langflow", "低代码", "nocode"],
            "编程开发": ["编程", "代码", "python", "java", "react", "vue", "docker", "linux", "git", "前端", "后端", "开发", "javascript", "typescript", "rust", "go", "api", "数据库", "sql", "redis", "微服务", "devops", "ci/cd"],
            "硬件与嵌入式": ["硬件", "芯片", "树莓派", "raspberry", "arduino", "电子", "3d打印", "嵌入式", "单片机", "esp32", "pcb", "电路", "焊接", "iot"],
            "科技数码": ["手机", "电脑", "数码", "测评", "拆解", "gpu", "显卡", "cpu", "ssd", "显示器", "耳机", "机械键盘", "nas", "路由器"],
            "网络安全": ["安全", "渗透", "ctf", "漏洞", "加密", "隐私", "vpn", "防火墙", "hack", "逆向", "取证", "owasp"],
            "数据科学": ["数据分析", "可视化", "爬虫", "机器学习", "深度学习", "pytorch", "tensorflow", "pandas", "numpy", "统计", "算法", "数据挖掘"],
            "健康医学": ["健康", "养生", "医生", "疾病", "饮食", "运动", "医疗", "皮肤", "中医", "营养", "心理", "睡眠", "急救"],
            "生活技能": ["厨艺", "美食", "清洁", "收纳", "维修", "园艺", "宠物", "理财", "旅行", "驾驶", "法律"],
            "教育学习": ["教程", "课程", "教学", "学习", "考研", "考试", "英语", "数学", "物理", "化学", "历史", "哲学"]
        }),
    }
    for k, v in defaults.items():
        c.execute("INSERT OR IGNORE INTO settings(key, value) VALUES(?, ?)", (k, v))

    conn.commit()
    conn.close()
