# Argument Assembly Layer 改造手册

## 核心问题

Raw snippets 直接映射到 Standards 会导致**主体错乱**。

```
❌ 现在的流程：
Snippet "Dr. Chen received IEEE Award"    ──→ Awards Standard
Snippet "Dr. Zhang received ACM Fellowship" ──→ Awards Standard
Snippet "The committee selected Dr. Chen..." ──→ Awards Standard

→ Writing LLM 可能写出："Dr. Chen received the ACM Fellowship"（张冠李戴）
```

```
✅ 改造后的流程：
Snippet A + Snippet C → Argument: "Dr. Chen — IEEE Award (2021)" ──→ Awards Standard
Snippet B → 排除（跟本案申请人无关）

→ Writing LLM 输入主体明确，不会混淆
```

**Argument（验证论据）取代 Snippet 成为映射和写作的最小单元。**

---

## 一、前端布局改造

### 现状：三区

```
┌─────────┬──────────────────────┬──────────────┐
│ 文档     │ Snippet 卡片池        │ Standards    │
│ Viewer   │ (EvidenceCardPool)   │ + Writing    │
│          │                      │ Canvas       │
└─────────┴──────────────────────┴──────────────┘
```

### 目标：四区

```
┌─────────┬─────────────┬──────────────┬──────────────┐
│         │ 中左         │ 中右          │              │
│ 文档     │ Snippet     │ Argument     │ Standards    │
│ Viewer   │ Pool        │ Assembly     │ + Petition   │
│         │             │              │ Preview      │
│         │ AI 提取的    │ 律师组装的    │              │
│         │ 证据碎片     │ 验证论据      │ 映射 + 生成  │
│         │             │              │              │
│         │  拖拽 ──→   │  拖拽 ──→    │              │
│         │             │  ← 关联信号  │              │
└─────────┴─────────────┴──────────────┴──────────────┘
```

### 四区职责

| 区域 | 组件 | 内容 | 交互 |
|------|------|------|------|
| 左 | DocumentViewer | 源文档 PDF 渲染 | 点击高亮 bbox |
| 中左 | SnippetPool (改造) | AI 提取的 raw snippets | 拖拽到中右 |
| 中右 | **ArgumentAssembly (新建)** | 律师组装的验证论据 | 接收 snippets、编辑标题、拖拽到右 |
| 右 | StandardsPanel + PetitionPreview (改造) | 法律标准 + 生成的段落 | 接收 Arguments、触发写作 |

---

## 二、数据模型

### 增强 Argument 类型

现有 Argument 太简单（只有 title + description）。改为：

```typescript
// types/index.ts — 替换现有 Argument interface

export interface Argument {
  id: string;
  
  // === 核心内容 ===
  title: string;                    // 论据标题（律师填写或 AI 建议）
  subject: string;                  // 论据主体："Dr. Chen" — 防止主体错乱的关键字段
  claimType: ArgumentClaimType;     // 论据类型
  
  // === 组成 snippets ===
  snippetIds: string[];             // 组成这个论据的 snippet IDs
  
  // === 状态 ===
  status: ArgumentStatus;
  standardKey?: string;             // 映射到的 standard（拖拽到右侧后填入）
  
  // === 元数据 ===
  isAIGenerated: boolean;           // AI 建议的 vs 律师手动创建的
  createdAt: Date;
  updatedAt: Date;
  notes?: string;                   // 律师备注
}

export type ArgumentClaimType = 
  | 'award'           // 获奖
  | 'membership'      // 会员资格
  | 'publication'     // 发表
  | 'contribution'    // 原创贡献
  | 'salary'          // 薪资
  | 'judging'         // 评审
  | 'media'           // 媒体报道
  | 'leading_role'    // 领导角色
  | 'exhibition'      // 展览
  | 'commercial'      // 商业成就
  | 'other';

export type ArgumentStatus = 
  | 'draft'           // 刚创建，snippets 还没验证
  | 'verified'        // 律师已验证所有 snippets 属于同一主体/论点
  | 'mapped'          // 已映射到 standard
  | 'used';           // 已被 writing LLM 使用

// 更新 WritingEdge，保持不变但语义更清晰
export type WritingEdgeType = 'snippet-to-argument' | 'argument-to-standard';
```

