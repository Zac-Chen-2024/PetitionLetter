import { useState, useRef, useEffect, useCallback } from 'react';
import { useTranslation } from 'react-i18next';
import { useApp } from '../context/AppContext';
import { legalStandards } from '../data/legalStandards';
import { STANDARD_KEY_TO_ID } from '../constants/colors';
import type { Position, Argument, SubArgument } from '../types';

// ============================================
// Types for internal use
// ============================================

interface ArgumentNode {
  id: string;
  type: 'argument';
  position: Position;
  data: {
    title: string;
    subject: string;
    standardKey?: string;
    snippetCount: number;
    isAIGenerated: boolean;
    completenessScore?: number;
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
    argumentCount: number;
  };
}

interface SubArgumentNode {
  id: string;
  type: 'subargument';
  position: Position;
  data: {
    title: string;
    purpose: string;
    relationship: string;  // LLM 生成的关系描述
    argumentId: string;
    snippetCount: number;
    isAIGenerated: boolean;
  };
}

type NodeType = ArgumentNode | StandardNode | SubArgumentNode;

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

const ArrangeIcon = () => (
  <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 5a1 1 0 011-1h14a1 1 0 011 1v2a1 1 0 01-1 1H5a1 1 0 01-1-1V5zM4 13a1 1 0 011-1h6a1 1 0 011 1v6a1 1 0 01-1 1H5a1 1 0 01-1-1v-6zM16 13a1 1 0 011-1h2a1 1 0 011 1v6a1 1 0 01-1 1h-2a1 1 0 01-1-1v-6z" />
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
}

function ArgumentNodeComponent({
  node,
  isSelected,
  onSelect,
  onDrag,
  scale,
  onPositionReport,
  t,
  transformVersion,
}: DraggableNodeProps & {
  node: ArgumentNode;
  onPositionReport?: (id: string, rect: DOMRect) => void;
  t: (key: string, options?: Record<string, unknown>) => string;
  transformVersion?: number;  // Triggers position update when canvas transforms
}) {
  const [isDragging, setIsDragging] = useState(false);
  const dragStartPos = useRef<Position | null>(null);
  const nodeStartPos = useRef<Position | null>(null);
  const nodeRef = useRef<HTMLDivElement>(null);

  const handleMouseDown = (e: React.MouseEvent) => {
    e.stopPropagation();
    setIsDragging(true);
    dragStartPos.current = { x: e.clientX, y: e.clientY };
    nodeStartPos.current = { ...node.position };
    onSelect();
  };

  // Report position to parent for connection lines
  // Re-report when canvas transforms (scale/offset changes)
  useEffect(() => {
    if (!nodeRef.current || !onPositionReport) return;

    const reportPosition = () => {
      if (!nodeRef.current) return;
      const rect = nodeRef.current.getBoundingClientRect();
      onPositionReport(node.id, rect);
    };

    // Initial report with requestAnimationFrame to ensure DOM is ready
    requestAnimationFrame(reportPosition);

    // Listen for scroll/resize events
    window.addEventListener('resize', reportPosition);
    window.addEventListener('scroll', reportPosition, true);

    return () => {
      window.removeEventListener('resize', reportPosition);
      window.removeEventListener('scroll', reportPosition, true);
    };
  }, [node.id, node.position.x, node.position.y, onPositionReport, transformVersion]);

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

  // Completeness indicator color
  const getCompletenessColor = (score?: number) => {
    if (!score) return 'bg-slate-200';
    if (score >= 80) return 'bg-green-500';
    if (score >= 50) return 'bg-yellow-500';
    return 'bg-red-400';
  };

  return (
    <div
      ref={nodeRef}
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
          w-[320px] p-4 rounded-xl border-2 border-purple-400 bg-purple-50 shadow-md transition-all
          ${isSelected ? 'ring-2 ring-offset-2 ring-purple-500 shadow-lg border-purple-500' : 'hover:shadow-lg hover:border-purple-500'}
        `}
      >
        {/* Header */}
        <div className="flex items-start justify-between gap-2 mb-2">
          <span className="text-base font-bold text-purple-800 line-clamp-2">{node.data.title}</span>
          {node.data.isAIGenerated && (
            <span className="text-[10px] px-2 py-0.5 bg-purple-200 text-purple-700 rounded flex-shrink-0">AI</span>
          )}
        </div>

        {/* Subject */}
        <p className="text-sm text-purple-600 mb-2 line-clamp-1">{node.data.subject}</p>

        {/* Stats row */}
        <div className="flex items-center justify-between text-xs">
          <span className="text-purple-500">{t('graph.node.snippets', { count: node.data.snippetCount })}</span>
          {node.data.completenessScore !== undefined && (
            <div className="flex items-center gap-1">
              <div className={`w-2.5 h-2.5 rounded-full ${getCompletenessColor(node.data.completenessScore)}`} />
              <span className="text-purple-500">{node.data.completenessScore}%</span>
            </div>
          )}
        </div>

        {/* Standard tag if mapped */}
        {node.data.standardKey && (
          <div className="mt-3 pt-2 border-t border-purple-200">
            <span className="text-xs px-2 py-1 bg-purple-200 text-purple-700 rounded-full">
              {node.data.standardKey}
            </span>
          </div>
        )}
      </div>
    </div>
  );
}

function StandardNodeComponent({ node, isSelected, onSelect, onDrag, scale, t }: DraggableNodeProps & { node: StandardNode; t: (key: string, options?: Record<string, unknown>) => string }) {
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
          w-[180px] p-4 rounded-xl bg-white shadow-lg transition-all
          ${isSelected ? 'ring-2 ring-offset-2 shadow-xl scale-105' : 'hover:shadow-xl'}
        `}
        style={{
          borderColor: node.data.color,
          borderWidth: '3px',
          borderStyle: 'solid',
        }}
      >
        <div className="flex items-center gap-2">
          <div
            className="w-5 h-5 rounded-full flex-shrink-0"
            style={{ backgroundColor: node.data.color }}
          />
          <span className="text-base font-bold text-slate-800">{node.data.shortName}</span>
        </div>
        <div className="mt-2 flex items-center justify-between">
          <span className="text-xs text-slate-400">{t('graph.legend.standard')}</span>
          {node.data.argumentCount > 0 && (
            <span className="text-xs px-2 py-0.5 bg-slate-100 text-slate-600 rounded">
              {t('graph.node.args', { count: node.data.argumentCount })}
            </span>
          )}
        </div>
      </div>
    </div>
  );
}

