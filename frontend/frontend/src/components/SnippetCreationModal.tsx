import { useState } from 'react';
import type { BoundingBox, MaterialType } from '../types';
import { MATERIAL_TYPE_CONFIG } from '../constants/colors';

// Use unified color system
const MATERIAL_TYPES = MATERIAL_TYPE_CONFIG;

interface SnippetCreationModalProps {
  boundingBox: BoundingBox;
  documentId: string;
  onConfirm: (data: {
    content: string;
    summary: string;
    materialType: MaterialType;
  }) => void;
  onCancel: () => void;
}

export function SnippetCreationModal({
  boundingBox,
  documentId,
  onConfirm,
  onCancel,
}: SnippetCreationModalProps) {
  const [summary, setSummary] = useState('');
  const [content, setContent] = useState('');
  const [materialType, setMaterialType] = useState<MaterialType>('other');

  // Extract exhibit name from documentId (e.g., "doc_A1" -> "Exhibit A1")
  const exhibitName = documentId.startsWith('doc_')
    ? `Exhibit ${documentId.replace('doc_', '')}`
    : documentId;

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!summary.trim()) return;

    onConfirm({
      content: content.trim() || summary.trim(),
      summary: summary.trim(),
      materialType,
    });
  };

  const selectedType = MATERIAL_TYPES.find(t => t.value === materialType);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      {/* Backdrop */}
      <div
        className="absolute inset-0 bg-black/40 backdrop-blur-sm"
        onClick={onCancel}
      />

      {/* Modal */}
      <div className="relative bg-white rounded-xl shadow-xl w-full max-w-md mx-4 overflow-hidden">
        {/* Header */}
        <div className="px-5 py-4 border-b border-slate-200 bg-slate-50">
          <h3 className="text-lg font-semibold text-slate-800">Create New Snippet</h3>
          <p className="text-sm text-slate-500 mt-0.5">
            From: {exhibitName} (Page {boundingBox.page})
          </p>
        </div>

        {/* Form */}
        <form onSubmit={handleSubmit} className="p-5 space-y-4">
          {/* Selection Preview */}
          <div className="bg-slate-50 rounded-lg p-3 border border-slate-200">
            <p className="text-xs text-slate-500 mb-1">Selected Region</p>
            <div className="text-sm text-slate-700">
              Position: ({Math.round(boundingBox.x)}, {Math.round(boundingBox.y)}) |
              Size: {Math.round(boundingBox.width)} × {Math.round(boundingBox.height)}
            </div>
          </div>

          {/* Summary Input */}
          <div>
            <label className="block text-sm font-medium text-slate-700 mb-1.5">
              Summary <span className="text-red-500">*</span>
            </label>
            <input
              type="text"
              value={summary}
              onChange={(e) => setSummary(e.target.value)}
              placeholder="Brief description of the evidence..."
              className="w-full px-3 py-2 border border-slate-300 rounded-lg text-sm
                focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
              autoFocus
            />
          </div>

          {/* Content Input (Optional) */}
          <div>
            <label className="block text-sm font-medium text-slate-700 mb-1.5">
              Full Content <span className="text-slate-400">(optional)</span>
            </label>
            <textarea
              value={content}
              onChange={(e) => setContent(e.target.value)}
              placeholder="Full text content from the selection..."
              rows={3}
              className="w-full px-3 py-2 border border-slate-300 rounded-lg text-sm resize-none
                focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
            />
          </div>

          {/* Material Type Selection */}
          <div>
            <label className="block text-sm font-medium text-slate-700 mb-2">
              Material Type
            </label>
            <div className="grid grid-cols-4 gap-2">
              {MATERIAL_TYPES.map((type) => (
                <button
                  key={type.value}
                  type="button"
                  onClick={() => setMaterialType(type.value)}
                  className={`
                    px-2 py-1.5 rounded-lg text-xs font-medium
                    transition-all duration-200 border-2
                    ${materialType === type.value
                      ? 'border-current shadow-sm'
                      : 'border-transparent bg-slate-100 hover:bg-slate-200'
                    }
                  `}
                  style={{
                    color: materialType === type.value ? type.color : undefined,
                    backgroundColor: materialType === type.value ? `${type.color}15` : undefined,
                  }}
                >
                  {type.label}
                </button>
              ))}
            </div>
          </div>

          {/* Preview */}
          {summary && (
            <div className="p-3 rounded-lg border-2 border-dashed" style={{ borderColor: selectedType?.color }}>
              <p className="text-xs text-slate-500 mb-1">Preview</p>
              <div className="flex items-start gap-2">
                <div
                  className="w-2 h-2 rounded-full mt-1.5 flex-shrink-0"
                  style={{ backgroundColor: selectedType?.color }}
                />
                <div>
                  <p className="text-sm text-slate-700">{summary}</p>
                  <span
                    className="inline-block mt-1 px-1.5 py-0.5 text-[10px] rounded"
                    style={{
                      backgroundColor: `${selectedType?.color}20`,
                      color: selectedType?.color,
                    }}
                  >
                    {selectedType?.label}
                  </span>
                </div>
              </div>
            </div>
          )}
        </form>

        {/* Footer */}
        <div className="px-5 py-4 border-t border-slate-200 bg-slate-50 flex items-center justify-end gap-3">
          <button
            type="button"
            onClick={onCancel}
            className="px-4 py-2 text-sm font-medium text-slate-600 hover:text-slate-800 transition-colors"
          >
            Cancel
          </button>
          <button
            onClick={handleSubmit}
            disabled={!summary.trim()}
            className="px-4 py-2 text-sm font-medium text-white bg-blue-600 rounded-lg
              hover:bg-blue-700 disabled:bg-slate-300 disabled:cursor-not-allowed transition-colors"
          >
            Create Snippet
          </button>
        </div>
      </div>
    </div>
  );
}
