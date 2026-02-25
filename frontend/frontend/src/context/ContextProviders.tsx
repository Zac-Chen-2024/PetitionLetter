import { useEffect, type ReactNode } from 'react';
import { ProjectProvider, useProject } from './ProjectContext';
import { SnippetsProvider, useSnippets } from './SnippetsContext';
import { ArgumentsProvider, useArguments } from './ArgumentsContext';
import { UIProvider } from './UIContext';
import { WritingProvider, useWriting } from './WritingContext';
import { convertBackendArguments, convertBackendSubArguments } from './ArgumentsContext';
import type { Snippet, LetterSection } from '../types';
import { apiClient } from '../services/api';

// ============================================
// ContextProviders
// Nests all 5 context providers and includes a DataLoader
// that loads project data when projectId changes.
// ============================================

// Default color for unassigned snippets
const DEFAULT_SNIPPET_COLOR = '#94a3b8';

// Backend snippet format
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

/**
 * DataLoader: Sits inside all providers and loads data when projectId changes.
 * This replaces the single big useEffect that was in AppProvider.
 */
function DataLoader({ children }: { children: ReactNode }) {
  const { projectId, setIsLoading, setLoadError, setPipelineState } = useProject();
  const { setSnippets } = useSnippets();
  const { setArguments, setSubArguments } = useArguments();
  const { setLetterSections } = useWriting();

  useEffect(() => {
    let cancelled = false;

    async function loadProjectData() {
      setIsLoading(true);
      setLoadError(null);

      // CRITICAL: Clear all project-specific state before loading new project data.
      // Without this, switching from a project with data (e.g. yaruo_qu) to one
      // without (e.g. dehuan_liu) would show the old project's stale data.
      setSnippets([]);
      setArguments([]);
      setSubArguments([]);
      setLetterSections([]);

      // Helper: load saved V3 letter sections
      async function loadLetterSections() {
        console.log('[DataLoader] Loading letter sections...');
        try {
          const sectionsResp = await apiClient.get<{
            success: boolean;
            sections: Array<{
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
            }>;
          }>(`/write/v3/${projectId}/sections`);

          if (cancelled) return;

          if (sectionsResp.success && sectionsResp.sections && sectionsResp.sections.length > 0) {
            const converted: LetterSection[] = sectionsResp.sections.map((s, i) => ({
              id: `section-${s.section}`,
              title: s.section.split('_').map(w => w.charAt(0).toUpperCase() + w.slice(1)).join(' '),
              standardId: s.section,
              content: s.paragraph_text,
              isGenerated: true,
              order: i,
              sentences: s.sentences,
              provenanceIndex: s.provenance_index ? {
                bySubArgument: s.provenance_index.by_subargument || {},
                byArgument: s.provenance_index.by_argument || {},
                bySnippet: s.provenance_index.by_snippet || {},
              } : undefined,
            }));
            setLetterSections(converted);
            console.log(`Loaded ${converted.length} saved letter sections`);
          }
        } catch {
          console.log('No saved letter sections found');
        }
      }

      try {
        // Try loading from unified extraction API first (has subject attribution)
        try {
          const extractionResponse = await apiClient.get<{
            project_id: string;
            total: number;
            snippets: UnifiedSnippet[];
          }>(`/extraction/${projectId}/snippets?limit=500`);

          if (extractionResponse.snippets && extractionResponse.snippets.length > 0) {
            if (cancelled) return;
            const converted = extractionResponse.snippets.map(convertUnifiedSnippet);
            setSnippets(converted);
            setPipelineState(prev => ({ ...prev, stage: 'snippets_ready', snippetCount: converted.length }));
            console.log(`Loaded ${converted.length} unified extraction snippets from project ${projectId}`);

            // Also try to load generated arguments and sub-arguments
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
                  pending_snippet_ids?: string[];
                  needs_snippet_confirmation?: boolean;
                  is_ai_generated: boolean;
                  status: string;
                  created_at: string;
                }>;
                main_subject: string | null;
                generated_at: string | null;
              }>(`/arguments/${projectId}`);

              if (cancelled) return;

              if (argsResponse.arguments && argsResponse.arguments.length > 0) {
                const convertedArgs = convertBackendArguments(argsResponse.arguments);
                setArguments(convertedArgs);
                console.log(`Loaded ${convertedArgs.length} generated arguments from backend`);
              }

              const subArgsData = argsResponse.sub_arguments || [];
              const convertedSubArgs = convertBackendSubArguments(subArgsData);
              setSubArguments(convertedSubArgs);
              console.log(`Loaded ${convertedSubArgs.length} sub-arguments from backend`);
            } catch {
              console.log('No generated arguments found');
            }

            // Load saved letter sections (V3)
            await loadLetterSections();

            return; // Success
          }
        } catch {
          // Unified extraction not available, try legacy API
        }

        if (cancelled) return;

        // Fall back to legacy analysis API
        const response = await apiClient.get<{
          project_id: string;
          total: number;
          snippets: BackendSnippet[];
        }>(`/analysis/${projectId}/snippets?limit=500`);

        if (cancelled) return;

        if (response.snippets && response.snippets.length > 0) {
          const converted = response.snippets.map(convertBackendSnippet);
          setSnippets(converted);
          console.log(`Loaded ${converted.length} extracted snippets from project ${projectId}`);
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
              pending_snippet_ids?: string[];
              needs_snippet_confirmation?: boolean;
              is_ai_generated: boolean;
              status: string;
              created_at: string;
            }>;
            main_subject: string | null;
            generated_at: string | null;
          }>(`/arguments/${projectId}`);

          if (cancelled) return;

          if (argsResponse.arguments && argsResponse.arguments.length > 0) {
            const convertedArgs = convertBackendArguments(argsResponse.arguments);
            setArguments(convertedArgs);
            console.log(`Loaded ${convertedArgs.length} generated arguments from backend (legacy path)`);
          }

          const subArgsData = argsResponse.sub_arguments || [];
          const convertedSubArgs = convertBackendSubArguments(subArgsData);
          setSubArguments(convertedSubArgs);
          console.log(`Loaded ${convertedSubArgs.length} sub-arguments from backend (legacy path)`);
        } catch {
          console.log('No generated arguments found (legacy path)');
        }

        // Load saved letter sections (V3) - legacy path
        await loadLetterSections();

        if (!(response.snippets && response.snippets.length > 0)) {
          // Fall back to raw OCR data if no extracted snippets
          const rawResponse = await apiClient.get<{
            project_id: string;
            total: number;
            snippets: BackendSnippet[];
          }>(`/data/projects/${projectId}/snippets?limit=500`);

          if (cancelled) return;

          if (rawResponse.snippets && rawResponse.snippets.length > 0) {
            const converted = rawResponse.snippets.map(convertBackendSnippet);
            setSnippets(converted);
            console.log(`Loaded ${converted.length} raw OCR blocks from project ${projectId}`);
          }
        }
      } catch (err) {
        if (cancelled) return;
        console.error('Failed to load project data:', err);
        setLoadError(err instanceof Error ? err.message : 'Failed to load data');
      } finally {
        if (!cancelled) {
          setIsLoading(false);
        }
      }
    }

    loadProjectData();
    return () => { cancelled = true; };
  }, [projectId, setIsLoading, setLoadError, setPipelineState, setSnippets, setArguments, setSubArguments, setLetterSections]);

  return <>{children}</>;
}

/**
 * AppProviders: Nests all context providers in the correct order.
 * ProjectProvider is outermost (no dependencies).
 * SnippetsProvider and ArgumentsProvider are next.
 * UIProvider and WritingProvider are innermost.
 * DataLoader sits inside all providers to access all setters.
 */
export function AppProviders({ children }: { children: ReactNode }) {
  return (
    <ProjectProvider>
      <SnippetsProvider>
        <ArgumentsProvider>
          <UIProvider>
            <WritingProvider>
              <DataLoader>
                {children}
              </DataLoader>
            </WritingProvider>
          </UIProvider>
        </ArgumentsProvider>
      </SnippetsProvider>
    </ProjectProvider>
  );
}
