import { createContext, useContext, useState, useCallback, useMemo, type ReactNode } from 'react';
import type { Connection, Snippet, SelectionState, BoundingBox } from '../types';

// ============================================
// SnippetsContext
// Provides: raw snippets, connections (legacy), selection state
// ============================================

export interface SnippetsContextType {
  allSnippets: Snippet[];
  setSnippets: React.Dispatch<React.SetStateAction<Snippet[]>>;
  connections: Connection[];
  setConnections: React.Dispatch<React.SetStateAction<Connection[]>>;
  addSnippet: (snippet: Omit<Snippet, 'id'>) => void;
  removeSnippet: (snippetId: string) => void;
  addConnection: (snippetId: string, standardId: string, isConfirmed: boolean) => void;
  removeConnection: (connectionId: string) => void;
  confirmConnection: (connectionId: string) => void;
  getConnectionsForSnippet: (snippetId: string) => Connection[];
  getConnectionsForStandard: (standardId: string) => Connection[];
  selectionState: SelectionState;
  setSelectionState: (state: SelectionState) => void;
  startSelection: (documentId: string, pageNumber: number, point: { x: number; y: number }) => void;
  updateSelection: (point: { x: number; y: number }) => void;
  endSelection: () => { boundingBox: BoundingBox; documentId: string } | null;
  cancelSelection: () => void;
}

const SnippetsContext = createContext<SnippetsContextType | undefined>(undefined);

export function SnippetsProvider({ children }: { children: ReactNode }) {
  // Start with empty snippets - will be loaded from backend via DataLoader
  const [snippets, setSnippets] = useState<Snippet[]>([]);
  // Start with empty connections
  const [connections, setConnections] = useState<Connection[]>([]);

  // Selection state for creating snippets
  const [selectionState, setSelectionState] = useState<SelectionState>({
    isSelecting: false,
    startPoint: null,
    endPoint: null,
    pageNumber: null,
    documentId: null,
  });

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

  // Connection management
  const addConnection = useCallback((snippetId: string, standardId: string, isConfirmed: boolean) => {
    setConnections(prev => {
      const exists = prev.some(
        conn => conn.snippetId === snippetId && conn.standardId === standardId
      );
      if (exists) {
        if (isConfirmed) {
          return prev.map(conn =>
            conn.snippetId === snippetId && conn.standardId === standardId
              ? { ...conn, isConfirmed: true }
              : conn
          );
        }
        return prev;
      }

      const newConnection: Connection = {
        id: `conn-${Date.now()}`,
        snippetId,
        standardId,
        isConfirmed,
        createdAt: new Date(),
      };
      return [...prev, newConnection];
    });
  }, []);

  const removeConnection = useCallback((connectionId: string) => {
    setConnections(prev => prev.filter(conn => conn.id !== connectionId));
  }, []);

  const confirmConnection = useCallback((connectionId: string) => {
    setConnections(prev => prev.map(conn =>
      conn.id === connectionId ? { ...conn, isConfirmed: true } : conn
    ));
  }, []);

  const getConnectionsForSnippet = useCallback((snippetId: string) => {
    return connections.filter(conn => conn.snippetId === snippetId);
  }, [connections]);

  const getConnectionsForStandard = useCallback((standardId: string) => {
    return connections.filter(conn => conn.standardId === standardId);
  }, [connections]);

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

  const value = useMemo<SnippetsContextType>(() => ({
    allSnippets: snippets,
    setSnippets,
    connections,
    setConnections,
    addSnippet,
    removeSnippet,
    addConnection,
    removeConnection,
    confirmConnection,
    getConnectionsForSnippet,
    getConnectionsForStandard,
    selectionState,
    setSelectionState,
    startSelection,
    updateSelection,
    endSelection,
    cancelSelection,
  }), [snippets, connections, selectionState, addSnippet, removeSnippet, addConnection, removeConnection, confirmConnection, getConnectionsForSnippet, getConnectionsForStandard, startSelection, updateSelection, endSelection, cancelSelection]);

  return <SnippetsContext.Provider value={value}>{children}</SnippetsContext.Provider>;
}

export function useSnippets() {
  const context = useContext(SnippetsContext);
  if (context === undefined) {
    throw new Error('useSnippets must be used within a SnippetsProvider');
  }
  return context;
}
