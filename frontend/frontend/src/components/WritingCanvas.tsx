import { useState, useRef, useEffect, useCallback } from 'react';
import { useTranslation } from 'react-i18next';
import { useApp } from '../context/AppContext';
import { legalStandards } from '../data/legalStandards';
import type { Position, Argument, WritingEdge, LetterSection } from '../types';

// ============================================
// Types for internal use
// ============================================

interface SnippetNode {
  id: string;
  type: 'snippet';
  position: Position;
  data: {
    summary: string;
    content: string;
    color: string;
  };
}

interface ArgumentNode {
  id: string;
  type: 'argument';
  position: Position;
  data: {
    title: string;
    description: string;
    isAIGenerated: boolean;
  };
}

interface StandardNode {
  id: string;
  type: 'standard';
  position: Position;
  data: {
    name: string;
    shortName: string;
    color: string;
  };
}

type NodeType = SnippetNode | ArgumentNode | StandardNode;

// ============================================
// Icons
// ============================================

const ZoomInIcon = () => (
  <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0zM10 7v6m3-3H7" />
  </svg>
);

const ZoomOutIcon = () => (
  <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0zM13 10H7" />
  </svg>
);

const FitIcon = () => (
  <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 8V4m0 0h4M4 4l5 5m11-1V4m0 0h-4m4 0l-5 5M4 16v4m0 0h4m-4 0l5-5m11 5l-5-5m5 5v-4m0 4h-4" />
  </svg>
);

const PlusIcon = () => (
  <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
  </svg>
);

const EditIcon = () => (
  <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15.232 5.232l3.536 3.536m-2.036-5.036a2.5 2.5 0 113.536 3.536L6.5 21.036H3v-3.572L16.732 3.732z" />
  </svg>
);

// ============================================
// Node Components
// ============================================

interface DraggableNodeProps {
  node: NodeType;
  isSelected: boolean;
  onSelect: () => void;
  onDrag: (id: string, position: Position) => void;
  scale: number;
  onStartDragConnect?: (nodeId: string) => void;
}

function SnippetNodeComponent({ node, isSelected, onSelect, onDrag, scale, onStartDragConnect }: DraggableNodeProps & { node: SnippetNode }) {
  const [isDragging, setIsDragging] = useState(false);
  const dragStartPos = useRef<Position | null>(null);
  const nodeStartPos = useRef<Position | null>(null);

  const handleMouseDown = (e: React.MouseEvent) => {
    e.stopPropagation();
    setIsDragging(true);
    dragStartPos.current = { x: e.clientX, y: e.clientY };
    nodeStartPos.current = { ...node.position };
    onSelect();
  };

  const handleConnectDrag = (e: React.MouseEvent) => {
    e.stopPropagation();
    onStartDragConnect?.(node.id);
  };

  useEffect(() => {
    if (!isDragging) return;

    const handleMouseMove = (e: MouseEvent) => {
      if (!dragStartPos.current || !nodeStartPos.current) return;
      const dx = (e.clientX - dragStartPos.current.x) / scale;
      const dy = (e.clientY - dragStartPos.current.y) / scale;
      onDrag(node.id, {
        x: nodeStartPos.current.x + dx,
        y: nodeStartPos.current.y + dy,
      });
    };

    const handleMouseUp = () => {
      setIsDragging(false);
      dragStartPos.current = null;
      nodeStartPos.current = null;
    };

    window.addEventListener('mousemove', handleMouseMove);
    window.addEventListener('mouseup', handleMouseUp);
    return () => {
      window.removeEventListener('mousemove', handleMouseMove);
      window.removeEventListener('mouseup', handleMouseUp);
    };
  }, [isDragging, node.id, onDrag, scale]);

  return (
    <div
      className={`
        absolute cursor-grab active:cursor-grabbing select-none
        ${isDragging ? 'z-50' : 'z-10'}
      `}
      style={{
        left: node.position.x,
        top: node.position.y,
        transform: 'translate(-50%, -50%)',
        pointerEvents: 'auto',
      }}
      onMouseDown={handleMouseDown}
    >
      <div
        className={`
          w-[160px] p-3 rounded-lg border-2 bg-white shadow-md transition-all relative group
          ${isSelected ? 'ring-2 ring-offset-2 ring-blue-400 shadow-lg' : 'hover:shadow-lg'}
        `}
        style={{ borderColor: node.data.color }}
      >
        <div className="flex items-start gap-2">
          <div
            className="w-2 h-2 rounded-full flex-shrink-0 mt-1"
            style={{ backgroundColor: node.data.color }}
          />
          <p className="text-xs text-slate-700 line-clamp-3">{node.data.summary}</p>
        </div>
        <div className="mt-2 text-[10px] text-slate-400">Snippet</div>
        {/* Connection handle */}
        <div
          className="absolute -right-2 top-1/2 -translate-y-1/2 w-4 h-4 bg-blue-500 rounded-full opacity-0 group-hover:opacity-100 cursor-crosshair transition-opacity flex items-center justify-center"
          onMouseDown={handleConnectDrag}
          title="Drag to connect"
        >
          <div className="w-2 h-2 bg-white rounded-full" />
        </div>
      </div>
    </div>
  );
}