function SubArgumentNodeComponent({
  node,
  isSelected,
  onSelect,
  onDrag,
  scale,
  t,
  onPositionReport,
  transformVersion,
}: DraggableNodeProps & {
  node: SubArgumentNode;
  t: (key: string, options?: Record<string, unknown>) => string;
  onPositionReport?: (id: string, rect: DOMRect) => void;
  transformVersion?: number;  // Triggers position update when canvas transforms
}) {
  const [isDragging, setIsDragging] = useState(false);
  const dragStartPos = useRef<Position | null>(null);
  const nodeStartPos = useRef<Position | null>(null);
  const nodeRef = useRef<HTMLDivElement>(null);

  const handleMouseDown = (e: React.MouseEvent) => {
    e.stopPropagation();
    setIsDragging(true);
    dragStartPos.current = { x: e.clientX, y: e.clientY };
    nodeStartPos.current = { ...node.position };
    onSelect();
  };

  // Report position to parent for connection lines
  // Re-report when canvas transforms (scale/offset changes)
  useEffect(() => {
    if (!nodeRef.current || !onPositionReport) return;

    const reportPosition = () => {
      if (!nodeRef.current) return;
      const rect = nodeRef.current.getBoundingClientRect();
      onPositionReport(node.id, rect);
    };

    requestAnimationFrame(reportPosition);
    window.addEventListener('resize', reportPosition);
    window.addEventListener('scroll', reportPosition, true);

    return () => {
      window.removeEventListener('resize', reportPosition);
      window.removeEventListener('scroll', reportPosition, true);
    };
  }, [node.id, node.position.x, node.position.y, onPositionReport, transformVersion]);

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
      ref={nodeRef}
      className={`
        absolute cursor-grab active:cursor-grabbing select-none
        ${isDragging ? 'z-50' : 'z-15'}
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
          w-[240px] p-3 rounded-lg border-2 border-emerald-400 bg-emerald-50 shadow-sm transition-all
          ${isSelected ? 'ring-2 ring-offset-2 ring-emerald-500 shadow-md border-emerald-500' : 'hover:shadow-md hover:border-emerald-500'}
        `}
      >
        {/* Header */}
        <div className="flex items-start justify-between gap-2 mb-1">
          <span className="text-sm font-semibold text-emerald-800 line-clamp-1">{node.data.title}</span>
          {node.data.isAIGenerated && (
            <span className="text-[9px] px-1.5 py-0.5 bg-emerald-200 text-emerald-700 rounded flex-shrink-0">AI</span>
          )}
        </div>

        {/* Purpose */}
        <p className="text-xs text-emerald-600 mb-2 line-clamp-2">{node.data.purpose}</p>

        {/* Relationship label */}
        <div className="flex items-center justify-between text-xs">
          <span className="px-2 py-0.5 bg-emerald-200 text-emerald-700 rounded-full text-[10px]">
            {node.data.relationship}
          </span>
          <span className="text-emerald-500">{t('graph.node.snippets', { count: node.data.snippetCount })}</span>
        </div>
      </div>
    </div>
  );
}

