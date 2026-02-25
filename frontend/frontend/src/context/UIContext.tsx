import { createContext, useContext, useState, useCallback, useEffect, useMemo, type ReactNode } from 'react';
import type { FocusState, ElementPosition, ViewMode, ArgumentViewMode, Position, Argument, WritingEdge, Connection, Snippet, WorkMode } from '../types';
import { toViewMode, toArgumentViewMode } from '../types';
import { STANDARD_KEY_TO_ID } from '../constants/colors';

// ============================================
// UIContext
// Provides: all UI/interaction state (focus, selection, positions, view modes, drag)
// ============================================

const STORAGE_KEY_VIEW_MODE = 'evidence-system-view-mode';
const STORAGE_KEY_ARGUMENT_VIEW_MODE = 'evidence-system-argument-view-mode';

// Panel bounds for clipping connection lines
interface PanelBounds {
  top: number;
  bottom: number;
  left: number;
  right: number;
}

export interface UIContextType {
  focusState: FocusState;
  setFocusState: (state: FocusState) => void;
  clearFocus: () => void;
  selectedSnippetId: string | null;
  setSelectedSnippetId: (id: string | null) => void;
  selectedDocumentId: string;
  setSelectedDocumentId: (id: string) => void;
  viewMode: ViewMode;
  setViewMode: (mode: ViewMode) => void;
  argumentViewMode: ArgumentViewMode;
  setArgumentViewMode: (mode: ArgumentViewMode) => void;
  argumentGraphPositions: Map<string, Position>;
  updateArgumentGraphPosition: (id: string, position: Position) => void;
  clearArgumentGraphPositions: () => void;
  draggedSnippetId: string | null;
  setDraggedSnippetId: (id: string | null) => void;
  draggedArgumentId: string | null;
  setDraggedArgumentId: (id: string | null) => void;
  hoveredSnippetId: string | null;
  setHoveredSnippetId: (id: string | null) => void;
  snippetPositions: Map<string, ElementPosition>;
  updateSnippetPosition: (id: string, position: ElementPosition) => void;
  pdfBboxPositions: Map<string, ElementPosition>;
  updatePdfBboxPosition: (id: string, position: ElementPosition) => void;
  argumentPositions: Map<string, ElementPosition>;
  updateArgumentPosition2: (id: string, position: ElementPosition) => void;
  subArgumentPositions: Map<string, ElementPosition>;
  updateSubArgumentPosition: (id: string, position: ElementPosition) => void;
  snippetPanelBounds: PanelBounds | null;
  setSnippetPanelBounds: (bounds: PanelBounds | null) => void;
  // isElementHighlighted needs cross-context data; takes them as parameters
  isElementHighlighted: (
    elementType: 'snippet' | 'standard',
    elementId: string,
    connections: Connection[],
    snippets: Snippet[],
    arguments_: Argument[],
    argumentMappings: WritingEdge[]
  ) => boolean;
  workMode: WorkMode;
  setWorkMode: (mode: WorkMode) => void;
}

const UIContext = createContext<UIContextType | undefined>(undefined);

