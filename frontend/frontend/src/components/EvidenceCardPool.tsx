import { useEffect, useRef, useState, useCallback, useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import { useApp } from '../context/AppContext';
import { materialTypeLabels, getStandardById, legalStandards } from '../data/legalStandards';
import { RelationshipGraphModal } from './RelationshipGraphModal';
import type { Snippet } from '../types';
import { getStandardKeyColor, STANDARD_KEY_TO_ID } from '../constants/colors';

// Default color for unassigned snippets
const DEFAULT_SNIPPET_COLOR = '#94a3b8';  // slate-400

// Arrow indicators for hidden connections
interface ScrollIndicatorProps {
  direction: 'up' | 'down';
  count: number;
  snippetIds: string[];
  onClick: () => void;
}

function ScrollIndicator({ direction, count, onClick }: ScrollIndicatorProps) {
  const { t } = useTranslation();
  if (count === 0) return null;

  const key = direction === 'up'
    ? (count !== 1 ? 'evidence.connectionsAbovePlural' : 'evidence.connectionsAbove')
    : (count !== 1 ? 'evidence.connectionsBelowPlural' : 'evidence.connectionsBelow');

  return (
    <button
      onClick={onClick}
      className={`
        absolute left-1/2 -translate-x-1/2 z-20
        flex items-center gap-2 px-3 py-1.5
        bg-slate-900 text-white text-xs font-medium
        rounded-full shadow-lg hover:bg-slate-800
        transition-all duration-200 hover:scale-105
        ${direction === 'up' ? 'top-2' : 'bottom-2'}
      `}
    >
      <svg
        className={`w-4 h-4 ${direction === 'up' ? 'rotate-180' : ''}`}
        fill="none"
        stroke="currentColor"
        viewBox="0 0 24 24"
      >
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 14l-7 7m0 0l-7-7m7 7V3" />
      </svg>
      <span>{t(key, { count })}</span>
    </button>
  );
}

// Icon for drag handle
const DragHandleIcon = () => (
  <svg className="w-4 h-4 text-slate-400" fill="currentColor" viewBox="0 0 24 24">
    <path d="M8 6a2 2 0 1 1-4 0 2 2 0 0 1 4 0zm0 6a2 2 0 1 1-4 0 2 2 0 0 1 4 0zm0 6a2 2 0 1 1-4 0 2 2 0 0 1 4 0zm8-12a2 2 0 1 1-4 0 2 2 0 0 1 4 0zm0 6a2 2 0 1 1-4 0 2 2 0 0 1 4 0zm0 6a2 2 0 1 1-4 0 2 2 0 0 1 4 0z" />
  </svg>
);

const LinkIcon = () => (
  <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13.828 10.172a4 4 0 00-5.656 0l-4 4a4 4 0 105.656 5.656l1.102-1.101m-.758-4.899a4 4 0 005.656 0l4-4a4 4 0 00-5.656-5.656l-1.1 1.1" />
  </svg>
);

const ExpandIcon = () => (
  <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
  </svg>
);

interface EvidenceCardProps {
  snippet: Snippet;
}

function EvidenceCard({ snippet }: EvidenceCardProps) {
  const {
    focusState,
    selectedSnippetId,
    setSelectedSnippetId,
    isElementHighlighted,
    draggedSnippetId,
    setDraggedSnippetId,
    updateSnippetPosition,
    getConnectionsForSnippet,
    setSelectedDocumentId,
    arguments: arguments_,
    argumentMappings,
    subArguments,
  } = useApp();

  // Check if this snippet is already assembled into an argument
  const isAssembled = arguments_.some(arg => arg.snippetIds?.includes(snippet.id));

  // Determine snippet color based on its Argument's standard mapping
  // When a standard is focused, show the color of that standard if this snippet belongs to it
  const snippetColor = useMemo(() => {
    // Find all arguments containing this snippet
    const containingArgs = arguments_.filter(arg => arg.snippetIds?.includes(snippet.id));
    if (containingArgs.length === 0) return DEFAULT_SNIPPET_COLOR;

    // If a standard is focused, check if any containing argument maps to that standard
    if (focusState.type === 'standard' && focusState.id) {
      const focusedStandardId = focusState.id;
      // Find an argument that maps to the focused standard
      for (const arg of containingArgs) {
        // Check AI-generated standardKey mapping
        const mappedStandardId = arg.standardKey ? STANDARD_KEY_TO_ID[arg.standardKey] : null;
        if (mappedStandardId === focusedStandardId) {
          return getStandardKeyColor(arg.standardKey!);
        }
        // Check manual drag-drop mapping
        const manualMapping = argumentMappings.find(m => m.source === arg.id && m.target === focusedStandardId);
        if (manualMapping) {
          const standard = legalStandards.find(s => s.id === focusedStandardId);
          if (standard?.color) return standard.color;
        }
      }
    }

    // If an argument is focused, use that argument's color
    if (focusState.type === 'argument' && focusState.id) {
      const focusedArg = containingArgs.find(arg => arg.id === focusState.id);
      if (focusedArg?.standardKey && STANDARD_KEY_TO_ID[focusedArg.standardKey]) {
        return getStandardKeyColor(focusedArg.standardKey);
      }
    }

    // Default: Use the first containing argument's color
    const firstArg = containingArgs[0];
    if (firstArg.standardKey && STANDARD_KEY_TO_ID[firstArg.standardKey]) {
      return getStandardKeyColor(firstArg.standardKey);
    }

    // Fallback: Check manual mappings
    const mapping = argumentMappings.find(m => m.source === firstArg.id);
    if (mapping) {
      const standard = legalStandards.find(s => s.id === mapping.target);
      if (standard?.color) return standard.color;
    }

    return DEFAULT_SNIPPET_COLOR;
  }, [snippet.id, arguments_, argumentMappings, focusState]);

  const cardRef = useRef<HTMLDivElement>(null);
  const [isExpanded, setIsExpanded] = useState(false);

  const isHighlighted = isElementHighlighted('snippet', snippet.id);
  // isFocused now depends on selectedSnippetId (for card visual highlighting)
  const isFocused = selectedSnippetId === snippet.id;
  const isDragging = draggedSnippetId === snippet.id;
  const connections = getConnectionsForSnippet(snippet.id);

  // Check if a standard is focused and this card is NOT connected to it via arguments
  const isFilteredOutByStandard = useMemo(() => {
    if (focusState.type !== 'standard' || !focusState.id) return false;
    const focusedStandardId = focusState.id;
    // Check if any argument containing this snippet maps to the focused standard
    return !arguments_.some(arg => {
      if (!arg.snippetIds?.includes(snippet.id)) return false;
      // Check AI-generated standardKey mapping
      const mappedStandardId = arg.standardKey ? STANDARD_KEY_TO_ID[arg.standardKey] : null;
      if (mappedStandardId === focusedStandardId) return true;
      // Check manual drag-drop mapping
      return argumentMappings.some(m => m.source === arg.id && m.target === focusedStandardId);
    });
  }, [focusState, snippet.id, arguments_, argumentMappings]);

  // Check if an argument is focused and this snippet is NOT part of that argument
  const isFilteredOutByArgument = focusState.type === 'argument' && focusState.id
    ? !arguments_.some(arg => arg.id === focusState.id && arg.snippetIds?.includes(snippet.id))
    : false;

  // Check if a sub-argument is focused and this snippet is NOT part of that sub-argument
  const isFilteredOutBySubArgument = focusState.type === 'subargument' && focusState.id
    ? !subArguments.some(sa => sa.id === focusState.id && sa.snippetIds?.includes(snippet.id))
    : false;

  const isFilteredOut = isFilteredOutByStandard || isFilteredOutByArgument || isFilteredOutBySubArgument;

  // Update position for SVG lines
  useEffect(() => {
    if (cardRef.current) {
      const updatePosition = () => {
        if (!cardRef.current) return;
        const rect = cardRef.current.getBoundingClientRect();
        updateSnippetPosition(snippet.id, {
          id: snippet.id,
          x: rect.right,
          y: rect.top + rect.height / 2,
          width: rect.width,
          height: rect.height,
        });
      };
      // Use requestAnimationFrame to ensure DOM has updated after layout changes
      requestAnimationFrame(updatePosition);
      window.addEventListener('resize', updatePosition);
      // Use capture mode (true) to catch scroll events from nested containers
      window.addEventListener('scroll', updatePosition, true);
      return () => {
        window.removeEventListener('resize', updatePosition);
        window.removeEventListener('scroll', updatePosition, true);
      };
    }
  }, [snippet.id, updateSnippetPosition, isExpanded, focusState]);

  const handleClick = () => {
    // Clicking Evidence Card only sets selectedSnippetId for PDF highlight
    // It does NOT change focusState (which controls filtering)
    if (selectedSnippetId === snippet.id) {
      setSelectedSnippetId(null);
    } else {
      setSelectedSnippetId(snippet.id);
      setSelectedDocumentId(snippet.documentId);
    }
  };

  const handleDragStart = (e: React.DragEvent) => {
    e.dataTransfer.setData('snippetId', snippet.id);
    e.dataTransfer.effectAllowed = 'link';
    setDraggedSnippetId(snippet.id);
  };

  const handleDragEnd = () => {
    setDraggedSnippetId(null);
  };

  // Get connected standards for display
  const connectedStandards = connections.map(conn => {
    const standard = getStandardById(conn.standardId);
    return standard ? { ...standard, isConfirmed: conn.isConfirmed } : null;
  }).filter(Boolean);

  // Filtered out cards have no connection to show, so completely hide them
  if (isFilteredOut) {
    return null;
  }

  return (
    <div
      ref={cardRef}
      draggable
      onDragStart={handleDragStart}
      onDragEnd={handleDragEnd}
      onClick={handleClick}
      className={`
        relative bg-white rounded-lg border transition-all duration-200 cursor-grab
        ${isDragging ? 'opacity-50 scale-95 cursor-grabbing' : ''}
        ${isAssembled ? 'opacity-60 border-green-400 bg-green-50/50' : ''}
        ${isFocused
          ? 'border-slate-900 ring-2 ring-slate-900 shadow-md z-10'
          : isHighlighted
            ? isAssembled ? 'border-green-400' : 'border-slate-200 hover:border-slate-300 hover:shadow-sm'
            : 'border-slate-100 opacity-30'
        }
      `}
    >
      {/* Card content */}
      <div className="p-2">
        {/* Header row */}
        <div className="flex items-start gap-1.5">
          {/* Drag handle */}
          <div className="flex-shrink-0 mt-0.5 cursor-grab active:cursor-grabbing">
            <DragHandleIcon />
          </div>

          {/* Main content */}
          <div className="flex-1 min-w-0">
            {/* Summary */}
            <p className="text-xs font-medium text-slate-900 leading-snug">
              {snippet.summary}
            </p>

            {/* Expandable full content */}
            {isExpanded && (
              <p className="mt-2 text-xs text-slate-600 leading-relaxed bg-slate-50 rounded p-2">
                {snippet.content}
              </p>
            )}

            {/* Tags row */}
            <div className="flex items-center gap-1 mt-1 flex-wrap">
              {/* Subject tag (from unified extraction) */}
              {snippet.subject && (
                <span
                  className={`inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded text-[10px] font-medium ${
                    snippet.isApplicantAchievement
                      ? 'bg-blue-100 text-blue-700'
                      : 'bg-slate-100 text-slate-600'
                  }`}
                  title={snippet.subjectRole || undefined}
                >
                  {snippet.subject}
                  {snippet.isApplicantAchievement && (
                    <svg className="w-2.5 h-2.5 text-blue-500" fill="currentColor" viewBox="0 0 20 20">
                      <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z" clipRule="evenodd" />
                    </svg>
                  )}
                </span>
              )}

              {/* Evidence type tag (from unified extraction) */}
              {snippet.evidenceType && (
                <span
                  className="inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-medium bg-amber-50 text-amber-700"
                >
                  {snippet.evidenceType}
                </span>
              )}

              {/* Material type tag (fallback if no evidence type) */}
              {!snippet.evidenceType && (
                <span
                  className="inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-medium"
                  style={{
                    backgroundColor: `${snippetColor}15`,
                    color: snippetColor,
                  }}
                >
                  {materialTypeLabels[snippet.materialType]}
                </span>
              )}

              {/* Assembled indicator - just checkmark */}
              {isAssembled && (
                <span className="inline-flex items-center justify-center w-4 h-4 rounded bg-green-100 text-green-700" title="Assembled">
                  <svg className="w-2.5 h-2.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={3} d="M5 13l4 4L19 7" />
                  </svg>
                </span>
              )}

              {/* Connected standards indicators */}
              {connectedStandards.slice(0, 2).map((std) => std && (
                <span
                  key={std.id}
                  className={`
                    inline-flex items-center gap-0.5 px-1 py-0.5 rounded text-[10px]
                    ${std.isConfirmed ? 'bg-slate-100 text-slate-600' : 'bg-slate-50 text-slate-400'}
                  `}
                >
                  <LinkIcon />
                  {std.shortName}
                </span>
              ))}
              {connectedStandards.length > 2 && (
                <span className="text-[10px] text-slate-400">
                  +{connectedStandards.length - 2}
                </span>
              )}
            </div>
          </div>

          {/* Expand button */}
          <button
            onClick={(e) => { e.stopPropagation(); setIsExpanded(!isExpanded); }}
            className={`
              flex-shrink-0 p-1 rounded transition-colors
              ${isExpanded ? 'bg-slate-100 text-slate-700' : 'text-slate-400 hover:text-slate-600 hover:bg-slate-50'}
            `}
          >
            <span className={`block transition-transform ${isExpanded ? 'rotate-180' : ''}`}>
              <ExpandIcon />
            </span>
          </button>
        </div>
      </div>

      {/* Color indicator bar */}
      <div
        className="absolute left-0 top-3 bottom-3 w-1 rounded-full"
        style={{ backgroundColor: snippetColor }}
      />
    </div>
  );
}

interface DocumentGroupProps {
  document: { id: string; name: string };
  snippets: Snippet[];
  filteredSnippets?: Snippet[]; // Snippets to actually display (may be filtered by focus)
}

function DocumentGroup({ document, snippets, filteredSnippets }: DocumentGroupProps) {
  const { focusState, setFocusState } = useApp();
  const [isCollapsed, setIsCollapsed] = useState(false);

  // Use filtered snippets if provided, otherwise use all snippets
  const displaySnippets = filteredSnippets || snippets;

  const isDocFocused = focusState.type === 'document' && focusState.id === document.id;

  const handleHeaderClick = () => {
    if (isDocFocused) {
      setFocusState({ type: 'none', id: null });
    } else {
      setFocusState({ type: 'document', id: document.id });
    }
  };

  return (
    <div className="mb-2">
      {/* Document header */}
      <button
        onClick={handleHeaderClick}
        className={`
          w-full flex items-center gap-2 px-2 py-1 rounded text-left transition-colors mb-1
          ${isDocFocused
            ? 'bg-slate-900 text-white'
            : 'bg-slate-100 text-slate-700 hover:bg-slate-200'
          }
        `}
      >
        <span
          onClick={(e) => { e.stopPropagation(); setIsCollapsed(!isCollapsed); }}
          className={`transition-transform ${isCollapsed ? '' : 'rotate-90'}`}
        >
          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
          </svg>
        </span>
        <svg className="w-4 h-4 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
        </svg>
        <span className="flex-1 text-sm font-medium truncate">{document.name}</span>
        <span className={`
          text-xs px-1.5 py-0.5 rounded
          ${isDocFocused ? 'bg-white/20' : 'bg-white'}
        `}>
          {displaySnippets.length}{filteredSnippets && filteredSnippets.length !== snippets.length ? `/${snippets.length}` : ''}
        </span>
      </button>

      {/* Snippets - render filtered snippets when in focus mode */}
      {!isCollapsed && (
        <div className="space-y-2 pl-2">
          {displaySnippets.map((snippet) => (
            <EvidenceCard
              key={snippet.id}
              snippet={snippet}
            />
          ))}
        </div>
      )}
    </div>
  );
}

// Graph icon for relationship button
const GraphIcon = () => (
  <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
    <circle cx="5" cy="6" r="2" strokeWidth={1.5} />
    <circle cx="12" cy="4" r="2" strokeWidth={1.5} />
    <circle cx="19" cy="6" r="2" strokeWidth={1.5} />
    <circle cx="5" cy="18" r="2" strokeWidth={1.5} />
    <circle cx="12" cy="20" r="2" strokeWidth={1.5} />
    <circle cx="19" cy="18" r="2" strokeWidth={1.5} />
    <path strokeLinecap="round" strokeWidth={1.5} d="M7 7l3 -2M14 3l3 2M7 17l3 2M14 21l3 -2M5 8v8M19 8v8M7 6h10M7 18h10" />
  </svg>
);

export function EvidenceCardPool() {
  const { t } = useTranslation();
  const { focusState, snippetPositions, connections, viewMode, setSnippetPanelBounds, allSnippets, arguments: arguments_, argumentMappings, subArguments } = useApp();
  const scrollContainerRef = useRef<HTMLDivElement>(null);
  const [containerRect, setContainerRect] = useState<DOMRect | null>(null);
  const [showGraphModal, setShowGraphModal] = useState(false);

  // Use snippets from context
  const snippets = allSnippets;

  // Helper: Check if a snippet is related to the current focus
  const isSnippetRelatedToFocus = useCallback((snippetId: string): boolean => {
    if (focusState.type === 'none' || !focusState.id) return true; // No filter when not focused

    if (focusState.type === 'argument') {
      // Check if snippet belongs to the focused argument
      const focusedArg = arguments_.find(arg => arg.id === focusState.id);
      return focusedArg?.snippetIds?.includes(snippetId) || false;
    }

    if (focusState.type === 'subargument') {
      // Check if snippet belongs to the focused sub-argument
      const focusedSubArg = subArguments.find(sa => sa.id === focusState.id);
      return focusedSubArg?.snippetIds?.includes(snippetId) || false;
    }

    if (focusState.type === 'standard') {
      // Check if snippet belongs to any argument that maps to the focused standard
      const focusedStandardId = focusState.id;
      return arguments_.some(arg => {
        if (!arg.snippetIds?.includes(snippetId)) return false;
        // Check AI-generated standardKey mapping
        const mappedStandardId = arg.standardKey ? STANDARD_KEY_TO_ID[arg.standardKey] : null;
        if (mappedStandardId === focusedStandardId) return true;
        // Check manual drag-drop mapping
        return argumentMappings.some(m => m.source === arg.id && m.target === focusedStandardId);
      });
    }

    return true;
  }, [focusState, arguments_, argumentMappings, subArguments]);

  // Update container rect on scroll, resize, and focusState change
  useEffect(() => {
    const container = scrollContainerRef.current;
    if (!container) return;

    const updateRect = () => {
      const rect = container.getBoundingClientRect();
      setContainerRect(rect);
      // Also update panel bounds for clipping connection lines
      setSnippetPanelBounds({
        top: rect.top,
        bottom: rect.bottom,
        left: rect.left,
        right: rect.right,
      });
      // Trigger custom event to notify all EvidenceCards to update their positions
      window.dispatchEvent(new CustomEvent('evidence-card-pool-scroll'));
    };

    // Use requestAnimationFrame to ensure DOM has updated after layout changes
    requestAnimationFrame(updateRect);
    container.addEventListener('scroll', updateRect);
    window.addEventListener('resize', updateRect);

    return () => {
      container.removeEventListener('scroll', updateRect);
      window.removeEventListener('resize', updateRect);
    };
  }, [setSnippetPanelBounds, focusState]);

  // Calculate hidden snippets with connections
  const { hiddenAbove, hiddenBelow } = useMemo(() => {
    if (!containerRect || viewMode !== 'line') {
      return { hiddenAbove: { count: 0, snippetIds: [] }, hiddenBelow: { count: 0, snippetIds: [] } };
    }

    const snippetIdsWithConnections = new Set(connections.map(c => c.snippetId));
    const aboveIds: string[] = [];
    const belowIds: string[] = [];
    let aboveCount = 0;
    let belowCount = 0;

    snippetPositions.forEach((pos, snippetId) => {
      if (!snippetIdsWithConnections.has(snippetId)) return;

      const connCount = connections.filter(c => c.snippetId === snippetId).length;

      // Check if snippet card is above visible area
      if (pos.y < containerRect.top) {
        aboveCount += connCount;
        if (!aboveIds.includes(snippetId)) aboveIds.push(snippetId);
      }
      // Check if snippet card is below visible area
      else if (pos.y > containerRect.bottom) {
        belowCount += connCount;
        if (!belowIds.includes(snippetId)) belowIds.push(snippetId);
      }
    });

    return {
      hiddenAbove: { count: aboveCount, snippetIds: aboveIds },
      hiddenBelow: { count: belowCount, snippetIds: belowIds },
    };
  }, [containerRect, snippetPositions, connections, viewMode]);

  // Scroll to first hidden snippet
  const scrollToSnippet = useCallback((snippetIds: string[], direction: 'up' | 'down') => {
    if (snippetIds.length === 0 || !scrollContainerRef.current) return;

    // Find the snippet position
    const targetId = direction === 'up' ? snippetIds[snippetIds.length - 1] : snippetIds[0];
    const targetPos = snippetPositions.get(targetId);

    if (targetPos && scrollContainerRef.current) {
      const container = scrollContainerRef.current;
      const containerTop = container.getBoundingClientRect().top;
      const currentScrollTop = container.scrollTop;

      // Calculate scroll target (center the card in view)
      const targetScrollTop = currentScrollTop + (targetPos.y - containerTop) - container.clientHeight / 2;

      container.scrollTo({
        top: Math.max(0, targetScrollTop),
        behavior: 'smooth',
      });
    }
  }, [snippetPositions]);

  // Group snippets by documentId (extracted from exhibits)
  // When focused, only show exhibits that have related snippets
  const snippetsByDocument = useMemo(() => {
    const groups: { document: { id: string; name: string }; snippets: Snippet[]; relatedSnippets: Snippet[] }[] = [];
    const docMap = new Map<string, Snippet[]>();

    snippets.forEach(s => {
      const docId = s.documentId || s.exhibitId || 'unknown';
      if (!docMap.has(docId)) {
        docMap.set(docId, []);
      }
      docMap.get(docId)!.push(s);
    });

    const hasFocus = focusState.type !== 'none' && focusState.id;

    docMap.forEach((snips, docId) => {
      // Filter to only related snippets when focused
      const relatedSnips = hasFocus
        ? snips.filter(s => isSnippetRelatedToFocus(s.id))
        : snips;

      // Skip this exhibit if no related snippets when focused
      if (hasFocus && relatedSnips.length === 0) return;

      // Extract exhibit name from docId (e.g., "doc_A1" -> "Exhibit A1")
      const exhibitName = docId.replace('doc_', '');
      groups.push({
        document: { id: docId, name: `Exhibit ${exhibitName}` },
        snippets: snips, // All snippets for this document
        relatedSnippets: relatedSnips, // Only related snippets (for display count)
      });
    });

    // Sort by document name
    groups.sort((a, b) => a.document.name.localeCompare(b.document.name));
    return groups;
  }, [snippets, focusState, isSnippetRelatedToFocus]);

  return (
    <div className="flex flex-col h-full bg-slate-50">
      {/* Header */}
      <div className="flex-shrink-0 px-4 py-2 bg-white border-b border-slate-200">
        <div className="flex items-center justify-between">
          <div>
            <h2 className="text-sm font-semibold text-slate-800">{t('evidence.title')}</h2>
            <p className="text-xs text-slate-500">
              {t('evidence.snippets', { count: snippets.length })}
            </p>
          </div>
          <button
            onClick={() => setShowGraphModal(true)}
            className="flex items-center gap-1.5 px-2.5 py-1.5 text-xs text-slate-500 hover:text-slate-700 hover:bg-slate-100 rounded-lg transition-colors"
            title="View Relationship Graph"
          >
            <GraphIcon />
            <span>Graph</span>
          </button>
        </div>
      </div>

      {/* Relationship Graph Modal */}
      <RelationshipGraphModal
        isOpen={showGraphModal}
        onClose={() => setShowGraphModal(false)}
      />

      {/* Cards list with scroll indicators */}
      <div className="flex-1 relative overflow-hidden">
        {/* Empty state when no snippets extracted */}
        {snippets.length === 0 ? (
          <div className="h-full flex items-center justify-center">
            <div className="text-center text-slate-400">
              <svg className="w-12 h-12 mx-auto mb-3 text-slate-300" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M19 11H5m14 0a2 2 0 012 2v6a2 2 0 01-2 2H5a2 2 0 01-2-2v-6a2 2 0 012-2m14 0V9a2 2 0 00-2-2M5 11V9a2 2 0 012-2m0 0V5a2 2 0 012-2h6a2 2 0 012 2v2M7 7h10" />
              </svg>
              <p className="text-sm font-medium">{t('evidence.noSnippetsYet', 'No evidence snippets yet')}</p>
              <p className="text-xs mt-1">{t('evidence.extractFirst', 'Click "Extract Snippets" to start')}</p>
            </div>
          </div>
        ) : (
          <>
            {/* Scroll indicators */}
            {viewMode === 'line' && (
              <>
                <ScrollIndicator
                  direction="up"
                  count={hiddenAbove.count}
                  snippetIds={hiddenAbove.snippetIds}
                  onClick={() => scrollToSnippet(hiddenAbove.snippetIds, 'up')}
                />
                <ScrollIndicator
                  direction="down"
                  count={hiddenBelow.count}
                  snippetIds={hiddenBelow.snippetIds}
                  onClick={() => scrollToSnippet(hiddenBelow.snippetIds, 'down')}
                />
              </>
            )}

            <div ref={scrollContainerRef} className="h-full overflow-y-auto p-2">
              {snippetsByDocument.map(({ document, snippets, relatedSnippets }) => (
                <DocumentGroup
                  key={document.id}
                  document={document}
                  snippets={snippets}
                  filteredSnippets={relatedSnippets}
                />
              ))}
            </div>
          </>
        )}
      </div>
    </div>
  );
}
