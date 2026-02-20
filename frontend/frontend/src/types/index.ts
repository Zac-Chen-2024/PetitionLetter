// Type definitions for Evidence-First Authoring System

export interface BoundingBox {
  x: number;
  y: number;
  width: number;
  height: number;
  page: number;
}

export interface Document {
  id: string;
  name: string;
  pageCount: number;
  type: 'contract' | 'recommendation' | 'award' | 'publication' | 'other';
}

export interface Snippet {
  id: string;
  documentId: string;
  content: string;
  summary: string;
  boundingBox: BoundingBox;
  materialType: MaterialType;
  color: string;
  exhibitId?: string;  // Exhibit ID for provenance tracking
  page?: number;       // Page number in the document
  // Unified extraction fields (with subject attribution)
  subject?: string;           // Who/what this snippet is about
  subjectRole?: string;       // Role of the subject (e.g., "recommender", "applicant")
  isApplicantAchievement?: boolean;  // Whether this is an applicant achievement
  evidenceType?: string;      // Type of evidence (e.g., "award", "publication")
}

export type MaterialType = 
  | 'salary'
  | 'leadership'
  | 'contribution'
  | 'award'
  | 'membership'
  | 'publication'
  | 'judging'
  | 'other';

export interface LegalStandard {
  id: string;
  name: string;
  shortName: string;
  description: string;
  color: string;
  order: number;
}

export interface Connection {
  id: string;
  snippetId: string;
  standardId: string;
  isConfirmed: boolean; // true = solid line (lawyer confirmed), false = dashed line (AI suggested)
  createdAt: Date;
}

export interface FocusState {
  type: 'none' | 'snippet' | 'standard' | 'document' | 'argument' | 'subargument';
  id: string | null;
}

export interface DragState {
  isDragging: boolean;
  snippetId: string | null;
  startPosition: { x: number; y: number } | null;
  currentPosition: { x: number; y: number } | null;
}

// Position tracking for SVG connections
export interface ElementPosition {
  id: string;
  x: number;
  y: number;
  width: number;
  height: number;
}

// View mode types
export type ViewMode = 'line' | 'sankey';

// Argument view mode (list vs graph)
export type ArgumentViewMode = 'list' | 'graph';

// Page navigation types
export type PageType = 'mapping' | 'materials' | 'writing';

// Selection state for creating snippets
export interface SelectionState {
  isSelecting: boolean;
  startPoint: { x: number; y: number } | null;
  endPoint: { x: number; y: number } | null;
  pageNumber: number | null;
  documentId: string | null;
}

// ============================================
// Material Organization Types
// ============================================

export type QualityStatus = 'pending' | 'approved' | 'rejected' | 'needs_review';

export interface RawMaterial {
  id: string;
  name: string;                    // 文件名
  fileUrl: string;                 // 文件存储路径
  pageCount: number;               // 页数
  uploadedAt: Date;                // 上传时间

  // AI 预分类
  suggestedType: MaterialType;     // AI 建议的材料类型
  suggestedExhibit: string | null; // AI 建议归属的 Exhibit

  // 质量审核
  qualityStatus: QualityStatus;
  qualityScore?: number;           // AI 评估的质量分数 (0-100)
  qualityNotes?: string;           // 审核备注

  // 归属
  exhibitId?: string;              // 确认归属的 Exhibit ID
}

export interface Exhibit {
  id: string;
  name: string;                    // 如 "Exhibit-A"
  label: string;                   // 如 "A"
  title: string;                   // 描述性标题，如 "Employment Records"
  order: number;                   // 显示顺序
  color: string;                   // UI 颜色

  // 包含的原始材料
  materialIds: string[];           // 组成此 Exhibit 的 RawMaterial IDs

  // 合并后的文档信息
  mergedFileUrl?: string;          // 合并后的 PDF 路径
  totalPageCount: number;          // 总页数
}

export interface ExhibitSection {
  id: string;
  exhibitId: string;               // 所属 Exhibit
  label: string;                   // 如 "A1", "A2"
  title: string;                   // 描述性标题

  // 页面范围
  startPage: number;
  endPage: number;

  // 来源追踪 - 一个 Section 可能由多个材料综合而成
  sourceMaterialIds: string[];     // 组成此分段的原始材料 IDs (多对多)
  order: number;                   // 显示顺序
}

// ============================================
// Writing Canvas Types (Argument-based structure)
// ============================================

export interface Position {
  x: number;
  y: number;
}

// Argument claim types - aligned with EB-1A standards
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

// Argument status in the assembly workflow
export type ArgumentStatus =
  | 'draft'           // 刚创建，snippets 还没验证
  | 'verified'        // 律师已验证所有 snippets 属于同一主体/论点
  | 'mapped'          // 已映射到 standard
  | 'used';           // 已被 writing LLM 使用

// ============================================
// Argument Qualification Types (Human-in-the-Loop)
// ============================================