// ============================================
// Connection Lines (Internal)
// ============================================

interface InternalConnectionLinesProps {
  argumentNodes: ArgumentNode[];
  standardNodes: StandardNode[];
  subArgumentNodes: SubArgumentNode[];
}

function InternalConnectionLines({ argumentNodes, standardNodes, subArgumentNodes }: InternalConnectionLinesProps) {
  const standardPositions = new Map(standardNodes.map(n => [n.id, n.position]));
  const argumentPositions = new Map(argumentNodes.map(n => [n.id, n.position]));

  return (
    <svg className="absolute" style={{ zIndex: 35, pointerEvents: 'none', left: 0, top: 0, width: '4000px', height: '3000px', overflow: 'visible' }}>
      <defs>
        <marker id="arg-arrowhead" markerWidth="10" markerHeight="7" refX="9" refY="3.5" orient="auto">
          <polygon points="0 0, 10 3.5, 0 7" fill="#a855f7" />
        </marker>
        <marker id="subarg-arrowhead" markerWidth="10" markerHeight="7" refX="9" refY="3.5" orient="auto">
          <polygon points="0 0, 10 3.5, 0 7" fill="#10b981" />
        </marker>
      </defs>

      {/* SubArgument → Argument connections (with relationship labels) */}
      {subArgumentNodes.map(subArgNode => {
        const argPos = argumentPositions.get(subArgNode.data.argumentId);
        if (!argPos) return null;

        const x1 = subArgNode.position.x + 120; // Right edge of subargument node (240px / 2)
        const y1 = subArgNode.position.y;
        const x2 = argPos.x - 160; // Left edge of argument node (320px / 2)
        const y2 = argPos.y;

        const midX = (x1 + x2) / 2;
        const pathD = `M ${x1} ${y1} C ${midX} ${y1}, ${midX} ${y2}, ${x2} ${y2}`;

        // Label position (middle of the curve)
        const labelX = midX;
        const labelY = (y1 + y2) / 2 - 8;

        return (
          <g key={`${subArgNode.id}-${subArgNode.data.argumentId}`}>
            <path
              d={pathD}
              fill="none"
              stroke="#10b981"
              strokeWidth={2}
              markerEnd="url(#subarg-arrowhead)"
              opacity={0.6}
            />
            {/* Relationship label */}
            <rect
              x={labelX - 40}
              y={labelY - 8}
              width={80}
              height={16}
              rx={4}
              fill="white"
              stroke="#10b981"
              strokeWidth={1}
              opacity={0.9}
            />
            <text
              x={labelX}
              y={labelY + 3}
              textAnchor="middle"
              fontSize={9}
              fill="#059669"
              fontWeight={500}
            >
              {subArgNode.data.relationship.slice(0, 12)}
            </text>
          </g>
        );
      })}

      {/* Argument → Standard connections */}
      {argumentNodes.map(argNode => {
        if (!argNode.data.standardKey) return null;

        const standardId = STANDARD_KEY_TO_ID[argNode.data.standardKey];
        const standardPos = standardPositions.get(standardId);
        if (!standardPos) return null;

        const x1 = argNode.position.x + 160; // Right edge of argument node (320px / 2)
        const y1 = argNode.position.y;
        const x2 = standardPos.x - 90; // Left edge of standard node (180px / 2)
        const y2 = standardPos.y;

        const midX = (x1 + x2) / 2;
        const pathD = `M ${x1} ${y1} C ${midX} ${y1}, ${midX} ${y2}, ${x2} ${y2}`;

        return (
          <path
            key={`${argNode.id}-${standardId}`}
            d={pathD}
            fill="none"
            stroke="#a855f7"
            strokeWidth={2}
            markerEnd="url(#arg-arrowhead)"
            opacity={0.6}
          />
        );
      })}
    </svg>
  );
}