### Snippet Pool 过滤状态

Snippet 加一个 `assembled` 标记，表示已经被拖入某个 Argument：

```typescript
// 不改 Snippet 接口本身，通过 Context 状态追踪
// 已组装的 snippet 在 Pool 中变灰/半透明，但仍可见
// 一个 snippet 可以属于多个 Arguments（同一证据支撑多个论点）
```

---

## 三、新建 ArgumentAssembly 组件

**文件：** `src/components/ArgumentAssembly.tsx`

### 核心功能

1. **接收 snippets 拖拽** — 从 SnippetPool 拖入
2. **创建 Argument** — 拖入第一个 snippet 时自动创建
3. **AI 建议标题和主体** — 分析 snippets 内容，建议 title 和 subject
4. **验证提示** — 如果 snippets 的主体不一致，弹出警告
5. **拖拽到 Standards** — 整个 Argument 卡片可拖到右侧映射

### 组件结构

```tsx
// ArgumentAssembly.tsx — 核心结构

interface ArgumentCardProps {
  argument: Argument;
  snippets: Snippet[];  // 该 argument 包含的 snippets
  onRemoveSnippet: (snippetId: string) => void;
  onUpdateArgument: (updates: Partial<Argument>) => void;
  onDragStart: (argumentId: string) => void;
  isExpanded: boolean;
  onToggleExpand: () => void;
}

const ArgumentCard: React.FC<ArgumentCardProps> = ({
  argument, snippets, onRemoveSnippet, onUpdateArgument, onDragStart,
  isExpanded, onToggleExpand
}) => {
  return (
    <div
      draggable
      onDragStart={() => onDragStart(argument.id)}
      className={`
        border rounded-lg p-3 mb-3 cursor-grab
        ${argument.status === 'verified' ? 'border-green-300 bg-green-50' : ''}
        ${argument.status === 'draft' ? 'border-amber-300 bg-amber-50' : ''}
        ${argument.status === 'mapped' ? 'border-blue-300 bg-blue-50' : ''}
      `}
    >
      {/* === 头部：标题 + 主体 + 状态 === */}
      <div className="flex items-center justify-between mb-2">
        <div className="flex-1">
          <input
            className="font-medium text-sm w-full bg-transparent border-b border-transparent 
                       hover:border-gray-300 focus:border-blue-500 focus:outline-none"
            value={argument.title}
            onChange={(e) => onUpdateArgument({ title: e.target.value })}
            placeholder="Argument title..."
          />
          <div className="flex items-center gap-2 mt-1">
            <span className="text-xs text-gray-500">Subject:</span>
            <input
              className="text-xs bg-transparent border-b border-dashed border-gray-300
                         focus:border-blue-500 focus:outline-none"
              value={argument.subject}
              onChange={(e) => onUpdateArgument({ subject: e.target.value })}
              placeholder="Who is this about?"
            />
          </div>
        </div>
        
        {/* 状态徽章 */}
        <StatusBadge status={argument.status} />
        
        {/* 展开/收起 */}
        <button onClick={onToggleExpand} className="ml-2 text-gray-400 hover:text-gray-600">
          {isExpanded ? '▼' : '▶'}
        </button>
      </div>

      {/* === Snippet 列表（展开时显示） === */}
      {isExpanded && (
        <div className="space-y-1.5 mt-2 pl-2 border-l-2 border-gray-200">
          {snippets.map(snip => (
            <SnippetChip
              key={snip.id}
              snippet={snip}
              onRemove={() => onRemoveSnippet(snip.id)}
            />
          ))}
          
          {/* Drop zone for additional snippets */}
          <DropZone
            onDrop={(snippetId) => {/* add to this argument */}}
            label="Drop snippet here to add"
          />
        </div>
      )}

      {/* === 收起时只显示 snippet 数量 === */}
      {!isExpanded && (
        <div className="text-xs text-gray-400">
          {snippets.length} snippet(s) · {argument.claimType}
        </div>
      )}

      {/* === 验证按钮 === */}
      {argument.status === 'draft' && (
        <button
          onClick={() => onUpdateArgument({ status: 'verified', updatedAt: new Date() })}
          className="mt-2 text-xs px-3 py-1 bg-green-100 text-green-700 rounded-full
                     hover:bg-green-200 transition-colors"
        >
          ✓ Verify this argument
        </button>
      )}
    </div>
  );
};


// Snippet 小卡片（在 Argument 内部显示）
const SnippetChip: React.FC<{
  snippet: Snippet;
  onRemove: () => void;
}> = ({ snippet, onRemove }) => (
  <div className="flex items-start gap-2 p-2 bg-white rounded border text-xs group">
    <div className="flex-1">
      <span className="text-gray-500">[{snippet.id}]</span>{' '}
      <span className="text-gray-700">{snippet.content.slice(0, 120)}...</span>
    </div>
    <button
      onClick={onRemove}
      className="opacity-0 group-hover:opacity-100 text-red-400 hover:text-red-600"
    >
      ✕
    </button>
  </div>
);
```

