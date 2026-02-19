/**
 * ReadOnlyPetitionPanel - User Study Condition B 专用组件
 *
 * 功能：
 * - 渲染 petition 文本
 * - inline citation [Exhibit A-1, p.3] 可点击跳转
 * - 支持选中文本标记错误
 */

import React, { useState, useCallback } from 'react';
import { logInteraction } from '../services/interactionLogger';

interface Citation {
  exhibit_id: string;
  page: number;
  start: number;
  end: number;
}

interface PetitionSection {
  title: string;
  text: string;
  citations: Citation[];
}

interface ErrorMark {
  id: string;
  sectionIndex: number;
  selection: string;
  startOffset: number;
  endOffset: number;
  errorType: 'factual' | 'citation' | 'omission' | 'logic' | 'other';
  note?: string;
}

interface Props {
  sections: PetitionSection[];
  onCitationClick: (exhibitId: string, page: number) => void;
  onMarkError?: (error: ErrorMark) => void;
  className?: string;
}

const ERROR_TYPES = [
  { value: 'factual', label: 'Factual Error', description: 'Numbers, dates, names inconsistent' },
  { value: 'citation', label: 'Citation Error', description: 'Wrong exhibit referenced' },
  { value: 'omission', label: 'Evidence Omission', description: 'Key evidence not cited' },
  { value: 'logic', label: 'Logic Issue', description: 'Evidence does not support claim' },
  { value: 'other', label: 'Other', description: 'Other type of error' },
] as const;