// ============================================
// Auto Layout Helper
// ============================================

function calculateTreeLayout(
  arguments_: Argument[],
  subArguments: SubArgument[],
  savedPositions: Map<string, Position>
): { argumentNodes: ArgumentNode[]; standardNodes: StandardNode[]; subArgumentNodes: SubArgumentNode[] } {
  // Position layout with sub-arguments on the left
  const SUBARG_X = 200;          // Base X for sub-arguments (reduced from 500)
  const SUBARG_X_OFFSET = 80;    // Horizontal offset for staggered layout
  const ARGUMENT_X = 800;        // Reduced from 1100
  const STANDARD_X = 1200;       // Reduced from 1500
  const START_Y = 100;
  const MIN_ARGUMENT_SPACING = 180;  // Minimum spacing between arguments
  const SUBARG_SPACING = 140;    // Vertical spacing between sub-arguments
  const SUBARG_CARD_HEIGHT = 100; // Approximate height of sub-argument card

  // Pre-calculate sub-argument counts per argument
  const subArgCountByArgument = new Map<string, number>();
  subArguments.forEach(sa => {
    const count = subArgCountByArgument.get(sa.argumentId) || 0;
    subArgCountByArgument.set(sa.argumentId, count + 1);
  });

  // Helper: calculate vertical space needed for an argument based on its sub-arguments
  const getArgumentHeight = (argId: string): number => {
    const subArgCount = subArgCountByArgument.get(argId) || 0;
    if (subArgCount <= 1) return MIN_ARGUMENT_SPACING;
    // Height = (subArgCount - 1) * spacing + card height + buffer
    return (subArgCount - 1) * SUBARG_SPACING + SUBARG_CARD_HEIGHT + 40;
  };

  // Group arguments by standardKey
  const argumentsByStandard = new Map<string, Argument[]>();
  const unmappedArguments: Argument[] = [];

  arguments_.forEach(arg => {
    if (arg.standardKey) {
      const list = argumentsByStandard.get(arg.standardKey) || [];
      list.push(arg);
      argumentsByStandard.set(arg.standardKey, list);
    } else {
      unmappedArguments.push(arg);
    }
  });

  // Helper: count arguments for a standard
  const getArgumentCount = (standardId: string): number => {
    let count = 0;
    argumentsByStandard.forEach((args, key) => {
      if (STANDARD_KEY_TO_ID[key] === standardId) {
        count += args.length;
      }
    });
    return count;
  };

  // Get standards that have arguments, sorted by argument count (descending)
  const standardsWithArgs = legalStandards
    .filter(s => {
      return Array.from(argumentsByStandard.keys()).some(key => STANDARD_KEY_TO_ID[key] === s.id);
    })
    .sort((a, b) => getArgumentCount(b.id) - getArgumentCount(a.id));

  // Build nodes with aligned positions:
  // - Arguments for each standard are grouped together
  // - Standard is positioned at the vertical center of its argument group
  const argumentNodes: ArgumentNode[] = [];
  const standardNodes: StandardNode[] = [];

  let currentY = START_Y;

  // Process each standard in order (from legalStandards array)
  standardsWithArgs.forEach((standard) => {
    // Find all arguments for this standard
    const standardArgs: Argument[] = [];
    argumentsByStandard.forEach((args, key) => {
      if (STANDARD_KEY_TO_ID[key] === standard.id) {
        standardArgs.push(...args);
      }
    });

    if (standardArgs.length === 0) return;

    // Calculate Y positions for this group of arguments with dynamic spacing
    const groupStartY = currentY;
    const argPositions: number[] = [];
    let argY = groupStartY;

    standardArgs.forEach((arg, idx) => {
      argPositions.push(argY);
      if (idx < standardArgs.length - 1) {
        // Calculate spacing based on current and next argument's sub-argument count
        const currentHeight = getArgumentHeight(arg.id);
        const nextHeight = getArgumentHeight(standardArgs[idx + 1].id);
        const spacing = Math.max(currentHeight / 2 + nextHeight / 2, MIN_ARGUMENT_SPACING);
        argY += spacing;
      }
    });

    const groupEndY = argPositions[argPositions.length - 1];
    const standardY = (groupStartY + groupEndY) / 2;  // Standard at center of its argument group

    // Add argument nodes for this standard
    standardArgs.forEach((arg, idx) => {
      const savedPos = savedPositions.get(arg.id);
      argumentNodes.push({
        id: arg.id,
        type: 'argument' as const,
        position: savedPos || { x: ARGUMENT_X, y: argPositions[idx] },
        data: {
          title: arg.title,
          subject: arg.subject,
          standardKey: arg.standardKey,
          snippetCount: arg.snippetIds?.length || 0,
          isAIGenerated: arg.isAIGenerated,
          completenessScore: arg.completeness?.score,
        },
      });
    });

    // Add standard node at vertical center of its arguments
    const savedStandardPos = savedPositions.get(standard.id);
    standardNodes.push({
      id: standard.id,
      type: 'standard' as const,
      position: savedStandardPos || { x: STANDARD_X, y: standardY },
      data: {
        name: standard.name,
        shortName: standard.shortName,
        color: standard.color,
        argumentCount: standardArgs.length,
      },
    });

    // Move currentY to after this group (with extra spacing between groups)
    const lastArgHeight = getArgumentHeight(standardArgs[standardArgs.length - 1].id);
    currentY = groupEndY + lastArgHeight / 2 + MIN_ARGUMENT_SPACING;
  });

  // Add unmapped arguments at the end
  unmappedArguments.forEach(arg => {
    const savedPos = savedPositions.get(arg.id);
    const argHeight = getArgumentHeight(arg.id);
    argumentNodes.push({
      id: arg.id,
      type: 'argument' as const,
      position: savedPos || { x: ARGUMENT_X, y: currentY },
      data: {
        title: arg.title,
        subject: arg.subject,
        standardKey: arg.standardKey,
        snippetCount: arg.snippetIds?.length || 0,
        isAIGenerated: arg.isAIGenerated,
        completenessScore: arg.completeness?.score,
      },
    });
    currentY += Math.max(argHeight, MIN_ARGUMENT_SPACING);
  });

  // Build sub-argument nodes
  // Group sub-arguments by their parent argument
  const subArgsByArgument = new Map<string, SubArgument[]>();
  subArguments.forEach(sa => {
    const list = subArgsByArgument.get(sa.argumentId) || [];
    list.push(sa);
    subArgsByArgument.set(sa.argumentId, list);
  });

  const subArgumentNodes: SubArgumentNode[] = [];

  // Position sub-arguments aligned with their parent argument
  // Stagger groups horizontally based on argument index
  argumentNodes.forEach((argNode, argIndex) => {
    const argSubArgs = subArgsByArgument.get(argNode.id) || [];
    if (argSubArgs.length === 0) return;

    // Calculate vertical range for sub-arguments
    const totalHeight = (argSubArgs.length - 1) * SUBARG_SPACING;
    const startY = argNode.position.y - totalHeight / 2;

    // Staggered X position for the entire group based on argument index
    const groupStaggerX = SUBARG_X + (argIndex % 2) * SUBARG_X_OFFSET;

    argSubArgs.forEach((sa, idx) => {
      const savedPos = savedPositions.get(sa.id);
      subArgumentNodes.push({
        id: sa.id,
        type: 'subargument' as const,
        position: savedPos || { x: groupStaggerX, y: startY + idx * SUBARG_SPACING },
        data: {
          title: sa.title,
          purpose: sa.purpose,
          relationship: sa.relationship,
          argumentId: sa.argumentId,
          snippetCount: sa.snippetIds?.length || 0,
          isAIGenerated: sa.isAIGenerated,
        },
      });
    });
  });

  return { argumentNodes, standardNodes, subArgumentNodes };
}

