import { createContext, useContext, useState, useCallback, useMemo, type ReactNode } from 'react';
import type { WritingEdge, LetterSection, Position, Snippet, Argument, SubArgument, PipelineState, MergeSuggestion } from '../types';
import { apiClient } from '../services/api';

// ============================================
// WritingContext
// Provides: writing canvas state, letter sections, pipeline operations
// ============================================

// Default color for unassigned snippets
const DEFAULT_SNIPPET_COLOR = '#94a3b8';  // slate-400

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
  snippet_id: string;
  block_id: string;
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
    materialType: 'other',
    color: DEFAULT_SNIPPET_COLOR,
    exhibitId: bs.exhibit_id,
    page: bs.page,
  };
}

function convertUnifiedSnippet(us: UnifiedSnippet): Snippet {
  return {
    id: us.snippet_id,
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
    subject: us.subject,
    subjectRole: us.subject_role,
    isApplicantAchievement: us.is_applicant_achievement,
    evidenceType: us.evidence_type,
  };
}

export interface WritingContextType {
  writingEdges: WritingEdge[];
  setWritingEdges: React.Dispatch<React.SetStateAction<WritingEdge[]>>;
  addWritingEdge: (source: string, target: string, type: WritingEdge['type']) => void;
  removeWritingEdge: (id: string) => void;
  confirmWritingEdge: (id: string) => void;
  letterSections: LetterSection[];
  setLetterSections: React.Dispatch<React.SetStateAction<LetterSection[]>>;
  updateLetterSection: (id: string, content: string) => void;
  writingNodePositions: Map<string, Position>;
  updateWritingNodePosition: (id: string, position: Position) => void;
  // Pipeline operations take projectId & llmProvider as parameters
  extractSnippets: (projectId: string, setSnippets: React.Dispatch<React.SetStateAction<Snippet[]>>, setPipelineState: React.Dispatch<React.SetStateAction<PipelineState>>) => Promise<void>;
  confirmAllMappings: (projectId: string, setPipelineState: React.Dispatch<React.SetStateAction<PipelineState>>) => Promise<void>;
  generatePetition: (projectId: string, llmProvider: string, setPipelineState: React.Dispatch<React.SetStateAction<PipelineState>>) => Promise<void>;
  reloadSnippets: (projectId: string, setSnippets: React.Dispatch<React.SetStateAction<Snippet[]>>) => Promise<void>;
  // Unified extraction
  unifiedExtract: (projectId: string, llmProvider: string, applicantName: string, setSnippets: React.Dispatch<React.SetStateAction<Snippet[]>>, setPipelineState: React.Dispatch<React.SetStateAction<PipelineState>>) => Promise<void>;
  generateMergeSuggestions: (projectId: string, llmProvider: string, applicantName: string) => Promise<MergeSuggestion[]>;
  confirmMerges: (projectId: string, confirmations: Array<{suggestion_id: string; status: string}>) => Promise<void>;
  applyMerges: (projectId: string, setSnippets: React.Dispatch<React.SetStateAction<Snippet[]>>) => Promise<void>;
  mergeSuggestions: MergeSuggestion[];
  loadMergeSuggestions: (projectId: string) => Promise<void>;
  isExtracting: boolean;
  isMerging: boolean;
  extractionProgress: { current: number; total: number; currentExhibit?: string } | null;
  // Regenerate sub-argument (needs cross-context data)
  regenerateSubArgumentInLetter: (
    subArgumentId: string,
    projectId: string,
    llmProvider: string,
    subArguments: SubArgument[],
    arguments_: Argument[]
  ) => Promise<void>;
  // Remove sub-argument sentences from letter (with cascade)
  removeSubArgumentFromLetter: (
    subArgumentId: string,
    arguments_: Argument[],
    projectId?: string,
    subArgTitle?: string
  ) => void;
  // Change cascade: accept/reject/commit
  acceptSuggestion: (sectionId: string, sentenceIndex: number) => void;
  rejectSuggestion: (sectionId: string, sentenceIndex: number) => void;
  commitChanges: (sectionId: string, projectId: string) => Promise<void>;
  dismissChanges: (sectionId: string) => void;
}

const WritingContext = createContext<WritingContextType | undefined>(undefined);

