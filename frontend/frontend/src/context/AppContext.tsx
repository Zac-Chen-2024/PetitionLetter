import { createContext, useContext, useState, useCallback, useEffect, type ReactNode } from 'react';
import type { FocusState, Connection, ElementPosition, Snippet, ViewMode, ArgumentViewMode, SelectionState, BoundingBox, Argument, SubArgument, WritingEdge, LetterSection, Position, ArgumentClaimType, ArgumentStatus, LLMProvider, PageType } from '../types';
import { legalStandards } from '../data/legalStandards';
import { getMaterialTypeColor, STANDARD_KEY_TO_ID } from '../constants/colors';
import { apiClient } from '../services/api';

// Pipeline Stage Types
export type PipelineStage =
  | 'ocr_complete'      // Stage 1: Only OCR results available
  | 'extracting'        // Extracting snippets
  | 'snippets_ready'    // Stage 2: Snippets extracted, awaiting confirmation
  | 'confirming'        // Confirming mappings
  | 'mapping_confirmed' // Stage 3: Mappings confirmed, can generate
  | 'generating'        // Generating petition
  | 'petition_ready';   // Stage 4: Petition generated

export interface PipelineState {
  stage: PipelineStage;
  progress?: number;           // 0-100 for extracting/generating
  snippetCount?: number;       // Number of extracted snippets
  confirmedMappings?: number;  // Number of confirmed mappings
  error?: string;
}

// Backend snippet format (no standard_key - classification at Argument level)
interface BackendSnippet {
  snippet_id: string;
  document_id: string;
  exhibit_id: string;
  text: string;
  page: number;
  bbox: { x1: number; y1: number; x2: number; y2: number } | null;
  block_type?: string;
}

// New unified extraction format (with subject attribution)
interface UnifiedSnippet {
  snippet_id: string;  // Full ID: snp_A1_p2_p2_b3_xxxxx
  block_id: string;    // Short ID: p2_b3
  exhibit_id: string;
  text: string;
  subject: string;
  subject_role: string;
  is_applicant_achievement: boolean;
  evidence_type: string;
  confidence: number;
  reasoning: string;
  page?: number;
  bbox?: { x1: number; y1: number; x2: number; y2: number } | null;
}

// Merge suggestion format
export interface MergeSuggestion {
  id: string;
  primary_entity_name: string;
  primary_entity_type: string;
  merge_entity_names: string[];
  reason: string;
  confidence: number;
  status: 'pending' | 'accepted' | 'rejected';
}

// Default color for unassigned snippets
const DEFAULT_SNIPPET_COLOR = '#94a3b8';  // slate-400

// Convert backend snippet to frontend format
// Color is now determined by the Argument it belongs to (handled in EvidenceCardPool)
function convertBackendSnippet(bs: BackendSnippet): Snippet {
  return {
    id: bs.snippet_id,
    documentId: bs.document_id || `doc_${bs.exhibit_id}`,
    content: bs.text,
    summary: bs.text.substring(0, 80) + (bs.text.length > 80 ? '...' : ''),
    boundingBox: bs.bbox ? {
      x: bs.bbox.x1,
      y: bs.bbox.y1,
      width: bs.bbox.x2 - bs.bbox.x1,
      height: bs.bbox.y2 - bs.bbox.y1,
      page: bs.page,
    } : { x: 0, y: 0, width: 100, height: 50, page: bs.page },
    materialType: 'other',  // No pre-classification
    color: DEFAULT_SNIPPET_COLOR,  // Gray by default, updated based on Argument
    exhibitId: bs.exhibit_id,
    page: bs.page,
  };
}

// Convert unified extraction snippet to frontend format
function convertUnifiedSnippet(us: UnifiedSnippet): Snippet {
  return {
    id: us.snippet_id,  // Use full snippet_id to match argument.snippet_ids
    documentId: `doc_${us.exhibit_id}`,
    content: us.text,
    summary: us.text.substring(0, 80) + (us.text.length > 80 ? '...' : ''),
    boundingBox: us.bbox ? {
      x: us.bbox.x1,
      y: us.bbox.y1,
      width: us.bbox.x2 - us.bbox.x1,
      height: us.bbox.y2 - us.bbox.y1,
      page: us.page || 1,
    } : { x: 0, y: 0, width: 100, height: 50, page: us.page || 1 },
    materialType: 'other',
    color: DEFAULT_SNIPPET_COLOR,
    exhibitId: us.exhibit_id,
    page: us.page || 1,
    // New unified extraction fields
    subject: us.subject,
    subjectRole: us.subject_role,
    isApplicantAchievement: us.is_applicant_achievement,
    evidenceType: us.evidence_type,
  };
}

// Panel bounds for clipping connection lines
interface PanelBounds {
  top: number;
  bottom: number;
  left: number;
  right: number;
}

interface AppContextType {
  // Project state
  projectId: string;
  setProjectId: (id: string) => void;
  isLoading: boolean;
  loadError: string | null;

  // AI Argument Generation
  isGeneratingArguments: boolean;
  generateArguments: (forceReanalyze?: boolean, applicantName?: string) => Promise<void>;
  generatedMainSubject: string | null;

  // Data
  connections: Connection[];
  allSnippets: Snippet[];

  // Focus state (for filtering - Argument/Standard level)
  focusState: FocusState;
  setFocusState: (state: FocusState) => void;
  clearFocus: () => void;

  // Selected snippet (for PDF highlight - independent of focusState)
  selectedSnippetId: string | null;
  setSelectedSnippetId: (id: string | null) => void;

  // Selected document for viewer
  selectedDocumentId: string;
  setSelectedDocumentId: (id: string) => void;

  // Connection management
  addConnection: (snippetId: string, standardId: string, isConfirmed: boolean) => void;
  removeConnection: (connectionId: string) => void;
  confirmConnection: (connectionId: string) => void;

  // Drag state
  draggedSnippetId: string | null;
  setDraggedSnippetId: (id: string | null) => void;

  // Element positions for SVG lines
  snippetPositions: Map<string, ElementPosition>;
  pdfBboxPositions: Map<string, ElementPosition>;
  updateSnippetPosition: (id: string, position: ElementPosition) => void;
  updatePdfBboxPosition: (id: string, position: ElementPosition) => void;

  // Panel bounds for clipping
  snippetPanelBounds: PanelBounds | null;
  setSnippetPanelBounds: (bounds: PanelBounds | null) => void;

  // View mode
  viewMode: ViewMode;
  setViewMode: (mode: ViewMode) => void;

  // Argument view mode (list vs graph)
  argumentViewMode: ArgumentViewMode;
  setArgumentViewMode: (mode: ArgumentViewMode) => void;

  // Argument graph node positions (for graph view)
  argumentGraphPositions: Map<string, Position>;
  updateArgumentGraphPosition: (id: string, position: Position) => void;
  clearArgumentGraphPositions: () => void;

  // Snippet management
  addSnippet: (snippet: Omit<Snippet, 'id'>) => void;
  removeSnippet: (snippetId: string) => void;

  // Selection state for creating snippets
  selectionState: SelectionState;
  setSelectionState: (state: SelectionState) => void;
  startSelection: (documentId: string, pageNumber: number, point: { x: number; y: number }) => void;
  updateSelection: (point: { x: number; y: number }) => void;
  endSelection: () => { boundingBox: BoundingBox; documentId: string } | null;
  cancelSelection: () => void;

  // Helpers
  getConnectionsForSnippet: (snippetId: string) => Connection[];
  getConnectionsForStandard: (standardId: string) => Connection[];
  isElementHighlighted: (elementType: 'snippet' | 'standard', elementId: string) => boolean;

  // ============================================
  // Argument Assembly State (NEW)
  // ============================================