export function UIProvider({ children }: { children: ReactNode }) {
  const [focusState, setFocusStateInternal] = useState<FocusState>({ type: 'none', id: null });
  const [selectedSnippetId, setSelectedSnippetId] = useState<string | null>(null);
  const [selectedDocumentId, setSelectedDocumentId] = useState<string>('');
  const [draggedSnippetId, setDraggedSnippetId] = useState<string | null>(null);
  const [draggedArgumentId, setDraggedArgumentId] = useState<string | null>(null);
  const [hoveredSnippetId, setHoveredSnippetId] = useState<string | null>(null);
  const [snippetPositions, setSnippetPositions] = useState<Map<string, ElementPosition>>(new Map());
  const [pdfBboxPositions, setPdfBboxPositions] = useState<Map<string, ElementPosition>>(new Map());
  const [argumentPositions, setArgumentPositions] = useState<Map<string, ElementPosition>>(new Map());
  const [subArgumentPositions, setSubArgumentPositions] = useState<Map<string, ElementPosition>>(new Map());
  const [snippetPanelBounds, setSnippetPanelBounds] = useState<PanelBounds | null>(null);
  const [workMode, setWorkMode] = useState<WorkMode>('verify');

  // View mode
  const [viewMode, setViewModeState] = useState<ViewMode>(() => {
    const saved = localStorage.getItem(STORAGE_KEY_VIEW_MODE);
    return toViewMode(saved);
  });

  // Argument view mode (list vs graph) - default to graph
  const [argumentViewMode, setArgumentViewModeState] = useState<ArgumentViewMode>(() => {
    const saved = localStorage.getItem(STORAGE_KEY_ARGUMENT_VIEW_MODE);
    return toArgumentViewMode(saved);
  });

  // Argument graph node positions (for graph view)
  const [argumentGraphPositions, setArgumentGraphPositions] = useState<Map<string, Position>>(new Map());

  // Persist view mode
  useEffect(() => {
    localStorage.setItem(STORAGE_KEY_VIEW_MODE, viewMode);
  }, [viewMode]);

  // Persist argument view mode
  useEffect(() => {
    localStorage.setItem(STORAGE_KEY_ARGUMENT_VIEW_MODE, argumentViewMode);
  }, [argumentViewMode]);

  // Wrapper for setFocusState: clear selectedSnippetId when focusing non-snippet
  const setFocusState = useCallback((state: FocusState) => {
    setFocusStateInternal(state);
    if (state.type !== 'snippet') {
      setSelectedSnippetId(null);
    }
  }, []);

  const clearFocus = useCallback(() => {
    setFocusState({ type: 'none', id: null });
  }, [setFocusState]);

  const setViewMode = useCallback((mode: ViewMode) => {
    setViewModeState(mode);
  }, []);

  const setArgumentViewMode = useCallback((mode: ArgumentViewMode) => {
    setArgumentViewModeState(mode);
  }, []);

  const updateArgumentGraphPosition = useCallback((id: string, position: Position) => {
    setArgumentGraphPositions(prev => {
      const newMap = new Map(prev);
      newMap.set(id, position);
      return newMap;
    });
  }, []);

  const clearArgumentGraphPositions = useCallback(() => {
    setArgumentGraphPositions(new Map());
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

  // isElementHighlighted: takes cross-context data as parameters
  const isElementHighlighted = useCallback((
    elementType: 'snippet' | 'standard',
    elementId: string,
    connections: Connection[],
    snippets: Snippet[],
    arguments_: Argument[],
    argumentMappings: WritingEdge[]
  ): boolean => {
    if (focusState.type === 'none') return true;

    if (focusState.type === 'snippet' && focusState.id) {
      if (elementType === 'snippet') {
        return elementId === focusState.id;
      }
      return arguments_.some(arg => {
        if (!arg.snippetIds?.includes(focusState.id!)) return false;
        if (arg.standardKey && STANDARD_KEY_TO_ID[arg.standardKey] === elementId) return true;
        return argumentMappings.some(m => m.source === arg.id && m.target === elementId);
      });
    }

    if (focusState.type === 'standard' && focusState.id) {
      if (elementType === 'standard') {
        return elementId === focusState.id;
      }
      const focusedStandardId = focusState.id;
      return arguments_.some(arg => {
        if (!arg.snippetIds?.includes(elementId)) return false;
        if (arg.standardKey && STANDARD_KEY_TO_ID[arg.standardKey] === focusedStandardId) return true;
        return argumentMappings.some(m => m.source === arg.id && m.target === focusedStandardId);
      });
    }

    if (focusState.type === 'argument' && focusState.id) {
      if (elementType === 'snippet') {
        const focusedArg = arguments_.find(arg => arg.id === focusState.id);
        return focusedArg?.snippetIds?.includes(elementId) || false;
      }
      if (elementType === 'standard') {
        const focusedArg = arguments_.find(arg => arg.id === focusState.id);
        if (!focusedArg) return false;
        if (focusedArg.standardKey && STANDARD_KEY_TO_ID[focusedArg.standardKey] === elementId) return true;
        return argumentMappings.some(m => m.source === focusState.id && m.target === elementId);
      }
    }

    if (focusState.type === 'document' && focusState.id) {
      if (elementType === 'snippet') {
        const snip = snippets.find(s => s.id === elementId);
        return snip?.documentId === focusState.id;
      }
      return connections.some(conn => {
        if (conn.standardId !== elementId) return false;
        const snip = snippets.find(s => s.id === conn.snippetId);
        return snip?.documentId === focusState.id;
      });
    }

    return true;
  }, [focusState]);

  const value = useMemo<UIContextType>(() => ({
    focusState,
    setFocusState,
    clearFocus,
    selectedSnippetId,
    setSelectedSnippetId,
    selectedDocumentId,
    setSelectedDocumentId,
    viewMode,
    setViewMode,
    argumentViewMode,
    setArgumentViewMode,
    argumentGraphPositions,
    updateArgumentGraphPosition,
    clearArgumentGraphPositions,
    draggedSnippetId,
    setDraggedSnippetId,
    draggedArgumentId,
    setDraggedArgumentId,
    hoveredSnippetId,
    setHoveredSnippetId,
    snippetPositions,
    updateSnippetPosition,
    pdfBboxPositions,
    updatePdfBboxPosition,
    argumentPositions,
    updateArgumentPosition2,
    subArgumentPositions,
    updateSubArgumentPosition,
    snippetPanelBounds,
    setSnippetPanelBounds,
    isElementHighlighted,
    workMode,
    setWorkMode,
  }), [focusState, selectedSnippetId, selectedDocumentId, viewMode, argumentViewMode, argumentGraphPositions, draggedSnippetId, draggedArgumentId, hoveredSnippetId, snippetPositions, pdfBboxPositions, argumentPositions, subArgumentPositions, snippetPanelBounds, workMode, setFocusState, clearFocus, setViewMode, setArgumentViewMode, updateArgumentGraphPosition, clearArgumentGraphPositions, updateSnippetPosition, updatePdfBboxPosition, updateArgumentPosition2, updateSubArgumentPosition, isElementHighlighted]);

  return <UIContext.Provider value={value}>{children}</UIContext.Provider>;
}

export function useUI() {
  const context = useContext(UIContext);
  if (context === undefined) {
    throw new Error('useUI must be used within a UIProvider');
  }
  return context;
}