function ArgumentNodeComponent({
  node,
  isSelected,
  onSelect,
  onDrag,
  scale,
  onTitleChange,
  onStartDragConnect,
}: DraggableNodeProps & {
  node: ArgumentNode;
  onTitleChange?: (id: string, title: string) => void;
}) {
  const { t } = useTranslation();
  const [isDragging, setIsDragging] = useState(false);
  const [isEditing, setIsEditing] = useState(false);
  const [title, setTitle] = useState(node.data.title);
  const dragStartPos = useRef<Position | null>(null);
  const nodeStartPos = useRef<Position | null>(null);

  const handleMouseDown = (e: React.MouseEvent) => {
    if (isEditing) return;
    e.stopPropagation();
    setIsDragging(true);
    dragStartPos.current = { x: e.clientX, y: e.clientY };
    nodeStartPos.current = { ...node.position };
    onSelect();
  };

  const handleSaveTitle = () => {
    setIsEditing(false);
    onTitleChange?.(node.id, title);
  };

  const handleConnectDrag = (e: React.MouseEvent) => {
    e.stopPropagation();
    onStartDragConnect?.(node.id);
  };

  useEffect(() => {
    if (!isDragging) return;

    const handleMouseMove = (e: MouseEvent) => {
      if (!dragStartPos.current || !nodeStartPos.current) return;
      const dx = (e.clientX - dragStartPos.current.x) / scale;
      const dy = (e.clientY - dragStartPos.current.y) / scale;
      onDrag(node.id, {
        x: nodeStartPos.current.x + dx,
        y: nodeStartPos.current.y + dy,
      });
    };

    const handleMouseUp = () => {
      setIsDragging(false);
      dragStartPos.current = null;
      nodeStartPos.current = null;
    };

    window.addEventListener('mousemove', handleMouseMove);
    window.addEventListener('mouseup', handleMouseUp);
    return () => {
      window.removeEventListener('mousemove', handleMouseMove);
      window.removeEventListener('mouseup', handleMouseUp);
    };
  }, [isDragging, node.id, onDrag, scale]);

  return (
    <div
      className={`
        absolute cursor-grab active:cursor-grabbing select-none
        ${isDragging ? 'z-50' : 'z-20'}
      `}
      style={{
        left: node.position.x,
        top: node.position.y,
        transform: 'translate(-50%, -50%)',
        pointerEvents: 'auto',
      }}
      onMouseDown={handleMouseDown}
    >
      <div
        className={`
          w-[180px] p-3 rounded-xl border-2 border-purple-400 bg-purple-50 shadow-md transition-all relative group
          ${isSelected ? 'ring-2 ring-offset-2 ring-purple-400 shadow-lg' : 'hover:shadow-lg'}
        `}
      >
        <div className="flex items-center justify-between gap-2 mb-1">
          {isEditing ? (
            <input
              type="text"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              onBlur={handleSaveTitle}
              onKeyDown={(e) => e.key === 'Enter' && handleSaveTitle()}
              className="flex-1 text-sm font-semibold text-purple-800 bg-white border border-purple-300 rounded px-1"
              autoFocus
            />
          ) : (
            <span className="text-sm font-semibold text-purple-800">{node.data.title}</span>
          )}
          <button
            onClick={(e) => {
              e.stopPropagation();
              setIsEditing(true);
            }}
            className="p-1 text-purple-400 hover:text-purple-600 transition-colors"
          >
            <EditIcon />
          </button>
        </div>
        <p className="text-xs text-purple-600">{node.data.description}</p>
        <div className="mt-2 flex items-center justify-between">
          <span className="text-[10px] text-purple-400 font-medium">{t('writing.nodeTypes.argument')}</span>
          {node.data.isAIGenerated && (
            <span className="text-[9px] px-1.5 py-0.5 bg-purple-200 text-purple-700 rounded">AI</span>
          )}
        </div>
        {/* Connection handle */}
        <div
          className="absolute -right-2 top-1/2 -translate-y-1/2 w-4 h-4 bg-purple-500 rounded-full opacity-0 group-hover:opacity-100 cursor-crosshair transition-opacity flex items-center justify-center"
          onMouseDown={handleConnectDrag}
          title="Drag to connect"
        >
          <div className="w-2 h-2 bg-white rounded-full" />
        </div>
      </div>
    </div>
  );
}