  // Arguments for assembly (main page)
  arguments: Argument[];
  addArgument: (argument: Omit<Argument, 'id' | 'createdAt' | 'updatedAt'>) => void;
  updateArgument: (id: string, updates: Partial<Omit<Argument, 'id' | 'createdAt'>>) => void;
  removeArgument: (id: string) => void;
  updateArgumentPosition: (id: string, position: Position) => void;

  // Snippet to Argument operations
  addSnippetToArgument: (argumentId: string, snippetId: string) => void;
  removeSnippetFromArgument: (argumentId: string, snippetId: string) => void;

  // Argument → Standard mappings (replaces snippet → standard connections)
  argumentMappings: WritingEdge[];  // argument-to-standard edges
  addArgumentMapping: (argumentId: string, standardKey: string) => void;
  removeArgumentMapping: (edgeId: string) => void;

  // Argument drag state
  draggedArgumentId: string | null;
  setDraggedArgumentId: (id: string | null) => void;

  // Argument positions for connection lines
  argumentPositions: Map<string, ElementPosition>;
  updateArgumentPosition2: (id: string, position: ElementPosition) => void;

  // SubArgument positions for connection lines
  subArgumentPositions: Map<string, ElementPosition>;
  updateSubArgumentPosition: (id: string, position: ElementPosition) => void;

  // Hover state for snippet linking hints
  hoveredSnippetId: string | null;
  setHoveredSnippetId: (id: string | null) => void;

  // ============================================
  // SubArgument State (次级子论点)
  // ============================================
  subArguments: SubArgument[];
  addSubArgument: (subArgument: Omit<SubArgument, 'id' | 'createdAt' | 'updatedAt'>) => void;
  updateSubArgument: (id: string, updates: Partial<Omit<SubArgument, 'id' | 'createdAt'>>) => void;
  removeSubArgument: (id: string) => void;

  // ============================================
  // Writing Canvas State (kept for step 2)
  // ============================================

  // Writing edges (connections in writing canvas)
  writingEdges: WritingEdge[];
  addWritingEdge: (source: string, target: string, type: WritingEdge['type']) => void;
  removeWritingEdge: (id: string) => void;
  confirmWritingEdge: (id: string) => void;

  // Letter sections
  letterSections: LetterSection[];
  updateLetterSection: (id: string, content: string) => void;

  // Node positions in writing canvas (for snippets and standards)
  writingNodePositions: Map<string, Position>;
  updateWritingNodePosition: (id: string, position: Position) => void;

  // ============================================
  // Pipeline State
  // ============================================
  pipelineState: PipelineState;
  extractSnippets: () => Promise<void>;
  confirmAllMappings: () => Promise<void>;
  generatePetition: () => Promise<void>;
  reloadSnippets: () => Promise<void>;
  canExtract: boolean;
  canConfirm: boolean;
  canGenerate: boolean;

  // ============================================
  // Unified Extraction State (NEW)
  // ============================================
  unifiedExtract: (applicantName: string) => Promise<void>;
  generateMergeSuggestions: (applicantName: string) => Promise<MergeSuggestion[]>;
  confirmMerges: (confirmations: Array<{suggestion_id: string; status: string}>) => Promise<void>;
  applyMerges: () => Promise<void>;
  mergeSuggestions: MergeSuggestion[];
  loadMergeSuggestions: () => Promise<void>;
  isExtracting: boolean;
  isMerging: boolean;
  extractionProgress: { current: number; total: number; currentExhibit?: string } | null;

  // ============================================
  // LLM Provider Settings
  // ============================================
  llmProvider: LLMProvider;
  setLlmProvider: (provider: LLMProvider) => void;

  // ============================================
  // Page Navigation
  // ============================================
  currentPage: PageType;
  setCurrentPage: (page: PageType) => void;
}

const AppContext = createContext<AppContextType | undefined>(undefined);

const STORAGE_KEY_SNIPPETS = 'evidence-system-snippets';
const STORAGE_KEY_CONNECTIONS = 'evidence-system-connections';
const STORAGE_KEY_VIEW_MODE = 'evidence-system-view-mode';
const STORAGE_KEY_ARGUMENTS = 'evidence-system-arguments';
const STORAGE_KEY_WRITING_EDGES = 'evidence-system-writing-edges';
const STORAGE_KEY_LETTER_SECTIONS = 'evidence-system-letter-sections';
const STORAGE_KEY_WRITING_NODE_POSITIONS = 'evidence-system-writing-node-positions';
const STORAGE_KEY_LLM_PROVIDER = 'evidence-system-llm-provider';
const STORAGE_KEY_ARGUMENT_VIEW_MODE = 'evidence-system-argument-view-mode';
const STORAGE_KEY_ARGUMENT_GRAPH_POSITIONS = 'evidence-system-argument-graph-positions';
const STORAGE_KEY_SUB_ARGUMENTS = 'evidence-system-sub-arguments';

// Initial arguments - empty, will be created via ArgumentAssembly panel
const initialArguments: Argument[] = [];

// Initial writing edges - empty, will be created via drag and drop
const initialWritingEdges: WritingEdge[] = [];

// Initial letter sections
const initialLetterSections: LetterSection[] = [
  {
    id: 'sec-intro',
    title: 'I. Introduction',
    content: 'Dr. Ming Zhang is a distinguished researcher in the field of artificial intelligence, with remarkable achievements in machine learning and natural language processing. This petition will demonstrate that the applicant meets the criteria for EB-1A extraordinary ability.',
    isGenerated: true,
    order: 1,
  },
  {
    id: 'sec-awards',
    title: 'II. Awards - Internationally Recognized Awards',
    standardId: 'std-awards',
    content: 'The applicant received the NeurIPS Best Paper Award in 2023, one of the most influential international conferences in artificial intelligence. This award fully demonstrates the applicant\'s outstanding contribution to the field.\n\nSee Exhibit A.',
    isGenerated: true,
    order: 2,
  },
  {
    id: 'sec-salary',
    title: 'III. High Salary',
    standardId: 'std-salary',
    content: 'The applicant\'s current annual salary is $280,000, placing them in the top 5% of the industry. According to the Bureau of Labor Statistics, the median annual salary for software engineers is $120,000, and the applicant\'s salary far exceeds this level.\n\nSee Exhibit B.',
    isGenerated: true,
    order: 3,
  },
  {
    id: 'sec-leading',
    title: 'IV. Leading Role - Critical Leadership Position',
    standardId: 'std-leading',
    content: 'The applicant serves as the head of the AI research team, managing 15 researchers and overseeing the technical direction of the company\'s core AI products. Under their leadership, the team has successfully delivered multiple critical projects.\n\nSee Exhibit C.',
    isGenerated: true,
    order: 4,
  },
  {
    id: 'sec-contribution',
    title: 'V. Original Contribution',
    standardId: 'std-contribution',
    content: 'The applicant\'s innovative algorithms have been cited by 500+ academic papers, and their open-source code is widely used by researchers globally. This work has made significant contributions to advancing the AI field.\n\nSee Exhibit D.',
    isGenerated: false,
    order: 5,
  },
  {
    id: 'sec-conclusion',
    title: 'VI. Conclusion',
    content: 'In summary, the applicant\'s outstanding achievements in artificial intelligence fully meet the EB-1A criteria. We respectfully request USCIS to approve this petition.',
    isGenerated: false,
    order: 6,
  },
];

// Initial node positions for writing canvas
const getInitialWritingNodePositions = (): Map<string, Position> => {
  const positions = new Map<string, Position>();

  // Snippet positions (left side)
  const connectedSnippetIds = ['snip-1', 'snip-2', 'snip-3', 'snip-4', 'snip-5', 'snip-7', 'snip-9'];
  connectedSnippetIds.forEach((id, index) => {
    positions.set(id, { x: 120, y: 80 + index * 100 });
  });

  // Standard positions (right side)
  const connectedStandardIds = ['std-awards', 'std-contribution', 'std-leading', 'std-salary'];
  connectedStandardIds.forEach((id, index) => {
    positions.set(id, { x: 680, y: 120 + index * 120 });
  });

  return positions;
};