### 主体冲突检测

当律师往一个 Argument 里拖入新 snippet 时，检查主体是否一致：

```typescript
// utils/subjectDetector.ts

/**
 * 简单的主体冲突检测
 * 从 snippet 文本中提取人名/组织名，对比是否一致
 * 
 * 不需要 LLM — 用正则 + 实体图数据
 */
export function detectSubjectConflict(
  existingSnippets: Snippet[],
  newSnippet: Snippet,
  entityGraph?: EntityGraphData  // 从 snippet_linker 获得
): SubjectConflict | null {
  
  // 方法 1：用实体图
  // 如果 entityGraph 可用，查找每个 snippet 关联的 person 实体
  if (entityGraph) {
    const existingSubjects = new Set<string>();
    for (const s of existingSnippets) {
      const entities = entityGraph.getEntitiesForSnippet(s.id);
      entities
        .filter(e => e.type === 'person')
        .forEach(e => existingSubjects.add(e.name));
    }
    
    const newEntities = entityGraph.getEntitiesForSnippet(newSnippet.id);
    const newPersons = newEntities.filter(e => e.type === 'person');
    
    for (const person of newPersons) {
      if (existingSubjects.size > 0 && !existingSubjects.has(person.name)) {
        return {
          type: 'person_mismatch',
          existing: Array.from(existingSubjects),
          incoming: person.name,
          message: `This snippet mentions "${person.name}", but the existing snippets are about "${Array.from(existingSubjects).join(', ')}". Are you sure?`
        };
      }
    }
  }
  
  // 方法 2：简单文本匹配 fallback
  // 如果没有实体图，用 argument.subject 字段做简单检查
  // ...
  
  return null; // 无冲突
}

interface SubjectConflict {
  type: 'person_mismatch' | 'topic_mismatch';
  existing: string[];
  incoming: string;
  message: string;
}
```

### 冲突提示 UI