// ============================================
// Main Component
// ============================================

export function ArgumentGraph() {
  const { t } = useTranslation();
  const {
    arguments: contextArguments,
    subArguments: contextSubArguments,
    argumentGraphPositions,
    updateArgumentGraphPosition,
    clearArgumentGraphPositions,
    setFocusState,
    focusState,
    updateArgumentPosition2,
    updateSubArgumentPosition,
    setSelectedSnippetId,
  } = useApp();

  const containerRef = useRef<HTMLDivElement>(null);
  const [scale, setScale] = useState(0.8);  // Start at 80% zoom
  const [offset, setOffset] = useState<Position>({ x: 0, y: 0 });
  const [isPanning, setIsPanning] = useState(false);
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const panStartPos = useRef<Position | null>(null);
  const offsetStartPos = useRef<Position | null>(null);

  // Transform version - increments on scale/offset changes to trigger position updates
  const [transformVersion, setTransformVersion] = useState(0);

  // Update transformVersion when scale or offset changes
  useEffect(() => {
    setTransformVersion(v => v + 1);
  }, [scale, offset.x, offset.y]);

  // Calculate layout
  const { argumentNodes, standardNodes, subArgumentNodes } = calculateTreeLayout(
    contextArguments,
    contextSubArguments,
    argumentGraphPositions
  );

  // Handle node drag
  const handleNodeDrag = useCallback((id: string, position: Position) => {
    updateArgumentGraphPosition(id, position);
  }, [updateArgumentGraphPosition]);

  // Handle argument position report for main page connection lines
  // Note: ConnectionLines expects x to be RIGHT edge (same as EvidenceCardPool)
  const handleArgumentPositionReport = useCallback((id: string, rect: DOMRect) => {
    updateArgumentPosition2(id, {
      id,
      x: rect.right,  // Right edge (ConnectionLines calculates left edge as x - width)
      y: rect.top + rect.height / 2,
      width: rect.width,
      height: rect.height,
    });
  }, [updateArgumentPosition2]);

  // Handle sub-argument position report for connection lines
  // ConnectionLines connects snippets to sub-arguments (not arguments)
  const handleSubArgumentPositionReport = useCallback((id: string, rect: DOMRect) => {
    updateSubArgumentPosition(id, {
      id,
      x: rect.right,  // Right edge
      y: rect.top + rect.height / 2,
      width: rect.width,
      height: rect.height,
    });
  }, [updateSubArgumentPosition]);

  // Handle argument selection - set focusState
  const handleArgumentSelect = useCallback((argumentId: string) => {
    setSelectedNodeId(argumentId);
    setFocusState({ type: 'argument', id: argumentId });
    setSelectedSnippetId(null);  // Clear snippet selection when focusing argument
  }, [setFocusState, setSelectedSnippetId]);

  // Handle sub-argument selection - set focusState and clear snippet selection
  const handleSubArgumentSelect = useCallback((subArgumentId: string) => {
    setSelectedNodeId(subArgumentId);
    setFocusState({ type: 'subargument', id: subArgumentId });
    setSelectedSnippetId(null);  // Clear snippet selection when focusing sub-argument
  }, [setFocusState, setSelectedSnippetId]);

  // Handle standard selection
  const handleStandardSelect = useCallback((standardId: string) => {
    setSelectedNodeId(standardId);
    setFocusState({ type: 'standard', id: standardId });
  }, [setFocusState]);

  // Check if a sub-argument should be highlighted (when its parent argument is focused)
  const isSubArgumentHighlighted = useCallback((subArgNode: SubArgumentNode): boolean => {
    // Highlighted if directly selected
    if (selectedNodeId === subArgNode.id) return true;
    // Highlighted if its parent argument is focused
    if (focusState.type === 'argument' && focusState.id === subArgNode.data.argumentId) return true;
    // Highlighted if this sub-argument is focused
    if (focusState.type === 'subargument' && focusState.id === subArgNode.id) return true;
    return false;
  }, [selectedNodeId, focusState]);

  // Handle canvas mouse events
  const handleCanvasMouseDown = (e: React.MouseEvent) => {
    const target = e.target as Element;
    const isCanvasClick = e.target === e.currentTarget || target.closest('svg') !== null;

    if (isCanvasClick) {
      setIsPanning(true);
      panStartPos.current = { x: e.clientX, y: e.clientY };
      offsetStartPos.current = { ...offset };
      setSelectedNodeId(null);
    }
  };

  // Handle mouse move for panning
  useEffect(() => {
    const handleMouseMove = (e: MouseEvent) => {
      if (isPanning && panStartPos.current && offsetStartPos.current) {
        setOffset({
          x: offsetStartPos.current.x + (e.clientX - panStartPos.current.x),
          y: offsetStartPos.current.y + (e.clientY - panStartPos.current.y),
        });
      }
    };

    const handleMouseUp = () => {
      if (isPanning) {
        setIsPanning(false);
        panStartPos.current = null;
        offsetStartPos.current = null;
      }
    };

    window.addEventListener('mousemove', handleMouseMove);
    window.addEventListener('mouseup', handleMouseUp);
    return () => {
      window.removeEventListener('mousemove', handleMouseMove);
      window.removeEventListener('mouseup', handleMouseUp);
    };
  }, [isPanning]);

  // Handle zoom
  const handleZoom = useCallback((delta: number) => {
    setScale(prev => Math.max(0.5, Math.min(2, prev + delta)));
  }, []);

  const handleFit = () => {
    setScale(1);
    setOffset({ x: 0, y: 0 });
  };

  // Handle auto-arrange nodes
  const handleArrangeNodes = useCallback(() => {
    clearArgumentGraphPositions();
    setScale(0.5);
    setOffset({ x: 0, y: 0 });
  }, [clearArgumentGraphPositions]);

  // Handle mouse wheel zoom
  const handleWheel = useCallback((e: WheelEvent) => {
    e.preventDefault();
    const delta = e.deltaY > 0 ? -0.1 : 0.1;
    setScale(prev => Math.max(0.5, Math.min(2, prev + delta)));
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
      if (e.key === 'Escape') {
        setSelectedNodeId(null);
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, []);

  // Get generateArguments from context
  const { generateArguments, isGeneratingArguments } = useApp();

  return (
    <div className="flex flex-col h-full bg-slate-50">
      {/* Header */}
      <div className="flex-shrink-0 px-4 py-2 bg-white border-b border-slate-200">
        <div className="flex items-center justify-between">
          <div>
            <h2 className="text-sm font-semibold text-slate-800">{t('header.writingTree')}</h2>
            <p className="text-xs text-slate-500">
              {t('graph.argumentCount', { arguments: contextArguments.length, subArguments: contextSubArguments.length })}
            </p>
          </div>
          <button
            onClick={() => generateArguments(true)}
            disabled={isGeneratingArguments}
            className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-white bg-purple-600 rounded-lg hover:bg-purple-700 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {isGeneratingArguments ? (
              <>
                <svg className="w-3.5 h-3.5 animate-spin" fill="none" viewBox="0 0 24 24">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                </svg>
                <span>Generating...</span>
              </>
            ) : (
              <>
                <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 10V3L4 14h7v7l9-11h-7z" />
                </svg>
                <span>Generate</span>
              </>
            )}
          </button>
        </div>
      </div>

      {/* Canvas area */}
      <div className="flex-1 relative overflow-hidden">
        {/* Zoom controls */}
        <div className="absolute top-3 right-3 z-50 flex flex-col gap-1 bg-white rounded-lg shadow-lg border border-slate-200 p-1">
          <button onClick={() => handleZoom(0.1)} className="p-1.5 hover:bg-slate-100 rounded transition-colors" title="Zoom In">
            <ZoomInIcon />
          </button>
          <button onClick={() => handleZoom(-0.1)} className="p-1.5 hover:bg-slate-100 rounded transition-colors" title="Zoom Out">
            <ZoomOutIcon />
          </button>
          <div className="border-t border-slate-200 my-0.5" />
          <button onClick={handleFit} className="p-1.5 hover:bg-slate-100 rounded transition-colors" title="Fit to View">
            <FitIcon />
          </button>
          <button onClick={handleArrangeNodes} className="p-1.5 hover:bg-slate-100 rounded transition-colors" title="Auto Arrange">
            <ArrangeIcon />
          </button>
        </div>

        {/* Scale indicator */}
        <div className="absolute bottom-3 right-3 z-50 bg-white/80 backdrop-blur-sm px-2 py-0.5 rounded border border-slate-200 text-xs text-slate-600">
          {Math.round(scale * 100)}%
        </div>

        {/* Legend */}
        <div className="absolute top-3 left-3 z-50 bg-white/90 backdrop-blur-sm p-2 rounded-lg border border-slate-200 text-[10px] space-y-1.5">
          <div className="flex items-center gap-2">
            <div className="w-3 h-3 rounded-lg bg-emerald-100 border-2 border-emerald-400" />
            <span>{t('graph.legend.subArgument')}</span>
          </div>
          <div className="flex items-center gap-2">
            <div className="w-3 h-3 rounded-lg bg-purple-100 border-2 border-purple-400" />
            <span>{t('graph.legend.argument')}</span>
          </div>
          <div className="flex items-center gap-2">
            <div className="w-3 h-3 rounded-lg border-2 border-blue-500 bg-white" />
            <span>{t('graph.legend.standard')}</span>
          </div>
        </div>

        {/* Canvas */}
        <div
          ref={containerRef}
          className={`absolute inset-0 ${isPanning ? 'cursor-grabbing' : 'cursor-grab'}`}
          onMouseDown={handleCanvasMouseDown}
        >
          {/* Grid background */}
          <svg className="absolute inset-0 w-full h-full" style={{ zIndex: 0 }}>
            <defs>
              <pattern
                id="arg-grid"
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
            <rect width="100%" height="100%" fill="url(#arg-grid)" />
          </svg>

          {/* Transformed content */}
          <div
            style={{
              transform: `translate(${offset.x}px, ${offset.y}px) scale(${scale})`,
              transformOrigin: '0 0',
              position: 'absolute',
              width: '4000px',
              height: '3000px',
              pointerEvents: 'none',
              zIndex: 1,  // Above grid background (z:0) to prevent clipping
            }}
          >
            {/* Internal connection lines */}
            <InternalConnectionLines
              argumentNodes={argumentNodes}
              standardNodes={standardNodes}
              subArgumentNodes={subArgumentNodes}
            />

            {/* Sub-argument nodes */}
            {subArgumentNodes.map(node => (
              <SubArgumentNodeComponent
                key={node.id}
                node={node}
                isSelected={isSubArgumentHighlighted(node)}
                onSelect={() => handleSubArgumentSelect(node.id)}
                onDrag={handleNodeDrag}
                scale={scale}
                t={t}
                onPositionReport={handleSubArgumentPositionReport}
                transformVersion={transformVersion}
              />
            ))}

            {/* Argument nodes */}
            {argumentNodes.map(node => (
              <ArgumentNodeComponent
                key={node.id}
                node={node}
                isSelected={selectedNodeId === node.id || focusState.id === node.id}
                onSelect={() => handleArgumentSelect(node.id)}
                onDrag={handleNodeDrag}
                scale={scale}
                onPositionReport={handleArgumentPositionReport}
                t={t}
                transformVersion={transformVersion}
              />
            ))}

            {/* Standard nodes */}
            {standardNodes.map(node => (
              <StandardNodeComponent
                key={node.id}
                node={node}
                isSelected={selectedNodeId === node.id || focusState.id === node.id}
                onSelect={() => handleStandardSelect(node.id)}
                onDrag={handleNodeDrag}
                scale={scale}
                t={t}
              />
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
