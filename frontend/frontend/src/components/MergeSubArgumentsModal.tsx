import { useState, useCallback, useMemo } from 'react';
import { apiClient } from '../services/api';
import type { SubArgument } from '../types';

// ============================================
// Types
// ============================================

interface MergeSubArgumentsModalProps {
  selectedSubArguments: SubArgument[];
  projectId: string;
  onConfirm: (data: {
    title: string;
    purpose: string;
    relationship: string;
  }) => void;
  onCancel: () => void;
}

// ============================================
// Component
// ============================================

export function MergeSubArgumentsModal({
  selectedSubArguments,
  projectId,
  onConfirm,
  onCancel,
}: MergeSubArgumentsModalProps) {
  // Pre-fill: use the sub-arg with the most snippets as default title
  const defaultSubArg = useMemo(() => {
    return [...selectedSubArguments].sort(
      (a, b) => (b.snippetIds?.length || 0) - (a.snippetIds?.length || 0)
    )[0];
  }, [selectedSubArguments]);

  // Merged purpose: concatenate unique purposes
  const defaultPurpose = useMemo(() => {
    const purposes = selectedSubArguments
      .map(sa => sa.purpose?.trim())
      .filter((p): p is string => !!p);
    const unique = [...new Set(purposes)];
    return unique.join('; ');
  }, [selectedSubArguments]);

  // Total unique snippet count
  const totalSnippets = useMemo(() => {
    const ids = new Set<string>();
    selectedSubArguments.forEach(sa => {
      (sa.snippetIds || []).forEach(id => ids.add(id));
    });
    return ids.size;
  }, [selectedSubArguments]);

  const [title, setTitle] = useState(defaultSubArg?.title || '');
  const [purpose, setPurpose] = useState(defaultPurpose);
  const [relationship, setRelationship] = useState(defaultSubArg?.relationship || '');
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [isGeneratingTitle, setIsGeneratingTitle] = useState(false);

  const handleSubmit = useCallback(async () => {
    if (!title.trim()) return;
    setIsSubmitting(true);
    try {
      onConfirm({
        title: title.trim(),
        purpose: purpose.trim(),
        relationship: relationship.trim(),
      });
    } finally {
      setIsSubmitting(false);
    }
  }, [title, purpose, relationship, onConfirm]);

  // AI generate title: ask the infer-relationship endpoint creatively
  // We use the sub-arg titles as context to generate a merged title
  const handleGenerateTitle = useCallback(async () => {
    setIsGeneratingTitle(true);
    try {
      const sourceTitles = selectedSubArguments.map(sa => sa.title).filter(Boolean);
      const argumentId = selectedSubArguments[0]?.argumentId;
      if (!argumentId) return;

      // Use infer-relationship endpoint with concatenated titles to get a synthesized name
      const response = await apiClient.post<{ success: boolean; relationship: string }>(
        `/arguments/${projectId}/infer-relationship`,
        {
          argument_id: argumentId,
          subargument_title: `Merged from: ${sourceTitles.join(' + ')}`,
        }
      );

      if (response.success && response.relationship) {
        // The relationship is a short phrase — use it as the title
        setTitle(response.relationship);
        setRelationship(response.relationship);
      }
    } catch (error) {
      console.error('Failed to generate title:', error);
    } finally {
      setIsGeneratingTitle(false);
    }
  }, [selectedSubArguments, projectId]);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      {/* Backdrop */}
      <div
        className="absolute inset-0 bg-black/40 backdrop-blur-sm"
        onClick={onCancel}
      />

      {/* Modal */}
      <div className="relative bg-white rounded-xl shadow-xl w-full max-w-lg mx-4 overflow-hidden max-h-[90vh] flex flex-col">
        {/* Header */}
        <div className="px-5 py-4 border-b border-slate-200 bg-slate-50 flex-shrink-0">
          <h3 className="text-lg font-semibold text-slate-800">
            Merge Sub-Arguments
          </h3>
          <p className="text-sm text-slate-500 mt-0.5">
            Combining {selectedSubArguments.length} sub-arguments into a new argument
          </p>
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto p-5 space-y-4">
          {/* Source sub-arguments list */}
          <div>
            <label className="block text-sm font-medium text-slate-700 mb-2">
              Sources
            </label>
            <div className="space-y-1.5">
              {selectedSubArguments.map(sa => (
                <div
                  key={sa.id}
                  className="flex items-center justify-between px-3 py-2 bg-emerald-50 border border-emerald-200 rounded-lg"
                >
                  <span className="text-sm text-emerald-800 truncate">
                    {sa.title || '(untitled)'}
                  </span>
                  <span className="text-xs text-emerald-600 flex-shrink-0 ml-2">
                    {sa.snippetIds?.length || 0} snippets
                  </span>
                </div>
              ))}
            </div>
            <p className="mt-1.5 text-xs text-slate-400">
              {totalSnippets} unique snippets will be combined
            </p>
          </div>

          {/* Title Input + AI Generate */}
          <div>
            <label className="block text-sm font-medium text-slate-700 mb-1.5">
              Title <span className="text-red-500">*</span>
            </label>
            <div className="flex gap-2">
              <input
                type="text"
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                placeholder="Title for the new argument"
                className="flex-1 px-3 py-2 border border-slate-300 rounded-lg text-sm
                  focus:outline-none focus:ring-2 focus:ring-emerald-500 focus:border-transparent"
                autoFocus
              />
              <button
                onClick={handleGenerateTitle}
                disabled={isGeneratingTitle}
                className="px-3 py-2 text-xs font-medium text-purple-700 bg-purple-50 border border-purple-200 rounded-lg hover:bg-purple-100 transition-colors disabled:opacity-50 flex items-center gap-1.5 flex-shrink-0"
                title="AI generate title"
              >
                {isGeneratingTitle ? (
                  <svg className="animate-spin h-3.5 w-3.5" fill="none" viewBox="0 0 24 24">
                    <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                    <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                  </svg>
                ) : (
                  <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 10V3L4 14h7v7l9-11h-7z" />
                  </svg>
                )}
                AI
              </button>
            </div>
          </div>

          {/* Purpose Input */}
          <div>
            <label className="block text-sm font-medium text-slate-700 mb-1.5">
              Purpose <span className="text-slate-400">(optional)</span>
            </label>
            <textarea
              value={purpose}
              onChange={(e) => setPurpose(e.target.value)}
              placeholder="What does the merged argument demonstrate?"
              rows={2}
              className="w-full px-3 py-2 border border-slate-300 rounded-lg text-sm
                focus:outline-none focus:ring-2 focus:ring-emerald-500 focus:border-transparent resize-none"
            />
          </div>

          {/* Relationship Input */}
          <div>
            <label className="block text-sm font-medium text-slate-700 mb-1.5">
              Relationship <span className="text-slate-400">(optional)</span>
            </label>
            <input
              type="text"
              value={relationship}
              onChange={(e) => setRelationship(e.target.value)}
              placeholder="How does this relate to the standard?"
              className="w-full px-3 py-2 border border-slate-300 rounded-lg text-sm
                focus:outline-none focus:ring-2 focus:ring-emerald-500 focus:border-transparent"
            />
          </div>

          {/* Info */}
          <div className="p-3 bg-amber-50 border border-amber-200 rounded-lg">
            <p className="text-xs text-amber-700">
              Merging creates a new argument with one sub-argument containing the combined evidence.
              The original sub-arguments will be deleted and their letter content removed.
            </p>
          </div>
        </div>

        {/* Footer */}
        <div className="px-5 py-4 border-t border-slate-200 bg-slate-50 flex-shrink-0">
          <div className="flex justify-end gap-2">
            <button
              onClick={onCancel}
              className="px-4 py-2 text-sm text-slate-600 hover:text-slate-800 border border-slate-300 rounded-lg"
            >
              Cancel
            </button>
            <button
              onClick={handleSubmit}
              disabled={!title.trim() || isSubmitting}
              className="px-4 py-2 text-sm text-white bg-emerald-600 hover:bg-emerald-700 rounded-lg disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2"
            >
              {isSubmitting ? (
                <>
                  <svg className="animate-spin h-4 w-4 text-white" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                    <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                    <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" />
                  </svg>
                  Merging...
                </>
              ) : (
                `Merge ${selectedSubArguments.length} Sub-Arguments`
              )}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
