/**
 * StandardFilterBar - Standard 过滤按钮组
 *
 * 替代原来的 StandardsPanel，提供更紧凑的 Standard 筛选功能
 */

import { useMemo } from 'react';
import { useApp } from '../context/AppContext';
import { legalStandards } from '../data/legalStandards';
import { STANDARD_KEY_TO_ID } from '../constants/colors';

export default function StandardFilterBar() {
  const {
    arguments: arguments_,
    argumentMappings,
    focusState,
    setFocusState
  } = useApp();

  // 计算每个 standard 的 argument 数量
  const standardCounts = useMemo(() => {
    const counts: Record<string, number> = {};

    // 初始化所有 standard 计数为 0
    legalStandards.forEach(std => {
      counts[std.id] = 0;
    });

    // 统计 AI 生成的 standardKey 映射
    arguments_.forEach(arg => {
      if (arg.standardKey) {
        const standardId = STANDARD_KEY_TO_ID[arg.standardKey];
        if (standardId && counts[standardId] !== undefined) {
          counts[standardId]++;
        }
      }
    });

    // 统计手动拖拽映射（避免重复计数）
    argumentMappings.forEach(mapping => {
      const arg = arguments_.find(a => a.id === mapping.source);
      if (arg) {
        // 只有当没有 AI 映射，或者手动映射到不同的 standard 时才计数
        const aiMappedId = arg.standardKey ? STANDARD_KEY_TO_ID[arg.standardKey] : null;
        if (aiMappedId !== mapping.target && counts[mapping.target] !== undefined) {
          counts[mapping.target]++;
        }
      }
    });

    return counts;
  }, [arguments_, argumentMappings]);

  // 按 argument 数量排序（有 argument 的优先）
  const sortedStandards = useMemo(() => {
    return [...legalStandards].sort((a, b) => {
      const countA = standardCounts[a.id] || 0;
      const countB = standardCounts[b.id] || 0;
      if (countA !== countB) return countB - countA;
      return a.order - b.order;
    });
  }, [standardCounts]);

  const handleClick = (standardId: string) => {
    if (focusState.type === 'standard' && focusState.id === standardId) {
      // 取消聚焦
      setFocusState({ type: 'none', id: null });
    } else {
      // 聚焦该 standard
      setFocusState({ type: 'standard', id: standardId });
    }
  };

  return (
    <div className="flex flex-wrap gap-1.5 p-2 bg-gray-50 border-b border-gray-200">
      {sortedStandards.map(standard => {
        const count = standardCounts[standard.id] || 0;
        const isFocused = focusState.type === 'standard' && focusState.id === standard.id;
        const hasArguments = count > 0;

        return (
          <button
            key={standard.id}
            onClick={() => handleClick(standard.id)}
            className={`
              inline-flex items-center gap-1.5 px-2 py-1 rounded-md text-xs font-medium
              transition-all duration-150 cursor-pointer
              ${isFocused
                ? 'ring-2 ring-offset-1 shadow-sm'
                : 'hover:bg-gray-100'
              }
              ${hasArguments
                ? 'text-gray-800'
                : 'text-gray-400'
              }
            `}
            style={{
              backgroundColor: isFocused ? `${standard.color}20` : 'white',
              borderColor: standard.color,
              borderWidth: '1px',
              borderStyle: 'solid',
              ringColor: isFocused ? standard.color : undefined,
            }}
          >
            {/* 颜色指示器 */}
            <span
              className="w-2 h-2 rounded-full flex-shrink-0"
              style={{ backgroundColor: standard.color }}
            />

            {/* 名称 */}
            <span className="truncate max-w-[80px]">
              {standard.shortName}
            </span>

            {/* 数量 */}
            {hasArguments && (
              <span
                className="ml-0.5 px-1.5 py-0.5 rounded-full text-[10px] font-semibold text-white"
                style={{ backgroundColor: standard.color }}
              >
                {count}
              </span>
            )}
          </button>
        );
      })}

      {/* 清除筛选按钮 */}
      {focusState.type === 'standard' && (
        <button
          onClick={() => setFocusState({ type: 'none', id: null })}
          className="inline-flex items-center gap-1 px-2 py-1 rounded-md text-xs font-medium
            text-gray-500 hover:text-gray-700 hover:bg-gray-100
            border border-gray-300 transition-colors"
        >
          <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
          </svg>
          Clear
        </button>
      )}
    </div>
  );
}