// AI recommendation for argument qualification
export type QualificationRecommendation = 'keep' | 'exclude' | 'merge';

// Human decision on argument
export type HumanDecision = 'approved' | 'excluded' | 'pending';

// Single qualification check item
export interface QualificationCheck {
  key: string;           // e.g., "has_criteria", "has_selectivity"
  label: string;         // Display label
  passed: boolean;       // Whether the check passed
  note?: string;         // Additional note (e.g., "普通续费会员")
}

// Qualification result for an argument
export interface ArgumentQualification {
  recommendation: QualificationRecommendation;  // AI recommendation
  confidence: number;                           // 0-1
  checks: QualificationCheck[];                 // Individual check results
  completeness: number;                         // 0-100 completeness score
  reasons?: string[];                           // Explanation for recommendation
}

// Evidence layer item (from argument_composer)
export interface EvidenceLayerItem {
  text: string;
  exhibit_id: string;
  purpose: string;  // direct_proof, selectivity_proof, credibility_proof, impact_proof
  snippet_id: string;
}

// Completeness score from argument_composer
export interface ArgumentCompleteness {
  has_claim: boolean;
  has_proof: boolean;
  has_significance: boolean;
  has_context: boolean;
  score: number;  // 0-100
}

// Argument node - evidence snippets assembled into a verified argument
// Core unit for mapping to standards and writing
export interface Argument {
  id: string;

  // === 核心内容 ===
  title: string;                    // 论据标题，如 "Dr. Chen — IEEE Award (2021)"
  subject: string;                  // 论据主体，防止主体错乱的关键字段
  claimType: ArgumentClaimType;     // 论据类型

  // === 组成 ===
  snippetIds: string[];             // 组成这个论据的 snippet IDs (向后兼容)
  subArgumentIds?: string[];        // 次级子论点 IDs (新增)

  // === 状态 ===
  status: ArgumentStatus;
  standardKey?: string;             // 映射到的 standard（拖拽到右侧后填入）

  // === Human-in-the-Loop: 资格审核 ===
  qualification?: ArgumentQualification;  // AI 资格检查结果
  humanDecision?: HumanDecision;          // 人类审核决策
  humanNote?: string;                     // 人类审核备注

  // === 律师风格结构 (from argument_composer) ===
  exhibits?: string[];              // 相关 Exhibit IDs
  layers?: {                        // 证据层级
    claim: EvidenceLayerItem[];
    proof: EvidenceLayerItem[];
    significance: EvidenceLayerItem[];
    context: EvidenceLayerItem[];
  };
  conclusion?: string;              // 法律结论
  completeness?: ArgumentCompleteness;  // 完整性评分

  // === 元数据 ===
  isAIGenerated: boolean;           // AI 建议的 vs 律师手动创建的
  createdAt: Date;
  updatedAt: Date;
  notes?: string;                   // 律师备注

  // === WritingCanvas 兼容 ===
  position?: Position;              // 画布上的位置（可选，仅 WritingCanvas 使用）
  description?: string;             // 描述（可选，向后兼容）
}

// SubArgument - 次级子论点，Snippet 和 Argument 之间的中间层级
export interface SubArgument {
  id: string;
  argumentId: string;               // 所属主论点

  // === 内容 ===
  title: string;                    // 如 "职责范围"、"业绩成就"
  purpose: string;                  // 这组证据的作用说明
  relationship: string;             // LLM 生成的关系描述，如 "证明管理能力"

  // === 关联 ===
  snippetIds: string[];             // 1-5 个 snippets

  // === 状态 ===
  isAIGenerated: boolean;
  status: 'draft' | 'verified';

  // === 位置 (用于图形视图) ===
  position?: Position;

  // === 时间戳 ===
  createdAt: Date;
  updatedAt: Date;
}

// Edge types for the writing canvas
export type WritingEdgeType = 'snippet-to-argument' | 'argument-to-standard';

// Edge connecting nodes in the writing canvas
export interface WritingEdge {
  id: string;
  source: string;        // snippetId or argumentId
  target: string;        // argumentId or standardId
  type: WritingEdgeType;
  isConfirmed: boolean;
  createdAt: Date;
}

// Sentence with provenance information
export interface SentenceWithProvenance {
  text: string;
  snippet_ids: string[];  // IDs of source snippets
}

// Letter section for petition document
export interface LetterSection {
  id: string;
  title: string;
  standardId?: string;   // Link to EB-1A standard
  content: string;
  isGenerated?: boolean;
  order?: number;
  sentences?: SentenceWithProvenance[];  // Sentences with provenance for highlighting
}

// ============================================
// LLM Provider Types
// ============================================

export type LLMProvider = 'deepseek' | 'openai';

export interface LLMProviderInfo {
  id: LLMProvider;
  name: string;
  description: string;
  models: string[];
}
