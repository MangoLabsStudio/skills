# 🧰 Skills

> Mango Labs 团队工具收集库 — 把你觉得好用的工具、脚本、Prompt、工作流丢进来

## 目录结构

```
skills/
├── scripts/        # 脚本工具（Python, Shell, JS...）
├── prompts/        # 好用的 AI Prompt 模板
├── workflows/      # 自动化工作流（n8n, Zapier, GitHub Actions...）
├── browser/        # 浏览器插件、油猴脚本、书签工具
└── resources/      # 资源合集（API、数据源、参考站点）
```

## 怎么提交

1. 找到对应分类文件夹，没有就新建
2. 每个工具一个文件夹或一个文件，附带简短说明
3. 命名格式：`工具名/` 或 `工具名.md`

### 单文件示例

```markdown
# 工具名

> 一句话说明这是干嘛的

- 链接：https://...
- 适用场景：xxx
- 使用方法：xxx
```

### 脚本示例

```
scripts/
└── twitter-thread-unroll/
    ├── README.md        # 说明 + 使用方法
    ├── unroll.py        # 脚本本身
    └── requirements.txt # 依赖（如果有）
```

## 提交规范

- Commit message 格式：`add: 工具名` / `update: 工具名` / `fix: 工具名`
- 不要提交 API Key、密码等敏感信息
- 大文件（>10MB）用链接代替

## 谁都可以提交

所有 Mango Labs 成员都有写权限，直接 push 到 main 就行。发现好东西随手丢进来。