```tsx
// 在 ArgumentCard 的 DropZone 处理中
const handleSnippetDrop = (snippetId: string) => {
  const newSnippet = getSnippetById(snippetId);
  const existingSnippets = argument.snippetIds.map(getSnippetById);
  
  const conflict = detectSubjectConflict(existingSnippets, newSnippet, entityGraph);
  
  if (conflict) {
    // 显示警告，但不阻止操作
    showConflictWarning(conflict);
    // 律师可以选择"仍然添加"或"取消"
  } else {
    addSnippetToArgument(argument.id, snippetId);
  }
};

// 警告弹窗
const ConflictWarning: React.FC<{
  conflict: SubjectConflict;
  onConfirm: () => void;
  onCancel: () => void;
}> = ({ conflict, onConfirm, onCancel }) => (
  <div className="absolute z-50 bg-amber-50 border border-amber-300 rounded-lg p-3 shadow-lg max-w-xs">
    <div className="flex items-start gap-2">
      <span className="text-amber-500 text-lg">⚠️</span>
      <div>
        <p className="text-sm font-medium text-amber-800">Subject Mismatch</p>
        <p className="text-xs text-amber-700 mt-1">{conflict.message}</p>
        <div className="flex gap-2 mt-2">
          <button
            onClick={onConfirm}
            className="text-xs px-2 py-1 bg-amber-200 rounded hover:bg-amber-300"
          >
            Add anyway
          </button>
          <button
            onClick={onCancel}
            className="text-xs px-2 py-1 bg-white border rounded hover:bg-gray-50"
          >
            Cancel
          </button>
        </div>
      </div>
    </div>
  </div>
);
```

---

## 四、AI 辅助 Argument 建议

当律师拖入第一个 snippet 时，可以让 AI 自动建议 title 和 subject。

### 后端端点

```python
# backend/app/routers/argument_suggest.py

@router.post("/suggest-argument")
async def suggest_argument(
    snippet_ids: List[str],
    project_id: str
):
    """
    分析 snippets，建议 Argument 的 title、subject、claimType
    Model: GPT-4o-mini（快、便宜、定式任务）
    """
    registry = load_registry(project_id)
    snippet_texts = [
        s for s in registry if s["snippet_id"] in snippet_ids
    ]
    
    context = "\n".join(
        f'[{s["snippet_id"]}] ({s["exhibit_id"]}): "{s["text"][:200]}"'
        for s in snippet_texts
    )
    
    prompt = f"""Analyze these evidence snippets and suggest an argument structure.

Snippets:
{context}

Return JSON:
{{
  "title": "Short argument title (e.g. 'Dr. Chen — IEEE Best Paper Award 2021')",
  "subject": "Main person or entity this argument is about",
  "claim_type": "one of: award, membership, publication, contribution, salary, judging, media, leading_role, exhibition, commercial, other",
  "summary": "One sentence describing what these snippets collectively prove"
}}
"""
    
    result = await call_llm_openai(
        prompt, 
        model="gpt-4o-mini",
        json_schema=argument_suggest_schema
    )
    return result
```

### 前端调用时机

```typescript
// 拖入第一个 snippet 创建 Argument 时
const handleCreateArgumentFromDrop = async (snippetId: string) => {
  // 1. 创建 draft argument
  const newArg: Argument = {
    id: `arg-${Date.now()}`,
    title: '',
    subject: '',
    claimType: 'other',
    snippetIds: [snippetId],
    status: 'draft',
    isAIGenerated: false,
    createdAt: new Date(),
    updatedAt: new Date(),
  };
  addArgument(newArg);
  
  // 2. 异步请求 AI 建议（不阻塞 UI）
  const suggestion = await api.suggestArgument([snippetId], projectId);
  if (suggestion) {
    updateArgument(newArg.id, {
      title: suggestion.title,
      subject: suggestion.subject,
      claimType: suggestion.claim_type,
    });
    // 律师可以接受或修改 AI 建议
  }
};
```

---

## 五、Snippet Pool 改造

### 改造 EvidenceCardPool

从"可拖拽到 Standards"改为"只可拖拽到 ArgumentAssembly"：

```
之前：SnippetPool ──拖拽──→ Standards
现在：SnippetPool ──拖拽──→ ArgumentAssembly ──拖拽──→ Standards
```

### 视觉状态变化

