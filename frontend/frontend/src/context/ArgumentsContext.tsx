import { createContext, useContext, useState, useCallback, useMemo, type ReactNode } from 'react';
import type { Argument, SubArgument, WritingEdge, Position, ArgumentStatus, ArgumentClaimType } from '../types';
import { toArgumentClaimType } from '../types';
import { apiClient } from '../services/api';

// ============================================
// ArgumentsContext
// Provides: argument assembly state, sub-arguments, argument generation
// ============================================

// Backend argument response types
interface BackendArgument {
  id: string;
  title: string;
  subject: string;
  snippet_ids: string[];
  standard_key: string;
  confidence?: number;
  is_ai_generated: boolean;
  sub_argument_ids?: string[];
  created_at: string;
  exhibits?: string[];
  layers?: { claim: any[]; proof: any[]; significance: any[]; context: any[] };
  conclusion?: string;
  completeness?: { has_claim: boolean; has_proof: boolean; has_significance: boolean; has_context: boolean; score: number };
}

interface BackendSubArgument {
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
}

export function convertBackendArguments(args: BackendArgument[]): Argument[] {
  return args.map((arg) => ({
    id: arg.id,
    title: arg.title,
    subject: arg.subject,
    snippetIds: arg.snippet_ids,
    standardKey: arg.standard_key,
    claimType: toArgumentClaimType(arg.standard_key),
    status: 'draft' as ArgumentStatus,
    isAIGenerated: arg.is_ai_generated,
    subArgumentIds: arg.sub_argument_ids || [],
    createdAt: new Date(arg.created_at),
    updatedAt: new Date(),
    exhibits: arg.exhibits,
    layers: arg.layers,
    conclusion: arg.conclusion,
    completeness: arg.completeness,
  }));
}

export function convertBackendSubArguments(subArgs: BackendSubArgument[]): SubArgument[] {
  return subArgs.map((sa) => ({
    id: sa.id,
    argumentId: sa.argument_id,
    title: sa.title,
    purpose: sa.purpose,
    relationship: sa.relationship,
    snippetIds: sa.snippet_ids,
    pendingSnippetIds: sa.pending_snippet_ids || [],
    needsSnippetConfirmation: sa.needs_snippet_confirmation || false,
    isAIGenerated: sa.is_ai_generated,
    status: sa.status as 'draft' | 'verified',
    createdAt: new Date(sa.created_at),
    updatedAt: new Date(),
  }));
}

export interface ArgumentsContextType {
  arguments: Argument[];
  setArguments: React.Dispatch<React.SetStateAction<Argument[]>>;
  addArgument: (argument: Omit<Argument, 'id' | 'createdAt' | 'updatedAt'>) => void;
  updateArgument: (id: string, updates: Partial<Omit<Argument, 'id' | 'createdAt'>>) => void;
  removeArgument: (id: string) => void;
  updateArgumentPosition: (id: string, position: Position) => void;
  addSnippetToArgument: (argumentId: string, snippetId: string) => void;
  removeSnippetFromArgument: (argumentId: string, snippetId: string) => void;
  argumentMappings: WritingEdge[];
  addArgumentMapping: (argumentId: string, standardKey: string) => void;
  removeArgumentMapping: (edgeId: string) => void;
  subArguments: SubArgument[];
  setSubArguments: React.Dispatch<React.SetStateAction<SubArgument[]>>;
  addSubArgument: (subArgument: Omit<SubArgument, 'id' | 'createdAt' | 'updatedAt'>, projectId: string) => Promise<SubArgument>;
  updateSubArgument: (id: string, updates: Partial<Omit<SubArgument, 'id' | 'createdAt'>>) => void;
  removeSubArgument: (id: string, projectId: string) => void;
  regenerateSubArgument: (subArgumentId: string, projectId: string) => Promise<void>;
  mergeSubArguments: (subArgumentIds: string[], title: string, purpose: string, relationship: string, projectId: string) => Promise<{ newArgument: Argument; movedSubArgumentIds: string[] }>;
  moveSubArguments: (subArgumentIds: string[], targetArgumentId: string, projectId: string) => Promise<void>;
  createArgument: (standardKey: string, projectId: string) => Promise<Argument>;
  removeStandard: (standardKey: string, projectId: string) => Promise<void>;
  isGeneratingArguments: boolean;
  generateArguments: (projectId: string, llmProvider: string, forceReanalyze?: boolean, applicantName?: string) => Promise<void>;
  generatedMainSubject: string | null;
}

const ArgumentsContext = createContext<ArgumentsContextType | undefined>(undefined);