function StandardNodeComponent({ node, isSelected, onSelect, onDrag, scale }: DraggableNodeProps & { node: StandardNode }) {
  const [isDragging, setIsDragging] = useState(false);
  const dragStartPos = useRef<Position | null>(null);
  const nodeStartPos = useRef<Position | null>(null);

  const handleMouseDown = (e: React.MouseEvent) => {
    e.stopPropagation();
    setIsDragging(true);
    dragStartPos.current = { x: e.clientX, y: e.clientY };
    nodeStartPos.current = { ...node.position };
    onSelect();
  };

  useEffect(() => {
    if (!isDragging) return;

    const handleMouseMove = (e: MouseEvent) => {
      if (!dragStartPos.current || !nodeStartPos.current) return;
      const dx = (e.clientX - dragStartPos.current.x) / scale;
      const dy = (e.clientY - dragStartPos.current.y) / scale;
      onDrag(node.id, {
        x: nodeStartPos.current.x + dx,
        y: nodeStartPos.current.y + dy,
      });
    };

    const handleMouseUp = () => {
      setIsDragging(false);
      dragStartPos.current = null;
      nodeStartPos.current = null;
    };

    window.addEventListener('mousemove', handleMouseMove);
    window.addEventListener('mouseup', handleMouseUp);
    return () => {
      window.removeEventListener('mousemove', handleMouseMove);
      window.removeEventListener('mouseup', handleMouseUp);
    };
  }, [isDragging, node.id, onDrag, scale]);

  return (
    <div
      className={`
        absolute cursor-grab active:cursor-grabbing select-none
        ${isDragging ? 'z-50' : 'z-30'}
      `}
      style={{
        left: node.position.x,
        top: node.position.y,
        transform: 'translate(-50%, -50%)',
        pointerEvents: 'auto',
      }}
      onMouseDown={handleMouseDown}
    >
      <div
        className={`
          w-[140px] p-3 rounded-xl border-3 bg-white shadow-lg transition-all
          ${isSelected ? 'ring-2 ring-offset-2 shadow-xl scale-105' : 'hover:shadow-xl'}
        `}
        style={{
          borderColor: node.data.color,
          borderWidth: '3px',
        }}
      >
        <div className="flex items-center gap-2">
          <div
            className="w-4 h-4 rounded-full flex-shrink-0"
            style={{ backgroundColor: node.data.color }}
          />
          <span className="text-sm font-bold text-slate-800">{node.data.shortName}</span>
        </div>
        <div className="mt-1 text-[10px] text-slate-400">Standard</div>
      </div>
    </div>
  );
}

// ============================================
// Connection Lines
// ============================================

interface ConnectionLinesProps {
  edges: WritingEdge[];
  nodes: Map<string, NodeType>;
  selectedEdgeId: string | null;
  onSelectEdge: (edgeId: string | null) => void;
  onDeleteEdge: (edgeId: string) => void;
}

function ConnectionLines({ edges, nodes, selectedEdgeId, onSelectEdge, onDeleteEdge }: ConnectionLinesProps) {
  const [hoveredEdgeId, setHoveredEdgeId] = useState<string | null>(null);

  return (
    <svg className="absolute inset-0 w-full h-full" style={{ zIndex: 5, pointerEvents: 'none' }}>
      <defs>
        <marker id="arrowhead" markerWidth="10" markerHeight="7" refX="9" refY="3.5" orient="auto">
          <polygon points="0 0, 10 3.5, 0 7" fill="#94a3b8" />
        </marker>
        <marker id="arrowhead-selected" markerWidth="10" markerHeight="7" refX="9" refY="3.5" orient="auto">
          <polygon points="0 0, 10 3.5, 0 7" fill="#3b82f6" />
        </marker>
        <marker id="arrowhead-hover" markerWidth="10" markerHeight="7" refX="9" refY="3.5" orient="auto">
          <polygon points="0 0, 10 3.5, 0 7" fill="#64748b" />
        </marker>
        <marker id="arrowhead-confirmed" markerWidth="10" markerHeight="7" refX="9" refY="3.5" orient="auto">
          <polygon points="0 0, 10 3.5, 0 7" fill="#22c55e" />
        </marker>
      </defs>
      {edges.map(edge => {
        const sourceNode = nodes.get(edge.source);
        const targetNode = nodes.get(edge.target);
        if (!sourceNode || !targetNode) return null;

        const x1 = sourceNode.position.x;
        const y1 = sourceNode.position.y;
        const x2 = targetNode.position.x;
        const y2 = targetNode.position.y;

        const midX = (x1 + x2) / 2;
        const pathD = `M ${x1} ${y1} C ${midX} ${y1}, ${midX} ${y2}, ${x2} ${y2}`;

        const isSelected = selectedEdgeId === edge.id;
        const isHovered = hoveredEdgeId === edge.id;

        // Determine stroke color and marker based on state
        let strokeColor = edge.isConfirmed ? '#22c55e' : '#94a3b8';
        let markerEnd = edge.isConfirmed ? 'url(#arrowhead-confirmed)' : 'url(#arrowhead)';
        if (isSelected) {
          strokeColor = '#3b82f6';
          markerEnd = 'url(#arrowhead-selected)';
        } else if (isHovered) {
          strokeColor = '#64748b';
          markerEnd = 'url(#arrowhead-hover)';
        }

        return (
          <g key={edge.id}>
            {/* Invisible wider path for easier clicking */}
            <path
              d={pathD}
              fill="none"
              stroke="transparent"
              strokeWidth={16}
              style={{ pointerEvents: 'stroke', cursor: 'pointer' }}
              onClick={(e) => {
                e.stopPropagation();
                onSelectEdge(edge.id);
              }}
              onMouseEnter={() => setHoveredEdgeId(edge.id)}
              onMouseLeave={() => setHoveredEdgeId(null)}
            />
            {/* Visible path */}
            <path
              d={pathD}
              fill="none"
              stroke={strokeColor}
              strokeWidth={isSelected ? 3 : isHovered ? 2.5 : 2}
              strokeDasharray={edge.isConfirmed ? 'none' : '5,5'}
              markerEnd={markerEnd}
              style={{ pointerEvents: 'none', transition: 'stroke 0.15s, stroke-width 0.15s' }}
            />
            {/* Delete button when selected */}
            {isSelected && (
              <g
                style={{ cursor: 'pointer', pointerEvents: 'auto' }}
                onClick={(e) => {
                  e.stopPropagation();
                  onDeleteEdge(edge.id);
                }}
              >
                <circle
                  cx={midX}
                  cy={(y1 + y2) / 2}
                  r={12}
                  fill="#ef4444"
                  className="transition-all hover:r-14"
                />
                <text
                  x={midX}
                  y={(y1 + y2) / 2}
                  textAnchor="middle"
                  dominantBaseline="central"
                  fill="white"
                  fontSize={14}
                  fontWeight="bold"
                  style={{ pointerEvents: 'none' }}
                >
                  ×
                </text>
              </g>
            )}
          </g>
        );
      })}
    </svg>
  );
}