```tsx
// 每个 snippet 卡片的状态样式
const snippetStateStyle = (snippetId: string) => {
  const isAssembled = arguments.some(arg => arg.snippetIds.includes(snippetId));
  const isLinked = snippetLinks.some(
    l => l.snippet_a === snippetId || l.snippet_b === snippetId
  );
  
  if (isAssembled) {
    return 'opacity-50 border-green-300';  // 已组装，半透明
  }
  if (isLinked) {
    return 'ring-1 ring-blue-200';         // 有关联信号，微微高亮
  }
  return '';                                // 默认状态
};
```

### 关联信号展示（复用 snippet_linker 数据）

```tsx
// 在 SnippetPool 中，hover 一个 snippet 时
// 高亮所有相关 snippets（通过 snippetLinks）
const [hoveredSnippetId, setHoveredSnippetId] = useState<string | null>(null);

const highlightedSnippetIds = useMemo(() => {
  if (!hoveredSnippetId) return new Set<string>();
  const ids = new Set<string>();
  for (const link of snippetLinks) {
    if (link.snippet_a === hoveredSnippetId) ids.add(link.snippet_b);
    if (link.snippet_b === hoveredSnippetId) ids.add(link.snippet_a);
  }
  return ids;
}, [hoveredSnippetId, snippetLinks]);
```

---

## 六、Standards Panel + Writing 改造

### 映射关系变更

```
之前：Connection { snippetId, standardId }          — snippet 直接映射 standard
现在：WritingEdge { argumentId, standardId }         — argument 映射 standard
```

Standards Panel 的 drop zone 接收的是 Argument 卡片，不再是 snippet 卡片。

### Writing LLM 输入变更

```python
# 之前：扁平 snippet 列表
context = """
[snip_001]: "Dr. Chen received IEEE Best Paper Award"
[snip_002]: "Dr. Zhang received ACM Fellowship"
[snip_003]: "The committee selected Dr. Chen..."
"""

# 现在：结构化 Argument 列表
context = """
## Argument: "Dr. Chen — IEEE Best Paper Award (2021)"
   Subject: Dr. Chen
   Status: Verified
   Evidence:
     [snip_001] (Exhibit A-1, p.2): "Dr. Chen received IEEE Best Paper Award"
     [snip_003] (Exhibit A-3, p.1): "The committee selected Dr. Chen for his contributions..."

## Argument: "Dr. Chen — NSF CAREER Award (2019)"  
   Subject: Dr. Chen
   Status: Verified
   Evidence:
     [snip_005] (Exhibit B-1, p.1): "NSF awarded Dr. Chen the CAREER grant..."
     [snip_008] (Exhibit B-2, p.3): "$2M funding for five years..."
"""
```

### 后端 context builder

```python
# backend/app/services/argument_context.py

def build_argument_context(
    arguments: List[Dict],
    snippet_registry: List[Dict],
    standard_key: str
) -> str:
    """
    构建给 Writing LLM 的 context
    只传入已映射到该 standard 且已 verified 的 arguments
    """
    snippet_map = {s["snippet_id"]: s for s in snippet_registry}
    relevant = [a for a in arguments 
                if a["standard_key"] == standard_key 
                and a["status"] in ("verified", "mapped", "used")]
    
    lines = []
    for arg in relevant:
        lines.append(f'## Argument: "{arg["title"]}"')
        lines.append(f'   Subject: {arg["subject"]}')
        lines.append(f'   Evidence:')
        
        for sid in arg["snippet_ids"]:
            snip = snippet_map.get(sid)
            if snip:
                lines.append(
                    f'     [{sid}] ({snip["exhibit_id"]}, p.{snip["page"]}): '
                    f'"{snip["text"][:200]}"'
                )
        lines.append('')
    
    return '\n'.join(lines)
```

---

## 七、Provenance 链更新

### 四层溯源

```
之前：Sentence → Snippet → BBox
现在：Sentence → Argument → Snippet(s) → BBox
```

### 3b 标注步骤的输入也要调整

