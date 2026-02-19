/**
 * SentenceSpan - 可点击的句子组件
 *
 * 用于 WritingCanvas 中的 sentence-level 渲染
 * 点击句子可以查看溯源信息并高亮源文档
 */

import React from 'react';

interface Props {
  text: string;
  index: number;
  hasProvenance: boolean;
  snippetCount: number;
  isActive?: boolean;
  isHighlighted?: boolean;
  onClick?: (index: number) => void;
  className?: string;
}

const SentenceSpan: React.FC<Props> = ({
  text,
  index,
  hasProvenance,
  snippetCount,
  isActive = false,
  isHighlighted = false,
  onClick,
  className = '',
}) => {
  const handleClick = (e: React.MouseEvent) => {
    e.stopPropagation();
    onClick?.(index);
  };

  // 根据状态确定样式
  const getStyles = () => {
    if (isActive) {
      // 当前选中的句子
      return 'bg-blue-100 border-blue-400 text-blue-900';
    }
    if (isHighlighted) {
      // 被高亮的句子（反向溯源时）
      return 'bg-yellow-100 border-yellow-400 text-yellow-900';
    }
    if (hasProvenance) {
      // 有溯源的句子
      return 'bg-green-50 border-green-300 text-gray-800 hover:bg-green-100';
    }
    // 无溯源的过渡句
    return 'bg-gray-50 border-gray-200 text-gray-500';
  };

  return (
    <span
      onClick={handleClick}
      className={`
        inline cursor-pointer transition-all duration-150
        border-b-2 px-0.5 py-0.5 rounded-sm
        ${getStyles()}
        ${className}
      `}
      title={
        hasProvenance
          ? `Click to view ${snippetCount} source(s)`
          : 'No direct source (transitional sentence)'
      }
    >
      {text}
      {hasProvenance && snippetCount > 0 && (
        <sup className="ml-0.5 text-xs font-medium text-blue-600">
          [{snippetCount}]
        </sup>
      )}
    </span>
  );
};

/**
 * SentenceList - 渲染一组句子
 */
interface SentenceListProps {
  sentences: Array<{
    text: string;
    snippet_ids: string[];
  }>;
  activeSentenceIndex?: number;
  highlightedSentenceIndices?: number[];
  onSentenceClick?: (index: number) => void;
  className?: string;
}

export const SentenceList: React.FC<SentenceListProps> = ({
  sentences,
  activeSentenceIndex,
  highlightedSentenceIndices = [],
  onSentenceClick,
  className = '',
}) => {
  return (
    <div className={`text-sm leading-relaxed ${className}`}>
      {sentences.map((sentence, idx) => (
        <React.Fragment key={idx}>
          <SentenceSpan
            text={sentence.text}
            index={idx}
            hasProvenance={sentence.snippet_ids.length > 0}
            snippetCount={sentence.snippet_ids.length}
            isActive={activeSentenceIndex === idx}
            isHighlighted={highlightedSentenceIndices.includes(idx)}
            onClick={onSentenceClick}
          />
          {idx < sentences.length - 1 && ' '}
        </React.Fragment>
      ))}
    </div>
  );
};

export default SentenceSpan;