export function ArgumentsProvider({ children }: { children: ReactNode }) {
  const [arguments_, setArguments] = useState<Argument[]>([]);
  const [argumentMappings, setArgumentMappings] = useState<WritingEdge[]>([]);
  const [subArguments, setSubArguments] = useState<SubArgument[]>([]);
  const [isGeneratingArguments, setIsGeneratingArguments] = useState(false);
  const [generatedMainSubject, setGeneratedMainSubject] = useState<string | null>(null);

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
    // Also remove argument mappings
    setArgumentMappings(prev => prev.filter(e => e.source !== id));
  }, []);

  const updateArgumentPosition = useCallback((id: string, position: Position) => {
    setArguments(prev => prev.map(arg =>
      arg.id === id ? { ...arg, position, updatedAt: new Date() } : arg
    ));
  }, []);

  // Snippet to Argument operations
  const addSnippetToArgument = useCallback((argumentId: string, snippetId: string) => {
    setArguments(prev => prev.map(arg => {
      if (arg.id === argumentId) {
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

  // Argument -> Standard mapping
  const addArgumentMapping = useCallback((argumentId: string, standardKey: string) => {
    setArgumentMappings(prev => {
      const exists = prev.some(e => e.source === argumentId && e.target === standardKey);
      if (exists) return prev;

      const newMapping: WritingEdge = {
        id: `am-${Date.now()}-${Math.random().toString(36).substr(2, 9)}`,
        source: argumentId,
        target: standardKey,
        type: 'argument-to-standard',
        isConfirmed: true,
        createdAt: new Date(),
      };
      return [...prev, newMapping];
    });

    // Also update the argument's standardKey
    setArguments(prev => prev.map(arg =>
      arg.id === argumentId ? { ...arg, standardKey, status: 'mapped' as const, updatedAt: new Date() } : arg
    ));
  }, []);

  const removeArgumentMapping = useCallback((edgeId: string) => {
    setArgumentMappings(prev => {
      const mapping = prev.find(e => e.id === edgeId);
      if (mapping) {
        // Also clear the argument's standardKey
        setArguments(prevArgs => prevArgs.map(arg =>
          arg.id === mapping.source ? { ...arg, standardKey: undefined, status: 'verified' as const, updatedAt: new Date() } : arg
        ));
      }
      return prev.filter(e => e.id !== edgeId);
    });
  }, []);

  // SubArgument Management
  const addSubArgument = useCallback(async (
    subArgumentData: Omit<SubArgument, 'id' | 'createdAt' | 'updatedAt'>,
    projectId: string
  ): Promise<SubArgument> => {
    const response = await apiClient.post<{
      success: boolean;
      subargument: {
        id: string;
        argument_id: string;
        title: string;
        purpose: string;
        relationship: string;
        snippet_ids: string[];
        is_ai_generated: boolean;
        status: string;
        created_at: string;
      };
    }>(`/arguments/${projectId}/subarguments`, {
      argument_id: subArgumentData.argumentId,
      title: subArgumentData.title,
      purpose: subArgumentData.purpose,
      relationship: subArgumentData.relationship,
      snippet_ids: subArgumentData.snippetIds,
    });

    if (!response.success) {
      throw new Error('Failed to create SubArgument');
    }

    const newSubArgument: SubArgument = {
      id: response.subargument.id,
      argumentId: response.subargument.argument_id,
      title: response.subargument.title,
      purpose: response.subargument.purpose,
      relationship: response.subargument.relationship,
      snippetIds: response.subargument.snippet_ids,
      isAIGenerated: response.subargument.is_ai_generated,
      status: response.subargument.status as 'draft' | 'verified',
      createdAt: new Date(response.subargument.created_at),
      updatedAt: new Date(),
    };

    setSubArguments(prev => [...prev, newSubArgument]);

    // Update parent argument's subArgumentIds
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

    return newSubArgument;
  }, []);

  const updateSubArgument = useCallback((id: string, updates: Partial<Omit<SubArgument, 'id' | 'createdAt'>>) => {
    setSubArguments(prev => prev.map(sa =>
      sa.id === id ? { ...sa, ...updates, updatedAt: new Date() } : sa
    ));
  }, []);

  const removeSubArgument = useCallback((id: string, projectId: string) => {
    // We need to read from current state at removal time
    setSubArguments(prev => {
      const subArg = prev.find(sa => sa.id === id);
      if (!subArg) return prev;

      // Update the parent argument's subArgumentIds
      setArguments(prevArgs => prevArgs.map(arg => {
        if (arg.id === subArg.argumentId) {
          return {
            ...arg,
            subArgumentIds: (arg.subArgumentIds || []).filter(saId => saId !== id),
            updatedAt: new Date(),
          };
        }
        return arg;
      }));

      // Call backend to persist deletion
      console.log(`[ArgumentsContext] removeSubArgument called with id=${id}, projectId=${projectId}`);
      if (projectId) {
        const deleteUrl = `/arguments/${projectId}/subarguments/${id}`;
        console.log(`[ArgumentsContext] Calling DELETE ${deleteUrl}`);
        apiClient.delete(deleteUrl)
          .then(() => console.log(`[ArgumentsContext] SubArgument ${id} deleted from backend successfully`))
          .catch((error) => console.error('[ArgumentsContext] Failed to delete SubArgument from backend:', error));
      }

      return prev.filter(sa => sa.id !== id);
    });
  }, []);

  const regenerateSubArgument = useCallback(async (subArgumentId: string, projectId: string) => {
    console.warn('regenerateSubArgument should be called via useApp() facade which has access to WritingContext');
  }, []);

  const removeStandard = useCallback(async (standardKey: string, projectId: string) => {
    const response = await apiClient.delete<{
      success: boolean;
      deleted_argument_ids: string[];
      deleted_subargument_ids: string[];
    }>(`/arguments/${projectId}/standards/${standardKey}`);

    if (response.success) {
      const deletedArgIds = new Set(response.deleted_argument_ids);
      const deletedSubArgIds = new Set(response.deleted_subargument_ids);
      setArguments(prev => prev.filter(a => !deletedArgIds.has(a.id)));
      setSubArguments(prev => prev.filter(sa => !deletedSubArgIds.has(sa.id)));
      // Also clean argument mappings
      setArgumentMappings(prev => prev.filter(e => !deletedArgIds.has(e.source)));
    }
  }, []);

  // Merge SubArguments → move them under a new Argument (regroup, not fuse)
  const mergeSubArguments = useCallback(async (
    subArgumentIds: string[],
    title: string,
    purpose: string,
    relationship: string,
    projectId: string
  ): Promise<{ newArgument: Argument; movedSubArgumentIds: string[] }> => {
    const response = await apiClient.post<{
      success: boolean;
      new_argument: {
        id: string;
        title: string;
        subject: string;
        snippet_ids: string[];
        standard_key: string;
        confidence: number;
        is_ai_generated: boolean;
        sub_argument_ids: string[];
        created_at: string;
      };
      moved_subargument_ids: string[];
    }>(`/arguments/${projectId}/subarguments/merge`, {
      subargument_ids: subArgumentIds,
      merged_title: title,
      merged_purpose: purpose,
      merged_relationship: relationship,
    });

    if (!response.success) {
      throw new Error('Failed to merge sub-arguments');
    }

    const argData = response.new_argument;
    const newArgument: Argument = {
      id: argData.id,
      title: argData.title,
      subject: argData.subject,
      snippetIds: argData.snippet_ids,
      standardKey: argData.standard_key,
      claimType: toArgumentClaimType(argData.standard_key),
      status: 'draft' as ArgumentStatus,
      isAIGenerated: argData.is_ai_generated,
      subArgumentIds: argData.sub_argument_ids || [],
      createdAt: new Date(argData.created_at),
      updatedAt: new Date(),
    };

    const movedSet = new Set(response.moved_subargument_ids);

    // Update moved sub-args: change their argumentId to the new Argument
    setSubArguments(prev => prev.map(sa =>
      movedSet.has(sa.id)
        ? { ...sa, argumentId: newArgument.id, updatedAt: new Date() }
        : sa
    ));

    // Remove moved sub-arg IDs from old parent arguments, then add the new Argument
    setArguments(prev => {
      const updated = prev.map(arg => {
        const oldIds = arg.subArgumentIds || [];
        const hasMoved = oldIds.some(id => movedSet.has(id));
        if (!hasMoved) return arg;
        return {
          ...arg,
          subArgumentIds: oldIds.filter(id => !movedSet.has(id)),
          updatedAt: new Date(),
        };
      });
      return [...updated, newArgument];
    });

    return { newArgument, movedSubArgumentIds: response.moved_subargument_ids };
  }, []);

  // Move SubArguments to an existing Argument
  const moveSubArguments = useCallback(async (
    subArgumentIds: string[],
    targetArgumentId: string,
    projectId: string
  ): Promise<void> => {
    const response = await apiClient.post<{
      success: boolean;
      moved_subargument_ids: string[];
      target_argument_id: string;
    }>(`/arguments/${projectId}/subarguments/move`, {
      subargument_ids: subArgumentIds,
      target_argument_id: targetArgumentId,
    });

    if (!response.success) {
      throw new Error('Failed to move sub-arguments');
    }

    const movedSet = new Set(response.moved_subargument_ids);

    // Update sub-args: change argumentId to target
    setSubArguments(prev => prev.map(sa =>
      movedSet.has(sa.id)
        ? { ...sa, argumentId: targetArgumentId, updatedAt: new Date() }
        : sa
    ));

    // Update arguments: remove from old parents, add to target
    setArguments(prev => prev.map(arg => {
      const oldIds = arg.subArgumentIds || [];
      if (arg.id === targetArgumentId) {
        const newIds = [...oldIds];
        for (const sid of subArgumentIds) {
          if (!newIds.includes(sid)) newIds.push(sid);
        }
        return { ...arg, subArgumentIds: newIds, updatedAt: new Date() };
      }
      if (oldIds.some(id => movedSet.has(id))) {
        return { ...arg, subArgumentIds: oldIds.filter(id => !movedSet.has(id)), updatedAt: new Date() };
      }
      return arg;
    }));
  }, []);

  // Create a new Argument under a standard (persisted to backend)
  const createArgument = useCallback(async (
    standardKey: string,
    projectId: string
  ): Promise<Argument> => {
    const response = await apiClient.post<{
      success: boolean;
      argument: BackendArgument;
    }>(`/arguments/${projectId}/arguments`, {
      standard_key: standardKey,
      title: '',
    });

    if (!response.success) {
      throw new Error('Failed to create argument');
    }

    const newArg = convertBackendArguments([response.argument])[0];
    setArguments(prev => [...prev, newArg]);
    return newArg;
  }, []);

  // AI Argument Generation
  const generateArguments = useCallback(async (
    projectId: string,
    llmProvider: string,
    forceReanalyze: boolean = false,
    applicantName?: string
  ) => {
    setIsGeneratingArguments(true);
    try {
      // Step 1: Run the generation pipeline
      await apiClient.post<{
        success: boolean;
      }>(`/arguments/${projectId}/generate`, {
        force_reanalyze: forceReanalyze,
        applicant_name: applicantName,
        provider: llmProvider,
      });

      // Step 2: Fetch generated arguments and sub-arguments
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
          pending_snippet_ids?: string[];
          needs_snippet_confirmation?: boolean;
          is_ai_generated: boolean;
          status: string;
          created_at: string;
        }>;
        main_subject: string | null;
        generated_at: string;
        stats: Record<string, unknown>;
      }>(`/arguments/${projectId}`);

      setGeneratedMainSubject(response.main_subject);

      const convertedArguments = convertBackendArguments(response.arguments);
      setArguments(convertedArguments);
      console.log(`Generated ${convertedArguments.length} arguments for ${response.main_subject}`);

      const subArgsData = response.sub_arguments || [];
      const convertedSubArgs = convertBackendSubArguments(subArgsData);
      setSubArguments(convertedSubArgs);
      console.log(`Generated ${convertedSubArgs.length} sub-arguments`);
    } catch (err) {
      console.error('Failed to generate arguments:', err);
      throw err;
    } finally {
      setIsGeneratingArguments(false);
    }
  }, []);

  const value = useMemo<ArgumentsContextType>(() => ({
    arguments: arguments_,
    setArguments,
    addArgument,
    updateArgument,
    removeArgument,
    updateArgumentPosition,
    addSnippetToArgument,
    removeSnippetFromArgument,
    argumentMappings,
    addArgumentMapping,
    removeArgumentMapping,
    subArguments,
    setSubArguments,
    addSubArgument,
    updateSubArgument,
    removeSubArgument,
    regenerateSubArgument,
    removeStandard,
    mergeSubArguments,
    moveSubArguments,
    createArgument,
    isGeneratingArguments,
    generateArguments,
    generatedMainSubject,
  }), [arguments_, argumentMappings, subArguments, isGeneratingArguments, generatedMainSubject, addArgument, updateArgument, removeArgument, updateArgumentPosition, addSnippetToArgument, removeSnippetFromArgument, addArgumentMapping, removeArgumentMapping, addSubArgument, updateSubArgument, removeSubArgument, regenerateSubArgument, removeStandard, mergeSubArguments, moveSubArguments, createArgument, generateArguments]);

  return <ArgumentsContext.Provider value={value}>{children}</ArgumentsContext.Provider>;
}

export function useArguments() {
  const context = useContext(ArgumentsContext);
  if (context === undefined) {
    throw new Error('useArguments must be used within an ArgumentsProvider');
  }
  return context;
}