// Current project ID - can be changed to load different projects
const DEFAULT_PROJECT_ID = 'yaruo_qu';

export function AppProvider({ children }: { children: ReactNode }) {
  const [projectId, setProjectId] = useState<string>(DEFAULT_PROJECT_ID);
  const [isLoading, setIsLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);

  // Pipeline state
  const [pipelineState, setPipelineState] = useState<PipelineState>({
    stage: 'ocr_complete',
    progress: 0,
  });

  // Start with empty snippets - will be loaded from backend
  const [snippets, setSnippets] = useState<Snippet[]>([]);

  // Start with empty connections - will be populated after snippet extraction
  const [connections, setConnections] = useState<Connection[]>([]);

  // Fetch pipeline stage and snippets from backend
  useEffect(() => {
    async function loadProjectData() {
      setIsLoading(true);
      setLoadError(null);
      try {
        // Load pipeline stage
        try {
          const stageResponse = await apiClient.get<{
            stage: PipelineStage;
            can_extract: boolean;
            can_confirm: boolean;
            can_generate: boolean;
          }>(`/analysis/${projectId}/stage`);

          setPipelineState(prev => ({
            ...prev,
            stage: stageResponse.stage,
          }));
        } catch {
          // Default to ocr_complete if stage endpoint not available
          setPipelineState(prev => ({ ...prev, stage: 'ocr_complete' }));
        }

        // Try loading from unified extraction API first (has subject attribution)
        try {
          const extractionResponse = await apiClient.get<{
            project_id: string;
            total: number;
            snippets: UnifiedSnippet[];
          }>(`/extraction/${projectId}/snippets?limit=500`);

          if (extractionResponse.snippets && extractionResponse.snippets.length > 0) {
            const converted = extractionResponse.snippets.map(convertUnifiedSnippet);
            setSnippets(converted);
            setPipelineState(prev => ({ ...prev, stage: 'snippets_ready', snippetCount: converted.length }));
            console.log(`Loaded ${converted.length} unified extraction snippets from project ${projectId}`);

            // Also try to load generated arguments and sub-arguments from backend
            try {
              const argsResponse = await apiClient.get<{
                project_id: string;
                arguments: Array<{
                  id: string;
                  title: string;
                  subject: string;
                  snippet_ids: string[];
                  standard_key: string;
                  confidence: number;
                  created_at: string;
                  is_ai_generated: boolean;
                  sub_argument_ids?: string[];
                }>;
                sub_arguments: Array<{
                  id: string;
                  argument_id: string;
                  title: string;
                  purpose: string;
                  relationship: string;
                  snippet_ids: string[];
                  is_ai_generated: boolean;
                  status: string;
                  created_at: string;
                }>;
                main_subject: string | null;
                generated_at: string | null;
              }>(`/arguments/${projectId}`);

              if (argsResponse.arguments && argsResponse.arguments.length > 0) {
                const convertedArgs: Argument[] = argsResponse.arguments.map((arg) => ({
                  id: arg.id,
                  title: arg.title,
                  subject: arg.subject,
                  snippetIds: arg.snippet_ids,
                  standardKey: arg.standard_key,
                  claimType: (arg.standard_key || 'other') as ArgumentClaimType,
                  status: 'draft' as ArgumentStatus,
                  isAIGenerated: arg.is_ai_generated,
                  subArgumentIds: arg.sub_argument_ids || [],
                  createdAt: new Date(arg.created_at),
                  updatedAt: new Date(),
                }));
                setArguments(convertedArgs);
                console.log(`Loaded ${convertedArgs.length} generated arguments from backend`);
              }

              // Load sub-arguments
              if (argsResponse.sub_arguments && argsResponse.sub_arguments.length > 0) {
                const convertedSubArgs: SubArgument[] = argsResponse.sub_arguments.map((sa) => ({
                  id: sa.id,
                  argumentId: sa.argument_id,
                  title: sa.title,
                  purpose: sa.purpose,
                  relationship: sa.relationship,
                  snippetIds: sa.snippet_ids,
                  isAIGenerated: sa.is_ai_generated,
                  status: sa.status as 'draft' | 'verified',
                  createdAt: new Date(sa.created_at),
                  updatedAt: new Date(),
                }));
                setSubArguments(convertedSubArgs);
                console.log(`Loaded ${convertedSubArgs.length} sub-arguments from backend`);
              }
            } catch {
              // Arguments not available yet, that's fine
              console.log('No generated arguments found');
            }

            return; // Success, no need to try other sources
          }
        } catch {
          // Unified extraction not available, try legacy API
        }

        // Fall back to legacy analysis API
        const response = await apiClient.get<{
          project_id: string;
          total: number;
          snippets: BackendSnippet[];
        }>(`/analysis/${projectId}/snippets?limit=500`);

        if (response.snippets && response.snippets.length > 0) {
          const converted = response.snippets.map(convertBackendSnippet);
          setSnippets(converted);
          console.log(`Loaded ${converted.length} extracted snippets from project ${projectId}`);
          // NOTE: snippet→standard connections removed - classification at Argument level
        }

        // Also try to load generated arguments and sub-arguments (for legacy path)
        try {
          const argsResponse = await apiClient.get<{
            project_id: string;
            arguments: Array<{
              id: string;
              title: string;
              subject: string;
              snippet_ids: string[];
              standard_key: string;
              confidence: number;
              created_at: string;
              is_ai_generated: boolean;
              sub_argument_ids?: string[];
            }>;
            sub_arguments: Array<{
              id: string;
              argument_id: string;
              title: string;
              purpose: string;
              relationship: string;
              snippet_ids: string[];
              is_ai_generated: boolean;
              status: string;
              created_at: string;
            }>;
            main_subject: string | null;
            generated_at: string | null;
          }>(`/arguments/${projectId}`);

          if (argsResponse.arguments && argsResponse.arguments.length > 0) {
            const convertedArgs: Argument[] = argsResponse.arguments.map((arg) => ({
              id: arg.id,
              title: arg.title,
              subject: arg.subject,
              snippetIds: arg.snippet_ids,
              standardKey: arg.standard_key,
              claimType: (arg.standard_key || 'other') as ArgumentClaimType,
              status: 'draft' as ArgumentStatus,
              isAIGenerated: arg.is_ai_generated,
              subArgumentIds: arg.sub_argument_ids || [],
              createdAt: new Date(arg.created_at),
              updatedAt: new Date(),
            }));
            setArguments(convertedArgs);
            console.log(`Loaded ${convertedArgs.length} generated arguments from backend (legacy path)`);
          }

          // Load sub-arguments
          if (argsResponse.sub_arguments && argsResponse.sub_arguments.length > 0) {
            const convertedSubArgs: SubArgument[] = argsResponse.sub_arguments.map((sa) => ({
              id: sa.id,
              argumentId: sa.argument_id,
              title: sa.title,
              purpose: sa.purpose,
              relationship: sa.relationship,
              snippetIds: sa.snippet_ids,
              isAIGenerated: sa.is_ai_generated,
              status: sa.status as 'draft' | 'verified',
              createdAt: new Date(sa.created_at),
              updatedAt: new Date(),
            }));
            setSubArguments(convertedSubArgs);
            console.log(`Loaded ${convertedSubArgs.length} sub-arguments from backend (legacy path)`);
          }
        } catch {
          // Arguments not available yet, that's fine
          console.log('No generated arguments found (legacy path)');
        }

        if (!(response.snippets && response.snippets.length > 0)) {
          // Fall back to raw OCR data if no extracted snippets
          const rawResponse = await apiClient.get<{
            project_id: string;
            total: number;
            snippets: BackendSnippet[];
          }>(`/data/projects/${projectId}/snippets?limit=500`);

          if (rawResponse.snippets && rawResponse.snippets.length > 0) {
            const converted = rawResponse.snippets.map(convertBackendSnippet);
            setSnippets(converted);
            console.log(`Loaded ${converted.length} raw OCR blocks from project ${projectId}`);
          }
        }
      } catch (err) {
        console.error('Failed to load project data:', err);
        setLoadError(err instanceof Error ? err.message : 'Failed to load data');
        // Keep empty snippets on error - no mock data fallback
      } finally {
        setIsLoading(false);
      }
    }

    loadProjectData();
  }, [projectId]);

  const [viewMode, setViewModeState] = useState<ViewMode>(() => {
    const saved = localStorage.getItem(STORAGE_KEY_VIEW_MODE);
    return (saved as ViewMode) || 'line';
  });

  // LLM Provider setting
  const [llmProvider, setLlmProviderState] = useState<LLMProvider>(() => {
    const saved = localStorage.getItem(STORAGE_KEY_LLM_PROVIDER);
    return (saved as LLMProvider) || 'deepseek';
  });

  // Page navigation state
  const [currentPage, setCurrentPage] = useState<PageType>('mapping');

  const setLlmProvider = useCallback((provider: LLMProvider) => {
    setLlmProviderState(provider);
    localStorage.setItem(STORAGE_KEY_LLM_PROVIDER, provider);
  }, []);

  // Writing canvas state
  const [arguments_, setArguments] = useState<Argument[]>(() => {
    const saved = localStorage.getItem(STORAGE_KEY_ARGUMENTS);
    if (saved) {
      const parsed = JSON.parse(saved);
      return parsed.map((a: Argument) => ({ ...a, createdAt: new Date(a.createdAt) }));
    }
    return initialArguments;
  });

  const [writingEdges, setWritingEdges] = useState<WritingEdge[]>(() => {
    const saved = localStorage.getItem(STORAGE_KEY_WRITING_EDGES);
    if (saved) {
      const parsed = JSON.parse(saved);
      return parsed.map((e: WritingEdge) => ({ ...e, createdAt: new Date(e.createdAt) }));
    }
    return initialWritingEdges;
  });

  const [letterSections, setLetterSections] = useState<LetterSection[]>(() => {
    const saved = localStorage.getItem(STORAGE_KEY_LETTER_SECTIONS);
    return saved ? JSON.parse(saved) : initialLetterSections;
  });

  const [writingNodePositions, setWritingNodePositions] = useState<Map<string, Position>>(() => {
    const saved = localStorage.getItem(STORAGE_KEY_WRITING_NODE_POSITIONS);
    if (saved) {
      const parsed = JSON.parse(saved);
      return new Map(Object.entries(parsed));
    }
    return getInitialWritingNodePositions();
  });

  const [focusState, setFocusState] = useState<FocusState>({ type: 'none', id: null });
  // Selected snippet ID for PDF highlight (independent of focusState)
  const [selectedSnippetId, setSelectedSnippetId] = useState<string | null>(null);
  const [selectedDocumentId, setSelectedDocumentId] = useState<string>('');
  const [draggedSnippetId, setDraggedSnippetId] = useState<string | null>(null);
  const [snippetPositions, setSnippetPositions] = useState<Map<string, ElementPosition>>(new Map());
  const [pdfBboxPositions, setPdfBboxPositions] = useState<Map<string, ElementPosition>>(new Map());
  const [snippetPanelBounds, setSnippetPanelBounds] = useState<PanelBounds | null>(null);

  // Argument Assembly state (NEW)
  const [draggedArgumentId, setDraggedArgumentId] = useState<string | null>(null);
  const [argumentPositions, setArgumentPositions] = useState<Map<string, ElementPosition>>(new Map());
  const [subArgumentPositions, setSubArgumentPositions] = useState<Map<string, ElementPosition>>(new Map());
  const [hoveredSnippetId, setHoveredSnippetId] = useState<string | null>(null);
  const [argumentMappings, setArgumentMappings] = useState<WritingEdge[]>([]);

  // AI Argument Generation state
  const [isGeneratingArguments, setIsGeneratingArguments] = useState(false);
  const [generatedMainSubject, setGeneratedMainSubject] = useState<string | null>(null);

  // Unified Extraction state (NEW)
  const [mergeSuggestions, setMergeSuggestions] = useState<MergeSuggestion[]>([]);
  const [isExtracting, setIsExtracting] = useState(false);
  const [isMerging, setIsMerging] = useState(false);
  const [extractionProgress, setExtractionProgress] = useState<{ current: number; total: number; currentExhibit?: string } | null>(null);

  // Argument view mode (list vs graph)
  const [argumentViewMode, setArgumentViewModeState] = useState<ArgumentViewMode>(() => {
    const saved = localStorage.getItem(STORAGE_KEY_ARGUMENT_VIEW_MODE);
    return (saved as ArgumentViewMode) || 'list';
  });

  // Argument graph node positions (for graph view)
  const [argumentGraphPositions, setArgumentGraphPositions] = useState<Map<string, Position>>(() => {
    const saved = localStorage.getItem(STORAGE_KEY_ARGUMENT_GRAPH_POSITIONS);
    if (saved) {
      const parsed = JSON.parse(saved);
      return new Map(Object.entries(parsed));
    }
    return new Map();
  });

  // SubArguments state (次级子论点)
  const [subArguments, setSubArguments] = useState<SubArgument[]>(() => {
    const saved = localStorage.getItem(STORAGE_KEY_SUB_ARGUMENTS);
    if (saved) {
      const parsed = JSON.parse(saved);
      return parsed.map((sa: SubArgument) => ({
        ...sa,
        createdAt: new Date(sa.createdAt),
        updatedAt: new Date(sa.updatedAt),
      }));
    }
    return [];
  });

  // Selection state for creating snippets
  const [selectionState, setSelectionState] = useState<SelectionState>({
    isSelecting: false,
    startPoint: null,
    endPoint: null,
    pageNumber: null,
    documentId: null,
  });

  // Persist to localStorage
  useEffect(() => {
    localStorage.setItem(STORAGE_KEY_SNIPPETS, JSON.stringify(snippets));
  }, [snippets]);

  useEffect(() => {
    localStorage.setItem(STORAGE_KEY_CONNECTIONS, JSON.stringify(connections));
  }, [connections]);

  useEffect(() => {
    localStorage.setItem(STORAGE_KEY_VIEW_MODE, viewMode);
  }, [viewMode]);

  // Persist writing canvas state
  useEffect(() => {
    localStorage.setItem(STORAGE_KEY_ARGUMENTS, JSON.stringify(arguments_));
  }, [arguments_]);

  useEffect(() => {
    localStorage.setItem(STORAGE_KEY_WRITING_EDGES, JSON.stringify(writingEdges));
  }, [writingEdges]);

  useEffect(() => {
    localStorage.setItem(STORAGE_KEY_LETTER_SECTIONS, JSON.stringify(letterSections));
  }, [letterSections]);

  useEffect(() => {
    const obj: Record<string, Position> = {};
    writingNodePositions.forEach((v, k) => { obj[k] = v; });
    localStorage.setItem(STORAGE_KEY_WRITING_NODE_POSITIONS, JSON.stringify(obj));
  }, [writingNodePositions]);

  // Persist argument view mode
  useEffect(() => {
    localStorage.setItem(STORAGE_KEY_ARGUMENT_VIEW_MODE, argumentViewMode);
  }, [argumentViewMode]);

  // Persist argument graph positions
  useEffect(() => {
    const obj: Record<string, Position> = {};
    argumentGraphPositions.forEach((v, k) => { obj[k] = v; });
    localStorage.setItem(STORAGE_KEY_ARGUMENT_GRAPH_POSITIONS, JSON.stringify(obj));
  }, [argumentGraphPositions]);

  // Persist sub-arguments
  useEffect(() => {
    localStorage.setItem(STORAGE_KEY_SUB_ARGUMENTS, JSON.stringify(subArguments));
  }, [subArguments]);

  const setViewMode = useCallback((mode: ViewMode) => {
    setViewModeState(mode);
  }, []);

  // Argument view mode setter
  const setArgumentViewMode = useCallback((mode: ArgumentViewMode) => {
    setArgumentViewModeState(mode);
  }, []);

  // Update argument graph position
  const updateArgumentGraphPosition = useCallback((id: string, position: Position) => {
    setArgumentGraphPositions(prev => {
      const newMap = new Map(prev);
      newMap.set(id, position);
      return newMap;
    });
  }, []);

  // Clear all argument graph positions (for auto-arrange)
  const clearArgumentGraphPositions = useCallback(() => {
    setArgumentGraphPositions(new Map());
  }, []);

  const clearFocus = useCallback(() => {
    setFocusState({ type: 'none', id: null });
  }, []);

  const addConnection = useCallback((snippetId: string, standardId: string, isConfirmed: boolean) => {
    // Check if connection already exists
    const exists = connections.some(
      conn => conn.snippetId === snippetId && conn.standardId === standardId
    );
    if (exists) {
      // If it exists and we want to confirm, just confirm it
      if (isConfirmed) {
        setConnections(prev => prev.map(conn =>
          conn.snippetId === snippetId && conn.standardId === standardId
            ? { ...conn, isConfirmed: true }
            : conn
        ));
      }
      return;
    }

    const newConnection: Connection = {
      id: `conn-${Date.now()}`,
      snippetId,
      standardId,
      isConfirmed,
      createdAt: new Date(),
    };
    setConnections(prev => [...prev, newConnection]);
  }, [connections]);

  const removeConnection = useCallback((connectionId: string) => {
    setConnections(prev => prev.filter(conn => conn.id !== connectionId));
  }, []);

  const confirmConnection = useCallback((connectionId: string) => {
    setConnections(prev => prev.map(conn =>
      conn.id === connectionId ? { ...conn, isConfirmed: true } : conn
    ));
  }, []);

  const updateSnippetPosition = useCallback((id: string, position: ElementPosition) => {
    setSnippetPositions(prev => {
      const newMap = new Map(prev);
      newMap.set(id, position);
      return newMap;
    });
  }, []);

  const updatePdfBboxPosition = useCallback((id: string, position: ElementPosition) => {
    setPdfBboxPositions(prev => {
      const newMap = new Map(prev);
      newMap.set(id, position);
      return newMap;
    });
  }, []);

  // Snippet management
  const addSnippet = useCallback((snippetData: Omit<Snippet, 'id'>) => {
    const newSnippet: Snippet = {
      ...snippetData,
      id: `snippet-${Date.now()}-${Math.random().toString(36).substr(2, 9)}`,
    };
    setSnippets(prev => [...prev, newSnippet]);
  }, []);

  const removeSnippet = useCallback((snippetId: string) => {
    setSnippets(prev => prev.filter(s => s.id !== snippetId));
    // Also remove all connections involving this snippet
    setConnections(prev => prev.filter(c => c.snippetId !== snippetId));
  }, []);

  // Selection methods for creating snippets
  const startSelection = useCallback((documentId: string, pageNumber: number, point: { x: number; y: number }) => {
    setSelectionState({
      isSelecting: true,
      startPoint: point,
      endPoint: point,
      pageNumber,
      documentId,
    });
  }, []);

  const updateSelection = useCallback((point: { x: number; y: number }) => {
    setSelectionState(prev => ({
      ...prev,
      endPoint: point,
    }));
  }, []);

  const endSelection = useCallback(() => {
    if (!selectionState.isSelecting || !selectionState.startPoint || !selectionState.endPoint ||
        !selectionState.documentId || selectionState.pageNumber === null) {
      return null;
    }

    const { startPoint, endPoint, pageNumber, documentId } = selectionState;

    // Calculate bounding box (normalize so x,y is always top-left)
    const boundingBox: BoundingBox = {
      x: Math.min(startPoint.x, endPoint.x),
      y: Math.min(startPoint.y, endPoint.y),
      width: Math.abs(endPoint.x - startPoint.x),
      height: Math.abs(endPoint.y - startPoint.y),
      page: pageNumber,
    };

    // Reset selection state
    setSelectionState({
      isSelecting: false,
      startPoint: null,
      endPoint: null,
      pageNumber: null,
      documentId: null,
    });

    // Only return if the selection is meaningful (not just a click)
    if (boundingBox.width < 10 || boundingBox.height < 10) {
      return null;
    }

    return { boundingBox, documentId };
  }, [selectionState]);

  const cancelSelection = useCallback(() => {
    setSelectionState({
      isSelecting: false,
      startPoint: null,
      endPoint: null,
      pageNumber: null,
      documentId: null,
    });
  }, []);

  // ============================================
  // Writing Canvas Methods
  // ============================================

  // Argument management
  const addArgument = useCallback((argumentData: Omit<Argument, 'id' | 'createdAt' | 'updatedAt'>) => {
    const newArgument: Argument = {
      ...argumentData,
      id: `arg-${Date.now()}-${Math.random().toString(36).substr(2, 9)}`,
      createdAt: new Date(),
      updatedAt: new Date(),
    };
    setArguments(prev => [...prev, newArgument]);
  }, []);

  const updateArgument = useCallback((id: string, updates: Partial<Omit<Argument, 'id' | 'createdAt'>>) => {
    setArguments(prev => prev.map(arg =>
      arg.id === id ? { ...arg, ...updates, updatedAt: new Date() } : arg
    ));
  }, []);

  const removeArgument = useCallback((id: string) => {
    setArguments(prev => prev.filter(arg => arg.id !== id));
    // Also remove all edges connected to this argument
    setWritingEdges(prev => prev.filter(e => e.source !== id && e.target !== id));
    // Also remove argument mappings
    setArgumentMappings(prev => prev.filter(e => e.source !== id));
  }, []);

  const updateArgumentPosition = useCallback((id: string, position: Position) => {
    setArguments(prev => prev.map(arg =>
      arg.id === id ? { ...arg, position, updatedAt: new Date() } : arg
    ));
  }, []);

  // Snippet to Argument operations (NEW)
  const addSnippetToArgument = useCallback((argumentId: string, snippetId: string) => {
    setArguments(prev => prev.map(arg => {
      if (arg.id === argumentId) {
        // Avoid duplicates
        if (arg.snippetIds.includes(snippetId)) return arg;
        return {
          ...arg,
          snippetIds: [...arg.snippetIds, snippetId],
          updatedAt: new Date(),
        };
      }
      return arg;
    }));
  }, []);

  const removeSnippetFromArgument = useCallback((argumentId: string, snippetId: string) => {
    setArguments(prev => prev.map(arg => {
      if (arg.id === argumentId) {
        return {
          ...arg,
          snippetIds: arg.snippetIds.filter(id => id !== snippetId),
          updatedAt: new Date(),
        };
      }
      return arg;
    }));
  }, []);

  // ============================================
  // SubArgument Management (次级子论点)
  // ============================================

  const addSubArgument = useCallback((subArgumentData: Omit<SubArgument, 'id' | 'createdAt' | 'updatedAt'>) => {
    const newSubArgument: SubArgument = {
      ...subArgumentData,
      id: `subarg-${Date.now()}-${Math.random().toString(36).substr(2, 9)}`,
      createdAt: new Date(),
      updatedAt: new Date(),
    };
    setSubArguments(prev => [...prev, newSubArgument]);

    // Also update the parent argument's subArgumentIds
    setArguments(prev => prev.map(arg => {
      if (arg.id === subArgumentData.argumentId) {
        const existingSubArgIds = arg.subArgumentIds || [];
        return {
          ...arg,
          subArgumentIds: [...existingSubArgIds, newSubArgument.id],
          updatedAt: new Date(),
        };
      }
      return arg;
    }));
  }, []);

  const updateSubArgument = useCallback((id: string, updates: Partial<Omit<SubArgument, 'id' | 'createdAt'>>) => {
    setSubArguments(prev => prev.map(sa =>
      sa.id === id ? { ...sa, ...updates, updatedAt: new Date() } : sa
    ));
  }, []);

  const removeSubArgument = useCallback((id: string) => {
    const subArg = subArguments.find(sa => sa.id === id);
    setSubArguments(prev => prev.filter(sa => sa.id !== id));

    // Also update the parent argument's subArgumentIds
    if (subArg) {
      setArguments(prev => prev.map(arg => {
        if (arg.id === subArg.argumentId) {
          return {
            ...arg,
            subArgumentIds: (arg.subArgumentIds || []).filter(saId => saId !== id),
            updatedAt: new Date(),
          };
        }
        return arg;
      }));
    }
  }, [subArguments]);

  // Argument → Standard mapping (NEW - replaces snippet → standard)
  const addArgumentMapping = useCallback((argumentId: string, standardKey: string) => {
    // Check if mapping already exists
    const exists = argumentMappings.some(
      e => e.source === argumentId && e.target === standardKey
    );
    if (exists) return;

    const newMapping: WritingEdge = {
      id: `am-${Date.now()}-${Math.random().toString(36).substr(2, 9)}`,
      source: argumentId,
      target: standardKey,
      type: 'argument-to-standard',
      isConfirmed: true,  // User dragged = confirmed
      createdAt: new Date(),
    };
    setArgumentMappings(prev => [...prev, newMapping]);

    // Also update the argument's standardKey
    setArguments(prev => prev.map(arg =>
      arg.id === argumentId ? { ...arg, standardKey, status: 'mapped' as const, updatedAt: new Date() } : arg
    ));
  }, [argumentMappings]);

  const removeArgumentMapping = useCallback((edgeId: string) => {
    const mapping = argumentMappings.find(e => e.id === edgeId);
    setArgumentMappings(prev => prev.filter(e => e.id !== edgeId));

    // Also clear the argument's standardKey
    if (mapping) {
      setArguments(prev => prev.map(arg =>
        arg.id === mapping.source ? { ...arg, standardKey: undefined, status: 'verified' as const, updatedAt: new Date() } : arg
      ));
    }
  }, [argumentMappings]);

  // Argument position for connection lines (NEW)
  const updateArgumentPosition2 = useCallback((id: string, position: ElementPosition) => {
    setArgumentPositions(prev => {
      const newMap = new Map(prev);
      newMap.set(id, position);
      return newMap;
    });
  }, []);

  const updateSubArgumentPosition = useCallback((id: string, position: ElementPosition) => {
    setSubArgumentPositions(prev => {
      const newMap = new Map(prev);
      newMap.set(id, position);
      return newMap;
    });
  }, []);

  // Writing edge management
  const addWritingEdge = useCallback((source: string, target: string, type: WritingEdge['type']) => {
    // Check if edge already exists
    const exists = writingEdges.some(e => e.source === source && e.target === target);
    if (exists) return;

    const newEdge: WritingEdge = {
      id: `we-${Date.now()}-${Math.random().toString(36).substr(2, 9)}`,
      source,
      target,
      type,
      isConfirmed: false,
      createdAt: new Date(),
    };
    setWritingEdges(prev => [...prev, newEdge]);
  }, [writingEdges]);

  const removeWritingEdge = useCallback((id: string) => {
    setWritingEdges(prev => prev.filter(e => e.id !== id));
  }, []);

  const confirmWritingEdge = useCallback((id: string) => {
    setWritingEdges(prev => prev.map(e =>
      e.id === id ? { ...e, isConfirmed: true } : e
    ));
  }, []);

  // Letter section management
  const updateLetterSection = useCallback((id: string, content: string) => {
    setLetterSections(prev => prev.map(s =>
      s.id === id ? { ...s, content } : s
    ));
  }, []);

  // Writing node position management
  const updateWritingNodePosition = useCallback((id: string, position: Position) => {
    setWritingNodePositions(prev => {
      const newMap = new Map(prev);
      newMap.set(id, position);
      return newMap;
    });
  }, []);

  const getConnectionsForSnippet = useCallback((snippetId: string) => {
    return connections.filter(conn => conn.snippetId === snippetId);
  }, [connections]);

  const getConnectionsForStandard = useCallback((standardId: string) => {
    return connections.filter(conn => conn.standardId === standardId);
  }, [connections]);

  const isElementHighlighted = useCallback((elementType: 'snippet' | 'standard', elementId: string): boolean => {
    if (focusState.type === 'none') return true;

    if (focusState.type === 'snippet' && focusState.id) {
      if (elementType === 'snippet') {
        return elementId === focusState.id;
      }
      // For standards, check if connected to the focused snippet via arguments
      return arguments_.some(arg => {
        if (!arg.snippetIds?.includes(focusState.id!)) return false;
        // Check AI-generated standardKey mapping
        if (arg.standardKey && STANDARD_KEY_TO_ID[arg.standardKey] === elementId) return true;
        // Check manual mapping
        return argumentMappings.some(m => m.source === arg.id && m.target === elementId);
      });
    }

    if (focusState.type === 'standard' && focusState.id) {
      if (elementType === 'standard') {
        return elementId === focusState.id;
      }
      // For snippets, check if connected to the focused standard via arguments
      const focusedStandardId = focusState.id;
      return arguments_.some(arg => {
        if (!arg.snippetIds?.includes(elementId)) return false;
        // Check AI-generated standardKey mapping
        if (arg.standardKey && STANDARD_KEY_TO_ID[arg.standardKey] === focusedStandardId) return true;
        // Check manual mapping
        return argumentMappings.some(m => m.source === arg.id && m.target === focusedStandardId);
      });
    }

    if (focusState.type === 'argument' && focusState.id) {
      if (elementType === 'snippet') {
        // Check if snippet belongs to the focused argument
        const focusedArg = arguments_.find(arg => arg.id === focusState.id);
        return focusedArg?.snippetIds?.includes(elementId) || false;
      }
      if (elementType === 'standard') {
        // Check if standard is mapped to the focused argument
        const focusedArg = arguments_.find(arg => arg.id === focusState.id);
        if (!focusedArg) return false;
        // Check AI-generated standardKey mapping
        if (focusedArg.standardKey && STANDARD_KEY_TO_ID[focusedArg.standardKey] === elementId) return true;
        // Check manual mapping
        return argumentMappings.some(m => m.source === focusState.id && m.target === elementId);
      }
    }

    if (focusState.type === 'document' && focusState.id) {
      if (elementType === 'snippet') {
        const snip = snippets.find(s => s.id === elementId);
        return snip?.documentId === focusState.id;
      }
      // For standards, check if any connected snippets are from the focused document
      return connections.some(conn => {
        if (conn.standardId !== elementId) return false;
        const snip = snippets.find(s => s.id === conn.snippetId);
        return snip?.documentId === focusState.id;
      });
    }

    return true;
  }, [focusState, connections, snippets, arguments_, argumentMappings]);

  // ============================================
  // Pipeline Methods
  // ============================================

  const extractSnippets = useCallback(async () => {
    setPipelineState(prev => ({ ...prev, stage: 'extracting', progress: 0 }));
    try {
      const response = await apiClient.post<{
        success: boolean;
        snippet_count: number;
        by_standard: Record<string, number>;
        message: string;
      }>(`/analysis/extract/${projectId}`, { use_llm: false });

      if (response.success) {
        setPipelineState(prev => ({
          ...prev,
          stage: 'snippets_ready',
          progress: 100,
          snippetCount: response.snippet_count,
        }));

        // Reload snippets
        const snippetsResponse = await apiClient.get<{
          snippets: BackendSnippet[];
        }>(`/analysis/${projectId}/snippets?limit=500`);

        if (snippetsResponse.snippets) {
          const converted = snippetsResponse.snippets.map(convertBackendSnippet);
          setSnippets(converted);
        }
      }
    } catch (err) {
      setPipelineState(prev => ({
        ...prev,
        stage: 'ocr_complete',
        error: err instanceof Error ? err.message : 'Extraction failed',
      }));
    }
  }, [projectId]);

  const confirmAllMappings = useCallback(async () => {
    setPipelineState(prev => ({ ...prev, stage: 'confirming' }));
    try {
      const response = await apiClient.post<{
        success: boolean;
        confirmed_count: number;
      }>(`/analysis/${projectId}/snippets/confirm-all`, {});

      if (response.success) {
        setPipelineState(prev => ({
          ...prev,
          stage: 'mapping_confirmed',
          confirmedMappings: response.confirmed_count,
        }));
      }
    } catch (err) {
      setPipelineState(prev => ({
        ...prev,
        stage: 'snippets_ready',
        error: err instanceof Error ? err.message : 'Confirmation failed',
      }));
    }
  }, [projectId]);

  const generatePetition = useCallback(async () => {
    setPipelineState(prev => ({ ...prev, stage: 'generating', progress: 0 }));
    try {
      // Get all available sections (EB-1A standards that have snippets)
      const standardsToGenerate = [
        'awards',
        'membership',
        'published_material',
        'judging',
        'original_contribution',
        'scholarly_articles',
        'leading_role',
        'exhibitions'
      ];

      const generatedSections: LetterSection[] = [];

      for (let i = 0; i < standardsToGenerate.length; i++) {
        const section = standardsToGenerate[i];
        setPipelineState(prev => ({
          ...prev,
          progress: Math.round((i / standardsToGenerate.length) * 100),
        }));

        try {
          const response = await apiClient.post<{
            success: boolean;
            section: string;
            paragraph_text: string;
            sentences: Array<{ text: string; snippet_ids: string[] }>;
            snippet_count: number;
          }>(`/write/v2/${projectId}/${section}`, {});

          if (response.success && response.paragraph_text) {
            generatedSections.push({
              id: `section-${section}`,
              title: section.split('_').map(w => w.charAt(0).toUpperCase() + w.slice(1)).join(' '),
              standardId: section,
              content: response.paragraph_text,
              isGenerated: true,
              order: i,
              sentences: response.sentences,
            });
          }
        } catch (sectionErr) {
          // Skip sections that fail (may not have snippets)
          console.log(`Skipped section ${section}:`, sectionErr);
        }
      }

      // Update letter sections state
      if (generatedSections.length > 0) {
        setLetterSections(generatedSections);
      }

      setPipelineState(prev => ({
        ...prev,
        stage: 'petition_ready',
        progress: 100,
      }));
    } catch (err) {
      setPipelineState(prev => ({
        ...prev,
        stage: 'mapping_confirmed',
        error: err instanceof Error ? err.message : 'Generation failed',
      }));
    }
  }, [projectId]);

  // Computed properties for pipeline state
  const canExtract = pipelineState.stage === 'ocr_complete';
  const canConfirm = pipelineState.stage === 'snippets_ready';
  const canGenerate = pipelineState.stage === 'mapping_confirmed';

  // AI Argument Generation - uses new legal pipeline with sub-arguments
  const generateArguments = useCallback(async (forceReanalyze: boolean = false, applicantName?: string) => {
    setIsGeneratingArguments(true);
    try {
      // Step 1: Run the generation pipeline (creates legal_arguments.json with arguments + sub_arguments)
      await apiClient.post<{
        success: boolean;
      }>(`/arguments/${projectId}/generate`, {
        force_reanalyze: forceReanalyze,
        applicant_name: applicantName,
        provider: llmProvider  // Pass LLM provider selection
      });

      // Step 2: Fetch generated arguments and sub-arguments from main endpoint
      const response = await apiClient.get<{
        project_id: string;
        arguments: Array<{
          id: string;
          title: string;
          subject: string;
          snippet_ids: string[];
          standard_key: string;
          confidence: number;
          created_at: string;
          is_ai_generated: boolean;
          sub_argument_ids?: string[];
          // Extended lawyer-style fields
          exhibits?: string[];
          layers?: {
            claim: Array<{ text: string; exhibit_id: string; purpose: string; snippet_id: string }>;
            proof: Array<{ text: string; exhibit_id: string; purpose: string; snippet_id: string }>;
            significance: Array<{ text: string; exhibit_id: string; purpose: string; snippet_id: string }>;
            context: Array<{ text: string; exhibit_id: string; purpose: string; snippet_id: string }>;
          };
          conclusion?: string;
          completeness?: {
            has_claim: boolean;
            has_proof: boolean;
            has_significance: boolean;
            has_context: boolean;
            score: number;
          };
        }>;
        sub_arguments: Array<{
          id: string;
          argument_id: string;
          title: string;
          purpose: string;
          relationship: string;
          snippet_ids: string[];
          is_ai_generated: boolean;
          status: string;
          created_at: string;
        }>;
        main_subject: string | null;
        generated_at: string;
        stats: Record<string, unknown>;
      }>(`/arguments/${projectId}`);

      setGeneratedMainSubject(response.main_subject);

      // Convert backend arguments to frontend format
      const convertedArguments: Argument[] = response.arguments.map((arg) => ({
        id: arg.id,
        title: arg.title,
        subject: arg.subject,
        snippetIds: arg.snippet_ids,
        standardKey: arg.standard_key,
        claimType: (arg.standard_key || 'other') as ArgumentClaimType,
        status: 'draft' as ArgumentStatus,
        isAIGenerated: arg.is_ai_generated,
        subArgumentIds: arg.sub_argument_ids || [],
        createdAt: new Date(arg.created_at),
        updatedAt: new Date(),
        // Extended fields for lawyer-style display
        exhibits: arg.exhibits,
        layers: arg.layers,
        conclusion: arg.conclusion,
        completeness: arg.completeness,
      }));

      setArguments(convertedArguments);
      console.log(`Generated ${convertedArguments.length} arguments for ${response.main_subject}`);

      // Convert and set sub-arguments
      if (response.sub_arguments && response.sub_arguments.length > 0) {
        const convertedSubArgs: SubArgument[] = response.sub_arguments.map((sa) => ({
          id: sa.id,
          argumentId: sa.argument_id,
          title: sa.title,
          purpose: sa.purpose,
          relationship: sa.relationship,
          snippetIds: sa.snippet_ids,
          isAIGenerated: sa.is_ai_generated,
          status: sa.status as 'draft' | 'verified',
          createdAt: new Date(sa.created_at),
          updatedAt: new Date(),
        }));
        setSubArguments(convertedSubArgs);
        console.log(`Generated ${convertedSubArgs.length} sub-arguments`);
      }
    } catch (err) {
      console.error('Failed to generate arguments:', err);
      throw err;
    } finally {
      setIsGeneratingArguments(false);
    }
  }, [projectId, llmProvider]);

  // Reload snippets from backend
  const reloadSnippets = useCallback(async () => {
    try {
      const response = await apiClient.get<{
        snippets: BackendSnippet[];
      }>(`/analysis/${projectId}/snippets?limit=500`);

      if (response.snippets && response.snippets.length > 0) {
        const converted = response.snippets.map(convertBackendSnippet);
        setSnippets(converted);
        console.log(`Reloaded ${converted.length} extracted snippets`);
        // NOTE: snippet→standard connections removed - classification at Argument level
      }
    } catch (err) {
      console.error('Failed to reload snippets:', err);
    }
  }, [projectId]);

  // ============================================
  // Unified Extraction Methods (NEW)
  // ============================================

  // Unified extraction - extract snippets + entities + relations in one pass
  const unifiedExtract = useCallback(async (applicantName: string) => {
    setIsExtracting(true);
    setExtractionProgress({ current: 0, total: 0 });
    setPipelineState(prev => ({ ...prev, stage: 'extracting', progress: 0 }));

    try {
      const response = await apiClient.post<{
        success: boolean;
        exhibits_processed: number;
        total_snippets: number;
        total_entities: number;
        total_relations: number;
        error?: string;
      }>(`/extraction/${projectId}/extract`, {
        applicant_name: applicantName,
        provider: llmProvider  // Pass LLM provider selection
      });

      if (response.success) {
        setPipelineState(prev => ({
          ...prev,
          stage: 'snippets_ready',
          progress: 100,
          snippetCount: response.total_snippets,
        }));

        // Reload snippets from unified extraction
        const snippetsResponse = await apiClient.get<{
          project_id: string;
          total: number;
          snippets: UnifiedSnippet[];
        }>(`/extraction/${projectId}/snippets?limit=500`);

        if (snippetsResponse.snippets) {
          const converted = snippetsResponse.snippets.map(convertUnifiedSnippet);
          setSnippets(converted);
          console.log(`Loaded ${converted.length} unified extraction snippets`);
        }
      } else {
        throw new Error(response.error || 'Extraction failed');
      }
    } catch (err) {
      setPipelineState(prev => ({
        ...prev,
        stage: 'ocr_complete',
        error: err instanceof Error ? err.message : 'Extraction failed',
      }));
      throw err;
    } finally {
      setIsExtracting(false);
      setExtractionProgress(null);
    }
  }, [projectId, llmProvider]);

  // Generate merge suggestions - returns suggestions for immediate use
  const generateMergeSuggestions = useCallback(async (applicantName: string): Promise<MergeSuggestion[]> => {
    setIsMerging(true);
    try {
      const response = await apiClient.post<{
        success: boolean;
        suggestion_count: number;
        suggestions: MergeSuggestion[];
      }>(`/extraction/${projectId}/merge-suggestions/generate`, {
        applicant_name: applicantName,
        provider: llmProvider  // Pass LLM provider selection
      });

      if (response.success) {
        setMergeSuggestions(response.suggestions);
        console.log(`Generated ${response.suggestion_count} merge suggestions`);
        return response.suggestions;
      }
      return [];
    } catch (err) {
      console.error('Failed to generate merge suggestions:', err);
      throw err;
    } finally {
      setIsMerging(false);
    }
  }, [projectId, llmProvider]);

  // Load existing merge suggestions
  const loadMergeSuggestions = useCallback(async () => {
    try {
      const response = await apiClient.get<{
        project_id: string;
        suggestions: MergeSuggestion[];
        status: { pending: number; accepted: number; rejected: number; applied: number };
      }>(`/extraction/${projectId}/merge-suggestions`);

      setMergeSuggestions(response.suggestions);
    } catch (err) {
      console.error('Failed to load merge suggestions:', err);
    }
  }, [projectId]);

  // Confirm/reject merge suggestions
  const confirmMerges = useCallback(async (confirmations: Array<{suggestion_id: string; status: string}>) => {
    try {
      const response = await apiClient.post<{
        success: boolean;
        updated: number;
      }>(`/extraction/${projectId}/merges/confirm`, confirmations);

      if (response.success) {
        // Reload suggestions to get updated statuses
        await loadMergeSuggestions();
        console.log(`Updated ${response.updated} merge confirmations`);
      }
    } catch (err) {
      console.error('Failed to confirm merges:', err);
      throw err;
    }
  }, [projectId, loadMergeSuggestions]);

  // Apply confirmed merges
  const applyMerges = useCallback(async () => {
    setIsMerging(true);
    try {
      const response = await apiClient.post<{
        success: boolean;
        applied_count: number;
        updated_snippets: number;
        updated_relations: number;
        error?: string;
      }>(`/extraction/${projectId}/merges/apply`, {});

      if (response.success) {
        console.log(`Applied ${response.applied_count} merges, updated ${response.updated_snippets} snippets`);

        // Reload snippets with updated subject names
        const snippetsResponse = await apiClient.get<{
          project_id: string;
          total: number;
          snippets: UnifiedSnippet[];
        }>(`/extraction/${projectId}/snippets?limit=500`);

        if (snippetsResponse.snippets) {
          const converted = snippetsResponse.snippets.map(convertUnifiedSnippet);
          setSnippets(converted);
        }

        // Clear suggestions
        setMergeSuggestions([]);
      } else {
        throw new Error(response.error || 'Apply merges failed');
      }
    } catch (err) {
      console.error('Failed to apply merges:', err);
      throw err;
    } finally {
      setIsMerging(false);
    }
  }, [projectId]);

  const value: AppContextType = {
    projectId,
    setProjectId,
    isLoading,
    loadError,
    // AI Argument Generation
    isGeneratingArguments,
    generateArguments,
    generatedMainSubject,
    connections,
    allSnippets: snippets,
    focusState,
    setFocusState,
    clearFocus,
    selectedSnippetId,
    setSelectedSnippetId,
    selectedDocumentId,
    setSelectedDocumentId,
    addConnection,
    removeConnection,
    confirmConnection,
    draggedSnippetId,
    setDraggedSnippetId,
    snippetPositions,
    pdfBboxPositions,
    updateSnippetPosition,
    updatePdfBboxPosition,
    snippetPanelBounds,
    setSnippetPanelBounds,
    viewMode,
    setViewMode,
    // Argument view mode (list vs graph)
    argumentViewMode,
    setArgumentViewMode,
    // Argument graph node positions
    argumentGraphPositions,
    updateArgumentGraphPosition,
    clearArgumentGraphPositions,
    addSnippet,
    removeSnippet,
    selectionState,
    setSelectionState,
    startSelection,
    updateSelection,
    endSelection,
    cancelSelection,
    getConnectionsForSnippet,
    getConnectionsForStandard,
    isElementHighlighted,
    // Argument Assembly state (NEW)
    arguments: arguments_,
    addArgument,
    updateArgument,
    removeArgument,
    updateArgumentPosition,
    addSnippetToArgument,
    removeSnippetFromArgument,
    argumentMappings,
    addArgumentMapping,
    removeArgumentMapping,
    draggedArgumentId,
    setDraggedArgumentId,
    argumentPositions,
    updateArgumentPosition2,
    subArgumentPositions,
    updateSubArgumentPosition,
    hoveredSnippetId,
    setHoveredSnippetId,
    // SubArgument state (次级子论点)
    subArguments,
    addSubArgument,
    updateSubArgument,
    removeSubArgument,
    // Writing canvas state (kept for step 2)
    writingEdges,
    addWritingEdge,
    removeWritingEdge,
    confirmWritingEdge,
    letterSections,
    updateLetterSection,
    writingNodePositions,
    updateWritingNodePosition,
    // Pipeline state
    pipelineState,
    extractSnippets,
    confirmAllMappings,
    generatePetition,
    reloadSnippets,
    canExtract,
    canConfirm,
    canGenerate,
    // Unified Extraction state (NEW)
    unifiedExtract,
    generateMergeSuggestions,
    confirmMerges,
    applyMerges,
    mergeSuggestions,
    loadMergeSuggestions,
    isExtracting,
    isMerging,
    extractionProgress,
    // LLM Provider
    llmProvider,
    setLlmProvider,
    // Page Navigation
    currentPage,
    setCurrentPage,
  };

  return <AppContext.Provider value={value}>{children}</AppContext.Provider>;
}

export function useApp() {
  const context = useContext(AppContext);
  if (context === undefined) {
    throw new Error('useApp must be used within an AppProvider');
  }
  return context;
}
