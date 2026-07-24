"""
Domain classification service.

Classifies video content into knowledge domains, extracts sub-categories,
and identifies tech entities / concepts as knowledge tags.
"""

from __future__ import annotations

from ..config import get_domain_taxonomy


# ──────────────────────────────────────────────────────────────────────────────
# Sub-category mapping: (keywords, sub_category_label)
# ──────────────────────────────────────────────────────────────────────────────
_SUB_CATEGORY_MAP: list[tuple[list[str], str]] = [
    (["n8n"], "n8n工作流"),
    (["langchain", "lang chain", "lang-chain"], "LangChain开发"),
    (["rag", "检索增强", "retrieval augmented"], "RAG系统"),
    (["prompt", "提示词", "提示工程"], "Prompt工程"),
    (["微调", "finetune", "fine-tune", "fine tune", "lora", "LoRA"], "微调训练"),
    (["python"], "Python编程"),
    (["docker", "容器化", "compose", "k8s", "kubernetes"], "Docker容器"),
    (["linux", "ubuntu", "centos", "debian", "shell", "bash"], "Linux运维"),
    (["react", "vue", "前端", "frontend", "nextjs", "next.js"], "前端开发"),
    (["sql", "mysql", "redis", "postgres", "postgresql", "mongodb", "数据库"], "数据库"),
    (["皮肤", "护肤", "dermatology", "skincare"], "皮肤管理"),
    (["饮食", "营养", "食物", "nutrition", "diet"], "营养饮食"),
    (["急救", "保命", "first aid", "cpr", "心肺复苏"], "急救知识"),
    (["心理", "情绪", "psychology", "mental", "焦虑", "抑郁"], "心理健康"),
]

# ──────────────────────────────────────────────────────────────────────────────
# Tech entities — each entry: (display_name, [aliases])
# Matching is case-insensitive on the combined title+content blob.
# ──────────────────────────────────────────────────────────────────────────────
_TECH_ENTITIES: list[tuple[str, list[str]]] = [
    ("n8n", ["n8n"]),
    ("DeepSeek", ["deepseek"]),
    ("GPT", ["gpt", "chatgpt", "gpt-4", "gpt4", "gpt-3"]),
    ("Claude", ["claude"]),
    ("Python", ["python"]),
    ("Docker", ["docker"]),
    ("Linux", ["linux"]),
    ("React", ["react"]),
    ("Vue", ["vue"]),
    ("Git", ["git", "github", "gitlab"]),
    ("Redis", ["redis"]),
    ("MySQL", ["mysql"]),
    ("MongoDB", ["mongodb", "mongo"]),
    ("FastAPI", ["fastapi", "fast api"]),
    ("LangChain", ["langchain", "lang chain"]),
    ("RAG", ["rag"]),
    ("MCP", ["mcp", "model context protocol"]),
    ("Agent", ["agent", "agents"]),
    ("Transformer", ["transformer"]),
    ("LoRA", ["lora"]),
    ("PyTorch", ["pytorch", "torch"]),
    ("TensorFlow", ["tensorflow", "tf"]),
    ("Pandas", ["pandas"]),
    ("NumPy", ["numpy"]),
    ("Ollama", ["ollama"]),
    ("Stable Diffusion", ["stable diffusion", "sdxl", "sd1.5"]),
    ("ComfyUI", ["comfyui", "comfy ui"]),
    ("FFmpeg", ["ffmpeg"]),
]

_CONCEPT_TAGS: list[str] = [
    "向量数据库",
    "嵌入模型",
    "提示工程",
    "工作流",
    "微服务",
    "容器化",
    "CI/CD",
    "数据可视化",
    "知识图谱",
    "自动化测试",
    "消息队列",
    "负载均衡",
    "缓存策略",
    "设计模式",
]

# Concept keyword hints used to detect concepts in text (concept → search terms)
_CONCEPT_HINTS: list[tuple[str, list[str]]] = [
    ("向量数据库", ["向量数据库", "vector database", "vector db", "milvus", "pinecone", "chroma", "qdrant", "faiss"]),
    ("嵌入模型", ["嵌入模型", "embedding", "embeddings", "向量化"]),
    ("提示工程", ["提示工程", "prompt engineering", "prompt工程"]),
    ("工作流", ["工作流", "workflow"]),
    ("微服务", ["微服务", "microservice", "micro-service"]),
    ("容器化", ["容器化", "containerization", "container"]),
    ("CI/CD", ["ci/cd", "cicd", "continuous integration", "continuous deployment", "jenkins", "gitlab ci"]),
    ("数据可视化", ["数据可视化", "data visualization", "可视化"]),
    ("知识图谱", ["知识图谱", "knowledge graph"]),
    ("自动化测试", ["自动化测试", "automated test", "unit test", "pytest", "jest"]),
    ("消息队列", ["消息队列", "message queue", "kafka", "rabbitmq", "rabbit mq", "nats"]),
    ("负载均衡", ["负载均衡", "load balancing", "load balancer"]),
    ("缓存策略", ["缓存策略", "cache strategy", "缓存"]),
    ("设计模式", ["设计模式", "design pattern"]),
]


def _combined_lower(title: str, content: str) -> str:
    return f"{title} {content}".lower()


# ──────────────────────────────────────────────────────────────────────────────
# 1. Domain classification
# ──────────────────────────────────────────────────────────────────────────────
def classify_domain(title: str, content: str = "") -> str:
    """
    Classify content into one of the knowledge domains defined in the taxonomy.
    Taxonomy is stored as {domain_name: [keywords]} dict in DB settings.
    """
    taxonomy = get_domain_taxonomy()
    blob = _combined_lower(title, content)

    if not taxonomy:
        return "未分类"

    best_domain = "未分类"
    best_score = 0

    for domain_name, keywords in taxonomy.items():
        score = 0
        for kw in keywords:
            kw_lower = str(kw).lower()
            if kw_lower and kw_lower in blob:
                score += 1
        if score > best_score:
            best_score = score
            best_domain = domain_name

    return best_domain


# ──────────────────────────────────────────────────────────────────────────────
# 2. Sub-category extraction
# ──────────────────────────────────────────────────────────────────────────────
def extract_sub_category(title: str, content: str = "") -> str:
    """
    Extract a finer-grained sub-category from title/content.

    Iterates through ``_SUB_CATEGORY_MAP`` in order and returns the label of
    the *first* mapping whose any keyword appears (case-insensitive) in the
    combined title+content blob.

    Returns ``""`` when nothing matches.
    """
    blob = _combined_lower(title, content)

    for keywords, label in _SUB_CATEGORY_MAP:
        for kw in keywords:
            if kw.lower() in blob:
                return label
    return ""


# ──────────────────────────────────────────────────────────────────────────────
# 3. Knowledge-tag extraction
# ──────────────────────────────────────────────────────────────────────────────
def extract_knowledge_tags(title: str, content: str = "") -> list[str]:
    """
    Extract tech entities and AI/DEV concepts from title+content.

    Returns a de-duplicated list of tag strings, entities first (in the
    canonical order defined by ``_TECH_ENTITIES``), then matched concepts
    (in the order defined by ``_CONCEPT_HINTS``).  The list never contains
    duplicates and is never ``None``.
    """
    blob = _combined_lower(title, content)
    tags: list[str] = []

    for display_name, aliases in _TECH_ENTITIES:
        for alias in aliases:
            if alias.lower() in blob:
                if display_name not in tags:
                    tags.append(display_name)
                break

    for concept, hints in _CONCEPT_HINTS:
        for hint in hints:
            if hint.lower() in blob:
                if concept not in tags:
                    tags.append(concept)
                break

    return tags
