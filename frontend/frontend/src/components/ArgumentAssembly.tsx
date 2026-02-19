import { useState, useRef, useEffect, useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import { useApp } from '../context/AppContext';
import type { Argument, Snippet, ArgumentStatus, HumanDecision } from '../types';
import { getStandardKeyColor, STANDARD_KEY_TO_ID } from '../constants/colors';
import StandardFilterBar from './StandardFilterBar';

// Qualification panel component - shows AI checks and human decision buttons
function QualificationPanel({
  argument,
  onDecision,
}: {
  argument: Argument;
  onDecision: (decision: HumanDecision) => void;
}) {
  const qual = argument.qualification;
  if (!qual) return null;

  const isExcludeRecommended = qual.recommendation === 'exclude';
  const isApproved = argument.humanDecision === 'approved';
  const isExcluded = argument.humanDecision === 'excluded';

  return (
    <div className={`
      mt-2 p-2 rounded-lg text-xs border
      ${isExcludeRecommended ? 'bg-red-50 border-red-200' : 'bg-green-50 border-green-200'}
      ${isExcluded ? 'opacity-50' : ''}
    `}>
      {/* AI Recommendation Badge */}
      <div className="flex items-center justify-between mb-2">
        <span className={`
          px-2 py-0.5 rounded-full text-[10px] font-medium
          ${isExcludeRecommended ? 'bg-red-100 text-red-700' : 'bg-green-100 text-green-700'}
        `}>
          AI: {qual.recommendation === 'keep' ? 'Recommend Keep' : qual.recommendation === 'exclude' ? 'Recommend Exclude' : 'Suggest Merge'}
        </span>
        <span className="text-slate-400">
          {Math.round(qual.confidence * 100)}% confidence
        </span>
      </div>

      {/* Qualification Checks */}
      <div className="space-y-1 mb-2">
        {qual.checks.map((check) => (
          <div key={check.key} className="flex items-center gap-2">
            <span className={check.passed ? 'text-green-600' : 'text-red-500'}>
              {check.passed ? '✓' : '✗'}
            </span>
            <span className={check.passed ? 'text-slate-600' : 'text-red-600'}>
              {check.label}
            </span>
            {check.note && (
              <span className="text-slate-400 text-[10px]">({check.note})</span>
            )}
          </div>
        ))}
      </div>

      {/* Completeness Bar */}
      <div className="mb-2">
        <div className="flex items-center justify-between text-[10px] text-slate-500 mb-1">
          <span>Completeness</span>
          <span>{qual.completeness}%</span>
        </div>
        <div className="h-1.5 bg-slate-200 rounded-full overflow-hidden">
          <div
            className={`h-full rounded-full transition-all ${
              qual.completeness >= 70 ? 'bg-green-500' : qual.completeness >= 40 ? 'bg-amber-500' : 'bg-red-500'
            }`}
            style={{ width: `${qual.completeness}%` }}
          />
        </div>
      </div>

      {/* Human Decision Buttons */}
      {!isApproved && !isExcluded && (
        <div className="flex gap-2 pt-2 border-t border-slate-200">
          <button
            onClick={() => onDecision('approved')}
            className="flex-1 px-2 py-1.5 bg-green-100 text-green-700 rounded hover:bg-green-200 transition-colors flex items-center justify-center gap-1"
          >
            <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
            </svg>
            Keep
          </button>
          <button
            onClick={() => onDecision('excluded')}
            className="flex-1 px-2 py-1.5 bg-red-100 text-red-700 rounded hover:bg-red-200 transition-colors flex items-center justify-center gap-1"
          >
            <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
            Exclude
          </button>
        </div>
      )}

      {/* Decision Made Indicator */}
      {(isApproved || isExcluded) && (
        <div className={`
          flex items-center justify-center gap-1 pt-2 border-t border-slate-200
          ${isApproved ? 'text-green-600' : 'text-red-600'}
        `}>
          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            {isApproved ? (
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
            ) : (
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            )}
          </svg>
          <span className="font-medium">
            {isApproved ? 'Approved' : 'Excluded'}
          </span>
          <button
            onClick={() => onDecision('pending')}
            className="ml-2 text-slate-400 hover:text-slate-600 text-[10px] underline"
          >
            Undo
          </button>
        </div>
      )}
    </div>
  );
}

// Status badge component
function StatusBadge({ status }: { status: ArgumentStatus }) {
  const colors: Record<ArgumentStatus, string> = {
    draft: 'bg-amber-100 text-amber-700 border-amber-300',
    verified: 'bg-green-100 text-green-700 border-green-300',
    mapped: 'bg-blue-100 text-blue-700 border-blue-300',
    used: 'bg-purple-100 text-purple-700 border-purple-300',
  };

  const labels: Record<ArgumentStatus, string> = {
    draft: 'Draft',
    verified: 'Verified',
    mapped: 'Mapped',
    used: 'Used',
  };

  return (
    <span className={`text-[10px] px-1.5 py-0.5 rounded border ${colors[status]}`}>
      {labels[status]}
    </span>
  );
}

// Snippet chip inside argument card
function SnippetChip({
  snippet,
  onRemove,
}: {
  snippet: Snippet;
  onRemove: () => void;
}) {
  return (
    <div className="flex items-start gap-2 p-2 bg-white rounded border text-xs group hover:border-slate-300">
      <div className="flex-1 min-w-0">
        <span className="text-slate-400 text-[10px]">[{snippet.exhibitId || snippet.id.slice(0, 8)}]</span>
        <span className="text-slate-600 ml-1 break-words">
          {snippet.content.slice(0, 100)}{snippet.content.length > 100 ? '...' : ''}
        </span>
      </div>
      <button
        onClick={(e) => {
          e.stopPropagation();
          onRemove();
        }}
        className="opacity-0 group-hover:opacity-100 text-red-400 hover:text-red-600 flex-shrink-0"
      >
        <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
        </svg>
      </button>
    </div>
  );
}

// Single argument card
function ArgumentCard({
  argument,
  snippets,
  isExpanded,
  isFocused,
  reviewMode,
  onToggleExpand,
  onUpdateArgument,
  onRemoveSnippet,
  onDragStart,
  onDragEnd,
  onClick,
  updatePosition,
}: {
  argument: Argument;
  snippets: Snippet[];
  isExpanded: boolean;
  isFocused: boolean;
  reviewMode: boolean;
  onToggleExpand: () => void;
  onUpdateArgument: (updates: Partial<Argument>) => void;
  onRemoveSnippet: (snippetId: string) => void;
  onDragStart: () => void;
  onDragEnd: () => void;
  onClick: () => void;
  updatePosition: (rect: DOMRect) => void;
}) {
  const cardRef = useRef<HTMLDivElement>(null);
  const [isEditingTitle, setIsEditingTitle] = useState(false);
  const [titleValue, setTitleValue] = useState(argument.title || '');

  // Update position for connection lines
  useEffect(() => {
    if (cardRef.current) {
      const rect = cardRef.current.getBoundingClientRect();
      updatePosition(rect);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [argument.id, isExpanded]);

  const handleDragStart = (e: React.DragEvent) => {
    e.dataTransfer.setData('argumentId', argument.id);
    e.dataTransfer.effectAllowed = 'link';
    onDragStart();
  };

  const handleClick = (e: React.MouseEvent) => {
    // Don't trigger click when editing title
    if (isEditingTitle) return;
    if ((e.target as HTMLElement).closest('input')) return;
    // Always update focus state when clicking anywhere on the card
    // (buttons have their own click handlers with stopPropagation)
    onClick();
  };

  // Get color from standardKey (if mapped) otherwise use status-based colors
  const standardColor = argument.standardKey ? getStandardKeyColor(argument.standardKey) : null;
  const hasMappedStandard = !!argument.standardKey && !!STANDARD_KEY_TO_ID[argument.standardKey];

  // Fallback status-based colors (used when no standard is mapped)
  const statusColors: Record<ArgumentStatus, string> = {
    draft: 'border-amber-300 bg-amber-50',
    verified: 'border-green-300 bg-green-50',
    mapped: 'border-blue-300 bg-blue-50',
    used: 'border-purple-300 bg-purple-50',
  };

  // Ring color for focused state - use standard color or default blue
  const ringColor = standardColor || '#3b82f6';

  return (
    <div
      ref={cardRef}
      draggable
      onDragStart={handleDragStart}
      onDragEnd={onDragEnd}
      onClick={handleClick}
      className={`
        border-2 rounded-lg p-3 cursor-grab active:cursor-grabbing
        transition-all duration-200 hover:shadow-md
        ${!hasMappedStandard ? statusColors[argument.status || 'draft'] : ''}
        ${isFocused ? 'ring-2 ring-offset-2 shadow-lg' : ''}
      `}
      style={{
        ...(hasMappedStandard ? {
          borderColor: standardColor || undefined,
          backgroundColor: standardColor ? `${standardColor}15` : undefined,
        } : {}),
        // Always set ring color when focused (not conditional on hasMappedStandard)
        ...(isFocused ? {
          ['--tw-ring-color' as string]: ringColor,
        } : {}),
      }}
    >
      {/* Header: Title + Subject + Status */}
      <div className="flex items-start justify-between gap-2">
        <div className="flex-1 min-w-0">
          {isEditingTitle ? (
            <input
              type="text"
              className="w-full text-sm font-medium bg-white border border-slate-300 rounded px-2 py-1 focus:outline-none focus:ring-2 focus:ring-blue-500"
              value={titleValue}
              onChange={(e) => setTitleValue(e.target.value)}
              onBlur={() => {
                setIsEditingTitle(false);
                if (titleValue !== argument.title) {
                  onUpdateArgument({ title: titleValue });
                }
              }}
              onKeyDown={(e) => {
                if (e.key === 'Enter') {
                  setIsEditingTitle(false);
                  if (titleValue !== argument.title) {
                    onUpdateArgument({ title: titleValue });
                  }
                }
              }}
              autoFocus
            />
          ) : (
            <h4
              className="text-sm font-medium text-slate-800 cursor-text hover:bg-white/50 rounded px-1 -mx-1"
              onClick={() => setIsEditingTitle(true)}
            >
              {argument.title || 'Untitled Argument'}
            </h4>
          )}

          {/* Subject line */}
          <div className="flex items-center gap-1 mt-1">
            <span className="text-[10px] text-slate-400">Subject:</span>
            <input
              className="text-xs text-slate-600 bg-transparent border-b border-dashed border-slate-300 focus:border-blue-500 focus:outline-none px-0.5"
              value={argument.subject || ''}
              onChange={(e) => onUpdateArgument({ subject: e.target.value })}
              placeholder="Who is this about?"
            />
          </div>
        </div>

        <div className="flex items-center gap-1.5 flex-shrink-0">
          <StatusBadge status={argument.status || 'draft'} />
          <button
            onClick={(e) => { e.stopPropagation(); onToggleExpand(); }}
            className="text-slate-400 hover:text-slate-600 p-0.5"
          >
            <svg
              className={`w-4 h-4 transition-transform ${isExpanded ? 'rotate-180' : ''}`}
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
            >
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
            </svg>
          </button>
        </div>
      </div>

      {/* Expanded: Snippet list */}
      {isExpanded && (
        <div className="mt-3 space-y-1.5 pl-2 border-l-2 border-slate-200">
          {snippets.length === 0 ? (
            <div className="text-xs text-slate-400 italic py-2">
              Drop snippets here to add evidence
            </div>
          ) : (
            snippets.map((snip) => (
              <SnippetChip
                key={snip.id}
                snippet={snip}
                onRemove={() => onRemoveSnippet(snip.id)}
              />
            ))
          )}

          {/* Drop zone for additional snippets */}
          <div
            className="border-2 border-dashed border-slate-200 rounded p-2 text-center text-xs text-slate-400 hover:border-slate-300 hover:bg-slate-50 transition-colors"
            onDragOver={(e) => {
              e.preventDefault();
              e.currentTarget.classList.add('border-blue-400', 'bg-blue-50');
            }}
            onDragLeave={(e) => {
              e.currentTarget.classList.remove('border-blue-400', 'bg-blue-50');
            }}
            onDrop={(e) => {
              e.preventDefault();
              e.currentTarget.classList.remove('border-blue-400', 'bg-blue-50');
              const snippetId = e.dataTransfer.getData('snippetId');
              if (snippetId) {
                // This will be handled by parent
                const event = new CustomEvent('addSnippetToArgument', {
                  detail: { argumentId: argument.id, snippetId }
                });
                window.dispatchEvent(event);
              }
            }}
          >
            + Drop snippet to add
          </div>
        </div>
      )}

      {/* Collapsed: Summary */}
      {!isExpanded && (
        <div className="mt-1 text-[10px] text-slate-400 flex items-center gap-2">
          <span>{snippets.length} snippet(s)</span>
          <span>|</span>
          <span className="capitalize">{(argument.claimType || 'other').replace('_', ' ')}</span>
          {argument.standardKey && (
            <>
              <span>|</span>
              <span className="text-blue-500">{argument.standardKey}</span>
            </>
          )}
        </div>
      )}

      {/* Qualification Panel (Review Mode) */}
      {reviewMode && argument.qualification && (
        <QualificationPanel
          argument={argument}
          onDecision={(decision) => onUpdateArgument({ humanDecision: decision })}
        />
      )}

      {/* Verify button for draft status (only show when not in review mode or no qualification) */}
      {!reviewMode && (argument.status || 'draft') === 'draft' && snippets.length > 0 && (
        <button
          onClick={() => onUpdateArgument({ status: 'verified' })}
          className="mt-2 w-full text-xs px-3 py-1.5 bg-green-100 text-green-700 rounded-lg hover:bg-green-200 transition-colors flex items-center justify-center gap-1"
        >
          <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
          </svg>
          Verify this argument
        </button>
      )}
    </div>
  );
}

// Main ArgumentAssembly component
export function ArgumentAssembly() {
  const { t } = useTranslation();
  const {
    arguments: arguments_,
    allSnippets,
    addArgument,
    updateArgument,
    removeArgument,
    addSnippetToArgument,
    removeSnippetFromArgument,
    draggedSnippetId,
    setDraggedArgumentId,
    updateArgumentPosition2,
    // AI Generation
    isGeneratingArguments,
    generateArguments,
    generatedMainSubject,
    // Focus state for filtering
    focusState,
    setFocusState,
    setSelectedSnippetId,
    argumentMappings,
  } = useApp();

  const [expandedIds, setExpandedIds] = useState<Set<string>>(new Set());
  const [isDragOver, setIsDragOver] = useState(false);
  const [generateError, setGenerateError] = useState<string | null>(null);

  // Applicant name input modal state
  const [showApplicantModal, setShowApplicantModal] = useState(false);
  const [applicantName, setApplicantName] = useState('');

  // Review mode state
  const [reviewMode, setReviewMode] = useState(false);

  // Filter arguments based on focusState
  // When a standard is focused, only show arguments mapped to that standard
  // Check both AI-generated standardKey AND manual drag-drop mappings
  const filteredArguments = useMemo(() => {
    if (focusState.type === 'standard' && focusState.id) {
      const focusedStandardId = focusState.id;
      return arguments_.filter(arg => {
        // Check AI-generated standardKey mapping
        if (arg.standardKey && STANDARD_KEY_TO_ID[arg.standardKey] === focusedStandardId) {
          return true;
        }
        // Check manual drag-drop mapping
        return argumentMappings.some(m => m.source === arg.id && m.target === focusedStandardId);
      });
    }
    return arguments_;
  }, [arguments_, focusState, argumentMappings]);

  // Handle argument click to set focusState
  const handleArgumentClick = (argumentId: string) => {
    if (focusState.type === 'argument' && focusState.id === argumentId) {
      // Click again to deselect
      setFocusState({ type: 'none', id: null });
    } else {
      // Clear snippet selection when focusing an argument (higher-level focus takes over)
      setSelectedSnippetId(null);
      setFocusState({ type: 'argument', id: argumentId });
    }
  };

  // Handle AI argument generation - show modal first
  const handleGenerateClick = () => {
    setShowApplicantModal(true);
  };

  // Actually generate after user provides applicant name
  const handleGenerateArguments = async () => {
    if (!applicantName.trim()) {
      return;
    }
    setShowApplicantModal(false);
    setGenerateError(null);
    try {
      await generateArguments(false, applicantName.trim());
    } catch (err) {
      setGenerateError(err instanceof Error ? err.message : 'Generation failed');
    }
  };

  // Listen for custom event from snippet drop inside argument card
  useEffect(() => {
    const handler = (e: CustomEvent<{ argumentId: string; snippetId: string }>) => {
      addSnippetToArgument(e.detail.argumentId, e.detail.snippetId);
    };
    window.addEventListener('addSnippetToArgument', handler as EventListener);
    return () => window.removeEventListener('addSnippetToArgument', handler as EventListener);
  }, [addSnippetToArgument]);

  // Expand is mutually exclusive - only one card can be expanded at a time
  const toggleExpand = (id: string) => {
    setExpandedIds((prev) => {
      if (prev.has(id)) {
        // Clicking expanded card collapses it
        return new Set();
      } else {
        // Clicking collapsed card expands it (and collapses others)
        return new Set([id]);
      }
    });
  };

  const getSnippetsForArgument = (arg: Argument): Snippet[] => {
    if (!allSnippets || !arg.snippetIds) return [];
    return arg.snippetIds
      .map((id) => allSnippets.find((s) => s.id === id))
      .filter((s): s is Snippet => s !== undefined);
  };

  // Handle drop to create new argument
  const handleDropNewArgument = (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragOver(false);

    const snippetId = e.dataTransfer.getData('snippetId');
    if (!snippetId) return;

    const snippet = allSnippets?.find((s) => s.id === snippetId);
    if (!snippet) return;

    // Create new argument with this snippet
    addArgument({
      title: '',
      subject: '',
      claimType: snippet.materialType === 'salary' ? 'salary' :
                 snippet.materialType === 'award' ? 'award' :
                 snippet.materialType === 'leadership' ? 'leading_role' :
                 snippet.materialType === 'contribution' ? 'contribution' :
                 snippet.materialType === 'membership' ? 'membership' :
                 snippet.materialType === 'publication' ? 'publication' :
                 snippet.materialType === 'judging' ? 'judging' : 'other',
      snippetIds: [snippetId],
      status: 'draft',
      isAIGenerated: false,
    });
  };

  return (
    <div className="h-full flex flex-col bg-slate-50">
      {/* Header */}
      <div className="flex-shrink-0 px-4 py-3 bg-white border-b border-slate-200">
        <div className="flex items-center justify-between">
          <div>
            <h2 className="text-sm font-semibold text-slate-800">{t('header.writingTree')}</h2>
            <p className="text-xs text-slate-500 mt-0.5">
              {arguments_.length} argument(s)
              {generatedMainSubject && (
                <span className="ml-2 text-blue-600">Subject: {generatedMainSubject}</span>
              )}
            </p>
          </div>
          <div className="flex items-center gap-2">
            {/* Review Mode Toggle */}
            <button
              onClick={() => setReviewMode(!reviewMode)}
              className={`
                text-xs px-3 py-1.5 rounded-lg flex items-center gap-1.5 transition-colors
                ${reviewMode
                  ? 'bg-amber-500 text-white hover:bg-amber-600'
                  : 'bg-slate-100 text-slate-600 hover:bg-slate-200'
                }
              `}
            >
              <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
              </svg>
              {reviewMode ? 'Exit Review' : 'Review'}
            </button>
            {/* Generate Button */}
            <button
              onClick={handleGenerateClick}
              disabled={isGeneratingArguments}
              className={`
                text-xs px-3 py-1.5 rounded-lg flex items-center gap-1.5 transition-colors
                ${isGeneratingArguments
                  ? 'bg-slate-100 text-slate-400 cursor-not-allowed'
                  : 'bg-blue-500 text-white hover:bg-blue-600'
                }
              `}
            >
              {isGeneratingArguments ? (
                <>
                  <svg className="w-3.5 h-3.5 animate-spin" fill="none" viewBox="0 0 24 24">
                    <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                    <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" />
                  </svg>
                  Generating...
                </>
              ) : (
                <>
                  <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 10V3L4 14h7v7l9-11h-7z" />
                  </svg>
                  Generate
                </>
              )}
            </button>
          </div>
        </div>
        {generateError && (
          <p className="text-xs text-red-500 mt-1">{generateError}</p>
        )}
        {/* Review Mode Stats */}
        {reviewMode && (
          <div className="mt-2 flex items-center gap-4 text-xs">
            <span className="text-green-600">
              ✓ {arguments_.filter(a => a.humanDecision === 'approved').length} approved
            </span>
            <span className="text-red-600">
              ✗ {arguments_.filter(a => a.humanDecision === 'excluded').length} excluded
            </span>
            <span className="text-slate-400">
              ○ {arguments_.filter(a => !a.humanDecision || a.humanDecision === 'pending').length} pending
            </span>
          </div>
        )}
      </div>

      {/* Standard Filter Bar */}
      <StandardFilterBar />

      {/* Argument list */}
      <div className="flex-1 overflow-y-auto p-3 space-y-3">
        {filteredArguments
          // In review mode, filter out excluded arguments unless explicitly viewing them
          .filter(arg => !reviewMode || arg.humanDecision !== 'excluded')
          .map((arg) => (
          <ArgumentCard
            key={arg.id}
            argument={arg}
            snippets={getSnippetsForArgument(arg)}
            isExpanded={expandedIds.has(arg.id)}
            isFocused={focusState.type === 'argument' && focusState.id === arg.id}
            reviewMode={reviewMode}
            onToggleExpand={() => toggleExpand(arg.id)}
            onUpdateArgument={(updates) => updateArgument(arg.id, updates)}
            onRemoveSnippet={(snippetId) => removeSnippetFromArgument(arg.id, snippetId)}
            onDragStart={() => setDraggedArgumentId(arg.id)}
            onDragEnd={() => setDraggedArgumentId(null)}
            onClick={() => handleArgumentClick(arg.id)}
            updatePosition={(rect) => {
              updateArgumentPosition2(arg.id, {
                id: arg.id,
                x: rect.right,
                y: rect.top + rect.height / 2,
                width: rect.width,
                height: rect.height,
              });
            }}
          />
        ))}

        {/* Empty state / Drop zone for new argument */}
        <div
          className={`
            border-2 border-dashed rounded-lg p-6 text-center transition-colors
            ${isDragOver
              ? 'border-blue-400 bg-blue-50'
              : draggedSnippetId
                ? 'border-slate-300 bg-white'
                : 'border-slate-200 bg-white/50'
            }
          `}
          onDragOver={(e) => {
            e.preventDefault();
            if (e.dataTransfer.types.includes('snippetid') || draggedSnippetId) {
              setIsDragOver(true);
            }
          }}
          onDragLeave={() => setIsDragOver(false)}
          onDrop={handleDropNewArgument}
        >
          <div className="text-slate-400">
            <svg className="w-8 h-8 mx-auto mb-2" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M12 6v6m0 0v6m0-6h6m-6 0H6" />
            </svg>
            <p className="text-sm">Drop snippet here to create new argument</p>
            <p className="text-xs mt-1">Or drag an argument to Standards panel</p>
          </div>
        </div>
      </div>

      {/* Applicant Name Input Modal */}
      {showApplicantModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
          <div className="bg-white rounded-xl shadow-2xl w-[400px] p-6">
            <h3 className="text-lg font-semibold text-slate-900 mb-2">
              Applicant Information
            </h3>
            <p className="text-sm text-slate-500 mb-4">
              Please enter the applicant's full name. This will help accurately identify which evidence belongs to the applicant.
            </p>
            <input
              type="text"
              value={applicantName}
              onChange={(e) => setApplicantName(e.target.value)}
              placeholder="e.g., Yaruo Qu"
              className="w-full px-3 py-2 border border-slate-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
              autoFocus
              onKeyDown={(e) => {
                if (e.key === 'Enter' && applicantName.trim()) {
                  handleGenerateArguments();
                }
              }}
            />
            <div className="flex justify-end gap-3 mt-6">
              <button
                onClick={() => setShowApplicantModal(false)}
                className="px-4 py-2 text-sm text-slate-600 hover:text-slate-800 hover:bg-slate-100 rounded-lg transition-colors"
              >
                Cancel
              </button>
              <button
                onClick={handleGenerateArguments}
                disabled={!applicantName.trim()}
                className="px-4 py-2 text-sm bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:bg-slate-300 disabled:cursor-not-allowed transition-colors"
              >
                Start Analysis
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