```python
# annotate_sentences 的 snippet reference 改为 argument reference
async def annotate_sentences_v2(
    paragraph_text: str,
    arguments: List[Dict],
    snippet_registry: List[Dict],
    section: str
) -> List[Dict]:
    """
    标注时以 argument 为单位引用，不直接引用 snippet
    """
    relevant = [a for a in arguments if a["standard_key"] == section]
    
    arg_ref = []
    for arg in relevant:
        snippet_texts = []
        for sid in arg["snippet_ids"]:
            snip = next((s for s in snippet_registry if s["snippet_id"] == sid), None)
            if snip:
                snippet_texts.append(f'{sid}: "{snip["text"][:100]}"')
        
        arg_ref.append(
            f'[{arg["id"]}] "{arg["title"]}" (Subject: {arg["subject"]})\n'
            f'  Contains: {"; ".join(snippet_texts)}'
        )
    
    prompt = f"""Split this paragraph into sentences and annotate each with the argument IDs it draws from.

PARAGRAPH:
{paragraph_text}

AVAILABLE ARGUMENTS:
{chr(10).join(arg_ref)}

Rules:
1. Reference argument IDs (arg_xxx), not individual snippet IDs
2. Every factual claim MUST reference at least one argument
3. Transitional sentences can have empty argument_ids
"""
    
    schema = {
        "type": "object",
        "properties": {
            "sentences": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "text": {"type": "string"},
                        "argument_ids": {
                            "type": "array",
                            "items": {"type": "string"}
                        }
                    },
                    "required": ["text", "argument_ids"]
                }
            }
        },
        "required": ["sentences"]
    }
    
    result = await call_llm_openai(prompt, model="gpt-4o-mini", json_schema=schema)
    return result["sentences"]
```

### 前端溯源交互更新

```
用户点击 petition 中一个句子
  → 显示关联的 Arguments（中右面板高亮对应 Argument 卡片）
    → 展开 Argument，显示组成的 Snippets
      → 点击 Snippet → DocumentViewer 高亮 BBox
```

比之前的 Sentence → Snippet 多了一层，但用户体验更好——律师先看到"这句话来自哪个论点"，再深入到具体证据。

---

## 八、AppContext 状态更新

```typescript
// context/AppContext.tsx — 新增/修改的状态

interface AppContextType {
  // ... 现有状态 ...
  
  // === Snippet Pool ===
  snippets: Snippet[];
  snippetLinks: SnippetLink[];              // 从后端 snippet_linker 获取
  hoveredSnippetId: string | null;
  setHoveredSnippetId: (id: string | null) => void;
  
  // === Argument Assembly（增强）===
  arguments: Argument[];
  addArgument: (arg: Argument) => void;
  updateArgument: (id: string, updates: Partial<Argument>) => void;
  removeArgument: (id: string) => void;
  addSnippetToArgument: (argId: string, snippetId: string) => void;
  removeSnippetFromArgument: (argId: string, snippetId: string) => void;
  
  // === Argument → Standard 映射 ===
  argumentMappings: WritingEdge[];           // argument-to-standard edges
  addArgumentMapping: (argId: string, standardKey: string) => void;
  removeArgumentMapping: (edgeId: string) => void;
  
  // === 溯源（更新）===
  activeSentence: GeneratedSentence | null;
  setActiveSentence: (s: GeneratedSentence | null) => void;
  activeArgumentId: string | null;           // 新增：当前高亮的 argument
  setActiveArgumentId: (id: string | null) => void;
  highlightedBBoxes: Array<{ page: number; bbox: BoundingBox; color: string }>;
}
```

---

## 九、迁移路径

### 已有代码可复用