const ReadOnlyPetitionPanel: React.FC<Props> = ({
  sections,
  onCitationClick,
  onMarkError,
  className = '',
}) => {
  const [selectedText, setSelectedText] = useState<{
    sectionIndex: number;
    text: string;
    startOffset: number;
    endOffset: number;
  } | null>(null);
  const [showErrorModal, setShowErrorModal] = useState(false);
  const [errorType, setErrorType] = useState<ErrorMark['errorType']>('factual');
  const [errorNote, setErrorNote] = useState('');
  const [markedErrors, setMarkedErrors] = useState<ErrorMark[]>([]);

  /**
   * 处理文本选择
   */
  const handleTextSelection = useCallback((sectionIndex: number) => {
    const selection = window.getSelection();
    if (!selection || selection.isCollapsed) {
      setSelectedText(null);
      return;
    }

    const text = selection.toString().trim();
    if (text.length < 3) {
      setSelectedText(null);
      return;
    }

    // 获取选择范围
    const range = selection.getRangeAt(0);
    const startOffset = range.startOffset;
    const endOffset = range.endOffset;

    setSelectedText({
      sectionIndex,
      text,
      startOffset,
      endOffset,
    });
  }, []);

  /**
   * 打开错误标记模态框
   */
  const openErrorModal = useCallback(() => {
    if (!selectedText) return;
    setShowErrorModal(true);
  }, [selectedText]);

  /**
   * 提交错误标记
   */
  const submitError = useCallback(() => {
    if (!selectedText) return;

    const error: ErrorMark = {
      id: `error_${Date.now()}`,
      sectionIndex: selectedText.sectionIndex,
      selection: selectedText.text,
      startOffset: selectedText.startOffset,
      endOffset: selectedText.endOffset,
      errorType,
      note: errorNote || undefined,
    };

    setMarkedErrors(prev => [...prev, error]);
    onMarkError?.(error);

    // 记录日志
    logInteraction('error_mark', {
      section: sections[selectedText.sectionIndex]?.title,
      error_type: errorType,
      selection: selectedText.text.substring(0, 100),
    });

    // 重置状态
    setShowErrorModal(false);
    setSelectedText(null);
    setErrorType('factual');
    setErrorNote('');
    window.getSelection()?.removeAllRanges();
  }, [selectedText, errorType, errorNote, sections, onMarkError]);

  /**
   * 渲染带有 citation 链接的文本
   */
  const renderTextWithCitations = (text: string, citations: Citation[], sectionIndex: number) => {
    // 解析 citation 模式: [Exhibit A-1, p.3] 或 (Exhibit A-1, p.3)
    const citationPattern = /\[(Exhibit\s+[\w-]+),?\s*p\.?\s*(\d+)\]|\((Exhibit\s+[\w-]+),?\s*p\.?\s*(\d+)\)/gi;

    const parts: React.ReactNode[] = [];
    let lastIndex = 0;
    let match;

    while ((match = citationPattern.exec(text)) !== null) {
      // 添加 citation 前的文本
      if (match.index > lastIndex) {
        parts.push(
          <span key={`text-${lastIndex}`}>
            {text.substring(lastIndex, match.index)}
          </span>
        );
      }

      // 解析 citation
      const exhibitId = (match[1] || match[3]).replace('Exhibit ', '');
      const page = parseInt(match[2] || match[4], 10);

      // 添加可点击的 citation 链接
      parts.push(
        <button
          key={`citation-${match.index}`}
          className="text-blue-600 hover:text-blue-800 hover:underline font-medium mx-0.5"
          onClick={(e) => {
            e.stopPropagation();
            onCitationClick(exhibitId, page);
            logInteraction('document_view', {
              exhibit_id: exhibitId,
              page,
              section: sections[sectionIndex]?.title,
            });
          }}
        >
          {match[0]}
        </button>
      );

      lastIndex = match.index + match[0].length;
    }

    // 添加剩余文本
    if (lastIndex < text.length) {
      parts.push(
        <span key={`text-${lastIndex}`}>
          {text.substring(lastIndex)}
        </span>
      );
    }

    return parts;
  };

  /**
   * 高亮已标记的错误
   */
  const getErrorHighlights = (sectionIndex: number) => {
    return markedErrors.filter(e => e.sectionIndex === sectionIndex);
  };

  return (
    <div className={`flex flex-col h-full ${className}`}>
      {/* Header */}
      <div className="px-4 py-3 border-b border-gray-200 bg-gray-50">
        <h2 className="text-lg font-semibold text-gray-800">
          Petition Review
        </h2>
        <p className="text-sm text-gray-500 mt-1">
          Click citations to view source documents. Select text to mark errors.
        </p>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto p-4 space-y-6">
        {sections.map((section, sectionIndex) => (
          <div
            key={sectionIndex}
            className="bg-white rounded-lg border border-gray-200 p-4"
          >
            {/* Section Title */}
            <h3 className="text-base font-semibold text-gray-800 mb-3 pb-2 border-b border-gray-100">
              {section.title}
            </h3>

            {/* Section Text */}
            <div
              className="text-sm text-gray-700 leading-relaxed cursor-text select-text"
              onMouseUp={() => handleTextSelection(sectionIndex)}
            >
              {renderTextWithCitations(section.text, section.citations, sectionIndex)}
            </div>

            {/* Error Marks */}
            {getErrorHighlights(sectionIndex).length > 0 && (
              <div className="mt-3 pt-3 border-t border-gray-100">
                <div className="text-xs text-gray-500 mb-2">
                  Marked Errors ({getErrorHighlights(sectionIndex).length}):
                </div>
                <div className="space-y-1">
                  {getErrorHighlights(sectionIndex).map(error => (
                    <div
                      key={error.id}
                      className="flex items-start gap-2 text-xs bg-red-50 text-red-700 px-2 py-1 rounded"
                    >
                      <span className="font-medium">{error.errorType}:</span>
                      <span className="text-red-600">"{error.selection.substring(0, 50)}..."</span>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        ))}
      </div>

      {/* Selection Toolbar */}
      {selectedText && (
        <div className="fixed bottom-4 left-1/2 transform -translate-x-1/2 bg-gray-800 text-white px-4 py-2 rounded-lg shadow-lg flex items-center gap-3 z-50">
          <span className="text-sm">
            Selected: "{selectedText.text.substring(0, 30)}..."
          </span>
          <button
            onClick={openErrorModal}
            className="px-3 py-1 bg-red-600 hover:bg-red-700 rounded text-sm font-medium"
          >
            Mark as Error
          </button>
          <button
            onClick={() => {
              setSelectedText(null);
              window.getSelection()?.removeAllRanges();
            }}
            className="px-3 py-1 bg-gray-600 hover:bg-gray-700 rounded text-sm"
          >
            Cancel
          </button>
        </div>
      )}

      {/* Error Modal */}
      {showErrorModal && selectedText && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
          <div className="bg-white rounded-lg shadow-xl w-full max-w-md p-6">
            <h3 className="text-lg font-semibold text-gray-800 mb-4">
              Mark Error
            </h3>

            <div className="mb-4">
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Selected Text
              </label>
              <div className="text-sm text-gray-600 bg-gray-50 p-2 rounded border">
                "{selectedText.text}"
              </div>
            </div>

            <div className="mb-4">
              <label className="block text-sm font-medium text-gray-700 mb-2">
                Error Type
              </label>
              <div className="space-y-2">
                {ERROR_TYPES.map(type => (
                  <label
                    key={type.value}
                    className={`flex items-start gap-2 p-2 rounded border cursor-pointer transition-colors ${
                      errorType === type.value
                        ? 'border-blue-500 bg-blue-50'
                        : 'border-gray-200 hover:border-gray-300'
                    }`}
                  >
                    <input
                      type="radio"
                      name="errorType"
                      value={type.value}
                      checked={errorType === type.value}
                      onChange={() => setErrorType(type.value)}
                      className="mt-0.5"
                    />
                    <div>
                      <div className="text-sm font-medium">{type.label}</div>
                      <div className="text-xs text-gray-500">{type.description}</div>
                    </div>
                  </label>
                ))}
              </div>
            </div>

            <div className="mb-4">
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Note (optional)
              </label>
              <textarea
                value={errorNote}
                onChange={(e) => setErrorNote(e.target.value)}
                className="w-full px-3 py-2 border border-gray-300 rounded text-sm"
                rows={2}
                placeholder="Add additional notes..."
              />
            </div>

            <div className="flex justify-end gap-2">
              <button
                onClick={() => {
                  setShowErrorModal(false);
                  setErrorType('factual');
                  setErrorNote('');
                }}
                className="px-4 py-2 text-sm text-gray-600 hover:text-gray-800"
              >
                Cancel
              </button>
              <button
                onClick={submitError}
                className="px-4 py-2 bg-red-600 hover:bg-red-700 text-white rounded text-sm font-medium"
              >
                Mark Error
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Summary Footer */}
      <div className="px-4 py-3 border-t border-gray-200 bg-gray-50">
        <div className="flex items-center justify-between text-sm text-gray-600">
          <span>
            {sections.length} sections
          </span>
          <span className="text-red-600 font-medium">
            {markedErrors.length} errors marked
          </span>
        </div>
      </div>
    </div>
  );
};

export default ReadOnlyPetitionPanel;
