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

// Work mode types (verify vs write)
export type WorkMode = 'verify' | 'write';

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
  snippetIds: string[];             // 已确认的 snippets
  pendingSnippetIds?: string[];     // AI推荐但未确认的 snippets

  // === 状态 ===
  isAIGenerated: boolean;
  status: 'draft' | 'verified';
  needsSnippetConfirmation?: boolean;  // 是否需要用户确认snippets

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

// Sentence with provenance information (V3: SubArgument-aware)
export interface SentenceWithProvenance {
  text: string;
  snippet_ids: string[];           // IDs of source snippets
  subargument_id?: string | null;  // V3: Source SubArgument
  argument_id?: string | null;     // V3: Source Argument
  exhibit_refs?: string[];         // V3: Exhibit references [F-1, F-2]
  sentence_type?: 'opening' | 'body' | 'closing';  // V3: Sentence position
  isEdited?: boolean;              // V3: Has been manually edited
  originalText?: string;           // V3: Original text before edit

  // Change cascade tracking
  changeStatus?: 'removed' | 'needs_adjustment' | 'suggested_replacement' | null;
  suggestedText?: string;          // LLM suggested replacement text
  changeReason?: string;           // Why this sentence needs adjustment
}

// Provenance index for fast lookups
export interface ProvenanceIndex {
  bySubArgument: Record<string, number[]>;  // subarg_id -> sentence indices
  byArgument: Record<string, number[]>;     // arg_id -> sentence indices
  bySnippet: Record<string, number[]>;      // snippet_id -> sentence indices
}

// Letter section for petition document (V3: with SubArgument mapping)
export interface LetterSection {
  id: string;
  title: string;
  standardId?: string;                      // Link to EB-1A standard
  content: string;
  isGenerated?: boolean;
  order?: number;
  sentences?: SentenceWithProvenance[];     // Sentences with provenance for highlighting

  // V3: SubArgument-level provenance
  provenanceIndex?: ProvenanceIndex;        // Fast lookup index

  // V3: Edit tracking
  isEdited?: boolean;
  lastEditedAt?: Date;

  // V3: UI state
  isExpanded?: boolean;

  // Change cascade tracking
  isStale?: boolean;                        // Has pending SubArgument changes
  pendingSuggestions?: Array<{              // LLM adjustment suggestions
    sentenceIndex: number;
    originalText: string;
    suggestedText: string;
    reason: string;
  }>;
}

// ============================================
// LLM Provider Types
// ============================================

export type ProjectType = 'EB-1A' | 'NIW';

export type LLMProvider = 'deepseek' | 'openai';

export interface LLMProviderInfo {
  id: LLMProvider;
  name: string;
  description: string;
  models: string[];
}

// ============================================
// Type Validation Functions
// ============================================

const ARGUMENT_CLAIM_TYPES: readonly string[] = [
  'award', 'membership', 'publication', 'contribution', 'salary',
  'judging', 'media', 'leading_role', 'exhibition', 'commercial', 'other',
];

const VIEW_MODES: readonly string[] = ['line', 'sankey'];
const ARGUMENT_VIEW_MODES: readonly string[] = ['list', 'graph'];
const LLM_PROVIDER_IDS: readonly string[] = ['deepseek', 'openai'];
const MATERIAL_TYPES: readonly string[] = [
  'salary', 'leadership', 'contribution', 'award',
  'membership', 'publication', 'judging', 'other',
];

export function toArgumentClaimType(value: string | undefined | null, fallback: ArgumentClaimType = 'other'): ArgumentClaimType {
  return ARGUMENT_CLAIM_TYPES.includes(value as string) ? (value as ArgumentClaimType) : fallback;
}

export function toViewMode(value: string | null, fallback: ViewMode = 'line'): ViewMode {
  return VIEW_MODES.includes(value as string) ? (value as ViewMode) : fallback;
}

export function toArgumentViewMode(value: string | null, fallback: ArgumentViewMode = 'graph'): ArgumentViewMode {
  return ARGUMENT_VIEW_MODES.includes(value as string) ? (value as ArgumentViewMode) : fallback;
}

export function toLLMProvider(value: string | null, fallback: LLMProvider = 'deepseek'): LLMProvider {
  return LLM_PROVIDER_IDS.includes(value as string) ? (value as LLMProvider) : fallback;
}

export function toMaterialType(value: string | null, fallback: MaterialType = 'other'): MaterialType {
  return MATERIAL_TYPES.includes(value as string) ? (value as MaterialType) : fallback;
}

// ============================================
// Pipeline & Extraction Types (shared across contexts)
// ============================================

export type PipelineStage =
  | 'ocr_complete'
  | 'extracting'
  | 'snippets_ready'
  | 'confirming'
  | 'mapping_confirmed'
  | 'generating'
  | 'petition_ready';

export interface PipelineState {
  stage: PipelineStage;
  progress?: number;
  snippetCount?: number;
  confirmedMappings?: number;
  error?: string;
}

export interface MergeSuggestion {
  id: string;
  primary_entity_name: string;
  primary_entity_type: string;
  merge_entity_names: string[];
  reason: string;
  confidence: number;
  status: 'pending' | 'accepted' | 'rejected';
}
