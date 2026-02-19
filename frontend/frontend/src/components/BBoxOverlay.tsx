/**
 * BBoxOverlay - BBox 高亮覆盖层
 *
 * 在 DocumentViewer 中显示 snippet 的高亮框
 * 支持多个 snippet 不同颜色高亮
 */

import React, { useMemo } from 'react';

interface BBox {
  x1: number;
  y1: number;
  x2: number;
  y2: number;
}

interface HighlightedSnippet {
  snippet_id: string;
  bbox: BBox;
  color?: string;
  label?: string;
  confidence?: number;
}

interface Props {
  snippets: HighlightedSnippet[];
  containerWidth: number;
  containerHeight: number;
  normalizedCoords?: boolean; // 坐标是否已归一化 (0-1000)
  onSnippetClick?: (snippetId: string) => void;
  onSnippetHover?: (snippetId: string | null) => void;
  activeSnippetId?: string;
  className?: string;
}

// 预定义的颜色列表
const COLORS = [
  { bg: 'rgba(59, 130, 246, 0.2)', border: '#3B82F6' },   // blue
  { bg: 'rgba(16, 185, 129, 0.2)', border: '#10B981' },   // green
  { bg: 'rgba(245, 158, 11, 0.2)', border: '#F59E0B' },   // amber
  { bg: 'rgba(239, 68, 68, 0.2)', border: '#EF4444' },    // red
  { bg: 'rgba(139, 92, 246, 0.2)', border: '#8B5CF6' },   // violet
  { bg: 'rgba(236, 72, 153, 0.2)', border: '#EC4899' },   // pink
  { bg: 'rgba(6, 182, 212, 0.2)', border: '#06B6D4' },    // cyan
  { bg: 'rgba(132, 204, 22, 0.2)', border: '#84CC16' },   // lime
];

const BBoxOverlay: React.FC<Props> = ({
  snippets,
  containerWidth,
  containerHeight,
  normalizedCoords = true,
  onSnippetClick,
  onSnippetHover,
  activeSnippetId,
  className = '',
}) => {
  // 为每个 snippet 分配颜色
  const snippetColors = useMemo(() => {
    const colorMap = new Map<string, typeof COLORS[0]>();
    snippets.forEach((snippet, idx) => {
      if (!colorMap.has(snippet.snippet_id)) {
        colorMap.set(snippet.snippet_id, COLORS[idx % COLORS.length]);
      }
    });
    return colorMap;
  }, [snippets]);

  // 计算实际坐标
  const calculatePosition = (bbox: BBox) => {
    if (normalizedCoords) {
      // 归一化坐标 (0-1000) 转为像素
      return {
        left: (bbox.x1 / 1000) * containerWidth,
        top: (bbox.y1 / 1000) * containerHeight,
        width: ((bbox.x2 - bbox.x1) / 1000) * containerWidth,
        height: ((bbox.y2 - bbox.y1) / 1000) * containerHeight,
      };
    }
    // 已经是像素坐标
    return {
      left: bbox.x1,
      top: bbox.y1,
      width: bbox.x2 - bbox.x1,
      height: bbox.y2 - bbox.y1,
    };
  };

  if (snippets.length === 0) {
    return null;
  }

  return (
    <div
      className={`absolute inset-0 pointer-events-none ${className}`}
      style={{ width: containerWidth, height: containerHeight }}
    >
      {snippets.map((snippet) => {
        const position = calculatePosition(snippet.bbox);
        const color = snippetColors.get(snippet.snippet_id) || COLORS[0];
        const isActive = activeSnippetId === snippet.snippet_id;

        return (
          <div
            key={snippet.snippet_id}
            className="absolute pointer-events-auto cursor-pointer transition-all duration-150"
            style={{
              left: position.left,
              top: position.top,
              width: position.width,
              height: position.height,
              backgroundColor: isActive
                ? color.bg.replace('0.2', '0.4')
                : color.bg,
              border: `2px solid ${color.border}`,
              borderRadius: '2px',
              boxShadow: isActive
                ? `0 0 0 2px ${color.border}40`
                : 'none',
            }}
            onClick={() => onSnippetClick?.(snippet.snippet_id)}
            onMouseEnter={() => onSnippetHover?.(snippet.snippet_id)}
            onMouseLeave={() => onSnippetHover?.(null)}
          >
            {/* Label */}
            {snippet.label && (
              <div
                className="absolute -top-5 left-0 px-1 py-0.5 text-xs font-medium rounded whitespace-nowrap"
                style={{
                  backgroundColor: color.border,
                  color: 'white',
                }}
              >
                {snippet.label}
              </div>
            )}

            {/* Confidence indicator */}
            {snippet.confidence !== undefined && (
              <div
                className="absolute -bottom-4 right-0 px-1 py-0.5 text-xs rounded"
                style={{
                  backgroundColor: 'white',
                  color: color.border,
                  border: `1px solid ${color.border}`,
                }}
              >
                {Math.round(snippet.confidence * 100)}%
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
};

/**
 * BBoxLegend - 图例组件
 */
interface LegendProps {
  snippets: Array<{
    snippet_id: string;
    text: string;
  }>;
  colors: Map<string, typeof COLORS[0]>;
  activeSnippetId?: string;
  onSnippetClick?: (snippetId: string) => void;
  className?: string;
}

export const BBoxLegend: React.FC<LegendProps> = ({
  snippets,
  colors,
  activeSnippetId,
  onSnippetClick,
  className = '',
}) => {
  return (
    <div className={`bg-white rounded-lg shadow p-3 ${className}`}>
      <div className="text-xs font-medium text-gray-500 mb-2">
        Highlighted Sources
      </div>
      <div className="space-y-1.5">
        {snippets.map((snippet) => {
          const color = colors.get(snippet.snippet_id) || COLORS[0];
          const isActive = activeSnippetId === snippet.snippet_id;

          return (
            <button
              key={snippet.snippet_id}
              onClick={() => onSnippetClick?.(snippet.snippet_id)}
              className={`
                flex items-start gap-2 w-full text-left text-xs p-1.5 rounded
                transition-colors
                ${isActive ? 'bg-gray-100' : 'hover:bg-gray-50'}
              `}
            >
              <div
                className="w-3 h-3 rounded flex-shrink-0 mt-0.5"
                style={{
                  backgroundColor: color.bg,
                  border: `2px solid ${color.border}`,
                }}
              />
              <span className="text-gray-700 line-clamp-2">
                {snippet.text.substring(0, 60)}...
              </span>
            </button>
          );
        })}
      </div>
    </div>
  );
};

export default BBoxOverlay;
