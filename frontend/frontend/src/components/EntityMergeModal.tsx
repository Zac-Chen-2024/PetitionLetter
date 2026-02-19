import React, { useState } from 'react';

interface MergeSuggestion {
  id: string;
  primary_entity_name: string;
  primary_entity_type: string;
  merge_entity_names: string[];
  reason: string;
  confidence: number;
  status: 'pending' | 'accepted' | 'rejected';
}

interface EntityMergeModalProps {
  isOpen: boolean;
  suggestions: MergeSuggestion[];
  onConfirm: (confirmations: Array<{suggestion_id: string; status: string}>) => void;
  onClose: () => void;
}

export function EntityMergeModal({
  isOpen,
  suggestions,
  onConfirm,
  onClose
}: EntityMergeModalProps) {
  const [decisions, setDecisions] = useState<Record<string, 'accepted' | 'rejected'>>({});

  if (!isOpen) return null;

  const pendingSuggestions = suggestions.filter(s => s.status === 'pending');

  const handleDecision = (id: string, status: 'accepted' | 'rejected') => {
    setDecisions(prev => ({
      ...prev,
      [id]: status
    }));
  };

  const handleAcceptAll = () => {
    const allAccepted: Record<string, 'accepted'> = {};
    pendingSuggestions.forEach(s => {
      allAccepted[s.id] = 'accepted';
    });
    setDecisions(allAccepted);
  };

  const handleConfirm = () => {
    const confirmations = Object.entries(decisions).map(([suggestion_id, status]) => ({
      suggestion_id,
      status
    }));
    onConfirm(confirmations);
  };

  const getTypeColor = (type: string) => {
    switch (type) {
      case 'person': return 'bg-blue-100 text-blue-800';
      case 'organization': return 'bg-green-100 text-green-800';
      case 'award': return 'bg-yellow-100 text-yellow-800';
      default: return 'bg-gray-100 text-gray-800';
    }
  };

  const getDecisionCount = () => {
    const accepted = Object.values(decisions).filter(d => d === 'accepted').length;
    const rejected = Object.values(decisions).filter(d => d === 'rejected').length;
    return { accepted, rejected, pending: pendingSuggestions.length - accepted - rejected };
  };

  const counts = getDecisionCount();

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
      <div className="bg-white rounded-lg shadow-xl w-full max-w-2xl max-h-[80vh] flex flex-col">
        {/* Header */}
        <div className="px-6 py-4 border-b border-gray-200 flex items-center justify-between">
          <div>
            <h2 className="text-lg font-semibold text-gray-900">Entity Merge Review</h2>
            <p className="text-sm text-gray-500 mt-1">
              Review AI-suggested entity merges. Same entity with different names will be combined.
            </p>
          </div>
          <button
            onClick={onClose}
            className="text-gray-400 hover:text-gray-600 text-2xl leading-none"
          >
            &times;
          </button>
        </div>

        {/* Summary */}
        <div className="px-6 py-3 bg-gray-50 border-b border-gray-200 flex items-center gap-4">
          <span className="text-sm text-gray-600">
            {pendingSuggestions.length} suggestions
          </span>
          <span className="text-sm text-green-600">
            {counts.accepted} accepted
          </span>
          <span className="text-sm text-red-600">
            {counts.rejected} rejected
          </span>
          <span className="text-sm text-gray-400">
            {counts.pending} pending
          </span>
        </div>

        {/* Suggestions List */}
        <div className="flex-1 overflow-y-auto px-6 py-4 space-y-4">
          {pendingSuggestions.length === 0 ? (
            <div className="text-center py-8 text-gray-500">
              No merge suggestions to review
            </div>
          ) : (
            pendingSuggestions.map(suggestion => (
              <div
                key={suggestion.id}
                className={`border rounded-lg p-4 ${
                  decisions[suggestion.id] === 'accepted'
                    ? 'border-green-300 bg-green-50'
                    : decisions[suggestion.id] === 'rejected'
                    ? 'border-red-300 bg-red-50'
                    : 'border-gray-200 bg-white'
                }`}
              >
                {/* Entity Type Badge */}
                <div className="flex items-center justify-between mb-2">
                  <span className={`text-xs px-2 py-0.5 rounded-full ${getTypeColor(suggestion.primary_entity_type)}`}>
                    {suggestion.primary_entity_type}
                  </span>
                  <span className="text-xs text-gray-400">
                    {Math.round(suggestion.confidence * 100)}% confidence
                  </span>
                </div>

                {/* Primary Entity */}
                <div className="mb-2">
                  <span className="font-medium text-gray-900">{suggestion.primary_entity_name}</span>
                  <span className="text-gray-400 mx-2">&larr;</span>
                  <span className="text-gray-600">
                    {suggestion.merge_entity_names.join(', ')}
                  </span>
                </div>

                {/* Reason */}
                <p className="text-sm text-gray-500 mb-3">
                  {suggestion.reason}
                </p>

                {/* Actions */}
                <div className="flex gap-2">
                  <button
                    onClick={() => handleDecision(suggestion.id, 'accepted')}
                    className={`px-3 py-1.5 text-sm rounded-md transition-colors ${
                      decisions[suggestion.id] === 'accepted'
                        ? 'bg-green-600 text-white'
                        : 'bg-green-100 text-green-700 hover:bg-green-200'
                    }`}
                  >
                    Accept
                  </button>
                  <button
                    onClick={() => handleDecision(suggestion.id, 'rejected')}
                    className={`px-3 py-1.5 text-sm rounded-md transition-colors ${
                      decisions[suggestion.id] === 'rejected'
                        ? 'bg-red-600 text-white'
                        : 'bg-red-100 text-red-700 hover:bg-red-200'
                    }`}
                  >
                    Reject
                  </button>
                </div>
              </div>
            ))
          )}
        </div>

        {/* Footer */}
        <div className="px-6 py-4 border-t border-gray-200 flex items-center justify-between bg-gray-50">
          <button
            onClick={handleAcceptAll}
            className="px-4 py-2 text-sm text-green-700 hover:text-green-800 hover:underline"
          >
            Accept All
          </button>
          <div className="flex gap-3">
            <button
              onClick={onClose}
              className="px-4 py-2 text-sm text-gray-600 hover:text-gray-800 border border-gray-300 rounded-md hover:bg-gray-50"
            >
              Cancel
            </button>
            <button
              onClick={handleConfirm}
              disabled={Object.keys(decisions).length === 0}
              className="px-4 py-2 text-sm text-white bg-blue-600 rounded-md hover:bg-blue-700 disabled:bg-gray-300 disabled:cursor-not-allowed"
            >
              Apply ({Object.keys(decisions).length}) Decisions
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

export default EntityMergeModal;