// ============================================
// Drag Connection Line (for creating new edges)
// ============================================

interface DragConnectionLineProps {
  startPos: Position;
  endPos: Position;
}

function DragConnectionLine({ startPos, endPos }: DragConnectionLineProps) {
  const midX = (startPos.x + endPos.x) / 2;
  const pathD = `M ${startPos.x} ${startPos.y} C ${midX} ${startPos.y}, ${midX} ${endPos.y}, ${endPos.x} ${endPos.y}`;

  return (
    <svg className="absolute inset-0 w-full h-full pointer-events-none" style={{ zIndex: 100 }}>
      <path
        d={pathD}
        fill="none"
        stroke="#3b82f6"
        strokeWidth={2}
        strokeDasharray="8,4"
        opacity={0.7}
      />
      <circle cx={endPos.x} cy={endPos.y} r={6} fill="#3b82f6" opacity={0.7} />
    </svg>
  );
}

// ============================================
// Letter Section Component
// ============================================

interface LetterSectionComponentProps {
  section: LetterSection;
  isHighlighted: boolean;
  onHover: (standardId?: string) => void;
  onEdit: (id: string, content: string) => void;
  onSentenceClick?: (snippetIds: string[]) => void;
  highlightedSnippetIds?: string[];
}

function LetterSectionComponent({ section, isHighlighted, onHover, onEdit, onSentenceClick, highlightedSnippetIds = [] }: LetterSectionComponentProps) {
  const { t } = useTranslation();
  const [isEditing, setIsEditing] = useState(false);
  const [editContent, setEditContent] = useState(section.content);
  const [hoveredSentenceIdx, setHoveredSentenceIdx] = useState<number | null>(null);

  const handleSave = () => {
    onEdit(section.id, editContent);
    setIsEditing(false);
  };

  // Render content with sentence-level provenance highlighting
  const renderContent = () => {
    if (!section.sentences || section.sentences.length === 0) {
      // No sentence-level provenance - just render plain text
      return (
        <p className="text-sm text-slate-600 whitespace-pre-wrap leading-relaxed">
          {section.content}
        </p>
      );
    }

    // Render each sentence as a clickable span with provenance info
    return (
      <div className="text-sm text-slate-600 leading-relaxed">
        {section.sentences.map((sentence, idx) => {
          const hasProvenance = sentence.snippet_ids && sentence.snippet_ids.length > 0;
          const isHovered = hoveredSentenceIdx === idx;
          const isHighlightedSentence = hasProvenance &&
            sentence.snippet_ids.some(id => highlightedSnippetIds.includes(id));

          return (
            <span
              key={idx}
              onClick={() => hasProvenance && onSentenceClick?.(sentence.snippet_ids)}
              onMouseEnter={() => setHoveredSentenceIdx(idx)}
              onMouseLeave={() => setHoveredSentenceIdx(null)}
              className={`
                ${hasProvenance ? 'cursor-pointer' : ''}
                ${isHovered && hasProvenance ? 'bg-blue-100 rounded' : ''}
                ${isHighlightedSentence ? 'bg-yellow-100 rounded' : ''}
                transition-colors
              `}
              title={hasProvenance ? `Sources: ${sentence.snippet_ids.length} snippet(s)` : undefined}
            >
              {sentence.text}
              {hasProvenance && (
                <sup className="text-[10px] text-blue-500 ml-0.5">
                  [{sentence.snippet_ids.length}]
                </sup>
              )}
              {' '}
            </span>
          );
        })}
      </div>
    );
  };

  return (
    <div
      className={`
        p-4 border-b border-slate-200 transition-all
        ${isHighlighted ? 'bg-blue-50 border-l-4 border-l-blue-400' : 'hover:bg-slate-50'}
      `}
      onMouseEnter={() => onHover(section.standardId)}
      onMouseLeave={() => onHover(undefined)}
    >
      <div className="flex items-center justify-between mb-2">
        <h3 className="text-sm font-semibold text-slate-800">{section.title}</h3>
        <div className="flex items-center gap-2">
          {section.isGenerated && (
            <span className="text-[10px] px-2 py-0.5 bg-green-100 text-green-700 rounded-full">
              {t('writing.aiGenerated')}
            </span>
          )}
          {section.sentences && section.sentences.length > 0 && (
            <span className="text-[10px] px-2 py-0.5 bg-blue-100 text-blue-700 rounded-full">
              {section.sentences.filter(s => s.snippet_ids?.length > 0).length} sources
            </span>
          )}
          {!isEditing && (
            <button
              onClick={() => setIsEditing(true)}
              className="text-xs text-slate-400 hover:text-slate-600"
            >
              {t('common.edit')}
            </button>
          )}
        </div>
      </div>

      {isEditing ? (
        <div className="space-y-2">
          <textarea
            value={editContent}
            onChange={(e) => setEditContent(e.target.value)}
            className="w-full h-32 text-sm text-slate-700 border border-slate-300 rounded-lg p-2 resize-none focus:outline-none focus:ring-2 focus:ring-blue-400"
          />
          <div className="flex gap-2">
            <button
              onClick={handleSave}
              className="text-xs px-3 py-1 bg-blue-500 text-white rounded hover:bg-blue-600"
            >
              {t('common.save')}
            </button>
            <button
              onClick={() => {
                setEditContent(section.content);
                setIsEditing(false);
              }}
              className="text-xs px-3 py-1 bg-slate-200 text-slate-700 rounded hover:bg-slate-300"
            >
              {t('common.cancel')}
            </button>
          </div>
        </div>
      ) : (
        renderContent()
      )}
    </div>
  );
}

