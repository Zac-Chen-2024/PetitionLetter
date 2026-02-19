/**
 * LinkedSnippetIndicator - Snippet 关联信号指示器
 *
 * 在 snippet 卡片上显示关联信息
 * hover 时高亮相关 snippets
 */

import React, { useState, useMemo } from 'react';
import type { SnippetLink } from '../services/snippetService';

interface Props {
  currentSnippetId: string;
  links: SnippetLink[];
  onHoverLink: (linkedIds: string[]) => void;
  className?: string;
}

const LinkedSnippetIndicator: React.FC<Props> = ({
  currentSnippetId,
  links,
  onHoverLink,
  className = '',
}) => {
  const [isExpanded, setIsExpanded] = useState(false);

  // 找到与当前 snippet 相关的所有链接
  const relatedLinks = useMemo(() => {
    return links.filter(
      link => link.snippet_a === currentSnippetId || link.snippet_b === currentSnippetId
    );
  }, [links, currentSnippetId]);

  // 获取关联的 snippet IDs
  const linkedIds = useMemo(() => {
    return relatedLinks.map(link =>
      link.snippet_a === currentSnippetId ? link.snippet_b : link.snippet_a
    );
  }, [relatedLinks, currentSnippetId]);

  // 获取所有共享实体
  const allSharedEntities = useMemo(() => {
    const entities = new Set<string>();
    relatedLinks.forEach(link => {
      link.shared_entities?.forEach(e => entities.add(e));
    });
    return Array.from(entities);
  }, [relatedLinks]);

  // 计算平均关联强度
  const avgStrength = useMemo(() => {
    if (relatedLinks.length === 0) return 0;
    const sum = relatedLinks.reduce((acc, link) => acc + link.strength, 0);
    return sum / relatedLinks.length;
  }, [relatedLinks]);

  if (relatedLinks.length === 0) {
    return null;
  }

  const handleMouseEnter = () => {
    onHoverLink(linkedIds);
  };

  const handleMouseLeave = () => {
    onHoverLink([]);
    setIsExpanded(false);
  };

  // 强度对应的颜色
  const strengthColor = avgStrength >= 0.7
    ? 'text-green-600'
    : avgStrength >= 0.4
    ? 'text-yellow-600'
    : 'text-gray-500';

  return (
    <div
      className={`relative ${className}`}
      onMouseEnter={handleMouseEnter}
      onMouseLeave={handleMouseLeave}
    >
      {/* 简洁指示器 */}
      <button
        onClick={() => setIsExpanded(!isExpanded)}
        className={`
          flex items-center gap-1 text-xs px-1.5 py-0.5 rounded
          bg-blue-50 hover:bg-blue-100 transition-colors
          ${strengthColor}
        `}
        title={`${relatedLinks.length} related snippet(s)`}
      >
        <svg
          className="w-3 h-3"
          fill="none"
          stroke="currentColor"
          viewBox="0 0 24 24"
        >
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            strokeWidth={2}
            d="M13.828 10.172a4 4 0 00-5.656 0l-4 4a4 4 0 105.656 5.656l1.102-1.101m-.758-4.899a4 4 0 005.656 0l4-4a4 4 0 00-5.656-5.656l-1.1 1.1"
          />
        </svg>
        <span>{relatedLinks.length}</span>
      </button>

      {/* 展开的详情面板 */}
      {isExpanded && (
        <div
          className="
            absolute left-0 top-full mt-1 z-10
            bg-white rounded-lg shadow-lg border border-gray-200
            p-3 min-w-[200px] max-w-[280px]
          "
        >
          <div className="text-xs font-medium text-gray-700 mb-2">
            Related Snippets ({relatedLinks.length})
          </div>

          {/* 共享实体 */}
          {allSharedEntities.length > 0 && (
            <div className="mb-2">
              <div className="text-xs text-gray-500 mb-1">Shared entities:</div>
              <div className="flex flex-wrap gap-1">
                {allSharedEntities.slice(0, 5).map((entity, idx) => (
                  <span
                    key={idx}
                    className="px-1.5 py-0.5 text-xs bg-blue-100 text-blue-700 rounded"
                  >
                    {entity}
                  </span>
                ))}
                {allSharedEntities.length > 5 && (
                  <span className="text-xs text-gray-400">
                    +{allSharedEntities.length - 5} more
                  </span>
                )}
              </div>
            </div>
          )}

          {/* 关联列表 */}
          <div className="space-y-1.5">
            {relatedLinks.slice(0, 5).map((link, idx) => {
              const otherSnippetId = link.snippet_a === currentSnippetId
                ? link.snippet_b
                : link.snippet_a;

              return (
                <div
                  key={idx}
                  className="flex items-center justify-between text-xs"
                >
                  <span className="text-gray-600 truncate max-w-[150px]">
                    {otherSnippetId}
                  </span>
                  <span className={`font-medium ${
                    link.strength >= 0.7
                      ? 'text-green-600'
                      : link.strength >= 0.4
                      ? 'text-yellow-600'
                      : 'text-gray-400'
                  }`}>
                    {Math.round(link.strength * 100)}%
                  </span>
                </div>
              );
            })}
            {relatedLinks.length > 5 && (
              <div className="text-xs text-gray-400 text-center pt-1">
                +{relatedLinks.length - 5} more links
              </div>
            )}
          </div>

          {/* Link Type */}
          <div className="mt-2 pt-2 border-t border-gray-100">
            <div className="flex items-center gap-1 text-xs text-gray-500">
              <span>Type:</span>
              <span className="font-medium">
                {relatedLinks[0]?.link_type || 'co-reference'}
              </span>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default LinkedSnippetIndicator;
