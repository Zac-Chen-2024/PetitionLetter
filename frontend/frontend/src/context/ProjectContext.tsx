import { createContext, useContext, useState, useCallback, useEffect, useMemo, type ReactNode } from 'react';
import type { LLMProvider, LegalStandard, PipelineStage, PipelineState, ProjectType } from '../types';
import { toLLMProvider } from '../types';
import { apiClient } from '../services/api';
import { legalStandards as defaultEB1AStandards } from '../data/legalStandards';

// ============================================
// ProjectContext
// Provides: project identity, loading status, LLM provider, pipeline stage,
//           project type, project number, legal standards
// ============================================

const STORAGE_KEY_LLM_PROVIDER = 'evidence-system-llm-provider';
const STORAGE_KEY_PROJECT_ID = 'evidence-system-project-id';
const DEFAULT_PROJECT_ID = 'yaruo_qu';

export interface ProjectContextType {
  projectId: string;
  setProjectId: (id: string) => void;
  isLoading: boolean;
  setIsLoading: (loading: boolean) => void;
  loadError: string | null;
  setLoadError: (error: string | null) => void;
  llmProvider: LLMProvider;
  setLlmProvider: (provider: LLMProvider) => void;
  pipelineState: PipelineState;
  setPipelineState: React.Dispatch<React.SetStateAction<PipelineState>>;
  projectType: ProjectType;
  projectNumber: string | null;
  legalStandards: LegalStandard[];
}

const ProjectContext = createContext<ProjectContextType | undefined>(undefined);

export function ProjectProvider({ children }: { children: ReactNode }) {
  const [projectId, setProjectIdState] = useState<string>(() => {
    return localStorage.getItem(STORAGE_KEY_PROJECT_ID) || DEFAULT_PROJECT_ID;
  });

  const setProjectId = useCallback((id: string) => {
    setProjectIdState(id);
    localStorage.setItem(STORAGE_KEY_PROJECT_ID, id);
  }, []);
  const [isLoading, setIsLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);

  // LLM Provider setting
  const [llmProvider, setLlmProviderState] = useState<LLMProvider>(() => {
    const saved = localStorage.getItem(STORAGE_KEY_LLM_PROVIDER);
    return toLLMProvider(saved);
  });

  // Pipeline state
  const [pipelineState, setPipelineState] = useState<PipelineState>({
    stage: 'ocr_complete',
    progress: 0,
  });

  // Project type & number
  const [projectType, setProjectType] = useState<ProjectType>('EB-1A');
  const [projectNumber, setProjectNumber] = useState<string | null>(null);
  const [legalStandards, setLegalStandards] = useState<LegalStandard[]>(defaultEB1AStandards);

  const setLlmProvider = useCallback((provider: LLMProvider) => {
    setLlmProviderState(provider);
    localStorage.setItem(STORAGE_KEY_LLM_PROVIDER, provider);
  }, []);

  // Load project info + standards when projectId changes
  useEffect(() => {
    let cancelled = false;

    async function loadProjectData() {
      // 1. Load project details (type + number)
      try {
        const project = await apiClient.get<{
          projectType?: string;
          projectNumber?: string;
        }>(`/projects/${projectId}`);

        if (!cancelled) {
          const pType = (project.projectType === 'NIW' ? 'NIW' : 'EB-1A') as ProjectType;
          setProjectType(pType);
          setProjectNumber(project.projectNumber || null);
        }
      } catch {
        if (!cancelled) {
          setProjectType('EB-1A');
          setProjectNumber(null);
        }
      }

      // 2. Load standards for this project
      try {
        const resp = await apiClient.get<{
          standards: LegalStandard[];
          projectType: string;
        }>(`/projects/${projectId}/standards`);

        if (!cancelled && resp.standards && resp.standards.length > 0) {
          setLegalStandards(resp.standards);
        }
      } catch {
        if (!cancelled) {
          setLegalStandards(defaultEB1AStandards);
        }
      }

      // 3. Load pipeline stage
      try {
        const stageResponse = await apiClient.get<{
          stage: PipelineStage;
          can_extract: boolean;
          can_confirm: boolean;
          can_generate: boolean;
        }>(`/analysis/${projectId}/stage`);

        if (!cancelled) {
          setPipelineState(prev => ({
            ...prev,
            stage: stageResponse.stage,
          }));
        }
      } catch {
        if (!cancelled) {
          setPipelineState(prev => ({ ...prev, stage: 'ocr_complete' }));
        }
      }
    }

    loadProjectData();
    return () => { cancelled = true; };
  }, [projectId]);

  const value = useMemo<ProjectContextType>(() => ({
    projectId,
    setProjectId,
    isLoading,
    setIsLoading,
    loadError,
    setLoadError,
    llmProvider,
    setLlmProvider,
    pipelineState,
    setPipelineState,
    projectType,
    projectNumber,
    legalStandards,
  }), [projectId, setProjectId, isLoading, loadError, llmProvider, pipelineState, setLlmProvider, projectType, projectNumber, legalStandards]);

  return <ProjectContext.Provider value={value}>{children}</ProjectContext.Provider>;
}

export function useProject() {
  const context = useContext(ProjectContext);
  if (context === undefined) {
    throw new Error('useProject must be used within a ProjectProvider');
  }
  return context;
}