// ============================================
// Main Component
// ============================================

export function WritingCanvas() {
  const { t } = useTranslation();
  const {
    allSnippets,
    arguments: contextArguments,
    writingEdges,
    letterSections,
    writingNodePositions,
    addArgument,
    updateArgument,
    updateArgumentPosition,
    addWritingEdge,
    removeWritingEdge,
    updateLetterSection,
    updateWritingNodePosition,
  } = useApp();

  const containerRef = useRef<HTMLDivElement>(null);
  const [scale, setScale] = useState(1);
  const [offset, setOffset] = useState<Position>({ x: 0, y: 0 });
  const [isPanning, setIsPanning] = useState(false);
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [selectedEdgeId, setSelectedEdgeId] = useState<string | null>(null);
  const [hoveredStandardId, setHoveredStandardId] = useState<string | undefined>(undefined);
  const panStartPos = useRef<Position | null>(null);
  const offsetStartPos = useRef<Position | null>(null);

  // Drag-to-connect state
  const [isDraggingConnection, setIsDraggingConnection] = useState(false);
  const [dragConnectionSource, setDragConnectionSource] = useState<string | null>(null);
  const [dragConnectionEnd, setDragConnectionEnd] = useState<Position | null>(null);

  // Provenance highlighting state
  const [highlightedSnippetIds, setHighlightedSnippetIds] = useState<string[]>([]);

  // Handle sentence click for provenance highlighting
  const handleSentenceClick = useCallback((snippetIds: string[]) => {
    setHighlightedSnippetIds(snippetIds);
    // Auto-clear after 3 seconds
    setTimeout(() => setHighlightedSnippetIds([]), 3000);
  }, []);

  // Build snippet nodes from context
  const snippetNodes: SnippetNode[] = allSnippets
    .filter(s => writingEdges.some(e => e.source === s.id))
    .map(s => ({
      id: s.id,
      type: 'snippet' as const,
      position: writingNodePositions.get(s.id) || { x: 120, y: 80 },
      data: {
        summary: s.summary,
        content: s.content,
        color: s.color,
      },
    }));

  // Build argument nodes from context
  const argumentNodes: ArgumentNode[] = contextArguments.map(arg => ({
    id: arg.id,
    type: 'argument' as const,
    position: arg.position,
    data: {
      title: arg.title,
      description: arg.description,
      isAIGenerated: arg.isAIGenerated,
    },
  }));

  // Build standard nodes
  const connectedStandardIds = new Set(writingEdges.filter(e => e.type === 'argument-to-standard').map(e => e.target));
  const standardNodes: StandardNode[] = legalStandards
    .filter(s => connectedStandardIds.has(s.id))
    .map(s => ({
      id: s.id,
      type: 'standard' as const,
      position: writingNodePositions.get(s.id) || { x: 680, y: 120 },
      data: {
        name: s.name,
        shortName: s.shortName,
        color: s.color,
      },
    }));

  // Create a map of all nodes for easy lookup
  const nodesMap = new Map<string, NodeType>();
  snippetNodes.forEach(n => nodesMap.set(n.id, n));
  argumentNodes.forEach(n => nodesMap.set(n.id, n));
  standardNodes.forEach(n => nodesMap.set(n.id, n));

  // Handle node drag
  const handleNodeDrag = useCallback((id: string, position: Position) => {
    if (id.startsWith('arg')) {
      updateArgumentPosition(id, position);
    } else {
      updateWritingNodePosition(id, position);
    }
  }, [updateArgumentPosition, updateWritingNodePosition]);

  // Handle argument title change
  const handleArgumentTitleChange = useCallback((id: string, title: string) => {
    updateArgument(id, { title });
  }, [updateArgument]);

  // Handle start drag connection
  const handleStartDragConnect = useCallback((nodeId: string) => {
    const node = nodesMap.get(nodeId);
    if (node) {
      setIsDraggingConnection(true);
      setDragConnectionSource(nodeId);
      setDragConnectionEnd(node.position);
    }
  }, [nodesMap]);

  // Handle canvas mouse events
  const handleCanvasMouseDown = (e: React.MouseEvent) => {
    const target = e.target as Element;
    const isCanvasClick = e.target === e.currentTarget || target.closest('svg') !== null;

    if (isCanvasClick && !isDraggingConnection) {
      setIsPanning(true);
      panStartPos.current = { x: e.clientX, y: e.clientY };
      offsetStartPos.current = { ...offset };
      setSelectedNodeId(null);
      setSelectedEdgeId(null);
    }
  };

  // Handle mouse move for panning and drag connection
  useEffect(() => {
    const handleMouseMove = (e: MouseEvent) => {
      if (isPanning && panStartPos.current && offsetStartPos.current) {
        setOffset({
          x: offsetStartPos.current.x + (e.clientX - panStartPos.current.x),
          y: offsetStartPos.current.y + (e.clientY - panStartPos.current.y),
        });
      }

      if (isDraggingConnection && containerRef.current) {
        const rect = containerRef.current.getBoundingClientRect();
        const x = (e.clientX - rect.left - offset.x) / scale;
        const y = (e.clientY - rect.top - offset.y) / scale;
        setDragConnectionEnd({ x, y });
      }
    };

    const handleMouseUp = (e: MouseEvent) => {
      if (isPanning) {
        setIsPanning(false);
        panStartPos.current = null;
        offsetStartPos.current = null;
      }

      if (isDraggingConnection && dragConnectionSource && containerRef.current) {
        // Check if dropped on a valid target
        const rect = containerRef.current.getBoundingClientRect();
        const x = (e.clientX - rect.left - offset.x) / scale;
        const y = (e.clientY - rect.top - offset.y) / scale;

        // Find target node
        let targetNode: NodeType | null = null;
        for (const [, node] of nodesMap) {
          const dx = Math.abs(node.position.x - x);
          const dy = Math.abs(node.position.y - y);
          if (dx < 80 && dy < 40) {
            targetNode = node;
            break;
          }
        }

        if (targetNode && targetNode.id !== dragConnectionSource) {
          const sourceNode = nodesMap.get(dragConnectionSource);
          if (sourceNode) {
            // Determine edge type based on source and target
            let edgeType: WritingEdge['type'] | null = null;
            if (sourceNode.type === 'snippet' && targetNode.type === 'argument') {
              edgeType = 'snippet-to-argument';
            } else if (sourceNode.type === 'argument' && targetNode.type === 'standard') {
              edgeType = 'argument-to-standard';
            }

            if (edgeType) {
              addWritingEdge(dragConnectionSource, targetNode.id, edgeType);
            }
          }
        }

        setIsDraggingConnection(false);
        setDragConnectionSource(null);
        setDragConnectionEnd(null);
      }
    };

    window.addEventListener('mousemove', handleMouseMove);
    window.addEventListener('mouseup', handleMouseUp);
    return () => {
      window.removeEventListener('mousemove', handleMouseMove);
      window.removeEventListener('mouseup', handleMouseUp);
    };
  }, [isPanning, isDraggingConnection, dragConnectionSource, offset, scale, nodesMap, addWritingEdge]);

  // Handle zoom
  const handleZoom = useCallback((delta: number) => {
    setScale(prev => Math.max(0.25, Math.min(2, prev + delta)));
  }, []);

  const handleFit = () => {
    setScale(1);
    setOffset({ x: 0, y: 0 });
  };

  // Handle mouse wheel zoom
  const handleWheel = useCallback((e: WheelEvent) => {
    e.preventDefault();
    const delta = e.deltaY > 0 ? -0.1 : 0.1;
    setScale(prev => Math.max(0.25, Math.min(2, prev + delta)));
  }, []);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    container.addEventListener('wheel', handleWheel, { passive: false });
    return () => {
      container.removeEventListener('wheel', handleWheel);
    };
  }, [handleWheel]);

  // Handle keyboard shortcuts
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Delete' || e.key === 'Backspace') {
        if (selectedEdgeId) {
          removeWritingEdge(selectedEdgeId);
          setSelectedEdgeId(null);
        }
      }
      if (e.key === 'Escape') {
        setSelectedNodeId(null);
        setSelectedEdgeId(null);
        if (isDraggingConnection) {
          setIsDraggingConnection(false);
          setDragConnectionSource(null);
          setDragConnectionEnd(null);
        }
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [selectedEdgeId, removeWritingEdge, isDraggingConnection]);

  // Add new argument node
  const handleAddArgument = () => {
    addArgument({
      title: t('writing.newArgument'),
      description: t('writing.clickToEdit'),
      position: { x: 400, y: 300 },
      isAIGenerated: false,
    });
  };

  // Handle edge selection
  const handleSelectEdge = (edgeId: string | null) => {
    setSelectedEdgeId(edgeId);
    setSelectedNodeId(null);
  };

  // Handle edge deletion
  const handleDeleteEdge = (edgeId: string) => {
    removeWritingEdge(edgeId);
    setSelectedEdgeId(null);
  };

  // Check if a standard is highlighted
  const isStandardHighlighted = (standardId: string) => {
    return hoveredStandardId === standardId;
  };

  // Get source position for drag connection line
  const dragSourceNode = dragConnectionSource ? nodesMap.get(dragConnectionSource) : null;

  return (
    <div className="flex flex-col h-full bg-slate-100">
      {/* Header */}
      <div className="flex-shrink-0 px-6 py-3 bg-white border-b border-slate-200">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-lg font-semibold text-slate-900">{t('writing.title')}</h1>
            <p className="text-xs text-slate-500 mt-0.5">{t('writing.subtitle')}</p>
          </div>
          <div className="flex items-center gap-3">
            <button
              onClick={handleAddArgument}
              className="flex items-center gap-2 px-3 py-1.5 text-sm text-purple-700 bg-purple-100 hover:bg-purple-200 rounded-lg transition-colors"
            >
              <PlusIcon />
              <span>{t('writing.addArgument')}</span>
            </button>
            <button className="flex items-center gap-2 px-3 py-1.5 text-sm text-white bg-blue-600 hover:bg-blue-700 rounded-lg transition-colors">
              <span>{t('writing.generateDocument')}</span>
            </button>
            <select className="text-sm border border-slate-200 rounded-lg px-3 py-1.5 bg-white">
              <option>{t('templates.eb1a')}</option>
              <option>{t('templates.eb1b')}</option>
              <option>{t('templates.niw')}</option>
            </select>
          </div>
        </div>
      </div>

      {/* Main content: Split view */}
      <div className="flex-1 flex overflow-hidden">
        {/* Left Panel: Node Graph Canvas */}
        <div className="flex-1 relative overflow-hidden border-r border-slate-300">
          {/* Zoom controls */}
          <div className="absolute top-4 right-4 z-50 flex flex-col gap-1 bg-white rounded-lg shadow-lg border border-slate-200 p-1">
            <button onClick={() => handleZoom(0.1)} className="p-2 hover:bg-slate-100 rounded transition-colors" title="Zoom In">
              <ZoomInIcon />
            </button>
            <button onClick={() => handleZoom(-0.1)} className="p-2 hover:bg-slate-100 rounded transition-colors" title="Zoom Out">
              <ZoomOutIcon />
            </button>
            <div className="border-t border-slate-200 my-1" />
            <button onClick={handleFit} className="p-2 hover:bg-slate-100 rounded transition-colors" title="Fit to View">
              <FitIcon />
            </button>
          </div>

          {/* Scale indicator */}
          <div className="absolute bottom-4 right-4 z-50 bg-white/80 backdrop-blur-sm px-3 py-1 rounded-lg border border-slate-200 text-sm text-slate-600">
            {Math.round(scale * 100)}%
          </div>

          {/* Legend */}
          <div className="absolute top-4 left-4 z-50 bg-white/90 backdrop-blur-sm p-3 rounded-lg border border-slate-200 text-xs space-y-2">
            <div className="flex items-center gap-2">
              <div className="w-3 h-3 rounded border-2 border-slate-400 bg-white" />
              <span>{t('writing.nodeTypes.snippet')}</span>
            </div>
            <div className="flex items-center gap-2">
              <div className="w-3 h-3 rounded-lg bg-purple-100 border-2 border-purple-400" />
              <span>{t('writing.nodeTypes.argument')}</span>
            </div>
            <div className="flex items-center gap-2">
              <div className="w-3 h-3 rounded-lg border-3 border-blue-500 bg-white" />
              <span>{t('writing.nodeTypes.standard')}</span>
            </div>
            <div className="border-t border-slate-200 pt-2 mt-2 space-y-1">
              <div className="flex items-center gap-2">
                <div className="w-6 h-0.5 bg-green-500" />
                <span>Confirmed</span>
              </div>
              <div className="flex items-center gap-2">
                <div className="w-6 h-0.5 border-t-2 border-dashed border-slate-400" />
                <span>AI Suggested</span>
              </div>
            </div>
          </div>

          {/* Canvas area */}
          <div
            ref={containerRef}
            className={`absolute inset-0 ${isPanning ? 'cursor-grabbing' : isDraggingConnection ? 'cursor-crosshair' : 'cursor-grab'}`}
            onMouseDown={handleCanvasMouseDown}
          >
            {/* Grid background */}
            <svg className="absolute inset-0 w-full h-full" style={{ zIndex: 0 }}>
              <defs>
                <pattern
                  id="grid"
                  width={40 * scale}
                  height={40 * scale}
                  patternUnits="userSpaceOnUse"
                  x={offset.x % (40 * scale)}
                  y={offset.y % (40 * scale)}
                >
                  <path
                    d={`M ${40 * scale} 0 L 0 0 0 ${40 * scale}`}
                    fill="none"
                    stroke="#e2e8f0"
                    strokeWidth="1"
                  />
                </pattern>
              </defs>
              <rect width="100%" height="100%" fill="url(#grid)" />
            </svg>

            {/* Transformed content */}
            <div
              style={{
                transform: `translate(${offset.x}px, ${offset.y}px) scale(${scale})`,
                transformOrigin: '0 0',
                position: 'absolute',
                width: '2000px',
                height: '1500px',
                pointerEvents: 'none',
              }}
            >
              {/* Connection lines */}
              <ConnectionLines
                edges={writingEdges}
                nodes={nodesMap}
                selectedEdgeId={selectedEdgeId}
                onSelectEdge={handleSelectEdge}
                onDeleteEdge={handleDeleteEdge}
              />

              {/* Drag connection line */}
              {isDraggingConnection && dragSourceNode && dragConnectionEnd && (
                <DragConnectionLine startPos={dragSourceNode.position} endPos={dragConnectionEnd} />
              )}

              {/* Snippet nodes */}
              {snippetNodes.map(node => (
                <SnippetNodeComponent
                  key={node.id}
                  node={node}
                  isSelected={selectedNodeId === node.id}
                  onSelect={() => { setSelectedNodeId(node.id); setSelectedEdgeId(null); }}
                  onDrag={handleNodeDrag}
                  scale={scale}
                  onStartDragConnect={handleStartDragConnect}
                />
              ))}

              {/* Argument nodes */}
              {argumentNodes.map(node => (
                <ArgumentNodeComponent
                  key={node.id}
                  node={node}
                  isSelected={selectedNodeId === node.id}
                  onSelect={() => { setSelectedNodeId(node.id); setSelectedEdgeId(null); }}
                  onDrag={handleNodeDrag}
                  scale={scale}
                  onTitleChange={handleArgumentTitleChange}
                  onStartDragConnect={handleStartDragConnect}
                />
              ))}

              {/* Standard nodes */}
              {standardNodes.map(node => (
                <StandardNodeComponent
                  key={node.id}
                  node={node}
                  isSelected={selectedNodeId === node.id || isStandardHighlighted(node.id)}
                  onSelect={() => { setSelectedNodeId(node.id); setSelectedEdgeId(null); }}
                  onDrag={handleNodeDrag}
                  scale={scale}
                />
              ))}
            </div>
          </div>
        </div>

        {/* Right Panel: Petition Letter */}
        <div className="w-[480px] flex-shrink-0 flex flex-col bg-white">
          {/* Letter Header */}
          <div className="flex-shrink-0 px-4 py-3 border-b border-slate-200 bg-slate-50">
            <div className="flex items-center justify-between">
              <div>
                <h2 className="text-sm font-semibold text-slate-800">{t('writing.petitionLetter')}</h2>
                <p className="text-xs text-slate-500">{t('writing.eb1aApplication')}</p>
              </div>
              <div className="flex items-center gap-2">
                <button className="text-xs px-2 py-1 text-slate-600 hover:text-slate-800 hover:bg-slate-200 rounded transition-colors">
                  {t('writing.exportWord')}
                </button>
                <button className="text-xs px-2 py-1 text-slate-600 hover:text-slate-800 hover:bg-slate-200 rounded transition-colors">
                  {t('writing.exportPdf')}
                </button>
              </div>
            </div>
          </div>

          {/* Letter Content */}
          <div className="flex-1 overflow-y-auto">
            {letterSections.map(section => (
              <LetterSectionComponent
                key={section.id}
                section={section}
                isHighlighted={section.standardId === hoveredStandardId ||
                  (selectedNodeId?.startsWith('std') && section.standardId === selectedNodeId)}
                onHover={setHoveredStandardId}
                onEdit={updateLetterSection}
                onSentenceClick={handleSentenceClick}
                highlightedSnippetIds={highlightedSnippetIds}
              />
            ))}
          </div>

          {/* Letter Footer */}
          <div className="flex-shrink-0 px-4 py-3 border-t border-slate-200 bg-slate-50">
            <div className="flex items-center justify-between text-xs text-slate-500">
              <span>{t('writing.sections', { count: letterSections.length })}</span>
              <span>
                {t('writing.generatedCount', {
                  generated: letterSections.filter(s => s.isGenerated).length,
                  pending: letterSections.filter(s => !s.isGenerated).length
                })}
              </span>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
