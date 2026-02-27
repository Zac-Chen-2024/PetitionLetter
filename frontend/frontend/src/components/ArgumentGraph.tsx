import { useState, useRef, useEffect, useCallback, useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import { useApp } from '../context/AppContext';
import { useLegalStandards } from '../hooks/useLegalStandards';
import { STANDARD_KEY_TO_ID } from '../constants/colors';
import toast from 'react-hot-toast';
import { apiClient } from '../services/api';
import StandardActionModal from './StandardActionModal';
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
    needsSnippetConfirmation?: boolean;  // 红点提示：有推荐snippets待确认
    pendingSnippetCount?: number;  // 推荐的snippets数量
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
  onAddSubArgument,
  onDelete,
}: DraggableNodeProps & {
  node: ArgumentNode;
  onPositionReport?: (id: string, rect: DOMRect) => void;
  t: (key: string, options?: Record<string, unknown>) => string;
  transformVersion?: number;  // Triggers position update when canvas transforms
  onAddSubArgument?: (argumentId: string) => void;
  onDelete?: (argumentId: string) => void;
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
          <div className="flex items-center gap-0.5 flex-shrink-0 -mt-1 -mr-1">
            {/* Add SubArgument button */}
            {onAddSubArgument && (
              <button
                onClick={(e) => {
                  e.stopPropagation();
                  onAddSubArgument(node.id);
                }}
                className="p-1 rounded hover:bg-purple-200 transition-colors"
                title="Add Sub-Argument"
              >
                <svg className="w-4 h-4 text-purple-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
                </svg>
              </button>
            )}
            {node.data.isAIGenerated && (
              <span className="text-[10px] px-2 py-0.5 bg-purple-200 text-purple-700 rounded">AI</span>
            )}
            {/* Delete button */}
            {onDelete && (
              <button
                onClick={(e) => { e.stopPropagation(); onDelete(node.id); }}
                className="p-1 rounded hover:bg-red-100 transition-colors"
                title="Delete this argument"
              >
                <svg className="w-3.5 h-3.5 text-red-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                </svg>
              </button>
            )}
          </div>
        </div>

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

function StandardNodeComponent({
  node, isSelected, onSelect, onDrag, scale, t,
  onRewrite, onRemove, isRewriting, hasLetterContent,
}: DraggableNodeProps & {
  node: StandardNode;
  t: (key: string, options?: Record<string, unknown>) => string;
  onRewrite?: (standardKey: string) => void;
  onRemove?: (standardKey: string) => void;
  isRewriting?: boolean;
  hasLetterContent?: boolean;
}) {
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
          w-[240px] p-4 rounded-xl bg-white shadow-lg transition-all
          ${isSelected ? 'ring-2 ring-offset-2 shadow-xl scale-105' : 'hover:shadow-xl'}
        `}
        style={{
          borderColor: node.data.color,
          borderWidth: '3px',
          borderStyle: 'solid',
        }}
      >
        {/* Top-right action buttons */}
        <div className="flex items-start justify-between gap-2">
          <div className="flex items-center gap-2">
            <div
              className="w-5 h-5 rounded-full flex-shrink-0"
              style={{ backgroundColor: node.data.color }}
            />
            <span className="text-base font-bold text-slate-800">{node.data.shortName}</span>
          </div>
          <div className="flex items-center gap-0.5 flex-shrink-0 -mt-1 -mr-1">
            {/* Rewrite button */}
            {onRewrite && (
              <button
                onClick={(e) => { e.stopPropagation(); onRewrite(node.id); }}
                disabled={isRewriting}
                className="p-1 rounded hover:bg-emerald-100 transition-colors disabled:opacity-50"
                title={t('graph.standard.rewrite', 'Rewrite')}
              >
                {isRewriting ? (
                  <svg className="w-3.5 h-3.5 text-emerald-600 animate-spin" fill="none" viewBox="0 0 24 24">
                    <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                    <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                  </svg>
                ) : (
                  <svg className="w-3.5 h-3.5 text-emerald-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
                  </svg>
                )}
              </button>
            )}
            {/* Remove button */}
            {onRemove && (
              <button
                onClick={(e) => { e.stopPropagation(); onRemove(node.id); }}
                className="p-1 rounded hover:bg-red-100 transition-colors"
                title={t('graph.standard.remove', 'Remove')}
              >
                <svg className="w-3.5 h-3.5 text-red-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                </svg>
              </button>
            )}
          </div>
        </div>
        <div className="mt-2 flex items-center justify-between">
          <div className="flex items-center gap-1.5">
            <span className="text-xs text-slate-400">{t('graph.legend.standard')}</span>
            {/* Letter content status indicator */}
            {hasLetterContent ? (
              <svg className="w-3.5 h-3.5 text-emerald-500" fill="currentColor" viewBox="0 0 20 20" title={t('graph.standard.written', 'Written')}>
                <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z" clipRule="evenodd" />
              </svg>
            ) : (
              <svg className="w-3.5 h-3.5 text-slate-300" fill="none" stroke="currentColor" viewBox="0 0 24 24" title={t('graph.standard.pending', 'Not written')}>
                <circle cx="12" cy="12" r="9" strokeWidth={2} />
              </svg>
            )}
          </div>
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
  onRegenerate,
  onTitleChange,
  onDelete,
  autoEdit,
  onAutoEditComplete,
  mergeMode,
  mergeChecked,
  mergeDisabled,
  projectId,
}: DraggableNodeProps & {
  node: SubArgumentNode;
  t: (key: string, options?: Record<string, unknown>) => string;
  onPositionReport?: (id: string, rect: DOMRect) => void;
  transformVersion?: number;  // Triggers position update when canvas transforms
  onRegenerate?: (subArgumentId: string) => void;
  onTitleChange?: (subArgumentId: string, newTitle: string) => void;
  onDelete?: (subArgumentId: string) => void;  // Delete callback
  autoEdit?: boolean;  // Auto-enter edit mode for newly created nodes
  onAutoEditComplete?: () => void;  // Callback when auto-edit is acknowledged
  mergeMode?: boolean;
  mergeChecked?: boolean;
  mergeDisabled?: boolean;
  projectId?: string;
}) {
  const [isDragging, setIsDragging] = useState(false);
  const [isEditing, setIsEditing] = useState(false);
  const [editTitle, setEditTitle] = useState(node.data.title);
  const [isRegenerating, setIsRegenerating] = useState(false);
  const [isGeneratingAITitle, setIsGeneratingAITitle] = useState(false);
  const dragStartPos = useRef<Position | null>(null);
  const nodeStartPos = useRef<Position | null>(null);
  const nodeRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const handleMouseDown = (e: React.MouseEvent) => {
    if (isEditing) return; // Don't start drag when editing
    e.stopPropagation();
    if (mergeMode) {
      // In merge mode: just toggle selection, no drag
      if (!mergeDisabled) onSelect();
      return;
    }
    setIsDragging(true);
    dragStartPos.current = { x: e.clientX, y: e.clientY };
    nodeStartPos.current = { ...node.position };
    onSelect();
  };

  // Handle double-click to edit title
  const handleDoubleClick = (e: React.MouseEvent) => {
    e.stopPropagation();
    setIsEditing(true);
    setEditTitle(node.data.title);
  };

  // Handle title edit completion
  const handleTitleSave = () => {
    if (editTitle.trim() && editTitle !== node.data.title) {
      onTitleChange?.(node.id, editTitle.trim());
    }
    setIsEditing(false);
  };

  // Handle title edit cancel
  const handleTitleCancel = () => {
    setEditTitle(node.data.title);
    setIsEditing(false);
  };

  // Handle key events in edit mode
  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter') {
      handleTitleSave();
    } else if (e.key === 'Escape') {
      handleTitleCancel();
    }
  };

  // Handle regenerate click
  const handleRegenerateClick = async (e: React.MouseEvent) => {
    e.stopPropagation();
    if (isRegenerating) return;
    setIsRegenerating(true);
    try {
      await onRegenerate?.(node.id);
    } finally {
      setIsRegenerating(false);
    }
  };

  // Handle delete click — delegate to parent (modal confirmation)
  const handleDeleteClick = (e: React.MouseEvent) => {
    e.stopPropagation();
    onDelete?.(node.id);
  };

  // Handle AI title generation
  const handleAITitle = async (e: React.MouseEvent) => {
    e.stopPropagation();
    if (isGeneratingAITitle || !projectId) return;
    setIsGeneratingAITitle(true);
    try {
      const response = await apiClient.post<{ success: boolean; relationship: string }>(
        `/arguments/${projectId}/infer-relationship`,
        {
          argument_id: node.data.argumentId,
          subargument_title: node.data.title || editTitle || 'merged sub-argument',
        }
      );
      if (response.success && response.relationship) {
        const newTitle = response.relationship;
        setEditTitle(newTitle);
        // If not in edit mode, save directly
        if (!isEditing) {
          onTitleChange?.(node.id, newTitle);
        }
      }
    } catch (error) {
      console.error('AI title generation failed:', error);
    } finally {
      setIsGeneratingAITitle(false);
    }
  };

  // Auto-enter edit mode for newly created nodes
  useEffect(() => {
    if (autoEdit && !isEditing) {
      setIsEditing(true);
      setEditTitle('');  // Start with empty title for new nodes
      onAutoEditComplete?.();
    }
  }, [autoEdit, isEditing, onAutoEditComplete]);

  // Focus input when entering edit mode
  useEffect(() => {
    if (isEditing && inputRef.current) {
      inputRef.current.focus();
      inputRef.current.select();
    }
  }, [isEditing]);

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
          w-[320px] p-3 rounded-lg border-2 shadow-sm transition-all
          ${mergeMode && mergeDisabled ? 'border-slate-300 bg-slate-100 opacity-40 cursor-not-allowed' : ''}
          ${mergeMode && !mergeDisabled && mergeChecked ? 'border-amber-500 bg-amber-50 ring-2 ring-offset-2 ring-amber-400 shadow-md' : ''}
          ${mergeMode && !mergeDisabled && !mergeChecked ? 'border-emerald-400 bg-emerald-50 hover:border-amber-400 cursor-pointer' : ''}
          ${!mergeMode && isSelected ? 'border-emerald-500 ring-2 ring-offset-2 ring-emerald-500 shadow-md bg-emerald-50' : ''}
          ${!mergeMode && !isSelected ? 'border-emerald-400 bg-emerald-50 hover:shadow-md hover:border-emerald-500' : ''}
        `}
      >
        {/* Header with title and actions */}
        <div className="flex items-start justify-between gap-2 mb-1">
          {/* Merge checkbox */}
          {mergeMode && !mergeDisabled && (
            <div className={`mt-0.5 w-5 h-5 rounded border-2 flex items-center justify-center flex-shrink-0 ${
              mergeChecked ? 'border-amber-500 bg-amber-500' : 'border-slate-300'
            }`}>
              {mergeChecked && (
                <svg className="w-3 h-3 text-white" fill="currentColor" viewBox="0 0 20 20">
                  <path fillRule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clipRule="evenodd" />
                </svg>
              )}
            </div>
          )}
          {isEditing ? (
            <input
              ref={inputRef}
              type="text"
              value={editTitle}
              onChange={(e) => setEditTitle(e.target.value)}
              onKeyDown={handleKeyDown}
              onBlur={handleTitleSave}
              className="flex-1 text-sm font-semibold text-emerald-800 bg-white border border-emerald-300 rounded px-1 py-0.5 focus:outline-none focus:ring-1 focus:ring-emerald-500"
              onClick={(e) => e.stopPropagation()}
            />
          ) : (
            <span
              className="text-sm font-semibold text-emerald-800 line-clamp-1 cursor-text hover:bg-emerald-100 rounded px-1 -mx-1"
              onDoubleClick={handleDoubleClick}
              title="Double-click to edit"
            >
              {node.data.title}
            </span>
          )}
          {!mergeMode && (
          <div className="flex items-center gap-0.5 flex-shrink-0 -mt-0.5 -mr-0.5">
            {/* Red dot indicator for pending snippet confirmation */}
            {node.data.needsSnippetConfirmation && (
              <span
                className="relative flex items-center justify-center w-5 h-5"
                title={`${node.data.pendingSnippetCount || 0} snippets to confirm`}
              >
                <span className="absolute inline-flex h-3 w-3 rounded-full bg-red-500 opacity-75 animate-ping" />
                <span className="relative inline-flex h-2.5 w-2.5 rounded-full bg-red-500" />
              </span>
            )}
            {/* AI title button */}
            <button
              onClick={handleAITitle}
              disabled={isGeneratingAITitle}
              className="p-1 rounded hover:bg-purple-100 transition-colors disabled:opacity-50"
              title="AI generate title"
            >
              {isGeneratingAITitle ? (
                <svg className="w-3.5 h-3.5 animate-spin text-purple-500" fill="none" viewBox="0 0 24 24">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                </svg>
              ) : (
                <svg className="w-3.5 h-3.5 text-purple-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 10V3L4 14h7v7l9-11h-7z" />
                </svg>
              )}
            </button>
            {/* Regenerate button */}
            <button
              onClick={handleRegenerateClick}
              disabled={isRegenerating}
              className="p-1 rounded hover:bg-emerald-200 transition-colors disabled:opacity-50"
              title="Regenerate this section"
            >
              {isRegenerating ? (
                <svg className="w-3.5 h-3.5 animate-spin text-emerald-600" fill="none" viewBox="0 0 24 24">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                </svg>
              ) : (
                <svg className="w-3.5 h-3.5 text-emerald-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
                </svg>
              )}
            </button>
            {node.data.isAIGenerated && (
              <span className="text-[9px] px-1.5 py-0.5 bg-emerald-200 text-emerald-700 rounded">AI</span>
            )}
            {/* Delete button — rightmost */}
            <button
              onClick={handleDeleteClick}
              className="p-1 rounded hover:bg-red-100 transition-colors"
              title="Delete this sub-argument"
            >
              <svg className="w-3.5 h-3.5 text-red-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
              </svg>
            </button>
          </div>
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
              fontSize={11}
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
        const x2 = standardPos.x - 120; // Left edge of standard node (240px / 2)
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
  savedPositions: Map<string, Position>,
  legalStandards: import('../types').LegalStandard[]
): { argumentNodes: ArgumentNode[]; standardNodes: StandardNode[]; subArgumentNodes: SubArgumentNode[] } {
  // Position layout with sub-arguments on the left
  const SUBARG_X = 200;          // Base X for sub-arguments
  const SUBARG_X_OFFSET = 80;    // Horizontal offset for staggered layout
  const ARGUMENT_X = 800;
  const STANDARD_X = 1200;
  const START_Y = 100;
  const MIN_ARGUMENT_SPACING = 280;  // Minimum spacing between argument centers
  const SUBARG_SPACING = 140;    // Vertical spacing between sub-argument centers
  const SUBARG_CARD_HEIGHT = 200; // Conservative max height of sub-argument card
  const BETWEEN_GROUP_GAP = 120; // Visual gap between standard groups
  const WITHIN_GROUP_GAP = 60;   // Visual gap between arguments within same standard

  // Pre-calculate sub-argument counts per argument
  const subArgCountByArgument = new Map<string, number>();
  subArguments.forEach(sa => {
    const count = subArgCountByArgument.get(sa.argumentId) || 0;
    subArgCountByArgument.set(sa.argumentId, count + 1);
  });

  // Helper: calculate full visual height of an argument's sub-arg group
  // (from top edge of first card to bottom edge of last card)
  const getArgumentHeight = (argId: string): number => {
    const subArgCount = subArgCountByArgument.get(argId) || 0;
    if (subArgCount <= 1) return SUBARG_CARD_HEIGHT;
    return (subArgCount - 1) * SUBARG_SPACING + SUBARG_CARD_HEIGHT;
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

    // Calculate how far the first arg's sub-args extend above its center
    const firstArgTopExtent = getArgumentHeight(standardArgs[0].id) / 2;
    // Place first argument so its top sub-arg card starts at currentY
    const groupStartY = currentY + firstArgTopExtent;
    const argPositions: number[] = [];
    let argY = groupStartY;

    standardArgs.forEach((arg, idx) => {
      argPositions.push(argY);
      if (idx < standardArgs.length - 1) {
        // Spacing = half-heights of adjacent args + visual gap
        const currentHeight = getArgumentHeight(arg.id);
        const nextHeight = getArgumentHeight(standardArgs[idx + 1].id);
        const spacing = Math.max(currentHeight / 2 + nextHeight / 2 + WITHIN_GROUP_GAP, MIN_ARGUMENT_SPACING);
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

    // Move currentY to the bottom edge of this group + gap
    const lastArgBottomExtent = getArgumentHeight(standardArgs[standardArgs.length - 1].id) / 2;
    currentY = groupEndY + lastArgBottomExtent + BETWEEN_GROUP_GAP;
  });

  // Add unmapped arguments at the end
  unmappedArguments.forEach(arg => {
    const savedPos = savedPositions.get(arg.id);
    const argHeight = getArgumentHeight(arg.id);
    const topExtent = argHeight / 2;
    const argY = currentY + topExtent;
    argumentNodes.push({
      id: arg.id,
      type: 'argument' as const,
      position: savedPos || { x: ARGUMENT_X, y: argY },
      data: {
        title: arg.title,
        subject: arg.subject,
        standardKey: arg.standardKey,
        snippetCount: arg.snippetIds?.length || 0,
        isAIGenerated: arg.isAIGenerated,
        completenessScore: arg.completeness?.score,
      },
    });
    currentY = argY + argHeight / 2 + BETWEEN_GROUP_GAP;
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
          needsSnippetConfirmation: sa.needsSnippetConfirmation,
          pendingSnippetCount: sa.pendingSnippetIds?.length || 0,
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
  const legalStandards = useLegalStandards();
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
    updateSubArgument,
    regenerateSubArgument,
    removeSubArgument,
    addSubArgument,
    mergeSubArguments,
    rewriteStandard,
    removeStandard,
    removeArgument,
    letterSections,
    projectId,
  } = useApp();

  const containerRef = useRef<HTMLDivElement>(null);
  const [scale, setScale] = useState(0.7);  // Start at 70% zoom
  const [offset, setOffset] = useState<Position>({ x: 0, y: 0 });
  const [isPanning, setIsPanning] = useState(false);
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [newlyCreatedSubArgId, setNewlyCreatedSubArgId] = useState<string | null>(null);
  // Standard action state
  const [rewritingStandardKey, setRewritingStandardKey] = useState<string | null>(null);
  const [removeModalStandardKey, setRemoveModalStandardKey] = useState<string | null>(null);
  const [isRemovingStandard, setIsRemovingStandard] = useState(false);
  // SubArgument delete modal state
  const [deleteSubArgModalId, setDeleteSubArgModalId] = useState<string | null>(null);
  // Argument delete modal state
  const [deleteArgModalId, setDeleteArgModalId] = useState<string | null>(null);
  // Batch delete confirmation
  const [batchDeleteConfirm, setBatchDeleteConfirm] = useState(false);
  // Merge mode state
  const [isMergeMode, setIsMergeMode] = useState(false);
  const [mergeSelectedIds, setMergeSelectedIds] = useState<Set<string>>(new Set());
  const [isMerging, setIsMerging] = useState(false);
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
    argumentGraphPositions,
    legalStandards
  );

  // Which standards have generated letter content
  const generatedStandardIds = useMemo(() => {
    const ids = new Set<string>();
    for (const section of letterSections) {
      if (section.standardId && section.isGenerated) {
        ids.add(`standard-${section.standardId}`);
      }
    }
    return ids;
  }, [letterSections]);

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

  // Handle sub-argument title change - infer relationship and recommend snippets
  const handleSubArgumentTitleChange = useCallback(async (subArgumentId: string, newTitle: string) => {
    // Find the sub-argument to get its argumentId
    const subArg = contextSubArguments.find(sa => sa.id === subArgumentId);
    if (!subArg) return;

    // Update title first (frontend state)
    updateSubArgument(subArgumentId, { title: newTitle });

    // Run both API calls in parallel: infer relationship + recommend snippets
    try {
      const [relationshipResponse, snippetsResponse] = await Promise.all([
        // 1. Infer relationship
        apiClient.post<{ success: boolean; relationship: string }>(
          `/arguments/${projectId}/infer-relationship`,
          {
            argument_id: subArg.argumentId,
            subargument_title: newTitle,
          }
        ),
        // 2. Recommend snippets
        apiClient.post<{
          success: boolean;
          recommended_snippets: Array<{
            snippet_id: string;
            text: string;
            exhibit_id: string;
            page: number;
            relevance_score: number;
            reason: string;
          }>;
        }>(`/arguments/${projectId}/recommend-snippets`, {
          argument_id: subArg.argumentId,
          title: newTitle,
          description: subArg.purpose || undefined,
          exclude_snippet_ids: subArg.snippetIds || [],
        }),
      ]);

      // Collect all updates
      let relationship = subArg.relationship;
      let pendingSnippetIds: string[] = [];
      let needsSnippetConfirmation = false;

      // Update relationship
      if (relationshipResponse.success && relationshipResponse.relationship) {
        relationship = relationshipResponse.relationship;
        updateSubArgument(subArgumentId, { relationship });
      }

      // Update pending snippets (recommendations) — only if there are actual results
      if (snippetsResponse.success && snippetsResponse.recommended_snippets && snippetsResponse.recommended_snippets.length > 0) {
        pendingSnippetIds = snippetsResponse.recommended_snippets.map(s => s.snippet_id);
        needsSnippetConfirmation = true;
        updateSubArgument(subArgumentId, {
          pendingSnippetIds,
          needsSnippetConfirmation,
        });
      }

      // Persist to backend - save title, relationship, and pending snippets
      await apiClient.put(`/arguments/${projectId}/subarguments/${subArgumentId}`, {
        title: newTitle,
        relationship,
        pending_snippet_ids: pendingSnippetIds,
        needs_snippet_confirmation: needsSnippetConfirmation,
      });
      console.log('[ArgumentGraph] SubArgument title/relationship/pendingSnippets saved to backend');

    } catch (error) {
      console.error('Failed to infer relationship or recommend snippets:', error);
    }
  }, [updateSubArgument, contextSubArguments, projectId]);

  // Handle sub-argument regenerate
  const handleSubArgumentRegenerate = useCallback(async (subArgumentId: string) => {
    if (regenerateSubArgument) {
      await regenerateSubArgument(subArgumentId);
    }
  }, [regenerateSubArgument]);

  // Handle add SubArgument - directly create on the tree
  const handleAddSubArgument = useCallback(async (argumentId: string) => {
    if (!addSubArgument) return;

    try {
      const newSubArg = await addSubArgument({
        argumentId,
        title: '',  // Start with empty title - user will type directly
        purpose: '',
        relationship: '',
        snippetIds: [],
        isAIGenerated: false,
        status: 'draft' as const,
      });

      // Set the newly created ID to trigger auto-edit mode
      if (newSubArg) {
        setNewlyCreatedSubArgId(newSubArg.id);
        setSelectedNodeId(newSubArg.id);
        setFocusState({ type: 'subargument', id: newSubArg.id });
      }
    } catch (error) {
      console.error('Failed to create SubArgument:', error);
    }
  }, [addSubArgument, setFocusState]);

  // Handle delete SubArgument — open modal
  const handleSubArgumentDelete = useCallback((subArgumentId: string) => {
    setDeleteSubArgModalId(subArgumentId);
  }, []);

  // Confirm delete SubArgument from modal (with undo)
  const handleSubArgumentDeleteConfirm = useCallback(() => {
    if (!deleteSubArgModalId || !removeSubArgument) return;
    const sa = contextSubArguments.find(s => s.id === deleteSubArgModalId);
    const label = (sa?.title || '').slice(0, 30);
    const idToDelete = deleteSubArgModalId;

    // Optimistic: remove from UI immediately
    removeSubArgument(idToDelete);
    if (focusState.type === 'subargument' && focusState.id === idToDelete) {
      setFocusState({ type: 'none', id: null });
    }
    setSelectedNodeId(null);
    setDeleteSubArgModalId(null);

    toast.success(
      (toastObj) => (
        <span className="flex items-center gap-2">
          <span>Removed "{label}"</span>
          <button
            className="text-emerald-400 font-semibold hover:text-emerald-300 ml-1"
            onClick={() => { toast.dismiss(toastObj.id); }}
          >
            OK
          </button>
        </span>
      ),
      { duration: 3000 },
    );
  }, [deleteSubArgModalId, removeSubArgument, focusState, setFocusState, contextSubArguments]);

  // Handle delete Argument — open modal
  const handleArgumentDelete = useCallback((argumentId: string) => {
    setDeleteArgModalId(argumentId);
  }, []);

  // Confirm delete Argument from modal
  const handleArgumentDeleteConfirm = useCallback(() => {
    if (!deleteArgModalId || !removeArgument) return;
    const arg = contextArguments.find(a => a.id === deleteArgModalId);
    removeArgument(deleteArgModalId);
    if (focusState.type === 'argument' && focusState.id === deleteArgModalId) {
      setFocusState({ type: 'none', id: null });
    }
    setSelectedNodeId(null);
    setDeleteArgModalId(null);
    toast.success(`Argument "${(arg?.title || '').slice(0, 30)}" removed`);
  }, [deleteArgModalId, removeArgument, focusState, setFocusState, contextArguments]);

  // ==================== Standard Action Handlers ====================

  const handleStandardRewrite = useCallback(async (standardKey: string) => {
    setRewritingStandardKey(standardKey);
    try {
      await rewriteStandard(standardKey);
      toast.success(`${standardKey.replace(/_/g, ' ')} section rewritten`);
    } catch (err) {
      toast.error('Failed to rewrite section');
    } finally {
      setRewritingStandardKey(null);
    }
  }, [rewriteStandard]);

  const handleStandardRemoveConfirm = useCallback(async () => {
    if (!removeModalStandardKey) return;
    setIsRemovingStandard(true);
    try {
      await removeStandard(removeModalStandardKey);
      toast.success(`${removeModalStandardKey.replace(/_/g, ' ')} removed`);
      setRemoveModalStandardKey(null);
    } catch (err) {
      toast.error('Failed to remove standard');
    } finally {
      setIsRemovingStandard(false);
    }
  }, [removeModalStandardKey, removeStandard]);

  // ==================== Merge Mode Logic ====================

  // Determine which standard_key the first selected sub-arg belongs to (for same-standard constraint)
  const mergeLockedStandardKey = useMemo(() => {
    if (mergeSelectedIds.size === 0) return null;
    const firstId = mergeSelectedIds.values().next().value;
    const sa = contextSubArguments.find(s => s.id === firstId);
    if (!sa) return null;
    const parentArg = contextArguments.find(a => a.id === sa.argumentId);
    return parentArg?.standardKey || null;
  }, [mergeSelectedIds, contextSubArguments, contextArguments]);

  // Toggle merge selection for a sub-argument
  const handleMergeToggle = useCallback((subArgId: string) => {
    setMergeSelectedIds(prev => {
      const next = new Set(prev);
      if (next.has(subArgId)) {
        next.delete(subArgId);
      } else {
        next.add(subArgId);
      }
      return next;
    });
  }, []);

  // Exit merge mode
  const exitMergeMode = useCallback(() => {
    setIsMergeMode(false);
    setMergeSelectedIds(new Set());
    setBatchDeleteConfirm(false);
  }, []);

  // Batch delete selected sub-arguments
  const handleBatchDeleteConfirm = useCallback(() => {
    if (!removeSubArgument || mergeSelectedIds.size === 0) return;
    const count = mergeSelectedIds.size;
    for (const id of mergeSelectedIds) {
      removeSubArgument(id);
    }
    setBatchDeleteConfirm(false);
    setIsMergeMode(false);
    setMergeSelectedIds(new Set());
    setSelectedNodeId(null);
    toast.success(`Removed ${count} sub-argument${count > 1 ? 's' : ''}`);
  }, [removeSubArgument, mergeSelectedIds]);

  // Handle merge: directly merge with defaults, no modal
  const handleMergeConfirm = useCallback(async () => {
    if (!mergeSubArguments || mergeSelectedIds.size < 2) return;
    setIsMerging(true);
    try {
      // Pick defaults from the sub-arg with most snippets
      const selectedSAs = contextSubArguments.filter(sa => mergeSelectedIds.has(sa.id));
      const bestSA = [...selectedSAs].sort(
        (a, b) => (b.snippetIds?.length || 0) - (a.snippetIds?.length || 0)
      )[0];
      const defaultTitle = bestSA?.title || 'Merged argument';
      const purposes = selectedSAs.map(sa => sa.purpose?.trim()).filter(Boolean);
      const defaultPurpose = [...new Set(purposes)].join('; ');
      const defaultRelationship = bestSA?.relationship || 'Combined evidence';

      const result = await mergeSubArguments(
        Array.from(mergeSelectedIds),
        defaultTitle,
        defaultPurpose,
        defaultRelationship,
      );

      // Focus the new Argument node (sub-args are moved, not fused)
      setSelectedNodeId(result.newArgument.id);
      setFocusState({ type: 'argument', id: result.newArgument.id });

      // Exit merge mode
      setIsMergeMode(false);
      setMergeSelectedIds(new Set());
      toast.success(`Merged ${mergeSelectedIds.size} sub-arguments`);
    } catch (error) {
      toast.error('Merge failed');
    } finally {
      setIsMerging(false);
    }
  }, [mergeSubArguments, mergeSelectedIds, contextSubArguments, setFocusState]);

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
    setScale(0.7);
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

  // Auto-center on SubArgument when focused from LetterPanel
  // Track last centered ID to avoid re-centering on every render
  const lastCenteredSubArgId = useRef<string | null>(null);
  useEffect(() => {
    if (focusState.type !== 'subargument' || !focusState.id) {
      lastCenteredSubArgId.current = null;
      return;
    }

    // Only center once per focus change
    if (lastCenteredSubArgId.current === focusState.id) return;

    // Find the focused SubArgument node
    const targetNode = subArgumentNodes.find(n => n.id === focusState.id);
    if (!targetNode) return;

    const container = containerRef.current;
    if (!container) return;

    lastCenteredSubArgId.current = focusState.id;

    // Get container dimensions
    const containerRect = container.getBoundingClientRect();
    const containerHeight = containerRect.height;

    // Set scale to 70%
    const targetScale = 0.7;
    setScale(targetScale);

    // Calculate offset to center the node vertically only
    const targetY = targetNode.position.y;
    const newOffsetY = (containerHeight / 2) - (targetY * targetScale);

    // Keep horizontal offset at default (0) like auto-arrange button
    setOffset({ x: 0, y: newOffsetY });
  }, [focusState.type, focusState.id, subArgumentNodes]);

  // Handle keyboard shortcuts
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        if (isMergeMode) {
          exitMergeMode();
        } else {
          setSelectedNodeId(null);
        }
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [isMergeMode, exitMergeMode]);

  // Get generateArguments from context
  const { generateArguments, isGeneratingArguments, workMode, setWorkMode } = useApp();

  return (
    <div className="flex flex-col h-full bg-slate-50">
      {/* Header */}
      <div className="flex-shrink-0 px-4 py-2 bg-white border-b border-slate-200">
        <div className="flex items-center justify-between">
          {/* Left side: Title + Generate button */}
          <div className="flex items-center gap-3">
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

          {/* Right side: Merge button + Write/Verify toggle */}
          <div className="flex items-center gap-2">
          <button
            onClick={() => {
              if (isMergeMode) {
                exitMergeMode();
              } else {
                setIsMergeMode(true);
                setMergeSelectedIds(new Set());
              }
            }}
            className={`flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-lg transition-colors ${
              isMergeMode
                ? 'text-white bg-amber-500 hover:bg-amber-600'
                : 'text-slate-600 bg-slate-100 hover:bg-slate-200'
            }`}
          >
            <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 7h12m0 0l-4-4m4 4l-4 4m0 6H4m0 0l4 4m-4-4l4-4" />
            </svg>
            <span>{isMergeMode ? 'Exit Merge' : 'Merge'}</span>
          </button>
          <button
            onClick={() => setWorkMode(workMode === 'verify' ? 'write' : 'verify')}
            className={`flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-lg transition-colors ${
              workMode === 'verify'
                ? 'text-white bg-blue-600 hover:bg-blue-700'
                : 'text-white bg-emerald-600 hover:bg-emerald-700'
            }`}
          >
            {workMode === 'verify' ? (
              <>
                <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z" />
                </svg>
                <span>Write</span>
              </>
            ) : (
              <>
                <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
                </svg>
                <span>Verify</span>
              </>
            )}
          </button>
          </div>
        </div>
      </div>

      {/* Merge mode banner */}
      {isMergeMode && (
        <div className="flex-shrink-0 px-4 py-1.5 bg-amber-50 border-b border-amber-200 text-xs text-amber-700">
          Click sub-argument cards to select them for merging. All selected must be under the same standard (can be from different arguments). Press Escape to cancel.
        </div>
      )}

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
            {subArgumentNodes.map(node => {
              // Find this sub-arg's standard_key via its parent argument
              const parentArg = contextArguments.find(a => a.id === node.data.argumentId);
              const nodeStandardKey = parentArg?.standardKey || null;
              const isMergeDisabled = isMergeMode && mergeLockedStandardKey !== null && nodeStandardKey !== mergeLockedStandardKey;
              const isMergeChecked = mergeSelectedIds.has(node.id);
              return (
                <SubArgumentNodeComponent
                  key={node.id}
                  node={node}
                  isSelected={isMergeMode ? isMergeChecked : isSubArgumentHighlighted(node)}
                  onSelect={() => {
                    if (isMergeMode) {
                      if (!isMergeDisabled) handleMergeToggle(node.id);
                    } else {
                      handleSubArgumentSelect(node.id);
                    }
                  }}
                  onDrag={isMergeMode ? () => {} : handleNodeDrag}
                  scale={scale}
                  t={t}
                  onPositionReport={handleSubArgumentPositionReport}
                  transformVersion={transformVersion}
                  onRegenerate={isMergeMode ? undefined : handleSubArgumentRegenerate}
                  onTitleChange={isMergeMode ? undefined : handleSubArgumentTitleChange}
                  onDelete={isMergeMode ? undefined : handleSubArgumentDelete}
                  autoEdit={node.id === newlyCreatedSubArgId}
                  onAutoEditComplete={() => setNewlyCreatedSubArgId(null)}
                  mergeMode={isMergeMode}
                  mergeChecked={isMergeChecked}
                  mergeDisabled={isMergeDisabled}
                  projectId={projectId}
                />
              );
            })}

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
                onAddSubArgument={handleAddSubArgument}
                onDelete={handleArgumentDelete}
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
                onRewrite={handleStandardRewrite}
                onRemove={(key) => setRemoveModalStandardKey(key)}
                isRewriting={rewritingStandardKey === node.id}
                hasLetterContent={generatedStandardIds.has(node.id)}
              />
            ))}
          </div>
        </div>

        {/* Merge mode floating action bar */}
        {isMergeMode && (
          <div className="absolute bottom-4 left-1/2 -translate-x-1/2 z-50 bg-white rounded-xl shadow-xl border border-amber-300 px-5 py-3 flex items-center gap-4">
            <span className="text-sm text-slate-700 font-medium">
              {mergeSelectedIds.size} selected
            </span>
            <button
              onClick={exitMergeMode}
              className="px-3 py-1.5 text-xs text-slate-600 hover:text-slate-800 border border-slate-300 rounded-lg"
            >
              Cancel
            </button>
            <button
              onClick={() => setBatchDeleteConfirm(true)}
              disabled={mergeSelectedIds.size < 1}
              className="px-4 py-1.5 text-xs text-white bg-red-600 hover:bg-red-700 rounded-lg disabled:opacity-50 disabled:cursor-not-allowed font-medium"
            >
              Delete {mergeSelectedIds.size}
            </button>
            <button
              onClick={handleMergeConfirm}
              disabled={mergeSelectedIds.size < 2 || isMerging}
              className="px-4 py-1.5 text-xs text-white bg-emerald-600 hover:bg-emerald-700 rounded-lg disabled:opacity-50 disabled:cursor-not-allowed font-medium"
            >
              {isMerging ? 'Merging...' : `Merge ${mergeSelectedIds.size}`}
            </button>
          </div>
        )}
      </div>

      {/* Standard remove confirmation modal */}
      {removeModalStandardKey && (() => {
        const stdNode = standardNodes.find(n => n.id === removeModalStandardKey);
        const argCount = contextArguments.filter(a => a.standardKey === removeModalStandardKey).length;
        const subArgCount = contextSubArguments.filter(sa => {
          const parentArg = contextArguments.find(a => a.id === sa.argumentId);
          return parentArg?.standardKey === removeModalStandardKey;
        }).length;
        return (
          <StandardActionModal
            standardName={stdNode?.data.name || removeModalStandardKey}
            standardColor={stdNode?.data.color || '#94a3b8'}
            argumentCount={argCount}
            subArgumentCount={subArgCount}
            onConfirm={handleStandardRemoveConfirm}
            onCancel={() => setRemoveModalStandardKey(null)}
            isRemoving={isRemovingStandard}
          />
        );
      })()}

      {/* SubArgument delete confirmation modal */}
      {deleteSubArgModalId && (() => {
        const sa = contextSubArguments.find(s => s.id === deleteSubArgModalId);
        return (
          <div className="fixed inset-0 z-50 flex items-center justify-center">
            <div className="absolute inset-0 bg-black/40 backdrop-blur-sm" onClick={() => setDeleteSubArgModalId(null)} />
            <div className="relative bg-white rounded-xl shadow-xl w-full max-w-sm mx-4 overflow-hidden">
              <div className="px-5 py-4 border-b border-slate-200 bg-slate-50">
                <div className="flex items-center gap-2">
                  <svg className="w-5 h-5 text-red-500 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-2.5L13.732 4c-.77-.833-1.964-.833-2.732 0L4.082 16.5c-.77.833.192 2.5 1.732 2.5z" />
                  </svg>
                  <h3 className="text-sm font-semibold text-slate-800">{t('graph.removeSubArg.title', 'Remove Sub-Argument')}</h3>
                </div>
              </div>
              <div className="px-5 py-4 space-y-3">
                <div className="flex items-center gap-2">
                  <div className="w-3 h-3 rounded-full bg-emerald-500 flex-shrink-0" />
                  <span className="text-sm font-medium text-slate-700 line-clamp-2">{sa?.title || deleteSubArgModalId}</span>
                </div>
                <p className="text-sm text-slate-600">
                  {t('graph.removeSubArg.description', 'This will permanently remove this sub-argument and its associated letter content.')}
                </p>
                <p className="text-xs text-red-600 font-medium">
                  {t('graph.removeStandard.warning', 'This action cannot be undone.')}
                </p>
              </div>
              <div className="px-5 py-4 border-t border-slate-200 bg-slate-50 flex items-center justify-end gap-3">
                <button
                  onClick={() => setDeleteSubArgModalId(null)}
                  className="px-4 py-2 text-sm font-medium text-slate-600 hover:text-slate-800 transition-colors"
                >
                  {t('common.cancel', 'Cancel')}
                </button>
                <button
                  onClick={handleSubArgumentDeleteConfirm}
                  className="px-4 py-2 text-sm font-medium text-white bg-red-600 rounded-lg hover:bg-red-700 transition-colors"
                >
                  {t('graph.removeStandard.confirm', 'Remove')}
                </button>
              </div>
            </div>
          </div>
        );
      })()}

      {/* Argument delete confirmation modal */}
      {deleteArgModalId && (() => {
        const arg = contextArguments.find(a => a.id === deleteArgModalId);
        const childCount = contextSubArguments.filter(sa => sa.argumentId === deleteArgModalId).length;
        return (
          <div className="fixed inset-0 z-50 flex items-center justify-center">
            <div className="absolute inset-0 bg-black/40 backdrop-blur-sm" onClick={() => setDeleteArgModalId(null)} />
            <div className="relative bg-white rounded-xl shadow-xl w-full max-w-sm mx-4 overflow-hidden">
              <div className="px-5 py-4 border-b border-slate-200 bg-slate-50">
                <div className="flex items-center gap-2">
                  <svg className="w-5 h-5 text-red-500 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-2.5L13.732 4c-.77-.833-1.964-.833-2.732 0L4.082 16.5c-.77.833.192 2.5 1.732 2.5z" />
                  </svg>
                  <h3 className="text-sm font-semibold text-slate-800">{t('graph.removeArg.title', 'Remove Argument')}</h3>
                </div>
              </div>
              <div className="px-5 py-4 space-y-3">
                <div className="flex items-center gap-2">
                  <div className="w-3 h-3 rounded-full bg-purple-500 flex-shrink-0" />
                  <span className="text-sm font-medium text-slate-700 line-clamp-2">{arg?.title || deleteArgModalId}</span>
                </div>
                <p className="text-sm text-slate-600">
                  {t('graph.removeArg.description', {
                    defaultValue: 'This will permanently remove this argument and its {{count}} sub-argument(s).',
                    count: childCount,
                  })}
                </p>
                <p className="text-xs text-red-600 font-medium">
                  {t('graph.removeStandard.warning', 'This action cannot be undone.')}
                </p>
              </div>
              <div className="px-5 py-4 border-t border-slate-200 bg-slate-50 flex items-center justify-end gap-3">
                <button
                  onClick={() => setDeleteArgModalId(null)}
                  className="px-4 py-2 text-sm font-medium text-slate-600 hover:text-slate-800 transition-colors"
                >
                  {t('common.cancel', 'Cancel')}
                </button>
                <button
                  onClick={handleArgumentDeleteConfirm}
                  className="px-4 py-2 text-sm font-medium text-white bg-red-600 rounded-lg hover:bg-red-700 transition-colors"
                >
                  {t('graph.removeStandard.confirm', 'Remove')}
                </button>
              </div>
            </div>
          </div>
        );
      })()}

      {/* Batch delete confirmation modal */}
      {batchDeleteConfirm && mergeSelectedIds.size > 0 && (
        <div className="fixed inset-0 z-50 flex items-center justify-center">
          <div className="absolute inset-0 bg-black/40 backdrop-blur-sm" onClick={() => setBatchDeleteConfirm(false)} />
          <div className="relative bg-white rounded-xl shadow-xl w-full max-w-sm mx-4 overflow-hidden">
            <div className="px-5 py-4 border-b border-slate-200 bg-slate-50">
              <div className="flex items-center gap-2">
                <svg className="w-5 h-5 text-red-500 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-2.5L13.732 4c-.77-.833-1.964-.833-2.732 0L4.082 16.5c-.77.833.192 2.5 1.732 2.5z" />
                </svg>
                <h3 className="text-sm font-semibold text-slate-800">{t('graph.batchDelete.title', 'Batch Delete')}</h3>
              </div>
            </div>
            <div className="px-5 py-4 space-y-3">
              <p className="text-sm text-slate-600">
                {t('graph.batchDelete.description', {
                  defaultValue: 'This will permanently remove {{count}} selected sub-argument(s) and their associated letter content.',
                  count: mergeSelectedIds.size,
                })}
              </p>
              <div className="max-h-32 overflow-y-auto space-y-1">
                {Array.from(mergeSelectedIds).map(id => {
                  const sa = contextSubArguments.find(s => s.id === id);
                  return (
                    <div key={id} className="flex items-center gap-2 text-xs text-slate-600">
                      <div className="w-2 h-2 rounded-full bg-emerald-500 flex-shrink-0" />
                      <span className="line-clamp-1">{sa?.title || id}</span>
                    </div>
                  );
                })}
              </div>
              <p className="text-xs text-red-600 font-medium">
                {t('graph.removeStandard.warning', 'This action cannot be undone.')}
              </p>
            </div>
            <div className="px-5 py-4 border-t border-slate-200 bg-slate-50 flex items-center justify-end gap-3">
              <button
                onClick={() => setBatchDeleteConfirm(false)}
                className="px-4 py-2 text-sm font-medium text-slate-600 hover:text-slate-800 transition-colors"
              >
                {t('common.cancel', 'Cancel')}
              </button>
              <button
                onClick={handleBatchDeleteConfirm}
                className="px-4 py-2 text-sm font-medium text-white bg-red-600 rounded-lg hover:bg-red-700 transition-colors"
              >
                {t('graph.batchDelete.confirm', { defaultValue: 'Delete {{count}}', count: mergeSelectedIds.size })}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