// Initial node positions for writing canvas
const getInitialWritingNodePositions = (): Map<string, Position> => {
  const positions = new Map<string, Position>();
  const connectedSnippetIds = ['snip-1', 'snip-2', 'snip-3', 'snip-4', 'snip-5', 'snip-7', 'snip-9'];
  connectedSnippetIds.forEach((id, index) => {
    positions.set(id, { x: 120, y: 80 + index * 100 });
  });
  const connectedStandardIds = ['std-awards', 'std-contribution', 'std-leading', 'std-salary'];
  connectedStandardIds.forEach((id, index) => {
    positions.set(id, { x: 680, y: 120 + index * 120 });
  });
  return positions;
};

export function WritingProvider({ children }: { children: ReactNode }) {
  const [writingEdges, setWritingEdges] = useState<WritingEdge[]>([]);
  const [letterSections, setLetterSections] = useState<LetterSection[]>([]);
  const [writingNodePositions, setWritingNodePositions] = useState<Map<string, Position>>(getInitialWritingNodePositions);

  // Unified extraction state
  const [mergeSuggestions, setMergeSuggestions] = useState<MergeSuggestion[]>([]);
  const [isExtracting, setIsExtracting] = useState(false);
  const [isMerging, setIsMerging] = useState(false);
  const [extractionProgress, setExtractionProgress] = useState<{ current: number; total: number; currentExhibit?: string } | null>(null);

  // Writing edge management
  const addWritingEdge = useCallback((source: string, target: string, type: WritingEdge['type']) => {
    setWritingEdges(prev => {
      const exists = prev.some(e => e.source === source && e.target === target);
      if (exists) return prev;

      const newEdge: WritingEdge = {
        id: `we-${Date.now()}-${Math.random().toString(36).substr(2, 9)}`,
        source,
        target,
        type,
        isConfirmed: false,
        createdAt: new Date(),
      };
      return [...prev, newEdge];
    });
  }, []);

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

  // Pipeline methods
  const extractSnippets = useCallback(async (
    projectId: string,
    setSnippets: React.Dispatch<React.SetStateAction<Snippet[]>>,
    setPipelineState: React.Dispatch<React.SetStateAction<PipelineState>>
  ) => {
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
  }, []);

  const confirmAllMappings = useCallback(async (
    projectId: string,
    setPipelineState: React.Dispatch<React.SetStateAction<PipelineState>>
  ) => {
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
  }, []);

  const generatePetition = useCallback(async (
    projectId: string,
    llmProvider: string,
    setPipelineState: React.Dispatch<React.SetStateAction<PipelineState>>
  ) => {
    setPipelineState(prev => ({ ...prev, stage: 'generating', progress: 0 }));
    try {
      const standardsToGenerate = [
        'awards', 'membership', 'published_material', 'judging',
        'original_contribution', 'scholarly_articles', 'leading_role', 'exhibitions'
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
            sentences: Array<{
              text: string;
              snippet_ids: string[];
              subargument_id?: string | null;
              argument_id?: string | null;
              exhibit_refs?: string[];
              sentence_type?: 'opening' | 'body' | 'closing';
            }>;
            provenance_index?: {
              by_subargument: Record<string, number[]>;
              by_argument: Record<string, number[]>;
              by_snippet: Record<string, number[]>;
            };
            validation?: {
              total_sentences: number;
              traced_sentences: number;
              warnings: string[];
            };
          }>(`/write/v3/${projectId}/${section}`, { provider: llmProvider });

          if (response.success && response.paragraph_text) {
            generatedSections.push({
              id: `section-${section}`,
              title: section.split('_').map(w => w.charAt(0).toUpperCase() + w.slice(1)).join(' '),
              standardId: section,
              content: response.paragraph_text,
              isGenerated: true,
              order: i,
              sentences: response.sentences,
              provenanceIndex: response.provenance_index,
            });
          }
        } catch (sectionErr) {
          console.log(`Skipped section ${section}:`, sectionErr);
        }
      }

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
  }, []);

  const reloadSnippets = useCallback(async (
    projectId: string,
    setSnippets: React.Dispatch<React.SetStateAction<Snippet[]>>
  ) => {
    try {
      const response = await apiClient.get<{
        snippets: BackendSnippet[];
      }>(`/analysis/${projectId}/snippets?limit=500`);

      if (response.snippets && response.snippets.length > 0) {
        const converted = response.snippets.map(convertBackendSnippet);
        setSnippets(converted);
        console.log(`Reloaded ${converted.length} extracted snippets`);
      }
    } catch (err) {
      console.error('Failed to reload snippets:', err);
    }
  }, []);

  // Unified extraction
  const unifiedExtract = useCallback(async (
    projectId: string,
    llmProvider: string,
    applicantName: string,
    setSnippets: React.Dispatch<React.SetStateAction<Snippet[]>>,
    setPipelineState: React.Dispatch<React.SetStateAction<PipelineState>>
  ) => {
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
        provider: llmProvider,
      });

      if (response.success) {
        setPipelineState(prev => ({
          ...prev,
          stage: 'snippets_ready',
          progress: 100,
          snippetCount: response.total_snippets,
        }));

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
  }, []);

  // Generate merge suggestions
  const generateMergeSuggestions = useCallback(async (
    projectId: string,
    llmProvider: string,
    applicantName: string
  ): Promise<MergeSuggestion[]> => {
    setIsMerging(true);
    try {
      const response = await apiClient.post<{
        success: boolean;
        suggestion_count: number;
        suggestions: MergeSuggestion[];
      }>(`/extraction/${projectId}/merge-suggestions/generate`, {
        applicant_name: applicantName,
        provider: llmProvider,
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
  }, []);

  // Load existing merge suggestions
  const loadMergeSuggestions = useCallback(async (projectId: string) => {
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
  }, []);

  // Confirm/reject merge suggestions
  const confirmMerges = useCallback(async (
    projectId: string,
    confirmations: Array<{suggestion_id: string; status: string}>
  ) => {
    try {
      const response = await apiClient.post<{
        success: boolean;
        updated: number;
      }>(`/extraction/${projectId}/merges/confirm`, confirmations);

      if (response.success) {
        // Reload suggestions to get updated statuses
        const suggestionsResponse = await apiClient.get<{
          project_id: string;
          suggestions: MergeSuggestion[];
          status: { pending: number; accepted: number; rejected: number; applied: number };
        }>(`/extraction/${projectId}/merge-suggestions`);
        setMergeSuggestions(suggestionsResponse.suggestions);
        console.log(`Updated ${response.updated} merge confirmations`);
      }
    } catch (err) {
      console.error('Failed to confirm merges:', err);
      throw err;
    }
  }, []);

  // Apply confirmed merges
  const applyMerges = useCallback(async (
    projectId: string,
    setSnippets: React.Dispatch<React.SetStateAction<Snippet[]>>
  ) => {
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

        const snippetsResponse = await apiClient.get<{
          project_id: string;
          total: number;
          snippets: UnifiedSnippet[];
        }>(`/extraction/${projectId}/snippets?limit=500`);

        if (snippetsResponse.snippets) {
          const converted = snippetsResponse.snippets.map(convertUnifiedSnippet);
          setSnippets(converted);
        }

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
  }, []);

  // Regenerate a specific SubArgument's sentences in the Letter
  const regenerateSubArgumentInLetter = useCallback(async (
    subArgumentId: string,
    projectId: string,
    llmProvider: string,
    subArguments: SubArgument[],
    arguments_: Argument[]
  ) => {
    const subArg = subArguments.find(sa => sa.id === subArgumentId);
    if (!subArg) {
      console.error(`SubArgument ${subArgumentId} not found`);
      return;
    }

    const arg = arguments_.find(a => a.id === subArg.argumentId);
    if (!arg || !arg.standardKey) {
      console.error(`Argument ${subArg.argumentId} not found or has no standardKey`);
      return;
    }

    const standardKey = arg.standardKey;
    const argId = arg.id;

    try {
      const response = await apiClient.post<{
        success: boolean;
        sentences: Array<{
          text: string;
          snippet_ids: string[];
          subargument_id: string | null;
          argument_id: string | null;
          exhibit_refs: string[];
          sentence_type: string;
        }>;
        provenance_index: {
          by_subargument: Record<string, number[]>;
          by_argument: Record<string, number[]>;
          by_snippet: Record<string, number[]>;
        };
      }>(`/write/v3/${projectId}/${standardKey}`, {
        subargument_ids: [subArgumentId],
        provider: llmProvider,
      });

      if (!response.success || !response.sentences) {
        console.error('Regeneration failed:', response);
        return;
      }

      const bodySentencesFromAPI = response.sentences.filter(
        s => s.sentence_type === 'body' && s.subargument_id === subArgumentId
      );

      if (bodySentencesFromAPI.length === 0) {
        console.warn('No body sentences returned from API');
        return;
      }

      setLetterSections(prev => prev.map(s => {
        if (s.standardId !== standardKey) return s;

        const indicesToReplace = s.provenanceIndex?.bySubArgument?.[subArgumentId] || [];
        const isNewSubArgument = indicesToReplace.length === 0;

        const oldSentences = [...s.sentences!];
        let newSentences: typeof oldSentences;

        if (isNewSubArgument) {
          const argumentIndices = s.provenanceIndex?.byArgument?.[argId] || [];
          if (argumentIndices.length > 0) {
            const insertAfterIdx = Math.max(...argumentIndices);
            newSentences = [
              ...oldSentences.slice(0, insertAfterIdx + 1),
              ...bodySentencesFromAPI,
              ...oldSentences.slice(insertAfterIdx + 1),
            ];
          } else {
            const closingIdx = oldSentences.findIndex(sent => sent.sentence_type === 'closing');
            if (closingIdx > 0) {
              newSentences = [
                ...oldSentences.slice(0, closingIdx),
                ...bodySentencesFromAPI,
                ...oldSentences.slice(closingIdx),
              ];
            } else {
              newSentences = [...oldSentences, ...bodySentencesFromAPI];
            }
          }
        } else {
          const sortedIndices = [...indicesToReplace].sort((a, b) => a - b);
          const firstIdx = sortedIndices[0];
          const lastIdx = sortedIndices[sortedIndices.length - 1];
          newSentences = [
            ...oldSentences.slice(0, firstIdx),
            ...bodySentencesFromAPI,
            ...oldSentences.slice(lastIdx + 1),
          ];
        }

        const newContent = newSentences.map(sent => sent.text).join(' ');

        const newProvenanceIndex = {
          bySubArgument: {} as Record<string, number[]>,
          byArgument: {} as Record<string, number[]>,
          bySnippet: {} as Record<string, number[]>,
        };

        newSentences.forEach((sent, idx) => {
          if (sent.subargument_id) {
            if (!newProvenanceIndex.bySubArgument[sent.subargument_id]) {
              newProvenanceIndex.bySubArgument[sent.subargument_id] = [];
            }
            newProvenanceIndex.bySubArgument[sent.subargument_id].push(idx);
          }
          if (sent.argument_id) {
            if (!newProvenanceIndex.byArgument[sent.argument_id]) {
              newProvenanceIndex.byArgument[sent.argument_id] = [];
            }
            newProvenanceIndex.byArgument[sent.argument_id].push(idx);
          }
          (sent.snippet_ids || []).forEach(snippetId => {
            if (!newProvenanceIndex.bySnippet[snippetId]) {
              newProvenanceIndex.bySnippet[snippetId] = [];
            }
            newProvenanceIndex.bySnippet[snippetId].push(idx);
          });
        });

        return {
          ...s,
          sentences: newSentences,
          content: newContent,
          provenanceIndex: newProvenanceIndex,
          lastEditedAt: new Date(),
        };
      }));

      console.log(`Successfully regenerated SubArgument ${subArgumentId}`);
    } catch (error) {
      console.error('Failed to regenerate SubArgument:', error);
    }
  }, []);

  // Remove sub-argument sentences from letter (with cascade visualization)
  const removeSubArgumentFromLetter = useCallback((
    subArgumentId: string,
    arguments_: Argument[],
    projectId?: string,
    subArgTitle?: string
  ) => {
    // Step 1: Mark sentences as 'removed' (red strikethrough) instead of deleting immediately
    setLetterSections(prev => prev.map(section => {
      const indicesToRemove = section.provenanceIndex?.bySubArgument?.[subArgumentId] || [];
      if (indicesToRemove.length === 0) return section;

      const newSentences = section.sentences?.map((sent, idx) => {
        if (indicesToRemove.includes(idx)) {
          return { ...sent, changeStatus: 'removed' as const };
        }
        return sent;
      }) || [];

      return {
        ...section,
        sentences: newSentences,
        isStale: true,
        lastEditedAt: new Date(),
      };
    }));

    // Step 2: Call LLM impact analysis (async, non-blocking)
    if (projectId) {
      // Find parent standard_key
      const parentArg = arguments_.find(a => a.subArgumentIds?.includes(subArgumentId));
      const standardKey = parentArg?.standardKey;

      if (standardKey) {
        apiClient.post<{
          success: boolean;
          suggestions: Array<{
            sentence_index: number;
            original_text: string;
            suggested_text: string;
            reason: string;
          }>;
        }>(`/write/v3/${projectId}/analyze-impact`, {
          standard_key: standardKey,
          change_type: 'deletion',
          affected_subargument_id: subArgumentId,
          affected_title: subArgTitle || '',
        }).then(response => {
          if (response.success && response.suggestions.length > 0) {
            setLetterSections(prev => prev.map(section => {
              if (section.standardId !== standardKey) return section;

              const newSentences = section.sentences?.map((sent, idx) => {
                const suggestion = response.suggestions.find(s => s.sentence_index === idx);
                if (suggestion && sent.changeStatus !== 'removed') {
                  return {
                    ...sent,
                    changeStatus: 'needs_adjustment' as const,
                    suggestedText: suggestion.suggested_text,
                    changeReason: suggestion.reason,
                  };
                }
                return sent;
              }) || [];

              return {
                ...section,
                sentences: newSentences,
                pendingSuggestions: response.suggestions,
              };
            }));
          }
        }).catch(err => {
          console.warn('Impact analysis failed (non-critical):', err);
        });
      }
    }
  }, []);

  // Accept a single suggestion
  const acceptSuggestion = useCallback((sectionId: string, sentenceIndex: number) => {
    setLetterSections(prev => prev.map(section => {
      if (section.id !== sectionId) return section;

      const newSentences = section.sentences?.map((sent, idx) => {
        if (idx === sentenceIndex && sent.suggestedText) {
          return {
            ...sent,
            text: sent.suggestedText,
            changeStatus: 'suggested_replacement' as const,
            originalText: sent.text,
          };
        }
        return sent;
      }) || [];

      return { ...section, sentences: newSentences };
    }));
  }, []);

  // Reject a single suggestion
  const rejectSuggestion = useCallback((sectionId: string, sentenceIndex: number) => {
    setLetterSections(prev => prev.map(section => {
      if (section.id !== sectionId) return section;

      const newSentences = section.sentences?.map((sent, idx) => {
        if (idx === sentenceIndex) {
          return {
            ...sent,
            changeStatus: undefined,
            suggestedText: undefined,
            changeReason: undefined,
          };
        }
        return sent;
      }) || [];

      // Remove from pendingSuggestions
      const newPending = section.pendingSuggestions?.filter(s => s.sentenceIndex !== sentenceIndex);

      return { ...section, sentences: newSentences, pendingSuggestions: newPending };
    }));
  }, []);

  // Commit all changes: apply accepted suggestions, remove 'removed' sentences, rebuild index, save
  const commitChanges = useCallback(async (sectionId: string, projectId: string) => {
    setLetterSections(prev => {
      const updated = prev.map(section => {
        if (section.id !== sectionId) return section;

        // Filter out removed sentences, keep the rest
        const newSentences = (section.sentences || [])
          .filter(sent => sent.changeStatus !== 'removed')
          .map(sent => ({
            ...sent,
            changeStatus: undefined,
            suggestedText: undefined,
            changeReason: undefined,
          }));

        const newContent = newSentences.map(sent => sent.text).join(' ');

        // Rebuild provenance index
        const newProvenanceIndex = {
          bySubArgument: {} as Record<string, number[]>,
          byArgument: {} as Record<string, number[]>,
          bySnippet: {} as Record<string, number[]>,
        };

        newSentences.forEach((sent, idx) => {
          if (sent.subargument_id) {
            if (!newProvenanceIndex.bySubArgument[sent.subargument_id]) {
              newProvenanceIndex.bySubArgument[sent.subargument_id] = [];
            }
            newProvenanceIndex.bySubArgument[sent.subargument_id].push(idx);
          }
          if (sent.argument_id) {
            if (!newProvenanceIndex.byArgument[sent.argument_id]) {
              newProvenanceIndex.byArgument[sent.argument_id] = [];
            }
            newProvenanceIndex.byArgument[sent.argument_id].push(idx);
          }
          (sent.snippet_ids || []).forEach(snippetId => {
            if (!newProvenanceIndex.bySnippet[snippetId]) {
              newProvenanceIndex.bySnippet[snippetId] = [];
            }
            newProvenanceIndex.bySnippet[snippetId].push(idx);
          });
        });

        return {
          ...section,
          sentences: newSentences,
          content: newContent,
          provenanceIndex: newProvenanceIndex,
          isStale: false,
          pendingSuggestions: undefined,
          lastEditedAt: new Date(),
        };
      });

      // Save to backend asynchronously
      const committedSection = updated.find(s => s.id === sectionId);
      if (committedSection?.standardId && projectId) {
        apiClient.post(`/write/v3/${projectId}/${committedSection.standardId}`, {
          additional_instructions: '__commit_only__',
        }).catch(err => {
          console.warn('Failed to persist committed changes:', err);
        });
      }

      return updated;
    });
  }, []);

  // Dismiss all changes (revert to clean state without applying)
  const dismissChanges = useCallback((sectionId: string) => {
    setLetterSections(prev => prev.map(section => {
      if (section.id !== sectionId) return section;

      // Remove 'removed' sentences and clear all change markers
      const newSentences = (section.sentences || [])
        .filter(sent => sent.changeStatus !== 'removed')
        .map(sent => ({
          ...sent,
          changeStatus: undefined,
          suggestedText: undefined,
          changeReason: undefined,
        }));

      const newContent = newSentences.map(sent => sent.text).join(' ');

      // Rebuild provenance index
      const newProvenanceIndex = {
        bySubArgument: {} as Record<string, number[]>,
        byArgument: {} as Record<string, number[]>,
        bySnippet: {} as Record<string, number[]>,
      };

      newSentences.forEach((sent, idx) => {
        if (sent.subargument_id) {
          if (!newProvenanceIndex.bySubArgument[sent.subargument_id]) {
            newProvenanceIndex.bySubArgument[sent.subargument_id] = [];
          }
          newProvenanceIndex.bySubArgument[sent.subargument_id].push(idx);
        }
        if (sent.argument_id) {
          if (!newProvenanceIndex.byArgument[sent.argument_id]) {
            newProvenanceIndex.byArgument[sent.argument_id] = [];
          }
          newProvenanceIndex.byArgument[sent.argument_id].push(idx);
        }
        (sent.snippet_ids || []).forEach(snippetId => {
          if (!newProvenanceIndex.bySnippet[snippetId]) {
            newProvenanceIndex.bySnippet[snippetId] = [];
          }
          newProvenanceIndex.bySnippet[snippetId].push(idx);
        });
      });

      return {
        ...section,
        sentences: newSentences,
        content: newContent,
        provenanceIndex: newProvenanceIndex,
        isStale: false,
        pendingSuggestions: undefined,
        lastEditedAt: new Date(),
      };
    }));
  }, []);

  const value = useMemo<WritingContextType>(() => ({
    writingEdges,
    setWritingEdges,
    addWritingEdge,
    removeWritingEdge,
    confirmWritingEdge,
    letterSections,
    setLetterSections,
    updateLetterSection,
    writingNodePositions,
    updateWritingNodePosition,
    extractSnippets,
    confirmAllMappings,
    generatePetition,
    reloadSnippets,
    unifiedExtract,
    generateMergeSuggestions,
    confirmMerges,
    applyMerges,
    mergeSuggestions,
    loadMergeSuggestions,
    isExtracting,
    isMerging,
    extractionProgress,
    regenerateSubArgumentInLetter,
    removeSubArgumentFromLetter,
    acceptSuggestion,
    rejectSuggestion,
    commitChanges,
    dismissChanges,
  }), [writingEdges, letterSections, writingNodePositions, mergeSuggestions, isExtracting, isMerging, extractionProgress, addWritingEdge, removeWritingEdge, confirmWritingEdge, updateLetterSection, updateWritingNodePosition, extractSnippets, confirmAllMappings, generatePetition, reloadSnippets, unifiedExtract, generateMergeSuggestions, confirmMerges, applyMerges, loadMergeSuggestions, regenerateSubArgumentInLetter, removeSubArgumentFromLetter, acceptSuggestion, rejectSuggestion, commitChanges, dismissChanges]);

  return <WritingContext.Provider value={value}>{children}</WritingContext.Provider>;
}

export function useWriting() {
  const context = useContext(WritingContext);
  if (context === undefined) {
    throw new Error('useWriting must be used within a WritingProvider');
  }
  return context;
}