| 现有代码 | 新用途 | 改动 |
|---------|--------|------|
| `Argument` type | 增强字段 | 加 subject, snippetIds, status, claimType |
| `WritingEdge` type | 不变 | snippet-to-argument + argument-to-standard 已有 |
| `initialArguments` mock | 增强 mock 数据 | 加 snippetIds, subject 等字段 |
| `initialWritingEdges` mock | 不变 | 已有正确的边关系 |
| `EvidenceCardPool` | 改为 SnippetPool，去掉直接映射 standard | 拖拽目标改为 ArgumentAssembly |
| `WritingCanvas` | 拆分：Argument 部分移到 ArgumentAssembly | 简化为只处理 Argument → Standard |

### 不需要改的

| 组件 | 原因 |
|------|------|
| DocumentViewer | 不变，仍然做 PDF 渲染 + bbox 高亮 |
| ConnectionLines | 改为连接 Argument → Standard（替代 Snippet → Standard）|
| 后端 snippet_registry | 不变，snippet 层不受影响 |
| 后端 snippet_linker | 不变，仍然输出 snippet 间关联 |
| 后端 bbox_matcher | 不变，仍然做 snippet → bbox 匹配 |

---

## 十、改造优先级

| 优先级 | 任务 | 工时 |
|--------|------|------|
| **P0** | 增强 Argument 类型定义 | 1h |
| **P0** | 新建 ArgumentAssembly 组件（基础拖拽 + 卡片渲染） | 6h |
| **P0** | 改造 SnippetPool（拖拽目标改为 ArgumentAssembly） | 2h |
| **P0** | 改造 Standards Panel（接收 Argument 而非 Snippet） | 2h |
| **P1** | 主体冲突检测（subjectDetector） | 3h |
| **P1** | AI 建议 Argument title/subject（后端 endpoint + 前端调用） | 3h |
| **P1** | 后端 build_argument_context（Writing LLM 输入改造） | 2h |
| **P1** | 后端 annotate_sentences_v2（标注以 argument 为单位） | 2h |
| **P2** | 溯源链更新：Sentence → Argument → Snippet → BBox | 3h |
| **P2** | Snippet 关联信号展示（hover 高亮） | 2h |
| **P2** | 交互日志更新（记录 argument 操作） | 1h |

**总工时：~27h ≈ 4-5 天**

### 关键路径

```
P0: Argument 类型 → ArgumentAssembly 组件 → SnippetPool 改造 → Standards 改造
     (这四步完成后前端四区布局可用)
         ↓
P1: 冲突检测 + AI 建议 + 后端 context/annotation 改造
     (这步完成后完整 pipeline 可跑)
         ↓
P2: 溯源更新 + 关联信号
```

---

## 十一、论文价值

这个改造对论文有三层加分：

**1. 设计洞察（Design Insight）**

> Raw evidence snippets cannot be directly used as writing units — they must first be assembled into verified arguments with explicit subject attribution, to prevent entity confusion in AI-generated text.

这来自你实际开发中发现的问题（主体错乱），是真实的 design insight，reviewer 会欣赏。

**2. 交互贡献**

Argument Assembly 把律师隐性的认知过程（"这几个证据放一起能证明什么"）变成了显式的交互步骤。这是 externalization of cognition，HCI 核心主题。

**3. ICAP 框架对齐**

Assembly 操作从 Active（浏览 snippets）升级到 Constructive（主动构建论据结构）。这直接支撑 Discussion 6.1 中 ICAP 的论证。

---

## 十二、与 v2 Manual 的关系

| 维度 | v2 Manual | 本 Manual |
|------|-----------|-----------|
| 范围 | 后端 pipeline + provenance engine | 前端 Argument Assembly 层 |
| 核心改动 | sentence-level provenance, 两步写作 | 四区布局, Argument 数据模型 |
| 写作输入 | snippets 直接喂给 LLM | Arguments 喂给 LLM |
| Provenance | Sentence → Snippet → BBox | Sentence → Argument → Snippet → BBox |
| 依赖关系 | 本 manual 的 Argument 模型是 v2 writing pipeline 的输入 |

两份 manual 互补：v2 是后端 pipeline，本 manual 是前端交互层 + 数据模型适配。
